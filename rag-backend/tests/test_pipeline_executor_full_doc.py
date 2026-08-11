"""Tests for pipeline_executor full-document retrieval mode (send_full_document=True)."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.pipeline_executor import (
    PER_DOC_TOKEN_LIMIT,
    TOTAL_TOKEN_BUDGET,
    PipelineExecutor,
)
from shared_contracts.models import PipelineExecutionContext, PipelineStep


def _make_step(**overrides) -> PipelineStep:
    defaults = {
        "step_id": "load_full",
        "type": "retrieval",
        "name": "Load Full Document",
        "system_prompt": "Use the document",
        "after_step_ids": [],
        "tag_ids": ["00000000-0000-0000-0000-000000000001"],
        "role": "rules",
        "top_k": 10,
    }
    defaults.update(overrides)
    return PipelineStep(**defaults)


def _make_ctx(domain_id: str | None = "dnd") -> PipelineExecutionContext:
    return PipelineExecutionContext(
        chat_id="00000000-0000-0000-0000-000000000001",
        message_id="00000000-0000-0000-0000-000000000002",
        query="test query",
        domain_id=domain_id,
        vault_ids=["vault-1"],
    )


@pytest.fixture
def db_session() -> AsyncSession:
    """Для тестов retrieval-шага БД не используется напрямую — get_documents_by_tag замокан."""
    return AsyncMock()


@pytest.mark.asyncio
async def test_send_full_document_happy_path(db_session: AsyncSession, monkeypatch):
    """send_full_document=True загружает полные тексты через reconstruct_full_text
    и формирует ctx.step_results через format_context_with_role."""
    docs = [
        {"document_id": "doc-1", "vault_id": "vault-1", "source_path": "a.md", "title": "Doc 1"},
        {"document_id": "doc-2", "vault_id": "vault-1", "source_path": "b.md", "title": "Doc 2"},
    ]
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        AsyncMock(return_value=docs),
    )

    texts = {
        "doc-1": "# Doc 1\nFull text content of doc 1.",
        "doc-2": "# Doc 2\nFull text content of doc 2.",
    }

    async def fake_reconstruct(document_id, vault_id, db_api_url):
        return texts[document_id]

    monkeypatch.setattr(
        "app.services.pipeline_executor.reconstruct_full_text",
        fake_reconstruct,
    )

    step = _make_step(send_full_document=True)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    chunks = []
    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        chunks.append(chunk)

    result_text = ctx.step_results[step.step_id]
    assert "[1]" in result_text
    assert "Doc 1" in result_text
    assert "Full text content of doc 1" in result_text
    assert "[2]" in result_text
    assert "Full text content of doc 2" in result_text
    assert "=== rules ===" in result_text
    assert any(c.get("type") == "step_complete" for c in chunks)


@pytest.mark.asyncio
async def test_send_full_document_skips_oversized_doc(db_session: AsyncSession, monkeypatch):
    """Документ больше PER_DOC_TOKEN_LIMIT пропускается."""
    docs = [
        {"document_id": "doc-big", "vault_id": "vault-1", "source_path": "big.md", "title": "Big"},
        {"document_id": "doc-small", "vault_id": "vault-1", "source_path": "small.md", "title": "Small"},
    ]
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        AsyncMock(return_value=docs),
    )

    big_text = "x" * (PER_DOC_TOKEN_LIMIT * 4 + 100)
    small_text = "# Small\nShort body."

    async def fake_reconstruct(document_id, vault_id, db_api_url):
        return {"doc-big": big_text, "doc-small": small_text}[document_id]

    monkeypatch.setattr(
        "app.services.pipeline_executor.reconstruct_full_text",
        fake_reconstruct,
    )

    step = _make_step(send_full_document=True)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        pass

    result_text = ctx.step_results[step.step_id]
    assert "Small" in result_text
    assert big_text[:100] not in result_text


@pytest.mark.asyncio
async def test_send_full_document_no_documents(db_session: AsyncSession, monkeypatch):
    """Если документов нет — записывается пустая строка и эмитится step_skipped_no_docs."""
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        AsyncMock(return_value=[]),
    )
    reconstruct_mock = AsyncMock()

    step = _make_step(send_full_document=True)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    chunks = []
    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        chunks.append(chunk)

    assert ctx.step_results[step.step_id] == ""
    assert any(c.get("type") == "step_skipped_no_docs" for c in chunks)
    reconstruct_mock.assert_not_called()


@pytest.mark.asyncio
async def test_send_full_document_reconstruct_returns_none(
    db_session: AsyncSession, monkeypatch
):
    """Если reconstruct вернул None или пустую строку — продолжаем без документа."""
    docs = [
        {"document_id": "doc-empty", "vault_id": "vault-1", "source_path": "empty.md", "title": "Empty"},
        {"document_id": "doc-ok", "vault_id": "vault-1", "source_path": "ok.md", "title": "OK"},
    ]
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        AsyncMock(return_value=docs),
    )

    async def fake_reconstruct(document_id, vault_id, db_api_url):
        return {"doc-empty": None, "doc-ok": "# OK\ntext"}[document_id]

    monkeypatch.setattr(
        "app.services.pipeline_executor.reconstruct_full_text",
        fake_reconstruct,
    )

    step = _make_step(send_full_document=True)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        pass

    result_text = ctx.step_results[step.step_id]
    assert "OK" in result_text
    assert "Empty" not in result_text


@pytest.mark.asyncio
async def test_send_full_document_no_domain_id(db_session: AsyncSession, monkeypatch):
    """Если domain_id пустой — get_documents_by_tag не вызывается, шаг пустой."""
    docs_mock = AsyncMock()
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        docs_mock,
    )

    step = _make_step(send_full_document=True)
    ctx = _make_ctx(domain_id=None)
    executor = PipelineExecutor(db_session)

    chunks = []
    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        chunks.append(chunk)

    docs_mock.assert_not_called()
    assert ctx.step_results[step.step_id] == ""
    assert any(c.get("type") == "step_skipped_no_docs" for c in chunks)


@pytest.mark.asyncio
async def test_send_full_document_total_budget_exceeded(
    db_session: AsyncSession, monkeypatch
):
    """Когда total превышает TOTAL_TOKEN_BUDGET — последующие документы пропускаются."""
    # Каждый документ ~13.5k токенов; 5 штук = 67.5k > 64k budget
    text_per_doc = "x" * 54_000  # 54000/4 = 13500 токенов
    docs = [
        {"document_id": f"doc-{i}", "vault_id": "vault-1", "source_path": f"{i}.md", "title": f"D{i}"}
        for i in range(5)
    ]
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        AsyncMock(return_value=docs),
    )

    async def fake_reconstruct(document_id, vault_id, db_api_url):
        return text_per_doc

    monkeypatch.setattr(
        "app.services.pipeline_executor.reconstruct_full_text",
        fake_reconstruct,
    )

    step = _make_step(send_full_document=True)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        pass

    # 5 * 13500 = 67500 > 64000. Должно попасть 4 документа (4 * 13500 = 54000)
    result_text = ctx.step_results[step.step_id]
    assert "[1]" in result_text
    assert "[5]" not in result_text


@pytest.mark.asyncio
async def test_send_full_document_exception_in_reconstruct(
    db_session: AsyncSession, monkeypatch
):
    """Исключение из reconstruct для одного документа не валит весь шаг."""
    docs = [
        {"document_id": "doc-fail", "vault_id": "vault-1", "source_path": "fail.md", "title": "Fail"},
        {"document_id": "doc-ok", "vault_id": "vault-1", "source_path": "ok.md", "title": "OK"},
    ]
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        AsyncMock(return_value=docs),
    )

    async def fake_reconstruct(document_id, vault_id, db_api_url):
        if document_id == "doc-fail":
            raise RuntimeError("network error")
        return "# OK\ntext"

    monkeypatch.setattr(
        "app.services.pipeline_executor.reconstruct_full_text",
        fake_reconstruct,
    )

    step = _make_step(send_full_document=True)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        pass

    result_text = ctx.step_results[step.step_id]
    assert "OK" in result_text
    assert "Fail" not in result_text


@pytest.mark.asyncio
async def test_send_full_document_false_uses_normal_path(
    db_session: AsyncSession, monkeypatch
):
    """При send_full_document=False идёт обычный путь — get_documents_by_tag не вызывается."""
    docs_mock = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        docs_mock,
    )
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_document_ids_by_tags",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.pipeline_executor.query_rewriter.rewrite_for_retrieval",
        AsyncMock(return_value="rewritten"),
    )
    monkeypatch.setattr(
        "app.services.pipeline_executor.retrieve",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        "app.services.pipeline_executor.retrieve_multi_vault",
        AsyncMock(return_value=[]),
    )

    step = _make_step(send_full_document=False)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    chunks = []
    async for chunk in executor._run_dag_step(step, ctx, provider=object()):
        chunks.append(chunk)

    docs_mock.assert_not_called()
    assert any(c.get("type") == "step_skipped_no_docs" for c in chunks)


@pytest.mark.asyncio
async def test_send_full_document_no_role_no_header(db_session: AsyncSession, monkeypatch):
    """Если role=None, заголовок '=== role ===' не добавляется."""
    docs = [
        {"document_id": "doc-1", "vault_id": "vault-1", "source_path": "a.md", "title": "Doc 1"},
    ]
    monkeypatch.setattr(
        "app.services.pipeline_executor.get_documents_by_tag",
        AsyncMock(return_value=docs),
    )

    async def fake_reconstruct(document_id, vault_id, db_api_url):
        return "Just text"

    monkeypatch.setattr(
        "app.services.pipeline_executor.reconstruct_full_text",
        fake_reconstruct,
    )

    step = _make_step(send_full_document=True, role=None)
    ctx = _make_ctx()
    executor = PipelineExecutor(db_session)

    async for chunk in executor._run_dag_step(step, ctx, provider=None):
        pass

    result_text = ctx.step_results[step.step_id]
    assert "Just text" in result_text
    assert "===" not in result_text
