"""
test_pipeline_executor.py — unit-тесты PipelineExecutor (DAG API).

Тестируем без живой БД и без HTTP: все зависимости mock'ируются.
Главные SUT: _build_levels(), _resolve_prompt(), PipelineExecutor._dag_execute().
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.pipeline_executor import (
    PipelineExecutor,
    _build_levels,
    _resolve_prompt,
)
from shared_contracts.models import FinalComposition, PipelineExecutionContext, PipelineStep


# ---------------------------------------------------------------------------
# Вспомогатели
# ---------------------------------------------------------------------------

def _make_retrieval_step(step_id: str, after: list[str] | None = None) -> PipelineStep:
    return PipelineStep(
        step_id=step_id,
        type="retrieval",
        name=step_id,
        system_prompt="",
        after_step_ids=after or [],
        top_k=3,
        tag_ids=[],
    )


def _make_validation_step(
    step_id: str,
    after: list[str] | None = None,
    validation_prompt: str = "Подтвердите",
    options: list[str] | None = None,
) -> PipelineStep:
    return PipelineStep(
        step_id=step_id,
        type="validation",
        name=step_id,
        system_prompt=validation_prompt,
        validation_prompt=validation_prompt,
        options=options or ["Да", "Нет"],
        after_step_ids=after or [],
    )


def _make_ctx(
    steps: list[PipelineStep],
    step_results: dict[str, Any] | None = None,
) -> PipelineExecutionContext:
    return PipelineExecutionContext(
        chat_id=str(uuid.uuid4()),
        message_id=str(uuid.uuid4()),
        query="тестовый запрос",
        pipeline_id="test-pipeline",
        domain_id="test-domain",
        steps=steps,
        final_composition=FinalComposition(system_prompt="Ответ: {step1.result}"),
        step_results=step_results or {},
        vault_ids=[],
    )


def _make_executor(chat=None) -> tuple[PipelineExecutor, AsyncMock]:
    """Mock-экземпляр PipelineExecutor с мокнутой DB."""
    db = AsyncMock()
    db.get = AsyncMock(return_value=chat or MagicMock())
    db.commit = AsyncMock()
    return PipelineExecutor(db=db), db


async def _collect(gen) -> list[dict]:
    """Helper: собрать все чанки из async-генератора."""
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return chunks


# ---------------------------------------------------------------------------
# Тесты: _build_levels
# ---------------------------------------------------------------------------

class TestBuildLevels:

    def test_single_start_step(self):
        steps = [_make_retrieval_step("a")]
        levels = _build_levels(steps)
        assert len(levels) == 1
        assert levels[0][0].step_id == "a"

    def test_linear_chain_three_steps(self):
        steps = [
            _make_retrieval_step("a"),
            _make_retrieval_step("b", after=["a"]),
            _make_retrieval_step("c", after=["b"]),
        ]
        levels = _build_levels(steps)
        assert len(levels) == 3
        assert levels[0][0].step_id == "a"
        assert levels[1][0].step_id == "b"
        assert levels[2][0].step_id == "c"

    def test_parallel_branches_same_level(self):
        steps = [
            _make_retrieval_step("a"),
            _make_retrieval_step("b"),  # тоже стартовый
        ]
        levels = _build_levels(steps)
        assert len(levels) == 1
        ids = {s.step_id for s in levels[0]}
        assert ids == {"a", "b"}

    def test_diamond_dependency(self):
        # a → b, a → c, b+c → d
        steps = [
            _make_retrieval_step("a"),
            _make_retrieval_step("b", after=["a"]),
            _make_retrieval_step("c", after=["a"]),
            _make_retrieval_step("d", after=["b", "c"]),
        ]
        levels = _build_levels(steps)
        level_ids = [{s.step_id for s in lvl} for lvl in levels]
        assert {"a"} in level_ids
        assert {"b", "c"} in level_ids
        assert {"d"} in level_ids

    def test_validation_step_in_levels(self):
        steps = [
            _make_retrieval_step("r1"),
            _make_validation_step("v1", after=["r1"]),
            _make_retrieval_step("r2", after=["v1"]),
        ]
        levels = _build_levels(steps)
        assert len(levels) == 3
        assert levels[1][0].step_id == "v1"


# ---------------------------------------------------------------------------
# Тесты: _resolve_prompt
# ---------------------------------------------------------------------------

class TestResolvePrompt:

    def _ctx(self, step_results):
        return _make_ctx([], step_results=step_results)

    def test_query_substitution(self):
        ctx = self._ctx({})
        ctx.query = "мой запрос"
        assert _resolve_prompt("Запрос: {query}", ctx) == "Запрос: мой запрос"

    def test_step_result_substitution(self):
        ctx = self._ctx({"s1": "результат"})
        assert _resolve_prompt("{s1.result}", ctx) == "результат"

    def test_dict_key_access(self):
        ctx = self._ctx({"s1": {"score": "42"}})
        assert _resolve_prompt("{s1.score}", ctx) == "42"

    def test_private_key_skipped(self):
        ctx = self._ctx({"_validation_v1": "ответ"})
        # приватные ключи не подставляются в шаблон
        result = _resolve_prompt("{_validation_v1.result}", ctx)
        assert result == "{_validation_v1.result}"  # плейсхолдер сохраняется


# ---------------------------------------------------------------------------
# Тесты: _dag_execute — basic flow
# ---------------------------------------------------------------------------

class TestDagExecute:

    def _mock_provider(self, tokens=("hello",)):
        prov = MagicMock()
        async def _gen(msgs):
            for t in tokens:
                yield t
        prov.generate_stream = _gen
        return prov

    @pytest.mark.asyncio
    async def test_no_active_provider_yields_error(self):
        steps = [_make_retrieval_step("s1")]
        ctx = _make_ctx(steps)
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc:
            mock_svc.get_active_provider.return_value = None
            chunks = await _collect(executor.run_stream(ctx))
        types = [c["type"] for c in chunks]
        assert "error" in types

    @pytest.mark.asyncio
    async def test_pipeline_selected_chunk_emitted(self):
        steps = [_make_retrieval_step("s1")]
        ctx = _make_ctx(steps)
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            chunks = await _collect(executor.run_stream(ctx))
        types = [c["type"] for c in chunks]
        assert "pipeline_selected" in types

    @pytest.mark.asyncio
    async def test_step_skipped_yields_step_skipped_no_docs(self):
        steps = [_make_retrieval_step("s1")]
        ctx = _make_ctx(steps)
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            chunks = await _collect(executor.run_stream(ctx))
        types = [c["type"] for c in chunks]
        assert "step_skipped_no_docs" in types

    @pytest.mark.asyncio
    async def test_final_composition_tokens_emitted(self):
        steps = [_make_retrieval_step("s1")]
        ctx = _make_ctx(steps)
        ctx.step_results["s1"] = "данные"
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider(tokens=("to", "ken"))
            chunks = await _collect(executor.run_stream(ctx))
        token_contents = [c["content"] for c in chunks if c["type"] == "token"]
        assert token_contents == ["to", "ken"]

    @pytest.mark.asyncio
    async def test_pipeline_complete_chunk_emitted(self):
        steps = [_make_retrieval_step("s1")]
        ctx = _make_ctx(steps)
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            chunks = await _collect(executor.run_stream(ctx))
        types = [c["type"] for c in chunks]
        assert "pipeline_complete" in types


# ---------------------------------------------------------------------------
# Тесты: validation-пауза
# ---------------------------------------------------------------------------

class TestValidationPause:

    def _mock_provider(self, tokens=("hello",)):
        prov = MagicMock()
        async def _gen(msgs):
            for t in tokens:
                yield t
        prov.generate_stream = _gen
        return prov

    @pytest.mark.asyncio
    async def test_validation_step_stops_stream(self):
        """validation-шаг должен остановить поток и эмитить validation_required."""
        steps = [
            _make_retrieval_step("r1"),
            _make_validation_step("v1", after=["r1"]),
        ]
        ctx = _make_ctx(steps, step_results={"r1": "данные"})
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            chunks = await _collect(executor.run_stream(ctx))
        types = [c["type"] for c in chunks]
        assert "validation_required" in types
        # после validation_required не должно быть pipeline_complete
        assert "pipeline_complete" not in types

    @pytest.mark.asyncio
    async def test_validation_required_chunk_fields(self):
        """validation_required chunk содержит нужные поля."""
        steps = [
            _make_validation_step("v1", options=["Да", "Нет", "Отложить"]),
        ]
        ctx = _make_ctx(steps)
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            chunks = await _collect(executor.run_stream(ctx))
        vr = next(c for c in chunks if c["type"] == "validation_required")
        assert "resume_token" in vr
        assert "options" in vr
        assert vr["options"] == ["Да", "Нет", "Отложить"]
        assert "step_name" in vr

    @pytest.mark.asyncio
    async def test_save_pause_state_called_with_full_context(self):
        """При validation-паузе executor сохраняет pause_state в БД."""
        steps = [_make_validation_step("v1")]
        ctx = _make_ctx(steps)
        executor, mock_db = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            await _collect(executor.run_stream(ctx))
        # DB commit вызывался — состояние сохранено
        mock_db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_save_pause_state_writes_full_context_snapshot(self):
        """Сохранённый pause_state содержит полный context_snapshot."""
        steps = [_make_validation_step("v1")]
        ctx = _make_ctx(steps)
        executor, mock_db = _make_executor()
        chat_mock = MagicMock()
        chat_mock.pipeline_pause_state = None
        mock_db.get = AsyncMock(return_value=chat_mock)

        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            await _collect(executor.run_stream(ctx))

        # pipeline_pause_state должен быть присвоен
        assert chat_mock.pipeline_pause_state is not None
        snapshot = chat_mock.pipeline_pause_state
        assert "context_snapshot" in snapshot
        assert snapshot["context_snapshot"]["chat_id"] == ctx.chat_id


# ---------------------------------------------------------------------------
# Тесты: возобновление после validation
# ---------------------------------------------------------------------------

class TestResumeFromValidation:

    def _mock_provider(self, tokens=("hello",)):
        prov = MagicMock()
        async def _gen(msgs):
            for t in tokens:
                yield t
        prov.generate_stream = _gen
        return prov

    @pytest.mark.asyncio
    async def test_resume_skips_validated_level(self):
        """При resume executor пропускает уже выполненные шаги."""
        steps = [
            _make_retrieval_step("r1"),
            _make_validation_step("v1", after=["r1"]),
            _make_retrieval_step("r2", after=["v1"]),
        ]
        ctx = _make_ctx(steps, step_results={"r1": "данные r1", "_validation_v1": "Да"})
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            chunks = await _collect(executor.resume_from_validation(ctx, "v1"))
        types = [c["type"] for c in chunks]
        # r1 уже выполнен, v1 уже подтверждён — только r2 должен выполняться
        assert "pipeline_complete" in types
        assert "validation_required" not in types

    @pytest.mark.asyncio
    async def test_resume_emits_pipeline_selected(self):
        steps = [
            _make_validation_step("v1"),
            _make_retrieval_step("r1", after=["v1"]),
        ]
        ctx = _make_ctx(steps, step_results={"_validation_v1": "Да"})
        executor, _ = _make_executor()
        with patch("app.services.pipeline_executor.settings_service") as mock_svc, \
             patch.object(executor, "_retrieve_for_step_dag", new_callable=AsyncMock, return_value=[]):
            mock_svc.get_active_provider.return_value = self._mock_provider()
            chunks = await _collect(executor.resume_from_validation(ctx, "v1"))
        types = [c["type"] for c in chunks]
        assert "pipeline_resumed" in types
