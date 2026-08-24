"""Embedding pipeline для одного файла.

Pure embedding-orchestration: берёт список чанков, возвращает список векторов.
Умеет два режима:
  - batch-endpoint (openai_compatible / sidecar): один HTTP-запрос на батч
  - per-chunk (Ollama): N параллельных запросов через semaphore

Cancel-проверка: каждые CHECK_CANCEL_INTERVAL чанков для Ollama,
каждый батч — для OpenAI-compatible.

Public API
----------
uses_batch_api(provider) -> bool
embed_chunks(chunks, embedding_model, provider, *, task_id=None, file_path=None,
             state_manager=None) -> list[list[float]]
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from embedding.base_provider import EmbeddingProvider
from embedding.openai_provider import OpenAICompatibleProvider
from parser.state.redis_state_manager import RedisStateManager

from config import EmbeddingModelConfig

logger = logging.getLogger(__name__)

# Прогресс embed_chunks логируется каждые N чанков.
PROGRESS_REPORT_INTERVAL = 10

# Проверять отмену каждые N чанков при почанковом эмбеддинге (Ollama).
CHECK_CANCEL_INTERVAL = 10

# Размер батча для batch-оптимизированных провайдеров (openai_compatible, sidecar).
# Для Ollama остаётся поперечное выполнение (N запросов с semaphore).
BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "64"))


def uses_batch_api(provider: EmbeddingProvider) -> bool:
    """True для провайдеров с нативным батч-эндпоинтом (OpenAI-compatible, sidecar)."""
    return isinstance(provider, OpenAICompatibleProvider)


async def embed_chunks(
    chunks: list[Any],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    *,
    task_id: str | None = None,
    file_path: str | None = None,
    state_manager: RedisStateManager | None = None,
) -> list[list[float]]:
    """Получить эмбеддинги для всех чанков файла. Возвращает список векторов."""
    logger.info(
        "Embedding start: file=%s total_chunks=%d model=%s",
        file_path or "?", len(chunks), embedding_model.model_id,
    )
    embed_start_time = asyncio.get_event_loop().time()

    embedding_texts = [
        chunk.metadata.get("embedding_text", chunk.text)
        for chunk in chunks
    ]

    if uses_batch_api(provider):
        vectors = await _embed_batch_path(
            embedding_texts, embedding_model, provider,
            task_id=task_id, file_path=file_path, state_manager=state_manager,
            start_time=embed_start_time,
        )
    else:
        vectors = await _embed_per_chunk_path(
            embedding_texts, embedding_model, provider,
            task_id=task_id, file_path=file_path, state_manager=state_manager,
            start_time=embed_start_time,
        )

    logger.info(
        "Embedding complete: file=%s %d chunks embedded in %.1fs",
        file_path or "?", len(chunks),
        asyncio.get_event_loop().time() - embed_start_time,
    )
    return vectors


async def _embed_batch_path(
    embedding_texts: list[str],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    *,
    task_id: str | None,
    file_path: str | None,
    state_manager: RedisStateManager | None,
    start_time: float,
) -> list[list[float]]:
    """Батч-путь: один HTTP-запрос на батч (openai_compatible / sidecar)."""
    vectors: list[list[float]] = []
    total = len(embedding_texts)
    for batch_start in range(0, total, BATCH_SIZE):
        if (
            state_manager is not None
            and task_id is not None
            and await state_manager.is_cancelled(task_id)
        ):
            raise asyncio.CancelledError

        batch = embedding_texts[batch_start: batch_start + BATCH_SIZE]
        batch_vectors = await provider.embed_batch(batch)

        for i, vector in enumerate(batch_vectors):
            if not vector:
                chunk_idx = batch_start + i
                logger.error(
                    "Embedding provider returned empty vector: file=%s chunk_index=%d model=%s",
                    file_path or "?", chunk_idx, embedding_model.model_id,
                )
                raise ValueError(
                    f"Embedding provider returned empty vector for chunk {chunk_idx} "
                    f"(file={file_path!r}, model={embedding_model.model_id!r}). "
                    "Check model availability, dimension settings, and provider logs."
                )
        vectors.extend(batch_vectors)

        done = min(batch_start + BATCH_SIZE, total)
        elapsed = asyncio.get_event_loop().time() - start_time
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - done) / rate if rate > 0 else 0
        logger.info(
            "Embedding progress (batch): file=%s %d/%d chunks (%.1f c/s, ETA ~%.0fs)",
            file_path or "?", done, total, rate, eta,
        )
    return vectors


async def _embed_per_chunk_path(
    embedding_texts: list[str],
    embedding_model: EmbeddingModelConfig,
    provider: EmbeddingProvider,
    *,
    task_id: str | None,
    file_path: str | None,
    state_manager: RedisStateManager | None,
    start_time: float,
) -> list[list[float]]:
    """Почанковый путь: Ollama — N параллельных HTTP-запросов с semaphore."""
    vectors: list[list[float]] = []
    total = len(embedding_texts)
    for index, embedding_text in enumerate(embedding_texts):
        if (
            state_manager is not None
            and task_id is not None
            and index % CHECK_CANCEL_INTERVAL == 0
            and await state_manager.is_cancelled(task_id)
        ):
            raise asyncio.CancelledError

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
        if processed_count % PROGRESS_REPORT_INTERVAL == 0 or processed_count == total:
            elapsed = asyncio.get_event_loop().time() - start_time
            rate = processed_count / elapsed if elapsed > 0 else 0
            eta = (total - processed_count) / rate if rate > 0 else 0
            logger.info(
                "Embedding progress: file=%s %d/%d chunks (%.1f c/s, ETA ~%.0fs)",
                file_path or "?", processed_count, total, rate, eta,
            )
    return vectors
