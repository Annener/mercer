"""context_engine.drift — DriftDetector.

Сравнивает последние сообщения чата с текущим Campaign State и возвращает
список "drift hints" — кандидатов на обновление state. Использует
подключаемый провайдер (host_sidecar / openai_compatible) через
``app.providers.drift``.

Phase 3: история чата периодически сжимается через ``ChatSummarizer``
(см. ``chat_summarizer.py``). DriftDetector получает
``[running_summary] + [последние 4 сообщения]`` вместо сырых последних N —
это адаптивно под n_ctx drift-модели и не теряет контекст длинных диалогов.

Все ошибки (провайдер недоступен, БД, парсинг) логируются и тихо
возвращают ``None`` — chat не должен ломаться из-за drift-detection.

Settings читаются из PlatformSetting через ``settings_service.get``:
- ``drift.confidence_threshold`` (default 0.5)
- ``drift.max_messages`` (default 10) — используется только когда
  summarizer отключён (нет summary в БД или summary errored).
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import ChatHistorySummary, Message
from app.providers.drift.base import DriftProvider
from app.providers.drift.host_sidecar import HostSidecarDriftProvider
from app.providers.drift.openai_compatible import OpenAICompatibleDriftProvider
from app.services.campaign_state_compiler import compile_campaign_state
from app.services.campaign_state_value_service import campaign_state_value_service
from app.services.settings_service import settings_service

from .chat_summarizer import KEEP_LAST_N, ChatSummarizer
from .scene_memory import write_drift

logger = logging.getLogger(__name__)


# Settings keys
_DRIFT_CONFIDENCE_THRESHOLD_KEY = "drift.confidence_threshold"
_DRIFT_MAX_MESSAGES_KEY = "drift.max_messages"

# Defaults — применяются, если ключа нет в PlatformSetting.
_DRIFT_DEFAULT_CONFIDENCE_THRESHOLD = 0.5
_DRIFT_DEFAULT_MAX_MESSAGES = 10

# Fallback для host_sidecar base_url, если DriftModel.base_url == NULL.
_DEFAULT_SIDECAR_BASE_URL = "http://host.docker.internal:8765"

# Бюджет токенов на компиляцию state для drift-провайдера.
# Меньше, чем в основном chat-промпте — drift-модель компактная.
_DRIFT_STATE_BUDGET_TOKENS = 2000


class DriftDetector:
    """Детектор рассинхрона между chat messages и campaign state."""

    def __init__(
        self,
        *,
        db_factory: async_sessionmaker[AsyncSession],
        redis_client: Any,
        summarizer: ChatSummarizer | None = None,
    ) -> None:
        self.db_factory = db_factory
        self.redis = redis_client
        # Summarizer опционален — если не передан, drift работает в legacy
        # режиме (читает последние max_messages целиком, без сжатия).
        # Но лучше всегда передавать — без него длинные чаты упираются
        # в n_ctx drift-модели.
        self.summarizer = summarizer

    async def detect(self, chat_id: str) -> list[dict[str, Any]] | None:
        """Запустить drift-detection для одного чата.

        Возвращает hints (list of dict) если успешно, ``[]`` если провайдер
        отработал, но ничего не нашёл, и ``None`` если пропущено
        (нет активной модели / нет сообщений / чат без campaign_id /
        провайдер недоступен / БД-ошибка).
        """
        try:
            async with self.db_factory() as db:
                return await self._detect_inner(chat_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "drift.detect: outer failure chat_id=%s: %s", chat_id, exc
            )
            return None

    async def _detect_inner(
        self, chat_id: str, db: AsyncSession
    ) -> list[dict[str, Any]] | None:
        # 0. Phase 3: summarizer (fire-and-forget) — обновит summary до
        #    того, как мы прочитаем сообщения. Если summarizer упал —
        #    просто продолжим со старым summary (или без него).
        if self.summarizer is not None:
            await self.summarizer.maybe_summarize(chat_id)

        # 1. Активная drift-модель
        drift_model = await settings_service.get_active_drift_model(db)
        if drift_model is None:
            logger.debug("drift.detect: no active drift model, skip chat_id=%s", chat_id)
            return None

        # 2. Настройки
        threshold = await self._get_confidence_threshold(db)
        max_messages = await self._get_max_messages(db)

        # 3. Сообщения: summary + последние KEEP_LAST_N (если есть summary)
        #    или последние max_messages (legacy fallback).
        messages = await self._read_messages_for_drift(
            chat_id, db, max_messages_legacy=max_messages
        )
        if not messages:
            logger.debug("drift.detect: no messages, skip chat_id=%s", chat_id)
            return None

        # 4. Chat + campaign_id
        from app.db.models import Chat

        try:
            chat = await db.get(Chat, _uuid.UUID(chat_id))
        except (ValueError, TypeError):
            return None
        if chat is None or not chat.campaign_id:
            logger.debug("drift.detect: chat missing or no campaign, skip chat_id=%s", chat_id)
            return None

        # 5. Campaign State
        current_state_text = await self._compile_state_text(chat.campaign_id, db)

        # 6. Провайдер
        provider = self._build_provider(drift_model)
        if provider is None:
            return None

        # 7. Запрос
        try:
            hints_raw = await provider.detect_drift(
                messages=[
                    {"role": m["role"], "content": m["content"]}
                    for m in messages
                ],
                current_state=current_state_text,
                schema_hint=None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "drift.detect: provider failed chat_id=%s: %s", chat_id, exc
            )
            return None

        # 8. Фильтрация по threshold
        hints = [h for h in (hints_raw or []) if self._confidence_ge(h, threshold)]
        if not hints:
            logger.info(
                "drift.detect: no hints above threshold chat_id=%s threshold=%.2f",
                chat_id,
                threshold,
            )
            return []

        # 9. Запись в scene_state.drift
        try:
            await write_drift(chat_id, hints, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "drift.detect: write_drift failed chat_id=%s: %s", chat_id, exc
            )
            return None

        logger.info(
            "drift.detect: %d hints written chat_id=%s threshold=%.2f",
            len(hints),
            chat_id,
            threshold,
        )
        return hints

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _confidence_ge(hint: dict[str, Any], threshold: float) -> bool:
        try:
            return float(hint.get("confidence", 0.0)) >= threshold
        except (TypeError, ValueError):
            return False

    async def _compile_state_text(
        self, campaign_id: Any, db: AsyncSession
    ) -> str:
        try:
            version = await campaign_state_value_service.get_active_state(
                db, campaign_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("drift.detect: get_active_state failed: %s", exc)
            return "(failed to load campaign state)"

        if version is None:
            return "(empty campaign state)"

        try:
            fields = await campaign_state_value_service.list_enabled_fields_ordered(
                db, campaign_id
            )
            block = compile_campaign_state(
                version, fields, budget_tokens=_DRIFT_STATE_BUDGET_TOKENS
            )
            return block.text or "(empty campaign state)"
        except Exception as exc:  # noqa: BLE001
            logger.warning("drift.detect: compile_campaign_state failed: %s", exc)
            return "(failed to compile campaign state)"

    async def _read_last_messages(
        self, chat_id: str, db: AsyncSession, *, n: int
    ) -> list[dict[str, str]]:
        from sqlalchemy import select

        from app.db.models import Message

        try:
            chat_uuid = _uuid.UUID(chat_id)
        except (ValueError, TypeError):
            return []
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_uuid)
            .order_by(Message.created_at.desc())
            .limit(max(1, n))
        )
        try:
            result = await db.execute(stmt)
        except Exception as exc:  # noqa: BLE001
            logger.warning("drift.detect: read messages failed: %s", exc)
            return []
        msgs = list(result.scalars().all())
        # Возвращаем в хронологическом порядке (старые → новые).
        return [
            {"role": m.role, "content": m.content} for m in reversed(msgs)
        ]

    async def _read_messages_for_drift(
        self, chat_id: str, db: AsyncSession, *, max_messages_legacy: int
    ) -> list[dict[str, str]]:
        """Phase 3: читает историю чата для drift-детектора.

        Возвращает:
          - если есть ``ChatHistorySummary`` для чата:
              ``[recap(role=user)] + последние KEEP_LAST_N сообщений``
          - если summary нет:
              последние ``max_messages_legacy`` сообщений (legacy fallback)

        Гарантия: recap-блок и последние сообщения не пересекаются
        (summarizer уплотняет только ``[0 … total - KEEP_LAST_N)``).
        """
        from sqlalchemy import select

        try:
            chat_uuid = _uuid.UUID(chat_id)
        except (ValueError, TypeError):
            return []

        # 1. Пытаемся достать summary.
        try:
            summary_row = await db.get(ChatHistorySummary, chat_uuid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "drift.detect: read summary failed chat_id=%s: %s",
                chat_id, exc,
            )
            summary_row = None

        # 2. Берём последние KEEP_LAST_N сообщений.
        try:
            stmt = (
                select(Message)
                .where(Message.chat_id == chat_uuid)
                .order_by(Message.created_at.desc())
                .limit(KEEP_LAST_N)
            )
            result = await db.execute(stmt)
            recent = list(result.scalars().all())
        except Exception as exc:  # noqa: BLE001
            logger.warning("drift.detect: read recent messages failed: %s", exc)
            return []
        # Хронологический порядок.
        recent = list(reversed(recent))

        # 3. Собираем выход.
        out: list[dict[str, str]] = []
        if (
            summary_row is not None
            and summary_row.summary_text
            and summary_row.summarized_messages_count > 0
        ):
            recap = (
                "[Conversation recap from earlier turns — characters, places, "
                "items, ongoing goals and unresolved threads]:\n"
                + summary_row.summary_text
            )
            # role=user: chatml-формат sidecar-а ожидает user/system чередование;
            # "user" — нейтральный выбор для фактического контекста, который
            # предшествует текущему диалогу.
            out.append({"role": "user", "content": recap})
            logger.debug(
                "drift.detect: used summary chat_id=%s chars=%d recent=%d",
                chat_id, len(summary_row.summary_text), len(recent),
            )

        if not recent and not out:
            # Совсем нет истории — fallback на legacy, чтобы drift хотя бы
            # попробовал обработать хоть что-то.
            return await self._read_last_messages(
                chat_id, db, n=max_messages_legacy
            )

        for m in recent:
            out.append({"role": m.role, "content": m.content})
        return out

    def _build_provider(self, model: Any) -> DriftProvider | None:
        provider_name = getattr(model, "provider", None)
        if provider_name == "host_sidecar":
            return HostSidecarDriftProvider(
                base_url=getattr(model, "base_url", None) or _DEFAULT_SIDECAR_BASE_URL,
                model_name=model.model_name,
                timeout_seconds=getattr(model, "timeout_seconds", 60) or 60,
            )
        if provider_name == "openai_compatible":
            api_key = (
                settings_service.decrypt_api_key(model.encrypted_api_key)
                if getattr(model, "encrypted_api_key", None)
                else ""
            )
            return OpenAICompatibleDriftProvider(
                base_url=model.base_url or "",
                model_name=model.model_name,
                api_key=api_key,
                timeout_seconds=getattr(model, "timeout_seconds", 60) or 60,
            )
        logger.warning("drift.detect: unknown provider=%s", provider_name)
        return None

    @staticmethod
    async def _get_confidence_threshold(db: AsyncSession) -> float:
        try:
            value = await settings_service.get(_DRIFT_CONFIDENCE_THRESHOLD_KEY, db)
        except (KeyError, Exception):  # noqa: BLE001
            return _DRIFT_DEFAULT_CONFIDENCE_THRESHOLD
        try:
            v = float(value)
            if 0.0 <= v <= 1.0:
                return v
        except (TypeError, ValueError):
            pass
        return _DRIFT_DEFAULT_CONFIDENCE_THRESHOLD

    @staticmethod
    async def _get_max_messages(db: AsyncSession) -> int:
        try:
            value = await settings_service.get(_DRIFT_MAX_MESSAGES_KEY, db)
        except (KeyError, Exception):  # noqa: BLE001
            return _DRIFT_DEFAULT_MAX_MESSAGES
        try:
            v = int(value)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
        return _DRIFT_DEFAULT_MAX_MESSAGES
