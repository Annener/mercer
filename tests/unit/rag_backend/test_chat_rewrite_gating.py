"""Tests for query-rewriter gating in chat.py::plain_stream.

Bug: query-rewriter (LLM-переформулировка) и сопутствующий статус
«Переформулирую вопрос для поиска в базе знаний…» срабатывали на КАЖДОЕ
follow-up сообщение в чате (при наличии `context.history`), вне зависимости
от того, включён ли RAG/пайплайн или нет. Это давало +1–3 сек задержки и
фантомный статус, когда retrieval ниже по коду не выполнялся.

Здесь проверяем новое условие `need_rewrite = rag_prefill_enabled ∨
locked_pipeline (real) ∨ tool_enabled`: rewrite + статус должны появиться,
если хотя бы одно из трёх условий истинно. Иначе — ни вызова rewrite,
ни статуса.

Тесты — source-level (как `test_chat_agent_loop_wiring.py`): behavioral
вызов `plain_stream` невозможен без полноценной БД/провайдера, поэтому
assert'ы идут по тексту `chat.py`. Этот паттерн уже используется в
проекте для аналогичных интеграционных контрактов.
"""
from __future__ import annotations

from app.api import chat as chat_module


def _source() -> str:
    return open(chat_module.__file__, encoding="utf-8").read()


def test_rewrite_status_gated_by_three_conditions():
    """В `plain_stream` должно быть gating-условие `need_rewrite` из трёх
    веток: `rag_prefill_enabled`, реально залоченный pipeline,
    `use_tool` (= tool_enabled)."""
    text = _source()
    assert "need_rewrite = (" in text, "Ожидается gating-условие need_rewrite"
    # Три источника истинности
    assert "rag_prefill_enabled" in text
    assert "_pipeline_locked_real" in text
    assert "use_tool" in text
    # Старый безусловный текст должен исчезнуть из источника.
    assert "Переформулирую вопрос для поиска" not in text, (
        "Старый безусловный rewrite-статус должен быть заменён на "
        "контекстный (только при need_rewrite=True)"
    )


def test_three_rewrite_status_variants_present():
    """Три разных статус-текста под разные причины rewrite."""
    text = _source()
    assert "Готовлю поисковый запрос для подмешивания базы знаний" in text
    assert "Готовлю запрос для пайплайна" in text
    assert "Готовлю запрос для поиска в базе знаний" in text


def test_tool_settings_load_before_rewrite():
    """`load_retrieval_tool_settings` должен зваться ДО `need_rewrite`,
    иначе gating не увидит `use_tool`."""
    text = _source()
    load_idx = text.find("load_retrieval_tool_settings(db)")
    # ищем первое вхождение `need_rewrite = (`
    gate_idx = text.find("need_rewrite = (")
    assert load_idx != -1
    assert gate_idx != -1
    assert load_idx < gate_idx, (
        "tool_settings должны загружаться раньше, чем вычисляется "
        "`need_rewrite`, чтобы gating видел tool_enabled"
    )


def test_locked_pipeline_sentinel_excluded():
    """`PIPELINE_NONE_ID == '__none__'` НЕ должен триггерить rewrite
    сам по себе. Проверяем, что условие исключает его явно."""
    text = _source()
    # В блоке `need_rewrite` должно быть явное отсечение sentinel.
    # Точное место: строка `bool(_locked_pipeline_id) and _locked_pipeline_id != PIPELINE_NONE_ID`
    assert "_locked_pipeline_id != PIPELINE_NONE_ID" in text


def test_rag_prefill_has_priority_in_status_text():
    """Текст статуса должен явно приоритизировать `rag_prefill_enabled`
    (все три условия одновременно не могут быть активны, но приоритет всё
    равно полезен как контракт)."""
    text = _source()
    # Найдём кусок ветвления для статуса:
    block_start = text.find("if need_rewrite and bool(context.history):")
    assert block_start != -1
    block = text[block_start:block_start + 800]
    # Порядок: rag_prefill → pipeline → tool. Первая `if` — rag_prefill.
    assert block.find("rag_prefill_enabled") < block.find("_pipeline_locked_real") < block.find('else')
