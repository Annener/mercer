"""Unit-тесты для FastAPI-эндпоинта /health (pdf-sidecar/app.py).

Использует httpx.AsyncClient с lifespan="off" — НЕ загружает реальные модели
(CrossEncoder, SentenceTransformer, unstructured).
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(monkeypatch):
    """Создаёт TestClient с lifespan=off и моками моделей."""
    # Мокаем is_loaded ДО импорта app.py
    mock_reranker_mod = MagicMock()
    mock_reranker_mod.is_loaded = MagicMock(return_value=True)
    mock_reranker_mod.load_reranker = MagicMock()
    mock_reranker_mod.rerank = MagicMock()
    mock_embedder_mod = MagicMock()
    mock_embedder_mod.is_loaded = MagicMock(return_value=False)
    mock_embedder_mod.load_embedder = MagicMock()
    mock_embedder_mod.embed = MagicMock()
    mock_parser_mod = MagicMock()
    mock_parser_mod.parse_pdf_unstructured = MagicMock()
    mock_parser_mod.warmup_models = MagicMock()
    mock_preprocessor_mod = MagicMock()
    mock_preprocessor_mod.preprocess = MagicMock(side_effect=lambda t, _h="": t)

    import sys
    sys.modules["reranker"] = mock_reranker_mod
    sys.modules["embedder"] = mock_embedder_mod
    sys.modules["parser"] = mock_parser_mod
    sys.modules["shared_contracts.preprocessing"] = mock_preprocessor_mod

    # Импортируем app.py
    if "app" in sys.modules:
        importlib.reload(sys.modules["app"])
    import app

    importlib.reload(app)
    # Подменяем импортированные символы в app-пространстве
    app.reranker_is_loaded = mock_reranker_mod.is_loaded
    app.embedder_is_loaded = mock_embedder_mod.is_loaded

    # Создаём клиент с отключённым lifespan (чтобы не запускать warmup)
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.app.router.lifespan_context = noop_lifespan

    yield TestClient(app.app), mock_reranker_mod, mock_embedder_mod


class TestHealth:
    def test_returns_ok_with_status(self, app_client):
        client, _, _ = app_client
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "pdf-sidecar"

    def test_includes_reranker_loaded_flag(self, app_client):
        client, reranker_mod, _ = app_client
        reranker_mod.is_loaded.return_value = True
        response = client.get("/health")
        assert response.json()["reranker_loaded"] == "True"

        reranker_mod.is_loaded.return_value = False
        response = client.get("/health")
        assert response.json()["reranker_loaded"] == "False"

    def test_includes_embedder_loaded_flag(self, app_client):
        client, _, embedder_mod = app_client
        embedder_mod.is_loaded.return_value = True
        response = client.get("/health")
        assert response.json()["embedder_loaded"] == "True"

        embedder_mod.is_loaded.return_value = False
        response = client.get("/health")
        assert response.json()["embedder_loaded"] == "False"

    def test_health_serializes_booleans_as_strings(self, app_client):
        """is_loaded() возвращает bool, в JSON пишется через str() — это контракт."""
        client, reranker_mod, embedder_mod = app_client
        reranker_mod.is_loaded.return_value = True
        embedder_mod.is_loaded.return_value = False
        body = client.get("/health").json()
        # Контракт: "True"/"False" строки, не bool
        assert body["reranker_loaded"] == "True"
        assert body["embedder_loaded"] == "False"