"""Unit-тесты для основных эндпоинтов pdf-sidecar/app.py: /parse, /parse/stream, /rerank, /embeddings.

Использует TestClient с lifespan=off и моками парсера/preprocessor/rerank/embed.
"""
from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mocks(monkeypatch):
    """Создаёт моки для всех зависимостей app.py."""
    mock_reranker_mod = MagicMock()
    mock_reranker_mod.is_loaded = MagicMock(return_value=True)
    mock_reranker_mod.load_reranker = MagicMock()
    mock_reranker_mod.rerank = MagicMock(return_value=[
        {"index": 0, "relevance_score": 0.9},
        {"index": 1, "relevance_score": 0.1},
    ])

    mock_embedder_mod = MagicMock()
    mock_embedder_mod.is_loaded = MagicMock(return_value=True)
    mock_embedder_mod.load_embedder = MagicMock()
    mock_embedder_mod.embed = MagicMock(return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])

    mock_parser_mod = MagicMock()
    mock_parser_mod.parse_pdf_unstructured = MagicMock(return_value={
        "pages": [{"text": "raw page text", "page_number": 1}],
        "headings": [{"text": "Heading", "page_number": 1, "y0": 0.0, "font_size": 0.0}],
        "metadata": {"source": "test.pdf", "parser": "unstructured-hi_res/yolox"},
        "page_count": 1,
    })
    mock_parser_mod.warmup_models = MagicMock()

    mock_preprocessor_mod = MagicMock()
    mock_preprocessor_mod.preprocess = MagicMock(side_effect=lambda text, hint="": f"PROCESSED:{text}")

    import sys
    sys.modules["reranker"] = mock_reranker_mod
    sys.modules["embedder"] = mock_embedder_mod
    sys.modules["parser"] = mock_parser_mod
    sys.modules["preprocessor"] = mock_preprocessor_mod

    yield {
        "reranker": mock_reranker_mod,
        "embedder": mock_embedder_mod,
        "parser": mock_parser_mod,
        "preprocessor": mock_preprocessor_mod,
        "sys": sys,
    }


@pytest.fixture
def app_client(mocks):
    import app

    importlib.reload(app)
    # Подменяем функции которые app.py уже заимпортировал на уровне модуля
    # (parse_pdf_unstructured, preprocess, rerank, _embed, is_loaded — все привязаны
    # к конкретным функциям при импорте, monkeypatch на sys.modules недостаточен)
    app.reranker_is_loaded = mocks["reranker"].is_loaded
    app.embedder_is_loaded = mocks["embedder"].is_loaded
    app._embed = mocks["embedder"].embed
    app.rerank = mocks["reranker"].rerank
    app.parse_pdf_unstructured = mocks["parser"].parse_pdf_unstructured
    app.preprocess = mocks["preprocessor"].preprocess

    @asynccontextmanager
    async def noop_lifespan(_app):
        yield

    app.app.router.lifespan_context = noop_lifespan

    return TestClient(app.app)


class TestParseEndpoint:
    def test_non_pdf_extension_rejected(self, app_client):
        response = app_client.post(
            "/parse",
            files={"file": ("test.txt", b"some bytes", "text/plain")},
        )
        assert response.status_code == 400
        assert "PDF" in response.json()["detail"]

    def test_empty_file_rejected(self, app_client):
        response = app_client.post(
            "/parse",
            files={"file": ("test.pdf", b"", "application/pdf")},
        )
        assert response.status_code == 400
        assert "Empty" in response.json()["detail"]

    def test_happy_path(self, app_client, mocks):
        response = app_client.post(
            "/parse",
            files={"file": ("test.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["page_count"] == 1
        # preprocessor был вызван
        assert mocks["preprocessor"].preprocess.called

    def test_parser_exception_returns_500(self, app_client, mocks):
        mocks["parser"].parse_pdf_unstructured.side_effect = RuntimeError("boom")
        response = app_client.post(
            "/parse",
            files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert response.status_code == 500
        assert "Parse error" in response.json()["detail"]


class TestParseStreamEndpoint:
    def test_non_pdf_extension_rejected(self, app_client):
        response = app_client.post(
            "/parse/stream",
            files={"file": ("test.docx", b"some bytes")},
        )
        assert response.status_code == 400

    def test_empty_file_rejected(self, app_client):
        response = app_client.post(
            "/parse/stream",
            files={"file": ("test.pdf", b"")},
        )
        assert response.status_code == 400

    def test_happy_path_emits_result_event(self, app_client, mocks):
        # parse_pdf_unstructured вызывается синхронно внутри потока
        mocks["parser"].parse_pdf_unstructured.return_value = {
            "pages": [{"text": "page text", "page_number": 1}],
            "headings": [],
            "metadata": {"source": "test.pdf", "parser": "unstructured-hi_res/yolox"},
            "page_count": 1,
        }

        response = app_client.post(
            "/parse/stream",
            files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert response.status_code == 200
        # Тело — NDJSON, последняя строка — result event
        body = response.text
        lines = [l for l in body.split("\n") if l.strip()]
        assert any('"type": "result"' in line for line in lines)
        # parser был вызван
        assert mocks["parser"].parse_pdf_unstructured.called

    def test_parser_error_emits_error_event(self, app_client, mocks):
        mocks["parser"].parse_pdf_unstructured.side_effect = RuntimeError("ghostscript failed")
        response = app_client.post(
            "/parse/stream",
            files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert response.status_code == 200
        body = response.text
        assert '"type": "error"' in body
        assert "ghostscript failed" in body


class TestRerankEndpoint:
    def test_returns_503_when_reranker_not_loaded(self, app_client, mocks):
        mocks["reranker"].is_loaded.return_value = False
        response = app_client.post(
            "/rerank",
            json={"query": "q", "documents": ["d1"]},
        )
        assert response.status_code == 503
        assert "not loaded" in response.json()["detail"]

    def test_empty_documents_returns_empty_results(self, app_client, mocks):
        response = app_client.post(
            "/rerank",
            json={"query": "q", "documents": []},
        )
        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_happy_path_returns_sorted_results(self, app_client, mocks):
        mocks["reranker"].rerank.return_value = [
            {"index": 1, "relevance_score": 0.95},
            {"index": 0, "relevance_score": 0.42},
        ]
        response = app_client.post(
            "/rerank",
            json={"query": "test query", "documents": ["doc A", "doc B"]},
        )
        assert response.status_code == 200
        body = response.json()
        assert "results" in body
        assert len(body["results"]) == 2
        assert body["results"][0]["index"] == 1
        assert body["results"][0]["relevance_score"] == 0.95

    def test_rerank_exception_returns_500(self, app_client, mocks):
        mocks["reranker"].rerank.side_effect = RuntimeError("model crashed")
        response = app_client.post(
            "/rerank",
            json={"query": "q", "documents": ["d1"]},
        )
        assert response.status_code == 500


class TestEmbeddingsEndpoint:
    def test_returns_503_when_embedder_not_loaded(self, app_client, mocks):
        mocks["embedder"].is_loaded.return_value = False
        response = app_client.post(
            "/embeddings",
            json={"input": "text", "model": "bge-m3"},
        )
        assert response.status_code == 503
        assert "not loaded" in response.json()["detail"]

    def test_empty_list_input_returns_empty_data(self, app_client, mocks):
        response = app_client.post(
            "/embeddings",
            json={"input": [], "model": "bge-m3"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body == {"data": [], "model": "bge-m3"}

    def test_string_input_converted_to_list(self, app_client, mocks):
        mocks["embedder"].embed.return_value = [[0.1, 0.2, 0.3]]
        response = app_client.post(
            "/embeddings",
            json={"input": "single text", "model": "bge-m3"},
        )
        assert response.status_code == 200
        # embed должен быть вызван со списком из одной строки
        mocks["embedder"].embed.assert_called_once_with(["single text"])

    def test_happy_path_returns_openai_format(self, app_client, mocks):
        mocks["embedder"].embed.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        response = app_client.post(
            "/embeddings",
            json={"input": ["text one", "text two"], "model": "bge-m3"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["model"] == "bge-m3"
        assert len(body["data"]) == 2
        assert body["data"][0] == {"index": 0, "embedding": [0.1, 0.2, 0.3]}
        assert body["data"][1] == {"index": 1, "embedding": [0.4, 0.5, 0.6]}

    def test_embed_exception_returns_500(self, app_client, mocks):
        mocks["embedder"].embed.side_effect = RuntimeError("encode failed")
        response = app_client.post(
            "/embeddings",
            json={"input": ["text"], "model": "bge-m3"},
        )
        assert response.status_code == 500