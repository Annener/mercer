from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from cryptography.fernet import Fernet
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import GenerationModelConfig
from app.db.models import EmbeddingModel, GenerationModel, PlatformSetting
from app.providers.generation.base import GenerationProvider
from app.providers.generation.openai_compatible import OpenAICompatibleProvider


DEFAULTS: dict[str, Any] = {
    "retrieval.enabled": True,
    "retrieval.top_k": 10,
    "retrieval.reranker_enabled": False,
    "chunking.chunk_size": 2000,
    "chunking.overlap": 64,
    "chunking.entity_aware_mode": True,
    "chat.max_clarification_turns": 3,
    "chat.stream_answers": True,
    "chat.auto_title": True,
    "reranker.enabled": False,
    "reranker.provider": None,
    "reranker.base_url": None,
    "reranker.model_name": None,
    "pdf_sidecar.url": "http://host.docker.internal:8765",
    "pdf_sidecar.timeout_seconds": 180,
    "pdf_sidecar.fallback_to_pdfminer": True,
}


class SettingsService:
    def __init__(self) -> None:
        self._settings_cache: dict[str, Any] = {}
        self._setting_types: dict[str, str] = {}
        self._active_provider: GenerationProvider | None = None
        self._provider_lock = asyncio.Lock()
        self._fernet: Fernet | None = None

    async def load_settings(self, db: AsyncSession) -> None:
        result = await db.execute(select(PlatformSetting))
        self._settings_cache.clear()
        self._setting_types.clear()
        for setting in result.scalars().all():
            self._setting_types[setting.key] = setting.value_type
            self._settings_cache[setting.key] = self._cast_value(setting.key, setting.value, setting.value_type)

    async def get(self, key: str, db: AsyncSession | None = None) -> Any:
        if key in self._settings_cache:
            return self._settings_cache[key]
        if db is None:
            raise KeyError(key)
        setting = await db.get(PlatformSetting, key)
        if setting is None:
            raise KeyError(key)
        self._setting_types[key] = setting.value_type
        value = self._cast_value(key, setting.value, setting.value_type)
        self._settings_cache[key] = value
        return value

    async def get_all(self, db: AsyncSession) -> dict[str, Any]:
        await self.load_settings(db)
        return dict(self._settings_cache)

    async def set(self, key: str, value: Any, db: AsyncSession) -> None:
        setting = await db.get(PlatformSetting, key)
        if setting is None:
            raise KeyError(key)
        converted = self._coerce_value(value, setting.value_type)
        async with self._transaction(db):
            setting.value = self._serialize_value(converted)
        self._setting_types[key] = setting.value_type
        self._settings_cache[key] = converted

    async def reset_all(self, db: AsyncSession) -> None:
        async with self._transaction(db):
            for key, value in DEFAULTS.items():
                setting = await db.get(PlatformSetting, key)
                if setting is not None:
                    setting.value = self._serialize_value(value)
                    self._settings_cache[key] = value

    def invalidate(self, key: str) -> None:
        self._settings_cache.pop(key, None)
        self._setting_types.pop(key, None)

    def get_active_provider(self) -> GenerationProvider | None:
        return self._active_provider

    async def load_active_provider(self, db: AsyncSession) -> None:
        result = await db.execute(select(GenerationModel).where(GenerationModel.is_active == True, GenerationModel.enabled == True))
        model = result.scalar_one_or_none()
        if model is None:
            self._active_provider = None
            return
        provider = self._build_generation_provider(model)
        async with self._provider_lock:
            self._active_provider = provider

    async def swap_provider(self, model_id: str, db: AsyncSession) -> None:
        async with self._transaction(db):
            model = await db.get(GenerationModel, model_id)
            if model is None or not model.enabled:
                raise KeyError(model_id)
            await db.execute(update(GenerationModel).values(is_active=False))
            model.is_active = True
        provider = self._build_generation_provider(model)
        async with self._provider_lock:
            self._active_provider = provider

    def encrypt_api_key(self, plain: str) -> str:
        return self._get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")

    def decrypt_api_key(self, encrypted: str) -> str:
        return self._get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")

    async def get_generation_model(self, model_id: str, db: AsyncSession) -> dict[str, Any] | None:
        model = await db.get(GenerationModel, model_id)
        return self._generation_model_dict(model) if model is not None else None

    async def list_generation_models(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(select(GenerationModel).order_by(GenerationModel.created_at.desc()))
        return [self._generation_model_dict(model) for model in result.scalars().all()]

    async def create_generation_model(self, data: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        payload = dict(data)
        api_key = payload.pop("api_key", None)
        if api_key:
            payload["encrypted_api_key"] = self.encrypt_api_key(str(api_key))
        model = GenerationModel(**payload)
        async with self._transaction(db):
            db.add(model)
        await db.refresh(model)
        return self._generation_model_dict(model)

    async def update_generation_model(self, model_id: str, data: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        model = await db.get(GenerationModel, model_id)
        if model is None:
            raise KeyError(model_id)
        payload = dict(data)
        api_key_marker = object()
        api_key = payload.pop("api_key", api_key_marker)
        async with self._transaction(db):
            for key, value in payload.items():
                if value is not None and hasattr(model, key):
                    setattr(model, key, value)
            if api_key is not api_key_marker:
                model.encrypted_api_key = self.encrypt_api_key(str(api_key)) if api_key else None
        await db.refresh(model)
        if model.is_active:
            await self.load_active_provider(db)
        return self._generation_model_dict(model)

    async def delete_generation_model(self, model_id: str, db: AsyncSession) -> None:
        model = await db.get(GenerationModel, model_id)
        if model is None:
            raise KeyError(model_id)
        if model.is_active:
            raise ValueError("Cannot delete active generation model")
        async with self._transaction(db):
            await db.delete(model)

    async def activate_generation_model(self, model_id: str, db: AsyncSession) -> None:
        await self.swap_provider(model_id, db)

    async def get_embedding_model(self, model_id: str, db: AsyncSession) -> dict[str, Any] | None:
        model = await db.get(EmbeddingModel, model_id)
        return self._embedding_model_dict(model) if model is not None else None

    async def list_embedding_models(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(select(EmbeddingModel).order_by(EmbeddingModel.created_at.desc()))
        return [self._embedding_model_dict(model) for model in result.scalars().all()]

    async def create_embedding_model(self, data: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        payload = dict(data)
        api_key = payload.pop("api_key", None)
        if api_key:
            payload["encrypted_api_key"] = self.encrypt_api_key(str(api_key))
        model = EmbeddingModel(**payload)
        async with self._transaction(db):
            db.add(model)
        await db.refresh(model)
        return self._embedding_model_dict(model)

    async def update_embedding_model(self, model_id: str, data: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        model = await db.get(EmbeddingModel, model_id)
        if model is None:
            raise KeyError(model_id)
        payload = dict(data)
        api_key_marker = object()
        api_key = payload.pop("api_key", api_key_marker)
        async with self._transaction(db):
            for key, value in payload.items():
                if value is not None and hasattr(model, key):
                    setattr(model, key, value)
            if api_key is not api_key_marker:
                model.encrypted_api_key = self.encrypt_api_key(str(api_key)) if api_key else None
        await db.refresh(model)
        return self._embedding_model_dict(model)

    async def delete_embedding_model(self, model_id: str, db: AsyncSession) -> None:
        model = await db.get(EmbeddingModel, model_id)
        if model is None:
            raise KeyError(model_id)
        async with self._transaction(db):
            await db.delete(model)

    def _build_generation_provider(self, model: GenerationModel) -> GenerationProvider:
        api_key = self.decrypt_api_key(model.encrypted_api_key) if model.encrypted_api_key else ""
        if model.provider == "openai_compatible":
            config = GenerationModelConfig(
                model_id=model.model_id,
                provider="openai_compatible",
                base_url=model.base_url,
                api_key_env="",
                enabled=model.enabled,
                timeout_seconds=model.timeout_seconds,
            )
            return OpenAICompatibleProvider(config=config, api_key=api_key, max_retries=1)
        raise ValueError(f"Unsupported generation provider: {model.provider}")

    def _get_fernet(self) -> Fernet:
        if self._fernet is None:
            key = os.getenv("ENCRYPTION_KEY")
            if not key:
                raise RuntimeError("ENCRYPTION_KEY is not configured")
            self._fernet = Fernet(key.encode("utf-8"))
        return self._fernet

    def _cast_value(self, key: str, value: Any, value_type: str) -> Any:
        """Convert a value read from DB (may be str from TEXT or native type from JSONB)
        to the expected Python type declared by value_type.
        """
        # JSONB уже десериализует JSON в native Python типы.
        # Если значение уже правильного типа — возвращаем сразу.
        if value is None:
            return DEFAULTS.get(key)

        if value_type == "bool":
            if isinstance(value, bool):
                return value
            # Приходит строкой (TEXT-эпоха) или числом из JSON (0/1)
            if isinstance(value, int):
                return bool(value)
            return str(value).lower() in {"true", "1", "yes", "on"}

        if value_type == "int":
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            return int(value)

        if value_type == "float":
            if isinstance(value, float):
                return value
            if isinstance(value, int) and not isinstance(value, bool):
                return float(value)
            return float(value)

        if value_type == "str":
            if isinstance(value, str):
                return None if value == "" and DEFAULTS.get(key) is None else value
            # JSONB может вернуть null -> None
            return str(value) if value is not None else DEFAULTS.get(key)

        # Для неизвестных типов — возвращаем как есть
        return value

    def _coerce_value(self, value: Any, value_type: str) -> Any:
        if value_type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str) and value.lower() in {"true", "1"}:
                return True
            if isinstance(value, str) and value.lower() in {"false", "0"}:
                return False
            raise ValueError("Invalid bool value")
        if value_type == "int":
            if isinstance(value, bool) or value is None:
                raise ValueError("Invalid int value")
            if isinstance(value, float) and not value.is_integer():
                raise ValueError("Invalid int value")
            return int(value)
        if value_type == "float":
            if isinstance(value, bool) or value is None:
                raise ValueError("Invalid float value")
            return float(value)
        if value_type == "str":
            return "" if value is None else str(value)
        raise ValueError(f"Unsupported setting type: {value_type}")

    def _serialize_value(self, value: Any) -> Any:
        """Prepare value for writing to DB.
        Since platform_settings.value is now JSONB, we store native Python types directly.
        SQLAlchemy + asyncpg will serialize them automatically.
        """
        # None храним как JSON null
        return value

    def _generation_model_dict(self, model: GenerationModel) -> dict[str, Any]:
        return {
            "model_id": model.model_id,
            "provider": model.provider,
            "display_name": model.display_name,
            "base_url": model.base_url,
            "timeout_seconds": model.timeout_seconds,
            "is_active": model.is_active,
            "enabled": model.enabled,
            "has_api_key": bool(model.encrypted_api_key),
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }

    def _embedding_model_dict(self, model: EmbeddingModel) -> dict[str, Any]:
        return {
            "model_id": model.model_id,
            "provider": model.provider,
            "display_name": model.display_name,
            "model_name": model.model_name,
            "base_url": model.base_url,
            "dimensions": model.dimensions,
            "timeout_seconds": model.timeout_seconds,
            "max_retries": model.max_retries,
            "enabled": model.enabled,
            "has_api_key": bool(model.encrypted_api_key),
            "created_at": model.created_at,
            "updated_at": model.updated_at,
        }

    @asynccontextmanager
    async def _transaction(self, db: AsyncSession) -> AsyncIterator[None]:
        if db.in_transaction():
            try:
                yield
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        else:
            async with db.begin():
                yield


settings_service = SettingsService()
