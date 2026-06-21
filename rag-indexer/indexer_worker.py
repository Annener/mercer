from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.db_client import IndexerDBClient
from config import EmbeddingModelConfig
from embedding.base_provider import EmbeddingProvider
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
from parser.state.redis_state_manager import RedisStateManager
from shared_contracts.models import (
    UpsertChunk,
    UpsertRequest,
)
from storage.storage_client import StorageClient

logger = logging.getLogger(__name__)

STORAGE_API_URL = os.getenv("STORAGE_API_URL", "http://db-api-server:8080")

_AVG_WORD_LEN_CHARS = 6
CHUNK_PROGRESS_REPORT_INTERVAL = 10
_PARSING_HEARTBEAT_INTERVAL = 3.0
CHECK_CANCEL_INTERVAL = 10  # проверять отмену каждые N чанков при эмбеддинге


async def run() -> None:
    raise NotImplementedError("Use run_indexing(task_id, vault_id, force_reindex) from the API service.")


async def run_indexing(
    task_id: str,
    vault_id: str,
    force_reindex: bool,
    db_client: IndexerDBClient,
    state_manager: RedisStateManager,
) -> None:
    """Основной воркер индексации. Использует RedisStateManager для хранения состояния."""
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
        parser_settings = {
            "sidecar_url": settings["pdf_sidecar.url"],
            "timeout_seconds": float(settings["pdf_sidecar.timeout_seconds"]),
            "fallback_to_pdfminer": bool(settings["pdf_sidecar.fallback_to_pdfminer"]),
        }

        all_files = await asyncio.to_thread(scan_vault, vault_path)

        all_files_info: list[dict[str, Any]] = []
        for f in all_files:
            relative_path = str(f.get("relative_path", "")).strip()
            if not relative_path:
                logger.warning("Skipping file with missing relative_path: %s", f.get("path", "unknown"))
                continue
            all_files_info.append({
                "relative_path": relative_path,
                "path": str(f["path"]),
                "checksum": f["checksum"],
                "last_modified": f["last_modified"],
                "extension": str(f.get("extension", "")),
            })

        # Разделяем файлы на «нужно индексировать» и «пропустить»
        new_and_changed: list[dict[str, Any]] = []
        skipped_files: list[dict[str, Any]] = []

        if not force_reindex:
            for file_info in all_files_info:
                relative_path = str(file_info.get("relative_path", ""))
                md5 = file_info["checksum"]
                mtime = int(file_info.get("last_modified") or 0)
                doc = await db_client.get_document_by_path(vault_id, relative_path)
                if doc is not None and doc["md5"] == md5 and doc["mtime"] == mtime and doc["status"] == "indexed":
                    skipped_files.append(file_info)
                else:
                    new_and_changed.append(file_info)
        else:
            new_and_changed = all_files_info

        # Создаём задачу в Redis
        await state_manager.create_task(
            task_id=task_id,
            vault_id=vault_id,
            files_to_index=[{"relative_path": f["relative_path"]} for f in new_and_changed],
            files_skipped=len(skipped_files),
            files_total=len(all_files_info),
        )

        indexed_count = 0
        uploaded_document_ids: list[str] = []

        for file_info in new_and_changed:
            if await state_manager.is_cancelled(task_id):
                await state_manager.mark_task_cancelled(task_id)
                return

            relative_path = str(file_info.get("relative_path", ""))
            if not relative_path:
                logger.warning("Skipping file with missing relative_path")
                continue

            absolute_path = str(file_info["path"])
            md5 = file_info["checksum"]
            mtime = int(file_info.get("last_modified") or 0)

            # Проверяем запись в таблице documents
            doc = await db_client.get_document_by_path(vault_id, relative_path)

            if doc is None:
                doc = await db_client.create_document(vault_id, relative_path, md5, mtime)
                logger.info("New document registered: %s id=%s", relative_path, doc["id"])
            else:
                # Файл изменился или force_reindex — удаляем старые чанки и переиндексируем
                logger.info(
                    "Re-indexing file (changed or forced): %s id=%s force=%s",
                    relative_path, doc["id"], force_reindex,
                )
                await _delete_chunks_from_lancedb(str(doc["id"]), vault_id, storage_client)
                await db_client.update_document_status(
                    str(doc["id"]), "pending", md5=md5, mtime=mtime
                )
                doc = await db_client.get_document_by_path(vault_id, relative_path)

            try:
                chunks_count, _doc_id = await _process_file(
                    task_id=task_id,
                    vault_id=vault_id,
                    file_info=file_info,
                    doc=doc,
                    embedding_model=embedding_model,
                    provider=provider,
                    storage_client=storage_client,
                    vault=vault,
                    chunk_size=int(chunk_size),
                    overlap=int(overlap),
                    entity_aware=bool(entity_aware),
                    parser_settings=parser_settings,
                    uploaded_document_ids=uploaded_document_ids,
                    state_manager=state_manager,
                    db_client=db_client,
                )
                indexed_count += 1
                await state_manager.increment_files_done(task_id)
                await state_manager.mark_file_indexed(vault_id, relative_path, md5, chunks_count)
                await db_client.update_vault_chunk_count(vault_id, chunks_count)
            except asyncio.CancelledError:
                await state_manager.mark_task_cancelled(task_id)
                return
            except Exception as exc:
                logger.warning("Failed to index file %s", relative_path, exc_info=True)
                try:
                    await state_manager.update_file_stage(
                        task_id,
                        relative_path,
                        stage="error",
                        error=str(exc),
                    )
                except Exception as state_err:
                    logger.error("Failed to update state for %s: %s", relative_path, state_err)
                if uploaded_document_ids:
                    logger.warning("Partial indexing detected. Rolling back documents: %s", uploaded_document_ids)
                    for document_id in uploaded_document_ids:
                        try:
                            await storage_client.delete_document(document_id, vault_id)
                        except Exception:
                            logger.critical("Failed to rollback document %s", document_id, exc_info=True)
                    await db_client.update_vault_binding_status(vault_id, "error")
                raise

        if await state_manager.is_cancelled(task_id):
            await state_manager.mark_task_cancelled(task_id)
            return

        await state_manager.mark_task_done(task_id)
        await db_client.update_vault_binding_status(vault_id, "bound")
        logger.info("Indexing task completed: task_id=%s vault_id=%s", task_id, vault_id)

    except Exception as exc:
        try:
            await db_client.update_vault_binding_status(vault_id, "error")
        except Exception:
            logger.warning("Failed to update vault status after indexing error: vault_id=%s", vault_id, exc_info=True)
        logger.error("Indexing task failed: task_id=%s vault_id=%s", task_id, vault_id, exc_info=True)
        try:
            await state_manager.mark_task_done(task_id, error=str(exc))
        except Exception:
            logger.warning("Failed to mark task as error: %s", task_id, exc_info=True)


async def _delete_chunks_from_lancedb(
    document_id: str,
    vault_id: str,
    storage_client: StorageClient,
) -> None:
    """Удаляет все чанки документа из LanceDB перед переиндексацией."""
    try:
        await storage_client.delete_document(document_id, vault_id)
        logger.info("Deleted LanceDB chunks for document_id=%s vault_id=%s", document_id, vault_id)
    except Exception:
        logger.warning(
            "Failed to delete LanceDB chunks for document_id=%s vault_id=%s",
            document_id, vault_id, exc_info=True,
        )


async def _process_file(
    task_id: str,
    vault_id: str,
    file_info: dict[str, Any],
    doc: dict[str, Any],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    storage_client: StorageClient,
    vault: dict[str, Any],
    chunk_size: int,
    overlap: int,
    entity_aware: bool,
    parser_settings: dict[str, Any],
    uploaded_document_ids: list[str],
    state_manager: RedisStateManager,
    db_client: IndexerDBClient,
) -> tuple[int, str]:
    """Обрабатывает один файл. Возвращает (chunks_count, pg_document_id)."""
    absolute_path = str(file_info["path"])
    relative_path = str(file_info.get("relative_path", ""))
    pg_document_id = str(doc["id"])

    if await state_manager.is_cancelled(task_id):
        raise asyncio.CancelledError

    await state_manager.update_file_stage(task_id, relative_path, stage="parsing")

    parsed = await _parse_file_with_progress(
        absolute_path,
        str(file_info.get("extension", "")),
        task_id=task_id,
        relative_path=relative_path,
        state_manager=state_manager,
        parser_settings=parser_settings,
    )

    if await state_manager.is_cancelled(task_id):
        raise asyncio.CancelledError

    await state_manager.update_file_stage(task_id, relative_path, stage="chunking")

    base_metadata: dict[str, Any] = dict(parsed.get("metadata") or {})
    base_metadata.update({
        "source_path": relative_path,
        "checksum": file_info["checksum"],
        "extension": file_info.get("extension", ""),
        "domain_id": vault.get("domain_id"),
    })

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
        await state_manager.update_file_stage(task_id, relative_path, stage="empty")
        await db_client.update_document_status(pg_document_id, "indexed",
                                                indexed_at=datetime.now(tz=timezone.utc))
        return 0, pg_document_id

    if entity_aware:
        chunks, _entities = await asyncio.to_thread(
            chunk_with_entities,
            text_for_chunking,
            pg_document_id,
            vault_id,
            chunk_size,
            overlap,
            base_metadata,
        )
    else:
        chunks = await asyncio.to_thread(
            chunk_text,
            text_for_chunking,
            pg_document_id,
            vault_id,
            chunk_size,
            overlap,
            base_metadata,
        )

    if not chunks:
        logger.warning("No valid chunks generated for file: %s", relative_path)
        await state_manager.update_file_stage(task_id, relative_path, stage="empty")
        await db_client.update_document_status(pg_document_id, "indexed",
                                                indexed_at=datetime.now(tz=timezone.utc))
        return 0, pg_document_id

    for idx, chunk in enumerate(chunks):
        source_hint = f"{relative_path}:chunk_{idx}"
        chunk.text = strip_page_markers(chunk.text)
        cleaned = await asyncio.to_thread(preprocess, chunk.text, source_hint)
        chunk.text = cleaned
        chunk.metadata["source_hint"] = source_hint

    chunks = [c for c in chunks if c.text.strip()]
    if not chunks:
        logger.warning("All chunks empty after preprocessing: %s", relative_path)
        await state_manager.update_file_stage(task_id, relative_path, stage="empty")
        await db_client.update_document_status(pg_document_id, "indexed",
                                                indexed_at=datetime.now(tz=timezone.utc))
        return 0, pg_document_id

    if is_pdf:
        _assign_page_numbers_and_headers(chunks, page_offsets, placed_headings)

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

    if await state_manager.is_cancelled(task_id):
        raise asyncio.CancelledError

    await state_manager.update_file_stage(
        task_id, relative_path, stage="indexing",
        chunks_total=len(chunks), chunks_done=0,
    )

    vectors = await _embed_chunks(
        chunks, embedding_model, provider,
        task_id=task_id, file_path=relative_path,
        state_manager=state_manager,
    )
    if len(vectors) != len(chunks):
        raise ValueError("Embedding provider returned an unexpected number of vectors.")

    upsert_chunks = [
        UpsertChunk(
            document_id=pg_document_id,
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
    uploaded_document_ids.append(pg_document_id)

    await db_client.update_document_status(
        pg_document_id,
        "indexed",
        indexed_at=datetime.now(tz=timezone.utc),
    )

    await state_manager.update_file_stage(
        task_id, relative_path, stage="done",
        chunks_total=len(chunks), chunks_done=len(chunks),
        checksum_md5=file_info["checksum"],
    )
    return len(chunks), pg_document_id


def _assign_page_numbers_and_headers(
    chunks: list[Any],
    page_offsets: list[tuple[int, int]],
    placed_headings: list[dict[str, Any]],
) -> None:
    for chunk in chunks:
        word_start = int(chunk.metadata.get("word_start", 0))
        estimated_char_offset = word_start * _AVG_WORD_LEN_CHARS
        page_number = page_number_for_offset(page_offsets, estimated_char_offset)
        if page_number is not None:
            chunk.metadata["page_number"] = page_number
        headers = resolve_headers_at_offset(placed_headings, estimated_char_offset)
        if headers:
            chunk.metadata["headers"] = headers


def _parse_file(path: str, extension: str, parser_settings: dict[str, Any]) -> dict[str, Any]:
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


async def _parse_file_with_progress(
    absolute_path: str,
    extension: str,
    task_id: str,
    relative_path: str,
    state_manager: RedisStateManager,
    parser_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parse_task = asyncio.ensure_future(
        asyncio.to_thread(_parse_file, absolute_path, extension, parser_settings or {})
    )
    if extension == ".pdf":
        while not parse_task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(parse_task), timeout=_PARSING_HEARTBEAT_INTERVAL
                )
            except asyncio.TimeoutError:
                if await state_manager.is_cancelled(task_id):
                    parse_task.cancel()
                    raise asyncio.CancelledError
                # heartbeat — просто ждём дальше
            except asyncio.CancelledError:
                parse_task.cancel()
                raise
            except Exception:
                break
    return await parse_task


async def _embed_chunks(
    chunks: list[Any],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    task_id: str | None = None,
    file_path: str | None = None,
    state_manager: RedisStateManager | None = None,
) -> list[list[float]]:
    vectors: list[list[float]] = []

    logger.info(
        "Embedding start: file=%s total_chunks=%d model=%s",
        file_path or "?", len(chunks), embedding_model.model_id,
    )
    embed_start_time = asyncio.get_event_loop().time()

    for index, chunk in enumerate(chunks):
        # Проверяем отмену каждые CHECK_CANCEL_INTERVAL чанков
        if state_manager is not None and task_id is not None and index % CHECK_CANCEL_INTERVAL == 0:
            if await state_manager.is_cancelled(task_id):
                raise asyncio.CancelledError

        embedding_text = chunk.metadata.get("embedding_text", chunk.text)

        result = await provider.embed([embedding_text])
        vector = result[0] if result else []
        if not vector:
            logger.error(
                "Embedding provider returned empty vector: file=%s chunk_index=%d model=%s",
                file_path or "?", index, embedding_model.model_id,
            )
            raise ValueError(
                f"Embedding provider returned empty vector for chunk {index} "
                f"(file={file_path!r}, model={embedding_model.model_id!r}). "
                "Check model availability, dimension settings, and provider logs."
            )

        vectors.append(vector)

        processed_count = index + 1
        if processed_count % CHUNK_PROGRESS_REPORT_INTERVAL == 0 or processed_count == len(chunks):
            elapsed = asyncio.get_event_loop().time() - embed_start_time
            rate = processed_count / elapsed if elapsed > 0 else 0
            eta = (len(chunks) - processed_count) / rate if rate > 0 else 0
            logger.info(
                "Embedding progress: file=%s %d/%d chunks (%.1f c/s, ETA ~%.0fs)",
                file_path or "?", processed_count, len(chunks), rate, eta,
            )

    logger.info(
        "Embedding complete: file=%s %d chunks embedded in %.1fs",
        file_path or "?", len(chunks),
        asyncio.get_event_loop().time() - embed_start_time,
    )

    return vectors


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


def _document_id(vault_id: str, relative_path: str) -> str:
    digest = hashlib.sha256(f"{vault_id}:{relative_path}".encode("utf-8")).hexdigest()[:16]
    return f"doc{digest}"


document_id = _document_id
