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

from app.config import EmbeddingModelConfig, GenerationModelConfig
from app.db.models import EmbeddingModel, GenerationModel, PlatformSetting, RerankModel, Vault
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

    # ------------------------------------------------------------------
    # Private helpers: lookup by model_id (string slug), not PK (UUID)
    # db.get(Model, model_id) падает с asyncpg.DataError, т.к. PK — UUID,
    # а model_id — строковой слаг (напр. '24234'). E-CHK03.
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_generation_model(model_id: str, db: AsyncSession) -> GenerationModel | None:
        result = await db.execute(
            select(GenerationModel).where(GenerationModel.model_id == model_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _get_embedding_model(model_id: str, db: AsyncSession) -> EmbeddingModel | None:
        result = await db.execute(
            select(EmbeddingModel).where(EmbeddingModel.model_id == model_id)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Platform settings
    # ------------------------------------------------------------------

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
        result = await db.execute(
            select(GenerationModel).where(
                GenerationModel.is_active == True, GenerationModel.enabled == True
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            self._active_provider = None
            return
        provider = self._build_generation_provider(model)
        async with self._provider_lock:
            self._active_provider = provider

    async def swap_provider(self, model_id: str, db: AsyncSession) -> None:
        # E-CHK03: was db.get(GenerationModel, model_id) — PK is UUID, model_id is string
        model = await self._get_generation_model(model_id, db)
        if model is None or not model.enabled:
            raise KeyError(model_id)
        async with self._transaction(db):
            await db.execute(update(GenerationModel).values(is_active=False))
            model.is_active = True
        provider = self._build_generation_provider(model)
        async with self._provider_lock:
            self._active_provider = provider

    def encrypt_api_key(self, plain: str) -> str:
        return self._get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")

    def decrypt_api_key(self, encrypted: str) -> str:
        return self._get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")

    # ------------------------------------------------------------------
    # GenerationModel CRUD
    # ------------------------------------------------------------------

    async def get_generation_model(self, model_id: str, db: AsyncSession) -> dict[str, Any] | None:
        # E-CHK03: was db.get(GenerationModel, model_id)
        model = await self._get_generation_model(model_id, db)
        return self._generation_model_dict(model) if model is not None else None

    async def list_generation_models(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(
            select(GenerationModel).order_by(GenerationModel.created_at.desc())
        )
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

    async def update_generation_model(
        self, model_id: str, data: dict[str, Any], db: AsyncSession
    ) -> dict[str, Any]:
        # E-CHK03: was db.get(GenerationModel, model_id)
        model = await self._get_generation_model(model_id, db)
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
                model.encrypted_api_key = (
                    self.encrypt_api_key(str(api_key)) if api_key else None
                )
        await db.refresh(model)
        if model.is_active:
            await self.load_active_provider(db)
        return self._generation_model_dict(model)

    async def delete_generation_model(self, model_id: str, db: AsyncSession) -> None:
        # E-CHK03: was db.get(GenerationModel, model_id) — падал с asyncpg.DataError
        model = await self._get_generation_model(model_id, db)
        if model is None:
            raise KeyError(model_id)
        if model.is_active:
            raise ValueError("Cannot delete active generation model")
        async with self._transaction(db):
            await db.delete(model)

    async def activate_generation_model(self, model_id: str, db: AsyncSession) -> None:
        await self.swap_provider(model_id, db)

    # ------------------------------------------------------------------
    # EmbeddingModel CRUD
    # ------------------------------------------------------------------

    async def get_embedding_model(self, model_id: str, db: AsyncSession) -> dict[str, Any] | None:
        # E-CHK03: was db.get(EmbeddingModel, model_id)
        model = await self._get_embedding_model(model_id, db)
        return self._embedding_model_dict(model) if model is not None else None

    async def list_embedding_models(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(
            select(EmbeddingModel).order_by(EmbeddingModel.created_at.desc())
        )
        return [self._embedding_model_dict(model) for model in result.scalars().all()]

    async def get_active_embedding_config(
        self,
        db: AsyncSession,
        vault_id: str | None = None,
    ) -> EmbeddingModelConfig | None:
        """Returns the EmbeddingModelConfig to use for retrieval.

        Приоритет выбора модели:
          1. vault_id задан → берём Vault.embedding_model_id — модель,
             которой реально индексировался ваулт.
          2. Fallback: первая enabled=True модель из embedding_models
             (по created_at ASC) — если vault не задан или у него
             нет embedding_model_id.

        Используется в fallback-путях (plain LLM stream),
        где AppConfig недоступен.
        """
        orm_model: EmbeddingModel | None = None

        # Шаг 1: если vault_id задан — берём модель привязанную к vaultу
        if vault_id is not None:
            vault_result = await db.execute(
                select(Vault).where(Vault.vault_id == vault_id)
            )
            vault = vault_result.scalar_one_or_none()
            if vault is not None and vault.embedding_model_id:
                orm_model = await self._get_embedding_model(vault.embedding_model_id, db)

        # Шаг 2: fallback — первая enabled-модель
        if orm_model is None:
            result = await db.execute(
                select(EmbeddingModel)
                .where(EmbeddingModel.enabled == True)
                .order_by(EmbeddingModel.created_at.asc())
                .limit(1)
            )
            orm_model = result.scalar_one_or_none()

        if orm_model is None:
            return None

        return self._build_embedding_config(orm_model)

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

    async def update_embedding_model(
        self, model_id: str, data: dict[str, Any], db: AsyncSession
    ) -> dict[str, Any]:
        # E-CHK03: was db.get(EmbeddingModel, model_id)
        model = await self._get_embedding_model(model_id, db)
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
                model.encrypted_api_key = (
                    self.encrypt_api_key(str(api_key)) if api_key else None
                )
        await db.refresh(model)
        return self._embedding_model_dict(model)

    async def delete_embedding_model(self, model_id: str, db: AsyncSession) -> None:
        # E-CHK03: was db.get(EmbeddingModel, model_id)
        model = await self._get_embedding_model(model_id, db)
        if model is None:
            raise KeyError(model_id)
        async with self._transaction(db):
            await db.delete(model)

    # ------------------------------------------------------------------
    # RerankModel CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_rerank_model(model_id: str, db: AsyncSession) -> RerankModel | None:
        result = await db.execute(
            select(RerankModel).where(RerankModel.model_id == model_id)
        )
        return result.scalar_one_or_none()

    async def list_rerank_models(self, db: AsyncSession) -> list[dict[str, Any]]:
        result = await db.execute(
            select(RerankModel).order_by(RerankModel.created_at.desc())
        )
        return [self._rerank_model_dict(model) for model in result.scalars().all()]

    async def create_rerank_model(self, data: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
        payload = dict(data)
        api_key = payload.pop("api_key", None)
        if api_key:
            payload["encrypted_api_key"] = self.encrypt_api_key(str(api_key))
        model = RerankModel(**payload)
        async with self._transaction(db):
            db.add(model)
        await db.refresh(model)
        return self._rerank_model_dict(model)

    async def update_rerank_model(
        self, model_id: str, data: dict[str, Any], db: AsyncSession
    ) -> dict[str, Any]:
        model = await self._get_rerank_model(model_id, db)
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
                model.encrypted_api_key = (
                    self.encrypt_api_key(str(api_key)) if api_key else None
                )
        await db.refresh(model)
        return self._rerank_model_dict(model)

    async def delete_rerank_model(self, model_id: str, db: AsyncSession) -> None:
        model = await self._get_rerank_model(model_id, db)
        if model is None:
            raise KeyError(model_id)
        async with self._transaction(db):
            await db.delete(model)

    async def activate_rerank_model(self, model_id: str, db: AsyncSession) -> dict[str, Any]:
        model = await self._get_rerank_model(model_id, db)
        if model is None or not model.enabled:
            raise KeyError(model_id)
        async with self._transaction(db):
            await db.execute(update(RerankModel).values(is_active=False))
            model.is_active = True
        await db.refresh(model)
        return self._rerank_model_dict(model)

    async def get_active_rerank_model(self, db: AsyncSession) -> RerankModel | None:
        result = await db.execute(
            select(RerankModel).where(
                RerankModel.is_active == True, RerankModel.enabled == True
            )
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_embedding_config(self, model: EmbeddingModel) -> EmbeddingModelConfig:
        """Bonvert ORM EmbeddingModel → EmbeddingModelConfig.

        Для openai_compatible: расшифрованный ключ прокидывается
        через sentinel env-переменную, которую читает _embed_openai_compatible.
        """
        api_key_env: str | None = None
        if model.encrypted_api_key:
            api_key_env = "_MERCER_FALLBACK_API_KEY"
            os.environ[api_key_env] = self.decrypt_api_key(model.encrypted_api_key)
        return EmbeddingModelConfig(
            model_id=model.model_id,
            provider=model.provider,
            model_name=model.model_name,
            base_url=model.base_url,
            dimensions=model.dimensions,
            timeout_seconds=model.timeout_seconds,
            max_retries=model.max_retries,
            enabled=model.enabled,
            api_key_env=api_key_env or "",
        )

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
        if value is None:
            return DEFAULTS.get(key)
        if value_type == "bool":
            if isinstance(value, bool):
                return value
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
            return str(value) if value is not None else DEFAULTS.get(key)
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

    def _serialize_value(self, value: Any) -> str:
        """Serialize a typed Python value to a VARCHAR string for storage.

        platform_settings.value is VARCHAR — asyncpg requires str, never bool/int/float.
        Symmetric with _cast_value: bool → "true"/"false", numeric → str(x), None → "".
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

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

    def _rerank_model_dict(self, model: RerankModel) -> dict[str, Any]:
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
