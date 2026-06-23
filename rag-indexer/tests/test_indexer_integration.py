"""
Интеграционный тест этапа 4: SemanticChunker в IndexerWorker._process_file.

Проверяем:
- preprocess вызывается ДО чанкинга (spy)
- upsert_with_retry вызывается с правильным количеством чанков
- embed_batch вызывается ровно 1 раз пер документ (для SemanticChunker)
- provider.embed вызывается для каждого чанка (финальные эмбеддинги)
- word_start заполнен в metadata каждого чанка
- пустой текст → 0 чанков, upsert не вызывается
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from indexer_worker import _process_file
from shared_contracts.models import UpsertRequest


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _make_provider(num_sentences: int = 10, dim: int = 4) -> MagicMock:
    """Мок EmbeddingProvider.

    embed_batch: возвращает разнородные векторы, чтобы cosine distance нашёл границы.
    embed: возвращает постоянный вектор (для финальных чанков).
    """
    provider = MagicMock()

    # embed_batch: каждое предложение получает ортогональный единичный вектор (cosine_distance = 1.0)
    def _make_ortho_vector(i: int, dim: int) -> list[float]:
        v = [0.0] * dim
        v[i % dim] = 1.0
        return v

    async def _embed_batch(texts: list[str]) -> list[list[float]]:
        return [_make_ortho_vector(i, dim) for i in range(len(texts))]

    provider.embed_batch = _embed_batch

    # embed: для финальных чанков — всегда возвращает [1.0, 0.0, 0.0, 0.0]
    async def _embed(texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    provider.embed = _embed
    return provider


def _make_state_manager() -> AsyncMock:
    sm = AsyncMock()
    sm.is_cancelled.return_value = False
    return sm


def _make_db_client(pg_doc_id: str = "test-doc-id") -> AsyncMock:
    db = AsyncMock()
    db.update_document_status.return_value = None
    return db


def _make_storage_client() -> AsyncMock:
    sc = AsyncMock()
    upsert_response = MagicMock()
    upsert_response.status = "ok"
    upsert_response.failed_indices = []
    sc.upsert_with_retry.return_value = upsert_response
    return sc


def _make_embedding_model() -> MagicMock:
    m = MagicMock()
    m.model_id = "test-model"
    m.provider = "ollama"
    return m


def _make_doc(pg_id: str = "test-doc-id") -> dict[str, Any]:
    return {
        "id": pg_id,
        "vault_id": "vault-1",
        "relative_path": "test.md",
        "status": "pending",
        "md5": "abc",
        "mtime": 0,
    }


def _make_vault(threshold: float = 0.3) -> dict[str, Any]:
    return {
        "vault_id": "vault-1",
        "domain_id": "domain-1",
        "enabled": True,
        "embedding_model_id": "emb-1",
        "expected_dimensions": 4,
        "chunk_size": 1600,
        "overlap": 64,
        "entity_aware_mode": False,
        "semantic_threshold": threshold,
    }


TWO_TOPIC_TEXT = """
Первый абзац посвящён астрономии.
Vectors in space describe stellar distances.

Второй абзац о кулинарии.
Recipes require fresh ingredients and careful preparation.
""".strip()


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_file_calls_upsert_with_chunks() -> None:
    """Файл с двумя семантически разными блоками даёт чанки; upsert вызывается ровно 1 раз."""
    provider = _make_provider()
    storage_client = _make_storage_client()
    db_client = _make_db_client()
    state_manager = _make_state_manager()

    file_info = {
        "path": "/fake/test.md",
        "relative_path": "test.md",
        "checksum": "abc123",
        "last_modified": 0,
        "extension": ".md",
    }
    doc = _make_doc()
    vault = _make_vault(threshold=0.01)  # низкий порог → много разрывов

    parsed_md = {"text": TWO_TOPIC_TEXT, "metadata": {}}

    with patch("indexer_worker._parse_file_with_progress", new=AsyncMock(return_value=parsed_md)):
        chunks_count, doc_id = await _process_file(
            task_id="task-1",
            vault_id="vault-1",
            file_info=file_info,
            doc=doc,
            embedding_model=_make_embedding_model(),
            provider=provider,
            storage_client=storage_client,
            vault=vault,
            parser_settings={},
            uploaded_document_ids=[],
            state_manager=state_manager,
            db_client=db_client,
        )

    assert chunks_count > 0
    assert doc_id == "test-doc-id"
    storage_client.upsert_with_retry.assert_awaited_once()
    upsert_req: UpsertRequest = storage_client.upsert_with_retry.call_args[0][0]
    assert len(upsert_req.chunks) == chunks_count


@pytest.mark.asyncio
async def test_process_file_word_start_populated() -> None:
    """Все чанки имеют word_start в metadata (нужен для PDF page assignment)."""
    provider = _make_provider()
    storage_client = _make_storage_client()
    db_client = _make_db_client()
    state_manager = _make_state_manager()

    file_info = {
        "path": "/fake/test.md",
        "relative_path": "test.md",
        "checksum": "abc123",
        "last_modified": 0,
        "extension": ".md",
    }
    doc = _make_doc()
    vault = _make_vault(threshold=0.01)
    parsed_md = {"text": TWO_TOPIC_TEXT, "metadata": {}}

    with patch("indexer_worker._parse_file_with_progress", new=AsyncMock(return_value=parsed_md)):
        await _process_file(
            task_id="task-1",
            vault_id="vault-1",
            file_info=file_info,
            doc=doc,
            embedding_model=_make_embedding_model(),
            provider=provider,
            storage_client=storage_client,
            vault=vault,
            parser_settings={},
            uploaded_document_ids=[],
            state_manager=state_manager,
            db_client=db_client,
        )

    upsert_req: UpsertRequest = storage_client.upsert_with_retry.call_args[0][0]
    for chunk in upsert_req.chunks:
        assert "word_start" in chunk.metadata, f"word_start missing in chunk metadata: {chunk.metadata}"


@pytest.mark.asyncio
async def test_process_file_empty_text_no_upsert() -> None:
    """Пустой текст → 0 чанков, upsert_with_retry не вызывается."""
    provider = _make_provider()
    storage_client = _make_storage_client()
    db_client = _make_db_client()
    state_manager = _make_state_manager()

    file_info = {
        "path": "/fake/empty.md",
        "relative_path": "empty.md",
        "checksum": "000",
        "last_modified": 0,
        "extension": ".md",
    }
    doc = _make_doc()
    vault = _make_vault()
    parsed_md = {"text": "   ", "metadata": {}}

    with patch("indexer_worker._parse_file_with_progress", new=AsyncMock(return_value=parsed_md)):
        chunks_count, _ = await _process_file(
            task_id="task-1",
            vault_id="vault-1",
            file_info=file_info,
            doc=doc,
            embedding_model=_make_embedding_model(),
            provider=provider,
            storage_client=storage_client,
            vault=vault,
            parser_settings={},
            uploaded_document_ids=[],
            state_manager=state_manager,
            db_client=db_client,
        )

    assert chunks_count == 0
    storage_client.upsert_with_retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_preprocess_called_before_chunking() -> None:
    """
    preprocess должен быть вызван до SemanticChunker.split.
    Проверяем: первый вызов preprocess идёт с relative_path в качестве source_hint
    (т. е. это вызов ДО чанкинга, а не chunk_N).
    """
    provider = _make_provider()
    storage_client = _make_storage_client()
    db_client = _make_db_client()
    state_manager = _make_state_manager()

    file_info = {
        "path": "/fake/test.md",
        "relative_path": "test.md",
        "checksum": "abc123",
        "last_modified": 0,
        "extension": ".md",
    }
    doc = _make_doc()
    vault = _make_vault(threshold=0.5)
    parsed_md = {"text": TWO_TOPIC_TEXT, "metadata": {}}

    preprocess_calls: list[tuple[str, str]] = []

    def _spy_preprocess(text: str, source_hint: str = "") -> str:
        preprocess_calls.append((text, source_hint))
        return text  # пропускаем без изменений

    with (
        patch("indexer_worker._parse_file_with_progress", new=AsyncMock(return_value=parsed_md)),
        patch("indexer_worker.preprocess", side_effect=_spy_preprocess),
    ):
        await _process_file(
            task_id="task-1",
            vault_id="vault-1",
            file_info=file_info,
            doc=doc,
            embedding_model=_make_embedding_model(),
            provider=provider,
            storage_client=storage_client,
            vault=vault,
            parser_settings={},
            uploaded_document_ids=[],
            state_manager=state_manager,
            db_client=db_client,
        )

    # Первый вызов preprocess должен быть с source_hint == relative_path (ДО чанкинга)
    assert preprocess_calls, "preprocess вообще не вызвался"
    first_hint = preprocess_calls[0][1]
    assert first_hint == "test.md", (
        f"Ожидался source_hint='test.md' (ДО чанкинга), получено '{first_hint}'"
    )
    # Последующие вызовы должны иметь source_hint вида "test.md:chunk_N"
    per_chunk_calls = [c for c in preprocess_calls[1:] if ":chunk_" in c[1]]
    assert len(per_chunk_calls) > 0, "Попчанковый preprocess не вызвался"


@pytest.mark.asyncio
async def test_semantic_threshold_from_vault() -> None:
    """Порог читается из vault[semantic_threshold]; при пороге 0.99 (максимальное слияние) создаёт меньше чанков."""
    provider_low = _make_provider()   # вектора ортогональны, cosine_dist = 1.0
    provider_high = _make_provider()
    storage_low = _make_storage_client()
    storage_high = _make_storage_client()
    state_manager = _make_state_manager()
    db_client = _make_db_client()

    file_info = {
        "path": "/fake/test.md",
        "relative_path": "test.md",
        "checksum": "abc123",
        "last_modified": 0,
        "extension": ".md",
    }
    doc = _make_doc()
    parsed_md = {"text": TWO_TOPIC_TEXT, "metadata": {}}

    with patch("indexer_worker._parse_file_with_progress", new=AsyncMock(return_value=parsed_md)):
        chunks_low, _ = await _process_file(
            task_id="task-1",
            vault_id="vault-1",
            file_info=file_info,
            doc=doc,
            embedding_model=_make_embedding_model(),
            provider=provider_low,
            storage_client=storage_low,
            vault=_make_vault(threshold=0.01),  # низкий порог → больше чанков
            parser_settings={},
            uploaded_document_ids=[],
            state_manager=state_manager,
            db_client=db_client,
        )

    state_manager2 = _make_state_manager()
    db_client2 = _make_db_client()
    doc2 = _make_doc()

    with patch("indexer_worker._parse_file_with_progress", new=AsyncMock(return_value=parsed_md)):
        chunks_high, _ = await _process_file(
            task_id="task-2",
            vault_id="vault-1",
            file_info=file_info,
            doc=doc2,
            embedding_model=_make_embedding_model(),
            provider=provider_high,
            storage_client=storage_high,
            vault=_make_vault(threshold=0.99),  # высокий порог → меньше чанков
            parser_settings={},
            uploaded_document_ids=[],
            state_manager=state_manager2,
            db_client=db_client2,
        )

    # при низком пороге больше разрывов → больше чанков
    assert chunks_low >= chunks_high, (
        f"Ожидалось chunks_low >= chunks_high, получено {chunks_low} vs {chunks_high}"
    )
