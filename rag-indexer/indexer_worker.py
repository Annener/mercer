from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from app.db_client import IndexerDBClient
from chunking_pipeline import (
    assign_page_numbers_and_headers,
    build_chunk_records,
    parse_file_with_progress,
)
from embedding.base_provider import EmbeddingProvider
from embedding_pipeline import embed_chunks
from parser.chunking.embedding_enricher import (
    build_embedding_text,
    extract_markdown_headers,
)
from parser.preprocessing.pdf_page_merger import (
    merge_pdf_pages,
    strip_page_markers,
)
from parser.preprocessing.preprocessor import preprocess
from parser.scanning.vault_scanner import scan_vault
from parser.semantic_chunker import SemanticChunker
from parser.state.redis_state_manager import RedisStateManager
from provider_factory import build_embedding_model_config, build_provider
from storage.storage_client import StorageClient

from config import EmbeddingModelConfig
from shared_contracts.models import (
    ChunkRecord,
    UpsertChunk,
    UpsertRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_VAULT_ROOT = "/data/vaults"
DEFAULT_STORAGE_API_URL = "http://db-api-server:8080"

_AVG_WORD_LEN_CHARS = 6
CHUNK_PROGRESS_REPORT_INTERVAL = 10
_PARSING_HEARTBEAT_INTERVAL = 3.0
CHECK_CANCEL_INTERVAL = 10  # проверять отмену каждые N чанков при эмбеддинге

# Размер батча для batch-оптимизированных провайдеров (openai_compatible, sidecar).
# Для Ollama остаётся поперечное выполнение (N запросов с semaphore).
_BATCH_EMBED_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))


async def run_indexing(
    task_id: str,
    vault_id: str,
    force_reindex: bool,
    db_client: IndexerDBClient,
    state_manager: RedisStateManager,
    source_paths: list[str] | None = None,
) -> None:
    """Основной воркер индексации. Использует RedisStateManager для хранения состояния.

    Args:
        task_id:       Unique task identifier.
        vault_id:      Target vault.
        force_reindex: Re-index even if checksum unchanged.
        db_client:     DB access.
        state_manager: Redis state manager.
        source_paths:  When provided, restrict processing to these relative
                       markdown paths inside the vault (targeted reindex for
                       update-mode apply). None means full vault scan —
                       existing behaviour, backward compatible.
    """
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
            logger.exception("Indexing task aborted: failed to decrypt embedding key: vault_id=%s", vault_id)
            return

        embedding_model = build_embedding_model_config(embedding_model_data)
        provider = build_provider(embedding_model, api_key)
        storage_client = StorageClient(os.getenv("STORAGE_API_URL", DEFAULT_STORAGE_API_URL))
        await db_client.update_vault_binding_status(vault_id, "indexing")

        vault_path = f"{os.getenv('VAULT_DATA_ROOT', DEFAULT_VAULT_ROOT)}/{vault_id}"
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

        # Phase 4: targeted reindex — restrict to caller-supplied paths.
        # source_paths contains relative paths as written by update-mode applier
        # (forward-slash, relative to vault root).  We normalise both sides to
        # strip leading slashes before comparing so there is no accidental mismatch.
        if source_paths is not None:
            normalised_targets = {p.lstrip("/") for p in source_paths}
            original_count = len(all_files_info)
            all_files_info = [
                f for f in all_files_info
                if f["relative_path"].lstrip("/") in normalised_targets
            ]
            logger.info(
                "targeted reindex: vault=%s requested=%d matched=%d/%d",
                vault_id,
                len(normalised_targets),
                len(all_files_info),
                original_count,
            )
            if not all_files_info:
                logger.warning(
                    "targeted reindex: no matching files found in vault=%s source_paths=%s",
                    vault_id,
                    source_paths,
                )
                # Nothing to do — mark task done immediately so the caller gets a clean task_id
                await state_manager.create_task(
                    task_id=task_id,
                    vault_id=vault_id,
                    files_to_index=[],
                    files_skipped=0,
                    files_total=0,
                )
                await state_manager.mark_task_done(task_id)
                return

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

            md5 = file_info["checksum"]
            mtime = int(file_info.get("last_modified") or 0)

            # Проверяем запись в таблице documents
            doc = await db_client.get_document_by_path(vault_id, relative_path)

            if doc is None:
                doc = await db_client.create_document(vault_id, relative_path, md5, mtime)
                logger.info("New document registered: %s id=%s", relative_path, doc["id"])
            else:
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
                except Exception:  # best-effort state update
                    logger.exception("Failed to update state for %s", relative_path)
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
            logger.exception("Failed to update vault status after indexing error: vault_id=%s", vault_id)
        logger.exception("Indexing task failed: task_id=%s vault_id=%s", task_id, vault_id)
        try:
            await state_manager.mark_task_done(task_id, error=str(exc))
        except Exception:
            logger.exception("Failed to mark task as error: %s", task_id)


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

    parsed = await parse_file_with_progress(
        absolute_path,
        str(file_info.get("extension", "")),
        task_id=task_id,
        relative_path=relative_path,
        state_manager=state_manager,
        parser_settings=parser_settings,
    )
    logger.info("Parsing complete: %s", relative_path)

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
        logger.info("Merging PDF pages: %s", relative_path)
        merged_text, page_offsets, placed_headings = await asyncio.to_thread(
            merge_pdf_pages,
            parsed["pages"],
            parsed.get("headings"),
        )
        text_for_chunking = merged_text
        logger.info(
            "PDF merge complete: %s chars=%d pages_index=%d",
            relative_path, len(text_for_chunking), len(page_offsets),
        )
    else:
        text_for_chunking = str(parsed.get("text", ""))

    if not text_for_chunking.strip():
        logger.warning("No text extracted from file: %s", relative_path)
        await state_manager.update_file_stage(task_id, relative_path, stage="empty")
        await db_client.update_document_status(pg_document_id, "indexed",
                                                indexed_at=datetime.now(tz=timezone.utc))
        return 0, pg_document_id

    logger.info("Preprocessing text for chunking: %s chars=%d", relative_path, len(text_for_chunking))
    cleaned_for_chunking = await asyncio.to_thread(preprocess, text_for_chunking, relative_path)
    logger.info("Preprocessing complete: %s chars=%d", relative_path, len(cleaned_for_chunking))

    semantic_threshold = float(vault.get("semantic_threshold", 0.3))
    logger.info(
        "SemanticChunker start: %s threshold=%.2f",
        relative_path, semantic_threshold,
    )
    raw_chunks: list[str] = await SemanticChunker(
        provider,
        semantic_threshold,
    ).split(cleaned_for_chunking)

    logger.info(
        "SemanticChunker complete: file=%s chunks=%d threshold=%.2f",
        relative_path, len(raw_chunks), semantic_threshold,
    )

    chunks: list[ChunkRecord] = build_chunk_records(
        raw_chunks=raw_chunks,
        document_id=pg_document_id,
        vault_id=vault_id,
        base_metadata=base_metadata,
    )

    if not chunks:
        logger.warning("No valid chunks generated for file: %s", relative_path)
        await state_manager.update_file_stage(task_id, relative_path, stage="empty")
        await db_client.update_document_status(pg_document_id, "indexed",
                                                indexed_at=datetime.now(tz=timezone.utc))
        return 0, pg_document_id

    logger.info("Post-processing %d chunks: strip + preprocess: %s", len(chunks), relative_path)
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
        assign_page_numbers_and_headers(chunks, page_offsets, placed_headings)

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

    vectors = await embed_chunks(
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

    # --- [Full Document Mode Этап 2] запись size-метаданных ---
    total_chars = sum(len(chunk.text) for chunk in chunks)
    total_chunks = len(chunks)
    estimated_tokens = total_chars // 4  # грубая оценка: ~4 символа на токен
    try:
        await db_client.update_document_size(
            document_id=pg_document_id,
            char_count=total_chars,
            chunk_count=total_chunks,
            estimated_tokens=estimated_tokens,
        )
        logger.info(
            "Document size metadata updated: document_id=%s chars=%d chunks=%d tokens~=%d",
            pg_document_id, total_chars, total_chunks, estimated_tokens,
        )
    except Exception:
        # Не блокируем индексацию при ошибке записи size-метаданных
        logger.warning(
            "Failed to update document size metadata: document_id=%s",
            pg_document_id, exc_info=True,
        )
    # --- [конец блока Full Document Mode] ---

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

