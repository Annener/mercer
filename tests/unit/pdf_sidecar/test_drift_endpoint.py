"""Unit-тесты для POST /drift (pdf-sidecar/drift.py, Phase 2a context-engine).

Подход: мокаем ``llama_cpp`` (через ``sys.modules``) до импорта ``drift``,
чтобы не требовать реальный .gguf файл и CUDA/Metal.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def drift_client(monkeypatch):
    """Создаёт TestClient для FastAPI-роутера ``drift`` с моком llama_cpp."""

    # Мок llama_cpp.Llama — create_chat_completion возвращает фиксированный JSON
    mock_llama_instance = MagicMock()
    mock_llama_instance.create_chat_completion = MagicMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "hints": [
                                    {
                                        "fact": "Дракон помирился с нами",
                                        "contradicts_field": None,
                                        "adds_field": "current_allies",
                                        "msg_ref": "msg-1",
                                        "confidence": 0.85,
                                    },
                                    {
                                        "fact": "Мы в новой локации",
                                        "contradicts_field": "current_location",
                                        "adds_field": None,
                                        "msg_ref": "msg-2",
                                        "confidence": 0.6,
                                    },
                                ]
                            }
                        )
                    }
                }
            ]
        }
    )

    mock_llama_cls = MagicMock(return_value=mock_llama_instance)

    mock_llama_cpp_module = MagicMock()
    mock_llama_cpp_module.Llama = mock_llama_cls
    sys.modules["llama_cpp"] = mock_llama_cpp_module

    # Чистим возможный закешированный импорт drift
    sys.modules.pop("drift", None)

    if "pdf-sidecar" not in sys.path:
        sys.path.insert(0, str(__file__).rsplit("/tests/", 1)[0] + "/pdf-sidecar")

    import drift  # type: ignore[import-not-found]

    # Сброс состояния модели перед каждым тестом
    drift._state["model"] = None
    drift._state["path"] = None

    # Вместо настоящего файла — создаём временный .gguf (его существование
    # достаточно для прохождения FileNotFoundError-проверки в _load_model_sync)
    fake_model = tempfile.NamedTemporaryFile(
        suffix=".gguf", delete=False, prefix="fake-qvikhr-"
    )
    fake_model.write(b"FAKE GGUF MODEL FILE")
    fake_model.close()
    monkeypatch.setenv("DRIFT_MODEL_PATH", fake_model.name)

    # Подключаем drift router к минимальному FastAPI app
    app = FastAPI()
    app.include_router(drift.router)

    yield TestClient(app), drift, mock_llama_cls, mock_llama_instance

    # Cleanup
    drift._state["model"] = None
    drift._state["path"] = None
    Path(fake_model.name).unlink(missing_ok=True)
    sys.modules.pop("llama_cpp", None)
    sys.modules.pop("drift", None)


class TestDriftEndpoint:
    def test_returns_hints(self, drift_client):
        client, _, _, _ = drift_client
        response = client.post(
            "/drift",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "messages": [{"role": "user", "content": "Дракон помирился с нами"}],
                "current_state": "(empty)",
                "schema_hint": None,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "hints" in body
        assert len(body["hints"]) == 2
        assert body["hints"][0]["fact"] == "Дракон помирился с нами"
        assert body["hints"][0]["confidence"] == 0.85

    def test_lazy_loads_model(self, drift_client):
        client, drift_mod, mock_llama_cls, _ = drift_client
        # Первый запрос — Llama() должен быть вызван (lazy load)
        assert mock_llama_cls.call_count == 0
        client.post(
            "/drift",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "messages": [{"role": "user", "content": "ping"}],
                "current_state": "(empty)",
            },
        )
        assert mock_llama_cls.call_count == 1
        # Второй запрос — load НЕ должен повторяться
        client.post(
            "/drift",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "messages": [{"role": "user", "content": "ping"}],
                "current_state": "(empty)",
            },
        )
        assert mock_llama_cls.call_count == 1

    def test_invalid_json_returns_502(self, drift_client):
        client, _, _, mock_instance = drift_client
        mock_instance.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "this is not json"}}]
        }
        # Сбрасываем кеш, чтобы второй вызов взял свежий mock
        import drift as drift_mod

        drift_mod._state["model"] = None
        drift_mod._state["path"] = None

        response = client.post(
            "/drift",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "messages": [{"role": "user", "content": "ping"}],
                "current_state": "(empty)",
            },
        )
        assert response.status_code == 502

    def test_hints_must_be_list(self, drift_client):
        client, _, _, mock_instance = drift_client
        mock_instance.create_chat_completion.return_value = {
            "choices": [{"message": {"content": json.dumps({"hints": "not a list"})}}]
        }
        import drift as drift_mod

        drift_mod._state["model"] = None
        drift_mod._state["path"] = None

        response = client.post(
            "/drift",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "messages": [{"role": "user", "content": "ping"}],
                "current_state": "(empty)",
            },
        )
        assert response.status_code == 502

    def test_temperature_matches_qvikhr_recommendation(self, drift_client):
        """QVikhr model card рекомендует temperature=0.3 для instruction-following.

        Если кто-то сбросит обратно на 0.0 — тест поймает рассинхрон с model card.
        """
        client, _, _, mock_instance = drift_client
        mock_instance.create_chat_completion.return_value = {
            "choices": [{"message": {"content": json.dumps({"hints": []})}}]
        }
        import drift as drift_mod

        drift_mod._state["model"] = None
        drift_mod._state["path"] = None

        response = client.post(
            "/drift",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "messages": [{"role": "user", "content": "ping"}],
                "current_state": "(empty)",
            },
        )
        assert response.status_code == 200
        call_kwargs = mock_instance.create_chat_completion.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3
        assert call_kwargs["response_format"] == {"type": "json_object"}

    def test_summarize_does_not_send_json_response_format(self, drift_client):
        """Регрессия: /drift/summarize не должен пробрасывать response_format

        в llama.cpp. Раньше ``_complete_once`` хардкодил
        ``response_format={"type": "json_object"}`` — модель получала
        конфликт (system prompt просит prose, JSON-mode требует JSON)
        и отдавала ``{}``. ``chat_summarizer`` на стороне rag-backend
        видел ``summary_chars=2`` и писал ``{}`` в БД.

        После фикса: ``/drift`` всё ещё использует JSON-режим
        (см. test_temperature_matches_qvikhr_recommendation), а
        ``/drift/summarize`` идёт в free-text режиме.
        """
        client, _, _, mock_instance = drift_client
        mock_instance.create_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": "Heroes met a dragon in the eastern caves."
                    }
                }
            ]
        }
        import drift as drift_mod

        drift_mod._state["model"] = None
        drift_mod._state["path"] = None

        response = client.post(
            "/drift/summarize",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "previous_summary": "Earlier: heroes camped near the forest.",
                "messages_to_compress": [
                    {"role": "user", "content": "We entered the caves."},
                    {"role": "assistant", "content": "A dragon appeared."},
                ],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["summary"] == "Heroes met a dragon in the eastern caves."
        call_kwargs = mock_instance.create_chat_completion.call_args.kwargs
        assert "response_format" not in call_kwargs, (
            f"/drift/summarize must not pass response_format to llama.cpp, "
            f"got: {call_kwargs.get('response_format')!r}"
        )

    def test_msg_ref_int_is_normalized_to_str(self, drift_client):
        """QVikhr-3-1.7B отдаёт msg_ref как int (Qwen2.5 — str).
        DriftHint принимает оба, но нормализует к str в JSON-ответе."""
        client, _, _, mock_instance = drift_client
        mock_instance.create_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "hints": [
                                    {
                                        "fact": "Дракон стал союзником",
                                        "contradicts_field": None,
                                        "adds_field": "current_allies",
                                        "msg_ref": 1,            # int от QVikhr
                                        "confidence": 0.95,
                                    },
                                ]
                            }
                        )
                    }
                }
            ]
        }
        import drift as drift_mod

        drift_mod._state["model"] = None
        drift_mod._state["path"] = None

        response = client.post(
            "/drift",
            json={
                "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
                "messages": [{"role": "user", "content": "ping"}],
                "current_state": "(empty)",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["hints"]) == 1
        assert body["hints"][0]["msg_ref"] == "1"  # int нормализован в str
        assert body["hints"][0]["adds_field"] == "current_allies"
