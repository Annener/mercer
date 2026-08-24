"""Chunking pipeline для одного файла.

Объединяет:
  - парсинг файла (.md / .pdf) с heartbeat-проверкой отмены
  - построение ChunkRecord из raw_chunks
  - назначение page_number и headers (для PDF)

Public API
----------
parse_file_with_progress(absolute_path, extension, task_id, relative_path,
                         state_manager, parser_settings=None) -> dict
build_chunk_records(raw_chunks, document_id, vault_id, base_metadata) -> list[ChunkRecord]
assign_page_numbers_and_headers(chunks, page_offsets, placed_headings) -> None
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from parser.parsing.md_parser import parse_markdown
from parser.parsing.pdf_parser import parse_pdf
from parser.preprocessing.pdf_page_merger import (
    page_number_for_offset,
    resolve_headers_at_offset,
)
from parser.state.redis_state_manager import RedisStateManager

from shared_contracts.models import ChunkRecord

# Средняя длина слова в символах. Используется только для оценки char_offset
# чанка по word_start (для page_number/headers). Не претендует на точность.
AVG_WORD_LEN_CHARS = 6

# Heartbeat-интервал для _parse_file_with_progress (PDF — может идти долго).
_PARSING_HEARTBEAT_INTERVAL = 3.0


def parse_file(path: str, extension: str, parser_settings: dict[str, Any]) -> dict[str, Any]:
    """Синхронный парсинг одного файла по расширению."""
    if extension == ".md":
        return parse_markdown(path)
    if extension == ".pdf":
        return parse_pdf(
            path,
            sidecar_url=str(parser_settings["sidecar_url"]),
            timeout_seconds=float(parser_settings.get("timeout_seconds", 180.0)),
            fallback_to_pdfminer=bool(parser_settings.get("fallback_to_pdfminer", True)),
        )
    raise ValueError(f"Unsupported file extension: {extension}")


async def parse_file_with_progress(
    absolute_path: str,
    extension: str,
    task_id: str,
    relative_path: str,
    state_manager: RedisStateManager,
    parser_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Парсинг файла с heartbeat-проверкой отмены (каждые _PARSING_HEARTBEAT_INTERVAL сек)."""
    del relative_path  # используется только в логах родительского вызывающего кода
    parse_task = asyncio.ensure_future(
        asyncio.to_thread(parse_file, absolute_path, extension, parser_settings or {})
    )
    if extension == ".pdf":
        while not parse_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(parse_task), timeout=_PARSING_HEARTBEAT_INTERVAL
                )
            except TimeoutError:
                if await state_manager.is_cancelled(task_id):
                    parse_task.cancel()
                    raise asyncio.CancelledError
            except asyncio.CancelledError:
                parse_task.cancel()
                raise
            except Exception:  # noqa: BLE001  # exit parse-wait loop on any failure
                break
    return await parse_task


def build_chunk_records(
    raw_chunks: list[str],
    document_id: str,
    vault_id: str,
    base_metadata: dict[str, Any],
) -> list[ChunkRecord]:
    """Преобразовать список текстов чанков в ChunkRecord с word_start/word_end."""
    records: list[ChunkRecord] = []
    global_word_offset = 0

    for raw_text in raw_chunks:
        if not raw_text.strip():
            continue
        word_count = len(raw_text.split())
        chunk_metadata = dict(base_metadata)
        chunk_metadata["word_start"] = global_word_offset
        chunk_metadata["word_end"] = global_word_offset + word_count
        records.append(
            ChunkRecord(
                chunk_id=f"chk_{uuid.uuid4().hex[:12]}",
                document_id=document_id,
                vault_id=vault_id,
                text=raw_text,
                vector=None,
                metadata=chunk_metadata,
                summary=None,
            )
        )
        global_word_offset += word_count

    return records


def assign_page_numbers_and_headers(
    chunks: list[Any],
    page_offsets: list[tuple[int, int]],
    placed_headings: list[dict[str, Any]],
) -> None:
    """Для каждого чанка вычислить page_number и активные headers (только PDF)."""
    for chunk in chunks:
        word_start = int(chunk.metadata.get("word_start", 0))
        estimated_char_offset = word_start * AVG_WORD_LEN_CHARS
        page_number = page_number_for_offset(page_offsets, estimated_char_offset)
        if page_number is not None:
            chunk.metadata["page_number"] = page_number
        headers = resolve_headers_at_offset(placed_headings, estimated_char_offset)
        if headers:
            chunk.metadata["headers"] = headers


__all__ = [
    "AVG_WORD_LEN_CHARS",
    "assign_page_numbers_and_headers",
    "build_chunk_records",
    "parse_file",
    "parse_file_with_progress",
]
