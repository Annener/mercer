"""Тесты PipelineExecutor — DAG-режим (Этап 6).

Все зависимости от БД и LLM-провайдера полностью mock'нуты.
Запуск: cd rag-backend && pytest app/tests/test_pipeline_executor.py -v
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pipeline_executor import PipelineExecutor, _build_levels, _resolve_prompt
from shared_contracts.models import (
    FinalComposition,
    PipelineExecutionContext,
    PipelineStep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _step(
    step_id: str,
    after: list[str] | None = None,
    kind: str = "retrieval",
    top_k: int = 3,
) -> PipelineStep:
    return PipelineStep(
        step_id=step_id,
        type=kind,
        name=step_id,
        system_prompt=f"prompt for {step_id}",
        after_step_ids=after or [],
        top_k=top_k,
        tag_ids=[],
        role=None,
        output_format="text",
        validation_prompt=None if kind != "validation" else "Please confirm",
        options=None if kind != "validation" else ["Yes", "No"],
    )


def _ctx(steps: list[PipelineStep], query: str = "test query") -> PipelineExecutionContext:
    return PipelineExecutionContext(
        chat_id="00000000-0000-0000-0000-000000000001",
        message_id="00000000-0000-0000-0000-000000000002",
        query=query,
        pipeline_id="pipe1",
        steps=steps,
        final_composition=FinalComposition(
            system_prompt="Answer based on {step_a.result}",
        ),
        domain_id="dom1",
        vault_ids=["v1"],
    )


async def _collect(gen: AsyncIterator[dict]) -> list[dict]:
    result = []
    async for chunk in gen:
        result.append(chunk)
    return result


# ---------------------------------------------------------------------------
# _build_levels
# ---------------------------------------------------------------------------

class TestBuildLevels:
    def test_linear(self):
        steps = [_step("a"), _step("b", after=["a"]), _step("c", after=["b"])]
        levels = _build_levels(steps)
        assert len(levels) == 3
        assert [s.step_id for s in levels[0]] == ["a"]
        assert [s.step_id for s in levels[1]] == ["b"]
        assert [s.step_id for s in levels[2]] == ["c"]

    def test_parallel_at_level_1(self):
        steps = [_step("a"), _step("b", after=["a"]), _step("c", after=["a"])]
        levels = _build_levels(steps)
        assert len(levels) == 2
        level1_ids = {s.step_id for s in levels[1]}
        assert level1_ids == {"b", "c"}

    def test_diamond(self):
        # a → b, a → c, b+c → d
        steps = [
            _step("a"),
            _step("b", after=["a"]),
            _step("c", after=["a"]),
            _step("d", after=["b", "c"]),
        ]
        levels = _build_levels(steps)
        # d должен быть в уровне >= 2
        d_level = next(i for i, lvl in enumerate(levels) if any(s.step_id == "d" for s in lvl))
        assert d_level >= 2

    def test_single_step(self):
        levels = _build_levels([_step("only")])
        assert len(levels) == 1
        assert levels[0][0].step_id == "only"


# ---------------------------------------------------------------------------
# _resolve_prompt
# ---------------------------------------------------------------------------

class TestResolvePrompt:
    def test_query_substituted(self):
        ctx = _ctx([])
        ctx.query = "hello"
        result = _resolve_prompt("Answer: {query}", ctx)
        assert result == "Answer: hello"

    def test_step_result_substituted(self):
        ctx = _ctx([])
        ctx.step_results["step_a"] = "context data"
        result = _resolve_prompt("{step_a.result}", ctx)
        assert result == "context data"

    def test_dict_key_access(self):
        ctx = _ctx([])
        ctx.step_results["step_a"] = {"summary": "brief", "details": "long"}
        result = _resolve_prompt("{step_a.summary}", ctx)
        assert result == "brief"

    def test_private_step_skipped(self):
        ctx = _ctx([])
        ctx.step_results["_validation_step_a"] = "yes"
        # приватные ключи не раскрываются через {_validation_step_a.result}
        result = _resolve_prompt("{_validation_step_a.result}", ctx)
        assert "{_validation_step_a.result}" in result

    def test_missing_step_keeps_placeholder(self):
        ctx = _ctx([])
        result = _resolve_prompt("{missing.result}", ctx)
        assert "{missing.result}" in result


# ---------------------------------------------------------------------------
# PipelineExecutor.run_stream — базовые сценарии
# ---------------------------------------------------------------------------

class TestRunStream:
    def _make_executor(self, db=None, session_factory=None):
        db = db or AsyncMock()
        return PipelineExecutor(db=db, session_factory=session_factory)

    @pytest.mark.asyncio
    async def test_no_provider_yields_error(self):
        executor = self._make_executor()
        ctx = _ctx([_step("a")])

        with patch(
            "app.services.pipeline_executor.settings_service",
        ) as mock_settings:
            mock_settings.get_active_provider.return_value = None
            chunks = await _collect(executor.run_stream(ctx))

        types = [c["type"] for c in chunks]
        assert "error" in types

    @pytest.mark.asyncio
    async def test_single_step_no_hits_skips(self):
        executor = self._make_executor()
        ctx = _ctx([_step("a")])

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            yield "final token"

        mock_provider.generate_stream = _fake_stream

        with (
            patch("app.services.pipeline_executor.settings_service") as ms,
            patch("app.services.pipeline_executor.get_document_ids_by_tags", new_callable=AsyncMock),
            patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]),
            patch("app.services.pipeline_executor.retrieve_multi_vault", new_callable=AsyncMock, return_value=[]),
        ):
            ms.get_active_provider.return_value = mock_provider
            ms.get = AsyncMock(return_value=5)
            chunks = await _collect(executor.run_stream(ctx))

        types = [c["type"] for c in chunks]
        assert "step_skipped_no_docs" in types
        assert "pipeline_complete" in types

    @pytest.mark.asyncio
    async def test_final_composition_streams_tokens(self):
        executor = self._make_executor()
        ctx = _ctx([])
        ctx.steps = []
        ctx.final_composition = FinalComposition(system_prompt="Say {query}")

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            for t in ["Hello", " world"]:
                yield t

        mock_provider.generate_stream = _fake_stream

        with patch("app.services.pipeline_executor.settings_service") as ms:
            ms.get_active_provider.return_value = mock_provider
            chunks = await _collect(executor.run_stream(ctx))

        token_chunks = [c for c in chunks if c["type"] == "token"]
        assert "".join(c["content"] for c in token_chunks) == "Hello world"
        assert chunks[-1]["type"] == "pipeline_complete"

    @pytest.mark.asyncio
    async def test_pipeline_selected_chunk_emitted(self):
        executor = self._make_executor()
        ctx = _ctx([])
        ctx.steps = []
        ctx.pipeline_id = "pipe-xyz"

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            yield "token"

        mock_provider.generate_stream = _fake_stream

        with patch("app.services.pipeline_executor.settings_service") as ms:
            ms.get_active_provider.return_value = mock_provider
            chunks = await _collect(executor.run_stream(ctx))

        first = chunks[0]
        assert first["type"] == "pipeline_selected"
        assert first["pipeline_id"] == "pipe-xyz"


# ---------------------------------------------------------------------------
# Validation step
# ---------------------------------------------------------------------------

class TestValidationStep:
    @pytest.mark.asyncio
    async def test_validation_emits_validation_required_and_stops(self):
        mock_db = AsyncMock()
        mock_chat = MagicMock()
        mock_db.get = AsyncMock(return_value=mock_chat)
        mock_db.commit = AsyncMock()

        executor = PipelineExecutor(db=mock_db)

        steps = [_step("v1", kind="validation")]
        ctx = _ctx(steps)

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            yield "should not reach"

        mock_provider.generate_stream = _fake_stream

        with patch("app.services.pipeline_executor.settings_service") as ms:
            ms.get_active_provider.return_value = mock_provider
            chunks = await _collect(executor.run_stream(ctx))

        types = [c["type"] for c in chunks]
        assert "validation_required" in types
        # pipeline НЕ должен завершиться — он остановлен
        assert "pipeline_complete" not in types

    @pytest.mark.asyncio
    async def test_validation_saves_pause_state(self):
        mock_db = AsyncMock()
        mock_chat = MagicMock()
        mock_chat.pipeline_pause_state = None
        mock_db.get = AsyncMock(return_value=mock_chat)
        mock_db.commit = AsyncMock()

        executor = PipelineExecutor(db=mock_db)
        steps = [_step("check", kind="validation")]
        ctx = _ctx(steps)
        ctx.query = "test query"
        ctx.step_results = {"prev": "some context"}

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            yield "x"

        mock_provider.generate_stream = _fake_stream

        with patch("app.services.pipeline_executor.settings_service") as ms:
            ms.get_active_provider.return_value = mock_provider
            await _collect(executor.run_stream(ctx))

        # pause_state был записан в chat
        assert mock_chat.pipeline_pause_state is not None
        assert mock_chat.pipeline_pause_state["step_id"] == "check"
        assert "resume_token" in mock_chat.pipeline_pause_state
        assert mock_chat.pipeline_pause_state["context_snapshot"]["query"] == "test query"

    @pytest.mark.asyncio
    async def test_resume_from_validation_continues_after_step(self):
        mock_db = AsyncMock()
        mock_db.get = AsyncMock(return_value=None)
        mock_db.commit = AsyncMock()

        executor = PipelineExecutor(db=mock_db)

        steps = [
            _step("check", kind="validation"),
            _step("final_step", after=["check"]),
        ]
        ctx = _ctx(steps)
        ctx.step_results = {"_validation_check": "yes"}

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            yield "after validation"

        mock_provider.generate_stream = _fake_stream

        with (
            patch("app.services.pipeline_executor.settings_service") as ms,
            patch("app.services.pipeline_executor.retrieve_multi_vault", new_callable=AsyncMock, return_value=[]),
            patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]),
        ):
            ms.get_active_provider.return_value = mock_provider
            ms.get = AsyncMock(return_value=5)
            chunks = await _collect(executor.resume_from_validation(ctx, "check"))

        types = [c["type"] for c in chunks]
        # step_skipped или step_complete для final_step, затем pipeline_complete
        assert "pipeline_complete" in types
        # validation_required НЕ должен появиться снова
        assert "validation_required" not in types


# ---------------------------------------------------------------------------
# Parallel levels
# ---------------------------------------------------------------------------

class TestParallelLevels:
    @pytest.mark.asyncio
    async def test_parallel_without_factory_runs_sequentially(self):
        """Без session_factory параллельные шаги исполняются последовательно с предупреждением."""
        mock_db = AsyncMock()
        executor = PipelineExecutor(db=mock_db, session_factory=None)

        steps = [_step("a"), _step("b1", after=["a"]), _step("b2", after=["a"])]
        ctx = _ctx(steps)

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            yield "done"

        mock_provider.generate_stream = _fake_stream

        with (
            patch("app.services.pipeline_executor.settings_service") as ms,
            patch("app.services.pipeline_executor.retrieve_multi_vault", new_callable=AsyncMock, return_value=[]),
            patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]),
        ):
            ms.get_active_provider.return_value = mock_provider
            ms.get = AsyncMock(return_value=5)
            chunks = await _collect(executor.run_stream(ctx))

        # Все три шага skipped (нет хитов), плюс pipeline_complete
        skipped = [c for c in chunks if c["type"] == "step_skipped_no_docs"]
        assert len(skipped) == 3
        assert chunks[-1]["type"] == "pipeline_complete"

    @pytest.mark.asyncio
    async def test_parallel_with_factory_uses_gather(self):
        """С session_factory параллельные шаги используют asyncio.gather."""
        from contextlib import asynccontextmanager

        call_order: list[str] = []

        @asynccontextmanager
        async def _fake_session():
            yield AsyncMock()

        mock_db = AsyncMock()
        executor = PipelineExecutor(db=mock_db, session_factory=_fake_session)

        steps = [_step("a"), _step("b1", after=["a"]), _step("b2", after=["a"])]
        ctx = _ctx(steps)

        mock_provider = MagicMock()

        async def _fake_stream(messages):
            yield "done"

        mock_provider.generate_stream = _fake_stream

        with (
            patch("app.services.pipeline_executor.settings_service") as ms,
            patch("app.services.pipeline_executor.retrieve_multi_vault", new_callable=AsyncMock, return_value=[]),
            patch("app.services.pipeline_executor.retrieve", new_callable=AsyncMock, return_value=[]),
        ):
            ms.get_active_provider.return_value = mock_provider
            ms.get = AsyncMock(return_value=5)
            chunks = await _collect(executor.run_stream(ctx))

        skipped = [c for c in chunks if c["type"] == "step_skipped_no_docs"]
        assert len(skipped) == 3
