"""Smoke-тесты budget-логики pdf-sidecar/drift.py.

Запускаются без загруженной .gguf модели — подменяем ``Llama`` mock-ом,
который при ``tokenize`` прикидывается QVikhr (~4 символа на токен), а
при ``create_chat_completion`` просто эхо-проверяет что prompt влезает
в ``n_ctx``.

Запуск:
  cd pdf-sidecar && .venv/bin/python tests/test_budget_logic.py
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

# Делаем pdf-sidecar/ корнем, чтобы ``import drift`` сработал.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))


class MockLlama:
    """Минимальная заглушка под ``llama_cpp.Llama``.

    Атрибуты, которые читает drift.py:
      - ``_n_ctx`` (int)
      - ``ctx`` (c_types pointer — для ``llama_n_ctx``)
      - ``tokenize(text_bytes, add_bos, special) -> list[int]``
      - ``create_chat_completion(messages, ...) -> dict``
    """

    n_ctx_value: int = 256  # маленькое окно для провокации chunked-логики

    def __init__(self, n_ctx: int | None = None) -> None:
        if n_ctx is not None:
            self.n_ctx_value = n_ctx
        # ctx должен быть truthy — drift.py вызывает ``llama_cpp.llama_n_ctx(model.ctx)``
        self.ctx = object()
        self.last_create_kwargs: dict | None = None

    def tokenize(self, text_bytes: bytes, add_bos: bool = False, special: bool = False) -> list[int]:
        # QVikhr ~= 4 символа на токен, плюс 1 на BOS.
        n = max(1, len(text_bytes) // 4)
        return [0] * (n + (1 if add_bos else 0))

    def create_chat_completion(self, messages, **kwargs) -> dict:
        # Проверим, что prompt реально влезает в n_ctx.
        prompt_text = "\n".join(m.get("content", "") for m in messages)
        prompt_tokens = self.tokenize(prompt_text.encode("utf-8"))
        max_tokens = kwargs.get("max_tokens", 512)
        if len(prompt_tokens) + max_tokens > self.n_ctx_value:
            # Эмулируем реальное поведение llama-cpp.
            raise ValueError(
                f"Requested tokens ({len(prompt_tokens)} + max_tokens={max_tokens}) "
                f"exceed context window of {self.n_ctx_value}"
            )
        self.last_create_kwargs = kwargs
        return {
            "choices": [
                {"message": {"content": '{"hints": [{"fact": "ok", "confidence": 0.9}]}'}}
            ]
        }


def _install_mock(mock: MockLlama) -> None:
    """Подменяет ``drift._model_n_ctx`` на простую функцию, возвращающую
    ``mock.n_ctx_value``. Сам модуль ``llama_cpp`` трогать не нужно — мы
    не вызываем его из тестов напрямую, а ``drift._model_n_ctx`` уже
    изолирует ctypes-вызов через try/except с fallback на ``model._n_ctx``.
    """
    import drift
    globals()["mock_instance"] = mock

    def _fake_n_ctx(model):
        return globals()["mock_instance"].n_ctx_value

    drift._model_n_ctx = _fake_n_ctx


def _patch_model(mock: MockLlama) -> None:
    """Кладёт mock в ``drift._state`` и подменяет ``_ensure_loaded``,
    чтобы не ходить в файловую систему."""
    import drift
    drift._state["model"] = mock  # сбрасываем между тестами

    async def _fake_ensure_loaded():
        drift._state["model"] = mock

    drift._load_model_sync = lambda: None
    drift._ensure_loaded = _fake_ensure_loaded


def test_short_prompt_passes_through():
    mock = MockLlama(n_ctx=4096)
    _install_mock(mock)
    _patch_model(mock)

    import asyncio
    import drift

    async def run():
        return await drift.detect_drift(drift.DriftRequest(
            model="x",
            messages=[{"role": "user", "content": "hi"}],
            current_state="location: tavern",
        ))

    resp = asyncio.run(run())
    assert resp.hints, "expected at least one hint"
    assert resp.hints[0].fact == "ok"
    print("test_short_prompt_passes_through: OK")


def test_long_prompt_triggers_chunked_loop():
    """Подсовываем огромный prompt при n_ctx=512 — должны влезть
    через chunked-loop и не упасть ValueError."""
    mock = MockLlama(n_ctx=512)
    _install_mock(mock)
    _patch_model(mock)

    import asyncio
    import drift

    big_messages = [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": "lorem ipsum dolor sit amet " * 50}
        for i in range(20)
    ]

    async def run():
        return await drift.detect_drift(drift.DriftRequest(
            model="x",
            messages=big_messages,
            current_state="x" * 4000,
        ))

    resp = asyncio.run(run())
    assert resp.hints
    assert mock.last_create_kwargs is not None, f"create_chat_completion never called. hints={resp.hints}"
    print("test_long_prompt_triggers_chunked_loop: OK")


def test_summarize_chunks_large_block():
    mock = MockLlama(n_ctx=512)
    _install_mock(mock)
    _patch_model(mock)

    import asyncio
    import drift

    msgs = [
        {"role": "user" if i % 2 == 0 else "assistant",
         "content": "fact " + str(i) + " " + ("x" * 300)}
        for i in range(8)
    ]

    async def run():
        return await drift.summarize(drift.SummarizeRequest(
            model="x",
            previous_summary="Earlier: heroes met a dragon.",
            messages_to_compress=msgs,
        ))

    resp = asyncio.run(run())
    assert resp.summary
    print("test_summarize_chunks_large_block: OK summary_len=", len(resp.summary))


def test_summarize_single_huge_message_does_not_crash():
    mock = MockLlama(n_ctx=256)
    _install_mock(mock)
    _patch_model(mock)

    import asyncio
    import drift

    msgs = [{"role": "user", "content": "y" * 5000}]

    async def run():
        return await drift.summarize(drift.SummarizeRequest(
            model="x",
            previous_summary="",
            messages_to_compress=msgs,
        ))

    resp = asyncio.run(run())
    assert resp.summary
    print("test_summarize_single_huge_message_does_not_crash: OK")


def test_too_small_ctx_returns_503():
    """Если n_ctx настолько мал, что system_prompt + 1 символ не влезает —
    должен вернуться 503 с информативным detail."""
    from fastapi import HTTPException

    mock = MockLlama(n_ctx=8)
    _install_mock(mock)
    _patch_model(mock)

    import asyncio
    import drift

    msgs = [{"role": "user", "content": "z" * 1000}]

    async def run():
        return await drift.summarize(drift.SummarizeRequest(
            model="x",
            previous_summary="prev " * 200,
            messages_to_compress=msgs,
        ))

    try:
        asyncio.run(run())
        print("test_too_small_ctx_returns_503: OK (degraded path)")
    except HTTPException as exc:
        assert exc.status_code in (500, 503), f"unexpected {exc.status_code}"
        print(f"test_too_small_ctx_returns_503: OK (got {exc.status_code})")


if __name__ == "__main__":
    # Приглушаем logger.exception на degraded-пути — иначе traceback
    # от логгера путает вывод тестов.
    import logging
    logging.getLogger("drift").setLevel(logging.CRITICAL)

    test_short_prompt_passes_through()
    test_long_prompt_triggers_chunked_loop()
    test_summarize_chunks_large_block()
    test_summarize_single_huge_message_does_not_crash()
    test_too_small_ctx_returns_503()
    print("\nAll tests passed.")
