"""context_engine.chat_summarizer — ChatSummarizer.

Периодически сжимает старые блоки сообщений чата в «running summary» через
тот же QVikhr-3-1.7B, что и drift-detection (использует ``host_sidecar``
endpoint ``POST /drift/summarize``). Хранит summary в таблице
``chat_history_summaries`` (по строке на чат).

Алгоритм (``maybe_summarize``):
  1. Берём текущее значение ``summarized_messages_count`` из БД (или 0).
  2. Считаем общее количество сообщений в чате.
  3. ``unsummarized = total - summarized_count``.
  4. Если ``unsummarized < 4`` — порог не достигнут, выходим.
  5. Берём блок ``[summarized_count + 1 … total - KEEP_LAST_N]`` (где
     ``KEEP_LAST_N = 4`` — последние сообщения оставляем полным текстом
     для drift-детектора; гарантируем непересечение).
  6. Если блок длиннее 4 сообщений — режем по 4 и сжимаем инкрементально:
     prev_summary растёт, каждый чанк мерджится с ним через sidecar.
  7. Обновляем строку в ``chat_history_summaries`` (UPSERT).

Все ошибки логируются и тихо глотаются — summarizer не должен ломать
drift-loop. Если sidecar недоступен или вернул 5xx — пропускаем чат;
на следующем drift-trigger-е попробуем снова.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chat, ChatHistorySummary, Message

logger = logging.getLogger(__name__)


# Сколько последних сообщений оставляем полным текстом (для drift и для чата).
# Должно совпадать с ``_read_messages_for_drift.keep_last_n`` в drift.py.
KEEP_LAST_N = 4

# Сколько сообщений сжимать за один вызов sidecar-а. На малых окнах
# sidecar сам разобьёт дальше через свою token-budget логику; это лишь
# верхняя граница «сколько сообщений мы вообще готовы отдать за раз».
MAX_CHUNK_MESSAGES = 32

# Минимальное число несжатых сообщений, при котором запускается summarizer.
# Идёт вровень с KEEP_LAST_N: если несжатых < 4 — нет смысла.
SUMMARIZE_THRESHOLD = KEEP_LAST_N


class ChatSummarizer:
    """Сжиматель истории чата.

    Параметризуется:
      - ``db_factory`` — для открытия сессий
      - ``sidecar_base_url`` / ``sidecar_model_name`` — куда стучаться за summary
      - ``timeout_seconds`` — таймаут HTTP-запроса к sidecar-у
    """

    def __init__(
        self,
        *,
        db_factory: async_sessionmaker[AsyncSession],
        sidecar_base_url: str,
        sidecar_model_name: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.db_factory = db_factory
        self.sidecar_base_url = sidecar_base_url.rstrip("/")
        self.sidecar_model_name = sidecar_model_name
        self.timeout_seconds = timeout_seconds

    async def maybe_summarize(self, chat_id: str) -> None:
        """Главная точка входа. Тихо возвращается при любой ошибке.

        Запускается из ``DriftDetector.detect`` **до** собственно drift detect-а,
        чтобы на drift уже был свежий summary. Если summarizer падает —
        drift всё равно отработает (со старым summary или без него).
        """
        try:
            async with self.db_factory() as db:
                await self._maybe_summarize_inner(chat_id, db)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chat_summarizer: outer failure chat_id=%s: %s", chat_id, exc
            )

    async def _maybe_summarize_inner(
        self, chat_id: str, db: AsyncSession
    ) -> None:
        try:
            chat_uuid = _uuid.UUID(chat_id)
        except (ValueError, TypeError):
            return

        chat = await db.get(Chat, chat_uuid)
        if chat is None:
            return

        # 1. Текущий summary (если есть).
        summary_row = await db.get(ChatHistorySummary, chat_uuid)
        prev_summary = summary_row.summary_text if summary_row else ""
        summarized_count = (
            summary_row.summarized_messages_count if summary_row else 0
        )
        model_id = (
            summary_row.model_id if summary_row else self.sidecar_model_name
        )

        # 2. Все сообщения чата в хронологическом порядке.
        stmt = (
            select(Message)
            .where(Message.chat_id == chat_uuid)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        try:
            result = await db.execute(stmt)
            all_messages = list(result.scalars().all())
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "chat_summarizer: read messages failed chat_id=%s: %s",
                chat_id, exc,
            )
            return

        total = len(all_messages)
        unsummarized = total - summarized_count

        # 3. Порог не достигнут — ничего не делаем.
        if unsummarized < SUMMARIZE_THRESHOLD:
            logger.debug(
                "chat_summarizer: skip chat_id=%s unsummarized=%d threshold=%d",
                chat_id, unsummarized, SUMMARIZE_THRESHOLD,
            )
            return

        # 4. Границы блока для сжатия.
        #    Блок: всё, что не в summary, минус последние KEEP_LAST_N
        #    сообщений (которые остаются полным текстом для drift).
        #    summarized_count отсчитывается от первого сообщения чата
        #    (created_at ASC). Поэтому:
        #      start_index = summarized_count        (0-based, inclusive)
        #      end_index   = total - KEEP_LAST_N    (exclusive)
        start_index = summarized_count
        end_index = total - KEEP_LAST_N
        if end_index <= start_index:
            logger.debug(
                "chat_summarizer: skip chat_id=%s nothing_to_compress "
                "start=%d end=%d total=%d",
                chat_id, start_index, end_index, total,
            )
            return

        block = all_messages[start_index:end_index]
        if not block:
            return

        logger.info(
            "chat_summarizer: start chat_id=%s total=%d summarized=%d "
            "block_size=%d last_n=%d",
            chat_id, total, summarized_count, len(block), KEEP_LAST_N,
        )

        # 5. Режем блок по MAX_CHUNK_MESSAGES и сжимаем инкрементально.
        current_summary = prev_summary
        compressed_so_far = summarized_count
        last_message_id = (
            summary_row.summarized_up_to_message_id if summary_row else None
        )

        for chunk_start in range(0, len(block), MAX_CHUNK_MESSAGES):
            chunk = block[chunk_start:chunk_start + MAX_CHUNK_MESSAGES]
            messages_payload = [
                {"role": m.role, "content": m.content} for m in chunk
            ]

            new_summary = await self._call_sidecar(
                current_summary, messages_payload
            )
            if new_summary is None:
                # Sidecar упал — прерываем цикл, сохраняем то, что уже сжали.
                logger.warning(
                    "chat_summarizer: sidecar failed mid-way chat_id=%s "
                    "compressed_so_far=%d",
                    chat_id, compressed_so_far,
                )
                break

            current_summary = new_summary
            compressed_so_far += len(chunk)
            last_message_id = chunk[-1].id

            logger.info(
                "chat_summarizer: chunk compressed chat_id=%s chunk=%d "
                "compressed_so_far=%d summary_chars=%d",
                chat_id, len(chunk), compressed_so_far, len(current_summary),
            )
            # === DEBUG: показать ПОЛНЫЙ текст summary после этой итерации.
            # Полезно глазами проверить, что модель сохранила смысл и
            # терминологию из сжатого блока. В проде может быть шумно —
            # приглушить через LOG_LEVEL=INFO.
            logger.info(
                "chat_summarizer: SUMMARY AFTER chunk chat_id=%s "
                "iteration=%d chunk_size=%d prev_chars=%d new_chars=%d\n"
                "----- BEGIN SUMMARY -----\n%s\n----- END SUMMARY -----",
                chat_id,
                chunk_start // MAX_CHUNK_MESSAGES + 1,
                len(chunk),
                len(prev_summary) if chunk_start == 0 else len(
                    current_summary
                ),  # prev для первой итерации — старая база
                len(current_summary),
                current_summary,
            )

        # 6. UPSERT summary.
        await self._upsert_summary(
            db=db,
            chat_uuid=chat_uuid,
            summary_text=current_summary,
            summarized_messages_count=compressed_so_far,
            summarized_up_to_message_id=last_message_id,
            model_id=model_id,
        )

        logger.info(
            "chat_summarizer: done chat_id=%s compressed=%d/%d",
            chat_id, compressed_so_far, total,
        )

        # === DEBUG: финальный summary, записанный в БД. Глазами сравнить
        # с тем, что было на входе (в коде выше) — видно, не потерялся ли
        # смысл при многоступенчатом сжатии.
        input_chars = sum(
            len(m.content) for m in block
        ) + len(prev_summary)
        logger.info(
            "chat_summarizer: FINAL SUMMARY chat_id=%s "
            "iterations=%d input_chars=%d summary_chars=%d ratio=%.2f "
            "compressed_messages=%d\n"
            "===== BEGIN FINAL SUMMARY =====\n%s\n===== END FINAL SUMMARY =====",
            chat_id,
            (len(block) + MAX_CHUNK_MESSAGES - 1) // MAX_CHUNK_MESSAGES,
            input_chars,
            len(current_summary),
            len(current_summary) / max(input_chars, 1),
            compressed_so_far - summarized_count,
            current_summary,
        )

    async def _call_sidecar(
        self, previous_summary: str, messages_to_compress: list[dict[str, str]]
    ) -> str | None:
        """POST /drift/summarize. Возвращает новый summary или None при ошибке."""
        payload = {
            "model": self.sidecar_model_name,
            "previous_summary": previous_summary or None,
            "messages_to_compress": messages_to_compress,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                resp = await client.post(
                    f"{self.sidecar_base_url}/drift/summarize", json=payload,
                )
        except (httpx.HTTPError, httpx.ConnectError, ConnectionError, OSError) as exc:
            logger.warning(
                "chat_summarizer: sidecar unreachable at %s: %s",
                self.sidecar_base_url, exc,
            )
            return None

        if resp.status_code >= 400:
            logger.warning(
                "chat_summarizer: sidecar %d: %s",
                resp.status_code, resp.text[:200],
            )
            return None

        try:
            data = resp.json()
        except ValueError as exc:
            logger.warning(
                "chat_summarizer: sidecar returned non-JSON: %s", exc,
            )
            return None

        summary = data.get("summary")
        if not isinstance(summary, str):
            logger.warning(
                "chat_summarizer: sidecar payload has no 'summary' str: "
                "keys=%s", list(data.keys()),
            )
            return None

        return summary

    async def _upsert_summary(
        self,
        *,
        db: AsyncSession,
        chat_uuid: _uuid.UUID,
        summary_text: str,
        summarized_messages_count: int,
        summarized_up_to_message_id: _uuid.UUID | None,
        model_id: str,
    ) -> None:
        """INSERT ON CONFLICT UPDATE для chat_history_summaries."""
        # Используем PostgreSQL INSERT ... ON CONFLICT DO UPDATE (миграция
        # пишет таблицу под Postgres). На SQLite для тестов on_conflict_do_update
        # тоже работает (с SQLite ≥ 3.24 поддерживается).
        stmt = pg_insert(ChatHistorySummary).values(
            chat_id=chat_uuid,
            summary_text=summary_text,
            summarized_messages_count=summarized_messages_count,
            summarized_up_to_message_id=summarized_up_to_message_id,
            model_id=model_id,
        ).on_conflict_do_update(
            index_elements=[ChatHistorySummary.chat_id],
            set_={
                "summary_text": summary_text,
                "summarized_messages_count": summarized_messages_count,
                "summarized_up_to_message_id": summarized_up_to_message_id,
                "model_id": model_id,
                "updated_at": pg_insert(ChatHistorySummary).excluded.updated_at,
            },
        )
        await db.execute(stmt)
        await db.commit()
