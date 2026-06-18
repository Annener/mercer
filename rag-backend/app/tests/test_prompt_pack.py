"""Unit-тесты для resolve_step_vars() из prompt_pack.py
и метода PipelineExecutionContext.resolve().

Без зависимостей от БД и HTTP — чистая логика.
"""
from __future__ import annotations

import json
import pytest

from app.services.prompt_pack import resolve_step_vars


# ---------------------------------------------------------------------------
# Базовые случаи
# ---------------------------------------------------------------------------

class TestResolveStepVarsText:
    """Тесты подстановки {STEP_ID.result} для строковых результатов."""

    def test_single_text_result(self):
        result = resolve_step_vars(
            "Контекст: {analyze.result}",
            {"analyze": "найдены документы"},
        )
        assert result == "Контекст: найдены документы"

    def test_multiple_text_results(self):
        result = resolve_step_vars(
            "A: {step_a.result}\nB: {step_b.result}",
            {"step_a": "ответ A", "step_b": "ответ B"},
        )
        assert result == "A: ответ A\nB: ответ B"

    def test_result_repeated(self):
        """Один step_id используется дважды в шаблоне."""
        result = resolve_step_vars(
            "{s.result} и снова {s.result}",
            {"s": "X"},
        )
        assert result == "X и снова X"

    def test_query_passthrough(self):
        """Переменная {query} не входит в паттерн STEP_ID.xxx — должна остаться как есть."""
        result = resolve_step_vars(
            "Запрос: {query}",
            {},
        )
        assert result == "Запрос: {query}"


class TestResolveStepVarsJson:
    """Тесты подстановки {STEP_ID.result} для dict-результатов."""

    def test_dict_result_serialized_to_json(self):
        data = {"answer": "да", "confidence": 0.9}
        result = resolve_step_vars(
            "JSON: {step.result}",
            {"step": data},
        )
        assert result == f"JSON: {json.dumps(data, ensure_ascii=False)}"

    def test_dict_key_access(self):
        result = resolve_step_vars(
            "Ответ: {step.answer}",
            {"step": {"answer": "да", "confidence": 0.9}},
        )
        assert result == "Ответ: да"

    def test_dict_key_access_int_value(self):
        result = resolve_step_vars(
            "Счёт: {step.score}",
            {"step": {"score": 42}},
        )
        assert result == "Счёт: 42"


# ---------------------------------------------------------------------------
# Граничные случаи — отсутствие step_id или ключа
# ---------------------------------------------------------------------------

class TestResolveStepVarsMissing:
    """Тесты поведения при отсутствующих step_id / ключах."""

    def test_missing_step_id_keeps_placeholder(self):
        """Если step_id не в step_results — placeholder остаётся."""
        result = resolve_step_vars(
            "Данные: {missing_step.result}",
            {},
        )
        assert result == "Данные: {missing_step.result}"

    def test_missing_key_in_dict_keeps_placeholder(self):
        """Если ключ не найден в dict — placeholder остаётся."""
        result = resolve_step_vars(
            "Ключ: {step.nonexistent}",
            {"step": {"answer": "да"}},
        )
        assert result == "Ключ: {step.nonexistent}"

    def test_key_access_on_string_value_keeps_placeholder(self):
        """Если результат — строка, а запрошен ключ — placeholder остаётся."""
        result = resolve_step_vars(
            "Ключ: {step.somekey}",
            {"step": "строковый результат"},
        )
        assert result == "Ключ: {step.somekey}"

    def test_empty_step_results(self):
        """Пустой step_results — все placeholders остаются."""
        template = "{a.result} + {b.key}"
        result = resolve_step_vars(template, {})
        assert result == template


# ---------------------------------------------------------------------------
# Комплексные шаблоны
# ---------------------------------------------------------------------------

class TestResolveStepVarsComplex:
    """Тесты сложных шаблонов с несколькими переменными и смешанными типами."""

    def test_mixed_present_and_missing(self):
        result = resolve_step_vars(
            "{present.result} | {absent.result}",
            {"present": "OK"},
        )
        assert result == "OK | {absent.result}"

    def test_text_around_variable(self):
        result = resolve_step_vars(
            "Начало {step.result} конец",
            {"step": "середина"},
        )
        assert result == "Начало середина конец"

    def test_no_variables_unchanged(self):
        template = "Просто текст без переменных"
        result = resolve_step_vars(template, {"step": "anything"})
        assert result == template

    def test_dict_result_and_key_same_step(self):
        """Один шаг используется как .result (весь JSON) и как .key (конкретное поле)."""
        data = {"title": "Заголовок", "body": "Тело"}
        result = resolve_step_vars(
            "Всё: {s.result} | Только: {s.title}",
            {"s": data},
        )
        expected_json = json.dumps(data, ensure_ascii=False)
        assert result == f"Всё: {expected_json} | Только: Заголовок"

    def test_validation_step_result(self):
        """Результат validation-шага — строка (ответ пользователя)."""
        result = resolve_step_vars(
            "Пользователь ответил: {confirm.result}",
            {"confirm": "да, продолжай"},
        )
        assert result == "Пользователь ответил: да, продолжай"


# ---------------------------------------------------------------------------
# PipelineExecutionContext.resolve() — интеграция {query} + {STEP_ID.*}
# ---------------------------------------------------------------------------

class TestPipelineExecutionContextResolve:
    """Тесты метода ctx.resolve() — интеграция query-замены и resolve_step_vars."""

    def _make_ctx(self, query: str, step_results: dict | None = None):
        """Создать PipelineExecutionContext с минимальными полями для тестирования."""
        from shared_contracts.models import PipelineExecutionContext
        return PipelineExecutionContext(
            chat_id="chat-test",
            message_id="msg-test",
            query=query,
            step_results=step_results or {},
        )

    def test_query_substituted(self):
        ctx = self._make_ctx(query="что такое RAG?")
        result = ctx.resolve("Вопрос: {query}")
        assert result == "Вопрос: что такое RAG?"

    def test_step_result_substituted(self):
        ctx = self._make_ctx(query="q", step_results={"analyze": "результат шага"})
        result = ctx.resolve("Контекст: {analyze.result}")
        assert result == "Контекст: результат шага"

    def test_query_and_step_result_together(self):
        ctx = self._make_ctx(
            query="расскажи о продукте",
            step_results={"search": "найдено 3 документа"},
        )
        result = ctx.resolve("Запрос: {query}\nДанные: {search.result}")
        assert result == "Запрос: расскажи о продукте\nДанные: найдено 3 документа"

    def test_query_with_curly_braces_not_conflicting(self):
        """query содержит фигурные скобки — они не должны ломать resolve_step_vars."""
        ctx = self._make_ctx(query="{не переменная}", step_results={"s": "val"})
        # {query} заменяется на строку с фигурными скобками;
        # resolve_step_vars после этого не должен их интерпретировать как переменные
        # (они не соответствуют паттерну STEP_ID.accessor)
        result = ctx.resolve("Q={query} S={s.result}")
        assert "{не переменная}" in result
        assert "val" in result

    def test_dict_step_result_key_access(self):
        ctx = self._make_ctx(
            query="test",
            step_results={"classify": {"category": "финансы", "confidence": 0.95}},
        )
        result = ctx.resolve("Категория: {classify.category}")
        assert result == "Категория: финансы"

    def test_missing_step_keeps_placeholder(self):
        ctx = self._make_ctx(query="q")
        result = ctx.resolve("Данные: {nonexistent.result}")
        assert result == "Данные: {nonexistent.result}"

    def test_empty_step_results_query_only(self):
        ctx = self._make_ctx(query="простой вопрос")
        result = ctx.resolve("Ответь на {query}")
        assert result == "Ответь на простой вопрос"

    def test_validation_feedback_in_context(self):
        """Ответ пользователя из validation-шага доступен через ctx.resolve()."""
        ctx = self._make_ctx(
            query="анализ",
            step_results={"user_confirm": "продолжай, всё верно"},
        )
        result = ctx.resolve("Пользователь: {user_confirm.result}. Запрос: {query}")
        assert result == "Пользователь: продолжай, всё верно. Запрос: анализ"

    def test_parallel_steps_both_available(self):
        """После параллельного выполнения оба результата доступны через ctx.resolve()."""
        ctx = self._make_ctx(
            query="комплексный запрос",
            step_results={
                "branch_a": "результат ветки A",
                "branch_b": "результат ветки B",
            },
        )
        result = ctx.resolve("{branch_a.result} + {branch_b.result}")
        assert result == "результат ветки A + результат ветки B"
