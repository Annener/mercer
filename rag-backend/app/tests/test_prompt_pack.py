"""Unit-тесты для resolve_step_vars() из prompt_pack.py.

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
