"""
Unit-тесты для pipeline_dag.py.

Не требуют БД, FastAPI или внешних зависимостей.
Запуск: pytest rag-backend/app/tests/test_pipeline_dag.py -v
"""

from __future__ import annotations

import sys
import os

# Добавляем корень rag-backend в путь, чтобы импортировать shared_contracts
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from pydantic import ValidationError

from app.services.pipeline_dag import (
    build_dag,
    detect_cycles,
    get_execution_levels,
    topological_sort,
    validate_dag,
)

# ---------------------------------------------------------------------------
# Вспомогательная фабрика шагов (создаём Pydantic-объекты напрямую,
# чтобы тесты не зависели от полного импорта приложения)
# ---------------------------------------------------------------------------

from shared_contracts.models import PipelineStep  # noqa: E402


def make_retrieval(step_id: str, after: list[str] | None = None) -> PipelineStep:
    return PipelineStep(
        step_id=step_id,
        type="retrieval",
        name=step_id,
        system_prompt="test",
        after_step_ids=after or [],
        top_k=5,
        tag_ids=[],
        role=None,
        output_format="text",
    )


def make_validation(step_id: str, after: list[str] | None = None) -> PipelineStep:
    return PipelineStep(
        step_id=step_id,
        type="validation",
        name=step_id,
        system_prompt="validate?",
        after_step_ids=after or [],
        validation_prompt="Продолжить?",
        options=["Да", "Нет"],
    )


# ---------------------------------------------------------------------------
# build_dag
# ---------------------------------------------------------------------------


class TestBuildDag:
    def test_linear_chain(self):
        steps = [
            make_retrieval("a"),
            make_retrieval("b", after=["a"]),
            make_retrieval("c", after=["b"]),
        ]
        dag = build_dag(steps)
        assert dag["a"] == ["b"]
        assert dag["b"] == ["c"]
        assert dag["c"] == []

    def test_parallel_branches(self):
        steps = [
            make_retrieval("start"),
            make_retrieval("branch1", after=["start"]),
            make_retrieval("branch2", after=["start"]),
        ]
        dag = build_dag(steps)
        assert set(dag["start"]) == {"branch1", "branch2"}

    def test_unknown_parent_ignored(self):
        """Ссылка на несуществующий step_id не вызывает KeyError при build."""
        steps = [
            make_retrieval("a", after=["nonexistent"]),
        ]
        dag = build_dag(steps)
        assert dag["a"] == []


# ---------------------------------------------------------------------------
# topological_sort
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_linear(self):
        steps = [
            make_retrieval("a"),
            make_retrieval("b", after=["a"]),
            make_retrieval("c", after=["b"]),
        ]
        levels = topological_sort(steps)
        assert levels == [["a"], ["b"], ["c"]]

    def test_parallel_level(self):
        steps = [
            make_retrieval("start"),
            make_retrieval("b1", after=["start"]),
            make_retrieval("b2", after=["start"]),
            make_retrieval("end", after=["b1", "b2"]),
        ]
        levels = topological_sort(steps)
        # Уровень 0: [start], уровень 1: [b1, b2] (любой порядок), уровень 2: [end]
        assert levels[0] == ["start"]
        assert set(levels[1]) == {"b1", "b2"}
        assert levels[2] == ["end"]

    def test_diamond(self):
        """A → B, A → C, B → D, C → D."""
        steps = [
            make_retrieval("A"),
            make_retrieval("B", after=["A"]),
            make_retrieval("C", after=["A"]),
            make_retrieval("D", after=["B", "C"]),
        ]
        levels = topological_sort(steps)
        assert levels[0] == ["A"]
        assert set(levels[1]) == {"B", "C"}
        assert levels[2] == ["D"]

    def test_cycle_returns_empty(self):
        """При цикле topological_sort возвращает []."""
        # Обходим pydantic-валидатор, патчим after_step_ids после создания
        a = make_retrieval("a")
        b = make_retrieval("b", after=["a"])
        # Создаём цикл напрямую, минуя валидатор (для теста detect_cycles)
        object.__setattr__(a, "after_step_ids", ["b"])
        steps = [a, b]
        assert topological_sort(steps) == []


# ---------------------------------------------------------------------------
# detect_cycles
# ---------------------------------------------------------------------------


class TestDetectCycles:
    def test_no_cycle(self):
        steps = [
            make_retrieval("a"),
            make_retrieval("b", after=["a"]),
        ]
        assert detect_cycles(steps) is None

    def test_direct_cycle(self):
        a = make_retrieval("a")
        b = make_retrieval("b", after=["a"])
        object.__setattr__(a, "after_step_ids", ["b"])
        cycle = detect_cycles([a, b])
        assert cycle is not None
        assert set(cycle) == {"a", "b"}

    def test_self_loop_via_validator(self):
        """Pydantic-валидатор должен запретить self-loop."""
        with pytest.raises(ValidationError):
            make_retrieval("a", after=["a"])


# ---------------------------------------------------------------------------
# validate_dag
# ---------------------------------------------------------------------------


class TestValidateDag:
    def test_valid_linear(self):
        steps = [
            make_retrieval("a"),
            make_retrieval("b", after=["a"]),
        ]
        assert validate_dag(steps) == []

    def test_no_start_step(self):
        """Все шаги имеют зависимости — нет стартового."""
        a = make_retrieval("a", after=["b"])
        b = make_retrieval("b", after=["a"])
        # Принудительно убираем валидацию цикла для теста no-start
        errors = validate_dag([a, b])
        # Должна быть ошибка о цикле или об отсутствии стартового шага
        assert len(errors) > 0

    def test_missing_after_step_id(self):
        steps = [
            make_retrieval("a", after=["nonexistent"]),
        ]
        errors = validate_dag(steps)
        assert any("nonexistent" in e for e in errors)

    def test_cycle_detected(self):
        a = make_retrieval("a")
        b = make_retrieval("b", after=["a"])
        object.__setattr__(a, "after_step_ids", ["b"])
        errors = validate_dag([a, b])
        assert any("цикл" in e.lower() for e in errors)

    def test_validation_step_without_children(self):
        steps = [
            make_retrieval("a"),
            make_validation("check", after=["a"]),
        ]
        errors = validate_dag(steps)
        assert any("check" in e and "потомков" in e for e in errors)

    def test_validation_step_with_children_ok(self):
        steps = [
            make_retrieval("a"),
            make_validation("check", after=["a"]),
            make_retrieval("final", after=["check"]),
        ]
        assert validate_dag(steps) == []


# ---------------------------------------------------------------------------
# get_execution_levels
# ---------------------------------------------------------------------------


class TestGetExecutionLevels:
    def test_linear_levels(self):
        steps = [
            make_retrieval("a"),
            make_retrieval("b", after=["a"]),
        ]
        levels = get_execution_levels(steps)
        assert len(levels) == 2
        assert levels[0][0].step_id == "a"
        assert levels[1][0].step_id == "b"

    def test_parallel_steps_same_level(self):
        steps = [
            make_retrieval("start"),
            make_retrieval("p1", after=["start"]),
            make_retrieval("p2", after=["start"]),
            make_retrieval("end", after=["p1", "p2"]),
        ]
        levels = get_execution_levels(steps)
        assert len(levels) == 3
        assert {s.step_id for s in levels[1]} == {"p1", "p2"}

    def test_cycle_raises_value_error(self):
        a = make_retrieval("a")
        b = make_retrieval("b", after=["a"])
        object.__setattr__(a, "after_step_ids", ["b"])
        with pytest.raises(ValueError, match="цикл"):
            get_execution_levels([a, b])

    def test_validation_in_levels(self):
        """Шаг validation корректно попадает в нужный уровень."""
        steps = [
            make_retrieval("fetch"),
            make_validation("approve", after=["fetch"]),
            make_retrieval("enrich", after=["approve"]),
        ]
        levels = get_execution_levels(steps)
        assert levels[0][0].step_id == "fetch"
        assert levels[1][0].step_id == "approve"
        assert levels[1][0].type == "validation"
        assert levels[2][0].step_id == "enrich"
