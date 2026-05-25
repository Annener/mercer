from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from config import AppConfig, EmbeddingModelConfig
from config_loader import get_config
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
from storage.binding_manager import create_or_get_binding, increment_chunk_count
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
    config: AppConfig | None = None,
    is_cancelled: CancelCallable | None = None,
    broadcast: BroadcastCallable | None = None,
) -> None:
    config = config or get_config()
    is_cancelled = is_cancelled or (lambda _: False)
    broadcast = broadcast or _noop_broadcast

    try:
        vault = config.vaults[vault_id]
        embedding_model = _select_embedding_model(config)
        provider = _build_provider(embedding_model)
        storage_client = StorageClient(STORAGE_API_URL)

        await create_or_get_binding(vault_id, embedding_model.model_id, provider.dimensions)

        files = await asyncio.to_thread(scan_vault, vault.path)

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

        for file_info in files_info:
            if is_cancelled(task_id):
                await _cancel_task(task_id, broadcast)
                return

            relative_path = str(file_info.get("relative_path", ""))
            if not relative_path:
                logger.warning("Skipping file with missing relative_path")
                continue

            previous_file_state = _previous_file_state(last_state, relative_path)
            if (
                previous_file_state is not None
                and previous_file_state.checksum_md5 == file_info["checksum"]
            ):
                await update_file_status(
                    task_id,
                    relative_path,
                    status="done",
                    progress_pct=100,
                    chunk_ids=previous_file_state.chunk_ids,
                    chunks_total=len(previous_file_state.chunk_ids),
                    chunks_processed=len(previous_file_state.chunk_ids),
                    error=None,
                )
                indexed_count += 1
                await _broadcast_chunk_progress(
                    task_id,
                    relative_path,
                    "done",
                    chunks_total=len(previous_file_state.chunk_ids),
                    chunks_processed=len(previous_file_state.chunk_ids),
                    broadcast=broadcast,
                )
                continue

            try:
                chunk_ids = await _process_file(
                    task_id=task_id,
                    vault_id=vault_id,
                    file_info=file_info,
                    embedding_model=embedding_model,
                    provider=provider,
                    storage_client=storage_client,
                    config=config,
                    is_cancelled=is_cancelled,
                    broadcast=broadcast,
                )
                indexed_count += 1
                await increment_chunk_count(vault_id, len(chunk_ids))
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

        if is_cancelled(task_id):
            await _cancel_task(task_id, broadcast)
            return

        await mark_task_done(task_id)
        final_state = await load_state(task_id)
        if final_state is not None:
            await save_last_successful_state(final_state)
        await _broadcast_task_complete(
            task_id, files_total=len(files_info), files_indexed=indexed_count, broadcast=broadcast
        )
        logger.info("Indexing task completed: task_id=%s vault_id=%s", task_id, vault_id)

    except Exception as exc:
        logger.error("Indexing task failed: task_id=%s vault_id=%s", task_id, vault_id, exc_info=True)
        try:
            if await load_state(task_id) is None:
                await create_state(task_id, vault_id, [])
            await mark_task_done(task_id, error=str(exc))
        except Exception:
            logger.warning("Failed to mark task as error: %s", task_id, exc_info=True)


async def _process_file(
    task_id: str,
    vault_id: str,
    file_info: dict[str, Any],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    storage_client: StorageClient,
    config: AppConfig,
    is_cancelled: CancelCallable,
    broadcast: BroadcastCallable,
) -> list[str]:
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
    )

    await _ensure_not_cancelled(task_id, is_cancelled)
    await update_file_status(task_id, relative_path, "chunking", 35)
    await _broadcast_chunk_progress(task_id, relative_path, "chunking", broadcast=broadcast)

    base_metadata: dict[str, Any] = dict(parsed.get("metadata") or {})
    base_metadata.update({
        "source_path": relative_path,
        "checksum": file_info["checksum"],
        "extension": file_info.get("extension", ""),
        "domain_id": config.vaults[vault_id].domain_id if vault_id in config.vaults else None,
    })
    document_id = _document_id(vault_id, relative_path)

    chunk_size = config.chunking.chunk_size
    overlap = config.chunking.overlap

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
        return []

    if config.chunking.entity_aware_mode:
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
        return []

    # Препроцессинг ПОСЛЕ чанкинга — на каждом чанке отдельно (V3.0)
    for idx, chunk in enumerate(chunks):
        source_hint = f"{relative_path}:chunk_{idx}"
        cleaned = await asyncio.to_thread(preprocess, chunk.text, source_hint)
        chunk.text = cleaned
        chunk.metadata["source_hint"] = source_hint

    chunks = [c for c in chunks if c.text.strip()]
    if not chunks:
        logger.warning("All chunks empty after preprocessing: %s", relative_path)
        await update_file_status(task_id, relative_path, "empty", 100, chunk_ids=[])
        await _broadcast_chunk_progress(task_id, relative_path, "empty", broadcast=broadcast)
        return []

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
    return chunk_ids


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
) -> dict[str, Any]:
    """
    Запускает _parse_file в потоке и параллельно каждые _PARSING_HEARTBEAT_INTERVAL
    секунд шлёт в UI heartbeat-событие stage=parsing, чтобы прогресс-бар не замирал.
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
                # Парсинг ещё идёт — шлём тик в UI
                await _broadcast_chunk_progress(
                    task_id, relative_path, "parsing", broadcast=broadcast
                )
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
) -> list[list[float]]:
    """
    V3.0: кэш и embedding по chunk.metadata["embedding_text"] (обогащённый текст).
    Отправляет прогресс по чанкам каждые CHUNK_PROGRESS_REPORT_INTERVAL чанков.
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
        embedded = await provider.embed(missing_texts)
        for offset, vector in enumerate(embedded):
            if not vector:
                raise ValueError(f"Embedding failed for chunk index {missing_indices[offset]}")
            chunk_index = missing_indices[offset]
            vectors[chunk_index] = vector
            embedding_text = chunks[chunk_index].metadata.get(
                "embedding_text", chunks[chunk_index].text
            )
            await asyncio.to_thread(
                save_cache,
                embedding_text,
                embedding_model.model_id,
                provider.dimensions,
                vector,
            )

            # processed_count = уже закэшированные + только что обработанные
            processed_count = cached_count + offset + 1

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

    return [vector for vector in vectors if vector is not None]


def _select_embedding_model(config: AppConfig) -> EmbeddingModelConfig:
    for embedding_model in config.embedding_models.values():
        if embedding_model.enabled:
            return embedding_model
    raise ValueError("No enabled embedding model configured.")


def _build_provider(embedding_model: EmbeddingModelConfig) -> EmbeddingProvider:
    if embedding_model.provider == "ollama":
        return OllamaEmbeddingProvider(
            base_url=embedding_model.base_url,
            model_name=embedding_model.model_name,
            dimensions=embedding_model.dimensions,
            timeout=embedding_model.timeout_seconds,
            max_retries=embedding_model.max_retries,
        )
    if embedding_model.provider == "openai_compatible":
        api_key_env = getattr(embedding_model, "api_key_env", "OPENAI_API_KEY")
        return OpenAICompatibleProvider(
            base_url=embedding_model.base_url,
            model_name=embedding_model.model_name,
            dimensions=embedding_model.dimensions,
            api_key=os.getenv(api_key_env, ""),
            timeout=embedding_model.timeout_seconds,
            max_retries=embedding_model.max_retries,
        )
    raise ValueError(f"Unsupported embedding provider: {embedding_model.provider}")


def _previous_file_state(
    last_state: IndexState | None, relative_path: str
) -> FileIndexState | None:
    if last_state is None:
        return None
    previous = last_state.files.get(relative_path)
    if previous is None or previous.status not in ("done", "indexed"):
        return None
    return previous


def _document_id(vault_id: str, relative_path: str) -> str:
    digest = hashlib.sha256(f"{vault_id}:{relative_path}".encode("utf-8")).hexdigest()[:16]
    return f"doc{digest}"


document_id = _document_id


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