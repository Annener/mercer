"""
test_pipeline_executor.py — тесты для DAG-based PipelineExecutor (Этап 6).

Все зависимости от БД, retrieval и LLM-провайдера mock'нуты.
Требуется pytest-asyncio (активны в Docker-окружении проекта).
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared_contracts.models import (
    FinalComposition,
    PipelineExecutionContext,
    PipelineStep,
)


# ── Фикстуры ──────────────────────────────────────────────────────────────────

def _step(step_id: str, after: list[str] | None = None, stype: str = "retrieval") -> PipelineStep:
    return PipelineStep(
        step_id=step_id,
        type=stype,
        name=step_id,
        system_prompt=f"prompt for {step_id}",
        after_step_ids=after or [],
        top_k=3,
        tag_ids=[],
        validation_prompt=f"validate {step_id}" if stype == "validation" else None,
        options=["Да", "Нет"] if stype == "validation" else None,
    )


def _ctx(steps: list[PipelineStep], final_prompt: str = "Final: {query}") -> PipelineExecutionContext:
    return PipelineExecutionContext(
        chat_id=str(uuid.uuid4()),
        query="тестовый запрос",
        domain_id="test-domain",
        pipeline_id="test-pipe",
        vault_ids=["vault-1"],
        steps=steps,
        final_composition=FinalComposition(system_prompt=final_prompt),
    )


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    return db


async def _collect(gen) -> list[dict]:
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return chunks


def _make_provider(token_response: str = "ответ LLM") -> MagicMock:
    provider = MagicMock()
    provider.generate = AsyncMock(return_value=token_response)

    async def _stream(messages, **kw):
        for word in token_response.split():
            yield word

    provider.generate_stream = _stream
    return provider


# ── Тесты: линейный пайплайн ──────────────────────────────────────────────────

class TestRunStreamLinear:
    """Линейный пайплайн: A → B → FinalComposition."""

    @pytest.mark.asyncio
    async def test_emits_pipeline_selected(self):
        steps = [_step("A"), _step("B", after=["A"])]
        ctx = _ctx(steps)
        db = _mock_db()

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)
        provider = _make_provider()

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.run_stream(ctx))

        types = [c["type"] for c in chunks]
        assert "pipeline_selected" in types

    @pytest.mark.asyncio
    async def test_skipped_steps_emit_step_skipped_no_docs(self):
        steps = [_step("A")]
        ctx = _ctx(steps)
        db = _mock_db()

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)
        provider = _make_provider()

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.run_stream(ctx))

        types = [c["type"] for c in chunks]
        assert "step_skipped_no_docs" in types

    @pytest.mark.asyncio
    async def test_tokens_emitted_in_final_composition(self):
        """Если retrieval возвращает хиты — LLM стримит токены."""
        from shared_contracts.models import SearchHit
        steps = [_step("A")]
        ctx = _ctx(steps, final_prompt="Result: {query}")
        db = _mock_db()

        hit = SearchHit(chunk_id="c1", document_id="d1", text="chunk text", score=0.9)

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)
        provider = _make_provider("первый второй третий")

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[hit]), \
             patch("app.services.pipeline_executor.format_context_with_role", return_value="ctx block"):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.run_stream(ctx))

        token_chunks = [c for c in chunks if c["type"] == "token"]
        assert len(token_chunks) > 0
        full_text = "".join(c["content"] for c in token_chunks)
        assert "первый" in full_text


# ── Тесты: параллельный уровень ───────────────────────────────────────────────

class TestParallelLevel:
    """Параллельный уровень: A и B стартуют одновременно (нет after_step_ids)."""

    @pytest.mark.asyncio
    async def test_parallel_steps_both_in_step_results(self):
        """Оба параллельных шага добавляются в ctx.step_results."""
        from shared_contracts.models import SearchHit
        steps = [_step("A"), _step("B")]
        ctx = _ctx(steps)
        db = _mock_db()

        hit = SearchHit(chunk_id="c1", document_id="d1", text="text", score=0.9)

        from app.services.pipeline_executor import PipelineExecutor
        mock_session = _mock_db()
        session_factory = MagicMock()
        session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        executor = PipelineExecutor(db=db, session_factory=session_factory)
        provider = _make_provider("ответ")

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[hit]), \
             patch("app.services.pipeline_executor.format_context_with_role", return_value="ctx block"):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.run_stream(ctx))

        assert "A" in ctx.step_results
        assert "B" in ctx.step_results

    @pytest.mark.asyncio
    async def test_parallel_fallback_without_session_factory(self):
        """Без session_factory параллельные шаги выполняются последовательно (деградация)."""
        steps = [_step("A"), _step("B")]
        ctx = _ctx(steps)
        db = _mock_db()

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db, session_factory=None)
        provider = _make_provider()

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.run_stream(ctx))

        error_chunks = [c for c in chunks if c["type"] == "error"]
        assert not error_chunks


# ── Тесты: validation-пауза ───────────────────────────────────────────────────

class TestValidationPause:
    """type=validation: пайплайн паузируется, emitует validation_required."""

    @pytest.mark.asyncio
    async def test_validation_step_emits_validation_required(self):
        steps = [
            _step("retrieve", stype="retrieval"),
            _step("validate", after=["retrieve"], stype="validation"),
        ]
        ctx = _ctx(steps)
        db = _mock_db()

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)
        provider = _make_provider()

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.run_stream(ctx))

        vr = [c for c in chunks if c["type"] == "validation_required"]
        assert len(vr) == 1
        assert vr[0]["step_id"] == "validate"
        assert "resume_token" in vr[0]
        assert isinstance(vr[0]["resume_token"], str) and len(vr[0]["resume_token"]) > 10

    @pytest.mark.asyncio
    async def test_validation_stops_stream_before_final(self):
        """После validation_required больше нет token-чанков."""
        steps = [
            _step("A", stype="retrieval"),
            _step("gate", after=["A"], stype="validation"),
        ]
        ctx = _ctx(steps)
        db = _mock_db()

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)
        provider = _make_provider("не должен появиться")

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.run_stream(ctx))

        token_chunks = [c for c in chunks if c["type"] == "token"]
        assert not token_chunks, "После validation не должно быть токенов"

    @pytest.mark.asyncio
    async def test_validation_saves_pause_state_to_db(self):
        """_save_pause_state вызывается с корректным step_id."""
        steps = [
            _step("A", stype="retrieval"),
            _step("validate", after=["A"], stype="validation"),
        ]
        ctx = _ctx(steps)
        mock_chat = MagicMock()
        mock_chat.pipeline_pause_state = None
        mock_chat.pipeline_versions = {}
        db = _mock_db()
        db.get = AsyncMock(return_value=mock_chat)

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)
        provider = _make_provider()

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            await _collect(executor.run_stream(ctx))

        assert mock_chat.pipeline_pause_state is not None
        assert mock_chat.pipeline_pause_state["step_id"] == "validate"
        assert "resume_token" in mock_chat.pipeline_pause_state
        assert "context_snapshot" in mock_chat.pipeline_pause_state


# ── Тесты: resume_from_validation ─────────────────────────────────────────────

class TestResumeFromValidation:

    @pytest.mark.asyncio
    async def test_resume_continues_from_next_level(self):
        """После validation emitует token-чанки из FinalComposition."""
        from shared_contracts.models import SearchHit
        steps = [
            _step("A", stype="retrieval"),
            _step("validate", after=["A"], stype="validation"),
            _step("B", after=["validate"], stype="retrieval"),
        ]
        ctx = _ctx(steps, final_prompt="final {query}")
        ctx.step_results["A"] = "результат A"
        ctx.step_results["_validation_validate"] = "Да"

        db = _mock_db()
        hit = SearchHit(chunk_id="c1", document_id="d1", text="text", score=0.9)

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)
        provider = _make_provider("итоговый ответ")

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[hit]), \
             patch("app.services.pipeline_executor.format_context_with_role", return_value="ctx"):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.resume_from_validation(ctx, "validate"))

        token_chunks = [c for c in chunks if c["type"] == "token"]
        assert len(token_chunks) > 0
        full_text = "".join(c["content"] for c in token_chunks)
        assert "итоговый" in full_text

    @pytest.mark.asyncio
    async def test_resume_unknown_step_id_starts_from_beginning(self):
        """Если step_id не найден в уровнях — выполнение с 0-го уровня (safe fallback)."""
        steps = [_step("A", stype="retrieval")]
        ctx = _ctx(steps)
        db = _mock_db()

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db, session_factory=None)
        provider = _make_provider()

        with patch("app.services.pipeline_executor.settings_service") as mock_ss, \
             patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]):
            mock_ss.get_active_provider.return_value = provider
            mock_ss.get = AsyncMock(return_value="5")
            chunks = await _collect(executor.resume_from_validation(ctx, "nonexistent_step"))

        error_chunks = [c for c in chunks if c["type"] == "error"]
        assert not error_chunks


# ── Тесты: нет активного провайдера ──────────────────────────────────────────

class TestNoActiveProvider:

    @pytest.mark.asyncio
    async def test_no_provider_emits_error(self):
        steps = [_step("A")]
        ctx = _ctx(steps)
        db = _mock_db()

        from app.services.pipeline_executor import PipelineExecutor

        executor = PipelineExecutor(db=db)

        with patch("app.services.pipeline_executor.settings_service") as mock_ss:
            mock_ss.get_active_provider.return_value = None
            chunks = await _collect(executor.run_stream(ctx))

        error_chunks = [c for c in chunks if c["type"] == "error"]
        assert len(error_chunks) == 1
        assert "model" in error_chunks[0]["message"].lower()
