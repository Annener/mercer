from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from app.db_client import IndexerDBClient
from config import EmbeddingModelConfig
from embedding.base_provider import EmbeddingProvider
from embedding.cache import get_cached, save_cache
from embedding.ollama_provider import OllamaEmbeddingProvider
from embedding.openai_provider import OpenAICompatibleProvider
from parser.chunking.embedding_enricher import (
    build_embedding_text,
    extract_markdown_headers,
)
from parser.chunking.entity_chunker import chunk_with_entities
from parser.chunking.generic_chunker import chunk_text
from parser.parsing.md_parser import parse_markdown
from parser.parsing.pdf_parser import parse_pdf
from parser.preprocessing.pdf_page_merger import (
    merge_pdf_pages,
    page_number_for_offset,
    resolve_headers_at_offset,
    strip_page_markers,
)
from parser.preprocessing.preprocessor import preprocess
from parser.scanning.vault_scanner import scan_vault
from parser.state.state_manager import (
    create_state,
    load_last_successful_state,
    load_state,
    mark_task_cancelled,
    mark_task_done,
    save_last_successful_state,
    update_file_status,
)
from shared_contracts.models import (
    FileIndexState,
    IndexState,
    UpsertChunk,
    UpsertRequest,
    WSFileChunkProgressMessage,
    WSFileStatusMessage,
    WSTaskCancelledMessage,
    WSTaskCompleteMessage,
)
from storage.storage_client import StorageClient

logger = logging.getLogger(__name__)

BroadcastCallable = Callable[[str, dict[str, Any]], Awaitable[None]]
CancelCallable = Callable[[str], bool]

STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")

# Эмпирический коэффициент: средний word+space в символах.
_AVG_WORD_LEN_CHARS = 6

# Как часто отправлять прогресс по чанкам (каждые N чанков)
CHUNK_PROGRESS_REPORT_INTERVAL = 10

# Интервал отправки «heartbeat» прогресса на стадии parsing (секунды).
# Во время парсинга PDF sidecar работает долго — без тиков UI не обновляется.
_PARSING_HEARTBEAT_INTERVAL = 3.0


async def run() -> None:
    raise NotImplementedError("Use run_indexing(task_id, vault_id, force_reindex) from the API service.")


async def run_indexing(
    task_id: str,
    vault_id: str,
    force_reindex: bool,
    db_client: IndexerDBClient,
    is_cancelled: CancelCallable | None = None,
    broadcast: BroadcastCallable | None = None,
) -> None:
    is_cancelled = is_cancelled or (lambda _: False)
    broadcast = broadcast or _noop_broadcast

    try:
        settings = await db_client.get_platform_settings()
        vault = await db_client.get_vault(vault_id)
        if vault is None or not vault["enabled"]:
            logger.error("Indexing task aborted: vault missing or disabled: vault_id=%s", vault_id)
            return
        if not vault.get("embedding_model_id"):
            await db_client.update_vault_binding_status(vault_id, "error")
            logger.error("Indexing task aborted: no embedding model bound: vault_id=%s", vault_id)
            return
        embedding_model_data = await db_client.get_embedding_model(vault["embedding_model_id"])
        if embedding_model_data is None:
            await db_client.update_vault_binding_status(vault_id, "error")
            logger.error("Indexing task aborted: embedding model missing: vault_id=%s", vault_id)
            return
        try:
            api_key = db_client.decrypt_api_key(embedding_model_data.get("encrypted_api_key"))
        except Exception:
            await db_client.update_vault_binding_status(vault_id, "error")
            logger.error("Indexing task aborted: failed to decrypt embedding key: vault_id=%s", vault_id, exc_info=True)
            return

        embedding_model = _embedding_model_config(embedding_model_data)
        provider = _build_provider(embedding_model, api_key)
        storage_client = StorageClient(STORAGE_API_URL)
        await db_client.update_vault_binding_status(vault_id, "indexing")

        vault_path = f"/data/vaults/{vault_id}"
        chunk_size = vault.get("chunk_size") or settings["chunking.chunk_size"]
        overlap = vault.get("overlap") or settings["chunking.overlap"]
        entity_aware = vault.get("entity_aware_mode")
        if entity_aware is None:
            entity_aware = settings["chunking.entity_aware_mode"]
        worlds = await db_client.get_worlds_for_vault(vault_id)

        files = await asyncio.to_thread(scan_vault, vault_path)

        files_info: list[dict[str, Any]] = []
        for f in files:
            relative_path = str(f.get("relative_path", "")).strip()
            if not relative_path:
                logger.warning("Skipping file with missing relative_path: %s", f.get("path", "unknown"))
                continue

            files_info.append({
                "relative_path": relative_path,
                "path": str(f["path"]),
                "checksum": f["checksum"],
                "last_modified": f["last_modified"],
                "extension": str(f.get("extension", "")),
            })

        await create_state(task_id, vault_id, files_info)

        last_state = None if force_reindex else await load_last_successful_state(vault_id)
        indexed_count = 0
        uploaded_document_ids: list[str] = []

        for file_info in files_info:
            if is_cancelled(task_id):
                await _cancel_task(task_id, broadcast)
                return

            relative_path = str(file_info.get("relative_path", ""))
            if not relative_path:
                logger.warning("Skipping file with missing relative_path")
                continue

            previous_file_state = _previous_file_state(last_state, relative_path)
            skip_reason = _should_skip(previous_file_state, file_info["checksum"])
            if skip_reason is not None:
                logger.debug("Skipping file %s: %s", relative_path, skip_reason)
                await update_file_status(
                    task_id,
                    relative_path,
                    status="done",
                    progress_pct=100,
                    chunk_ids=previous_file_state.chunk_ids,  # type: ignore[union-attr]
                    chunks_total=len(previous_file_state.chunk_ids),  # type: ignore[union-attr]
                    chunks_processed=len(previous_file_state.chunk_ids),  # type: ignore[union-attr]
                    error=None,
                )
                indexed_count += 1
                await _broadcast_chunk_progress(
                    task_id,
                    relative_path,
                    "done",
                    chunks_total=len(previous_file_state.chunk_ids),  # type: ignore[union-attr]
                    chunks_processed=len(previous_file_state.chunk_ids),  # type: ignore[union-attr]
                    broadcast=broadcast,
                )
                continue

            if previous_file_state is not None:
                logger.info(
                    "Re-indexing file %s (prev_status=%s checksum_match=%s)",
                    relative_path,
                    previous_file_state.status,
                    previous_file_state.checksum_md5 == file_info["checksum"],
                )

            try:
                chunk_ids, _document_id_uploaded = await _process_file(
                    task_id=task_id,
                    vault_id=vault_id,
                    file_info=file_info,
                    embedding_model=embedding_model,
                    provider=provider,
                    storage_client=storage_client,
                    vault=vault,
                    chunk_size=int(chunk_size),
                    overlap=int(overlap),
                    entity_aware=bool(entity_aware),
                    worlds=worlds,
                    uploaded_document_ids=uploaded_document_ids,
                    is_cancelled=is_cancelled,
                    broadcast=broadcast,
                )
                indexed_count += 1
                await db_client.update_vault_chunk_count(vault_id, len(chunk_ids))
            except asyncio.CancelledError:
                await _cancel_task(task_id, broadcast)
                return
            except Exception as exc:
                logger.warning("Failed to index file %s", relative_path, exc_info=True)
                try:
                    await update_file_status(
                        task_id,
                        relative_path,
                        status="error",
                        progress_pct=100,
                        error=str(exc),
                    )
                except Exception as state_err:
                    logger.error("Failed to update state for %s: %s", relative_path, state_err)
                await _broadcast_chunk_progress(
                    task_id, relative_path, "error", broadcast=broadcast, error=str(exc)
                )
                if uploaded_document_ids:
                    logger.warning("Partial indexing detected. Rolling back documents: %s", uploaded_document_ids)
                    for document_id in uploaded_document_ids:
                        try:
                            await storage_client.delete_document(document_id, vault_id)
                        except Exception:
                            logger.critical("Failed to rollback document %s", document_id, exc_info=True)
                    await db_client.update_vault_binding_status(vault_id, "error")
                raise

        if is_cancelled(task_id):
            await _cancel_task(task_id, broadcast)
            return

        await mark_task_done(task_id)
        await db_client.update_vault_binding_status(vault_id, "bound")
        final_state = await load_state(task_id)
        if final_state is not None:
            # Сохраняем полный state как есть — включая файлы с error.
            # При следующем запуске error-файлы будут переиндексированы,
            # done/indexed — пропущены (если checksum совпадает).
            await save_last_successful_state(final_state)
        await _broadcast_task_complete(
            task_id, files_total=len(files_info), files_indexed=indexed_count, broadcast=broadcast
        )
        logger.info("Indexing task completed: task_id=%s vault_id=%s", task_id, vault_id)

    except Exception as exc:
        try:
            await db_client.update_vault_binding_status(vault_id, "error")
        except Exception:
            logger.warning("Failed to update vault status after indexing error: vault_id=%s", vault_id, exc_info=True)
        logger.error("Indexing task failed: task_id=%s vault_id=%s", task_id, vault_id, exc_info=True)
        try:
            if await load_state(task_id) is None:
                await create_state(task_id, vault_id, [])
            await mark_task_done(task_id, error=str(exc))
            # Сохраняем частичный state даже при падении задачи.
            # Файлы которые успели завершиться (done/indexed/empty) не будут
            # переиндексированы при следующем запуске; error-файлы — будут.
            partial_state = await load_state(task_id)
            if partial_state is not None:
                await save_last_successful_state(partial_state)
        except Exception:
            logger.warning("Failed to mark task as error: %s", task_id, exc_info=True)


async def _process_file(
    task_id: str,
    vault_id: str,
    file_info: dict[str, Any],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    storage_client: StorageClient,
    vault: dict[str, Any],
    chunk_size: int,
    overlap: int,
    entity_aware: bool,
    worlds: list[dict[str, Any]],
    uploaded_document_ids: list[str],
    is_cancelled: CancelCallable,
    broadcast: BroadcastCallable,
) -> tuple[list[str], str]:
    absolute_path = str(file_info["path"])
    relative_path = str(file_info.get("relative_path", ""))

    await _ensure_not_cancelled(task_id, is_cancelled)
    await update_file_status(task_id, relative_path, "parsing", 10)
    await _broadcast_chunk_progress(task_id, relative_path, "parsing", broadcast=broadcast)

    parsed = await _parse_file_with_progress(
        absolute_path,
        str(file_info.get("extension", "")),
        task_id=task_id,
        relative_path=relative_path,
        broadcast=broadcast,
        is_cancelled=is_cancelled,
    )

    await _ensure_not_cancelled(task_id, is_cancelled)
    await update_file_status(task_id, relative_path, "chunking", 35)
    await _broadcast_chunk_progress(task_id, relative_path, "chunking", broadcast=broadcast)

    base_metadata: dict[str, Any] = dict(parsed.get("metadata") or {})
    base_metadata.update({
        "source_path": relative_path,
        "checksum": file_info["checksum"],
        "extension": file_info.get("extension", ""),
        "domain_id": vault.get("domain_id"),
    })
    base_metadata.update(_extract_world_metadata(relative_path, worlds))
    document_id = _document_id(vault_id, relative_path)

    is_pdf = "pages" in parsed

    page_offsets: list[tuple[int, int]] = []
    placed_headings: list[dict[str, Any]] = []
    text_for_chunking: str = ""

    if is_pdf:
        merged_text, page_offsets, placed_headings = await asyncio.to_thread(
            merge_pdf_pages,
            parsed["pages"],
            parsed.get("headings"),
        )
        text_for_chunking = merged_text
    else:
        text_for_chunking = str(parsed.get("text", ""))

    if not text_for_chunking.strip():
        logger.warning("No text extracted from file: %s", relative_path)
        await update_file_status(task_id, relative_path, "empty", 100, chunk_ids=[])
        await _broadcast_chunk_progress(task_id, relative_path, "empty", broadcast=broadcast)
        return [], document_id

    if entity_aware:
        chunks, _entities = await asyncio.to_thread(
            chunk_with_entities,
            text_for_chunking,
            document_id,
            vault_id,
            chunk_size,
            overlap,
            base_metadata,
        )
    else:
        chunks = await asyncio.to_thread(
            chunk_text,
            text_for_chunking,
            document_id,
            vault_id,
            chunk_size,
            overlap,
            base_metadata,
        )

    if not chunks:
        logger.warning("No valid chunks generated for file: %s", relative_path)
        await update_file_status(task_id, relative_path, "empty", 100, chunk_ids=[])
        await _broadcast_chunk_progress(task_id, relative_path, "empty", broadcast=broadcast)
        return [], document_id

    # Препроцессинг ПОСЛЕ чанкинга — на каждом чанке отдельно (V3.0)
    for idx, chunk in enumerate(chunks):
        source_hint = f"{relative_path}:chunk_{idx}"
        # Удаляем <!--PAGE:N--> из текста чанка — они нужны только для
        # восстановления page_number, в чанках LLM они мешают пониманию текста.
        chunk.text = strip_page_markers(chunk.text)
        cleaned = await asyncio.to_thread(preprocess, chunk.text, source_hint)
        chunk.text = cleaned
        chunk.metadata["source_hint"] = source_hint

    chunks = [c for c in chunks if c.text.strip()]
    if not chunks:
        logger.warning("All chunks empty after preprocessing: %s", relative_path)
        await update_file_status(task_id, relative_path, "empty", 100, chunk_ids=[])
        await _broadcast_chunk_progress(task_id, relative_path, "empty", broadcast=broadcast)
        return [], document_id

    # Для PDF: восстановление page_number и активного заголовка
    if is_pdf:
        _assign_page_numbers_and_headers(chunks, page_offsets, placed_headings)

    # Формирование embedding_text (V3.0 Dual-Text Pattern)
    for chunk in chunks:
        source_path = chunk.metadata.get("source_path", relative_path)
        headers = chunk.metadata.get("headers")

        if not is_pdf and not headers:
            headers = extract_markdown_headers(chunk.text)

        embedding_text = build_embedding_text(
            chunk_text=chunk.text,
            source_path=source_path,
            headers=headers,
            content_type=chunk.metadata.get("content_type"),
        )
        chunk.metadata["embedding_text"] = embedding_text
        if headers:
            chunk.metadata["headers"] = headers

    # Embedding по embedding_text (V3.0)
    await _ensure_not_cancelled(task_id, is_cancelled)
    await update_file_status(
        task_id,
        relative_path,
        "indexing",
        65,
        chunks_total=len(chunks),
        chunks_processed=0,
    )
    await _broadcast_chunk_progress(
        task_id,
        relative_path,
        "indexing",
        chunks_total=len(chunks),
        chunks_processed=0,
        broadcast=broadcast,
    )

    vectors = await _embed_chunks(
        chunks,
        embedding_model,
        provider,
        task_id=task_id,
        file_path=relative_path,
        broadcast=broadcast,
        is_cancelled=is_cancelled,
    )
    if len(vectors) != len(chunks):
        raise ValueError("Embedding provider returned an unexpected number of vectors.")

    upsert_chunks = [
        UpsertChunk(
            document_id=document_id,
            chunk_index=index,
            text=chunk.text,
            vector=vectors[index],
            metadata=chunk.metadata,
        )
        for index, chunk in enumerate(chunks)
    ]

    response = await storage_client.upsert_with_retry(
        UpsertRequest(vault_id=vault_id, chunks=upsert_chunks)
    )
    if response.status == "partial":
        raise ValueError(f"Failed to upsert chunk indices: {response.failed_indices}")
    uploaded_document_ids.append(document_id)

    chunk_ids = [f"{document_id}_{index}" for index in range(len(upsert_chunks))]
    await update_file_status(
        task_id,
        relative_path,
        "done",
        100,
        chunk_ids=chunk_ids,
        chunks_total=len(chunks),
        chunks_processed=len(chunks),
    )
    await _broadcast_chunk_progress(
        task_id,
        relative_path,
        "done",
        chunks_total=len(chunks),
        chunks_processed=len(chunks),
        broadcast=broadcast,
    )
    return chunk_ids, document_id


def _assign_page_numbers_and_headers(
    chunks: list[Any],
    page_offsets: list[tuple[int, int]],
    placed_headings: list[dict[str, Any]],
) -> None:
    """
    Для каждого PDF-чанка восстанавливает:
    - metadata["page_number"]
    - metadata["headers"]
    """
    for chunk in chunks:
        word_start = int(chunk.metadata.get("word_start", 0))
        estimated_char_offset = word_start * _AVG_WORD_LEN_CHARS

        page_number = page_number_for_offset(page_offsets, estimated_char_offset)
        if page_number is not None:
            chunk.metadata["page_number"] = page_number

        headers = resolve_headers_at_offset(placed_headings, estimated_char_offset)
        if headers:
            chunk.metadata["headers"] = headers


def _parse_file(path: str, extension: str) -> dict[str, Any]:
    if extension == ".md":
        return parse_markdown(path)
    if extension == ".pdf":
        return parse_pdf(path)
    raise ValueError(f"Unsupported file extension: {extension}")


async def _parse_file_with_progress(
    absolute_path: str,
    extension: str,
    task_id: str,
    relative_path: str,
    broadcast: BroadcastCallable,
    is_cancelled: CancelCallable | None = None,
) -> dict[str, Any]:
    """
    Запускает _parse_file в потоке и параллельно каждые _PARSING_HEARTBEAT_INTERVAL
    секунд шлёт в UI heartbeat-событие stage=parsing, чтобы прогресс-бар не замирал.
    Если is_cancelled() вернёт True — отменяет parse_task и бросает CancelledError.
    Замечание: asyncio.to_thread дождётся завершения текущего HTTP-запроса к sidecar,
    но следующую страницу/батч уже не запустит.
    """
    parse_task = asyncio.ensure_future(
        asyncio.to_thread(_parse_file, absolute_path, extension)
    )

    # Для не-PDF heartbeat не нужен — парсинг быстрый
    if extension == ".pdf":
        while not parse_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(parse_task), timeout=_PARSING_HEARTBEAT_INTERVAL
                )
            except asyncio.TimeoutError:
                # Проверяем флаг отмены — если выставлен, прерываем парсинг немедленно
                if is_cancelled is not None and is_cancelled(task_id):
                    parse_task.cancel()
                    raise asyncio.CancelledError
                # Парсинг ещё идёт — шлём тик в UI
                await _broadcast_chunk_progress(
                    task_id, relative_path, "parsing", broadcast=broadcast
                )
            except asyncio.CancelledError:
                parse_task.cancel()
                raise
            except Exception:
                break  # ошибка поймается ниже при await parse_task

    return await parse_task


async def _embed_chunks(
    chunks: list[Any],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    task_id: str | None = None,
    file_path: str | None = None,
    broadcast: BroadcastCallable | None = None,
    is_cancelled: CancelCallable | None = None,
) -> list[list[float]]:
    """
    V3.0: кэш и embedding по chunk.metadata["embedding_text"] (обогащённый текст).
    Отправляет прогресс по чанкам каждые CHUNK_PROGRESS_REPORT_INTERVAL чанков.
    Проверяет is_cancelled() перед каждым embed вызовом и бросает CancelledError.
    """
    vectors: list[list[float] | None] = []
    missing_texts: list[str] = []
    missing_indices: list[int] = []

    for index, chunk in enumerate(chunks):
        embedding_text = chunk.metadata.get("embedding_text", chunk.text)
        cached = await asyncio.to_thread(
            get_cached, embedding_text, embedding_model.model_id, provider.dimensions
        )
        if cached is None:
            vectors.append(None)
            missing_texts.append(embedding_text)
            missing_indices.append(index)
        else:
            vectors.append(cached)

    # Количество чанков с кэш-попаданием — они уже «обработаны» до начала embed
    cached_count = len(chunks) - len(missing_texts)

    if missing_texts:
        logger.info(
            "Embedding start: file=%s total_chunks=%d cached=%d to_embed=%d model=%s",
            file_path or "?", len(chunks), cached_count, len(missing_texts), embedding_model.model_id,
        )
        embed_start_time = asyncio.get_event_loop().time()

        # Embed по одному чанку — чтобы прогресс транслировался после каждого,
        # а не после окончания всего батча (fix: 8.5-минутная тишина).
        for offset, embedding_text in enumerate(missing_texts):
            # Проверяем отмену перед каждым embed-вызовом
            if is_cancelled is not None and task_id is not None and is_cancelled(task_id):
                raise asyncio.CancelledError
            result = await provider.embed([embedding_text])
            if not result or not result[0]:
                raise ValueError(f"Embedding failed for chunk index {missing_indices[offset]}")
            vector = result[0]

            chunk_index = missing_indices[offset]
            vectors[chunk_index] = vector

            await asyncio.to_thread(
                save_cache,
                embedding_text,
                embedding_model.model_id,
                provider.dimensions,
                vector,
            )

            # processed_count = уже закэшированные + только что обработанные
            processed_count = cached_count + offset + 1

            # Лог прогресса embedding есть здесь: каждые N чанков или последний
            if processed_count % CHUNK_PROGRESS_REPORT_INTERVAL == 0 or processed_count == len(chunks):
                elapsed = asyncio.get_event_loop().time() - embed_start_time
                rate = (offset + 1) / elapsed if elapsed > 0 else 0
                eta = (len(missing_texts) - offset - 1) / rate if rate > 0 else 0
                logger.info(
                    "Embedding progress: file=%s %d/%d chunks (%.1f c/s, ETA ~%.0fs)",
                    file_path or "?", processed_count, len(chunks), rate, eta,
                )

            # Прогресс по чанкам каждые N или на последнем
            if (
                broadcast is not None
                and task_id is not None
                and file_path is not None
                and (
                    processed_count % CHUNK_PROGRESS_REPORT_INTERVAL == 0
                    or processed_count == len(chunks)
                )
            ):
                await _broadcast_chunk_progress(
                    task_id,
                    file_path,
                    "indexing",
                    chunks_total=len(chunks),
                    chunks_processed=processed_count,
                    broadcast=broadcast,
                )

        logger.info(
            "Embedding complete: file=%s %d chunks embedded in %.1fs",
            file_path or "?", len(missing_texts),
            asyncio.get_event_loop().time() - embed_start_time,
        )

    return [vector for vector in vectors if vector is not None]


def _embedding_model_config(model: dict[str, Any]) -> EmbeddingModelConfig:
    return EmbeddingModelConfig(
        model_id=model["model_id"],
        provider=model["provider"],
        model_name=model["model_name"],
        base_url=model["base_url"],
        dimensions=int(model["dimensions"]),
        enabled=bool(model.get("enabled", True)),
        timeout_seconds=int(model.get("timeout_seconds", 30)),
        max_retries=int(model.get("max_retries", 3)),
    )


def _build_provider(embedding_model: EmbeddingModelConfig, api_key: str = "") -> EmbeddingProvider:
    if embedding_model.provider == "ollama":
        return OllamaEmbeddingProvider(
            base_url=embedding_model.base_url,
            model_name=embedding_model.model_name,
            dimensions=embedding_model.dimensions,
            timeout=embedding_model.timeout_seconds,
            max_retries=embedding_model.max_retries,
        )
    if embedding_model.provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=embedding_model.base_url,
            model_name=embedding_model.model_name,
            dimensions=embedding_model.dimensions,
            api_key=api_key,
            timeout=embedding_model.timeout_seconds,
            max_retries=embedding_model.max_retries,
        )
    raise ValueError(f"Unsupported embedding provider: {embedding_model.provider}")


def _previous_file_state(
    last_state: IndexState | None, relative_path: str
) -> FileIndexState | None:
    """Возвращает FileIndexState из last_state если файл там есть.

    Возвращает состояние для любого статуса (done, indexed, empty, error).
    Вызывающий код сам решает что делать:
    - done/indexed + checksum совпадает → пропустить
    - error → переиндексировать (даже если checksum тот же)
    - empty → пропустить (файл уже пытались — он пустой)
    - None (файла нет в стейте) → новый файл, индексировать
    """
    if last_state is None:
        return None
    return last_state.files.get(relative_path)


def _should_skip(previous: FileIndexState | None, current_checksum: str) -> str | None:
    """Определяет нужно ли пропустить файл.

    Возвращает строку-причину если нужно пропустить, None — если нужно индексировать.

    Правила:
    - Файла нет в стейте (previous=None) → новый, индексировать
    - done/indexed + checksum совпадает → пропустить
    - done/indexed + checksum изменился → файл изменён, индексировать
    - empty + checksum совпадает → пропустить (файл уже пытались, он пустой)
    - error → переиндексировать (даже если checksum тот же)
    - cancelled/pending/parsing/chunking/indexing → индексировать (задача была прервана)
    """
    if previous is None:
        return None  # новый файл

    if previous.status in ("done", "indexed"):
        if previous.checksum_md5 == current_checksum:
            return f"already indexed (status={previous.status})"
        return None  # файл изменён — переиндексировать

    if previous.status == "empty":
        if previous.checksum_md5 == current_checksum:
            return "previously empty, checksum unchanged"
        return None  # файл изменился — попытаться ещё раз

    # error / cancelled / pending / parsing / chunking / indexing — переиндексировать
    return None


def _document_id(vault_id: str, relative_path: str) -> str:
    digest = hashlib.sha256(f"{vault_id}:{relative_path}".encode("utf-8")).hexdigest()[:16]
    return f"doc{digest}"


document_id = _document_id


def _extract_world_metadata(relative_path: str, worlds: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_path = relative_path.lstrip("/")
    for world in worlds:
        prefix = str(world.get("path_prefix", "")).strip("/")
        if not prefix:
            continue
        prefix_with_sep = f"{prefix}/"
        if normalized_path != prefix and not normalized_path.startswith(prefix_with_sep):
            continue
        remainder = normalized_path.removeprefix(prefix_with_sep)
        parts = [part for part in remainder.split("/") if part]
        category = parts[0] if parts else None
        campaign_id = None
        if category == "campaigns" and len(parts) > 1:
            campaign_id = parts[1]
        return {
            "world_id": world.get("world_id"),
            "category": category,
            "campaign_id": campaign_id,
        }
    return {}


async def _ensure_not_cancelled(task_id: str, is_cancelled: CancelCallable) -> None:
    if is_cancelled(task_id):
        raise asyncio.CancelledError


async def _cancel_task(task_id: str, broadcast: BroadcastCallable) -> None:
    await mark_task_cancelled(task_id)
    event = WSTaskCancelledMessage(task_id=task_id)
    await broadcast(task_id, event.model_dump(mode="json"))


async def _broadcast_chunk_progress(
    task_id: str,
    file_path: str,
    stage: str,
    chunks_total: int = 0,
    chunks_processed: int = 0,
    broadcast: BroadcastCallable | None = None,
    error: str | None = None,
) -> None:
    """Отправляет WSFileChunkProgressMessage (V3.0)."""
    if broadcast is None:
        return
    event = WSFileChunkProgressMessage(
        task_id=task_id,
        file_path=file_path,
        stage=stage,  # type: ignore[arg-type]
        chunks_total=chunks_total,
        chunks_processed=chunks_processed,
        error=error,
    )
    await broadcast(task_id, event.model_dump(mode="json"))


async def _broadcast_task_complete(
    task_id: str,
    files_total: int,
    files_indexed: int,
    broadcast: BroadcastCallable,
) -> None:
    event = WSTaskCompleteMessage(
        task_id=task_id, files_total=files_total, files_indexed=files_indexed
    )
    await broadcast(task_id, event.model_dump(mode="json"))


async def _noop_broadcast(_task_id: str, _message: dict[str, Any]) -> None:
    return None
