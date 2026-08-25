"""Unit-тесты для pdf-sidecar/embedder.py.

Мокаем torch.backends.mps и _model.encode. Реальный SentenceTransformer
не нужен — это тяжёлая зависимость.
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fresh_embedder(monkeypatch):
    monkeypatch.delenv("EMBEDDER_FORCE_CPU", raising=False)
    monkeypatch.delenv("EMBEDDER_MODEL_ID", raising=False)
    monkeypatch.delenv("EMBED_BATCH_SIZE", raising=False)
    import embedder

    importlib.reload(embedder)
    yield embedder


class TestResolveDevice:
    def test_force_cpu_env_yes(self, fresh_embedder, monkeypatch):
        monkeypatch.setenv("EMBEDDER_FORCE_CPU", "yes")
        assert fresh_embedder._resolve_device() == "cpu"

    def test_force_cpu_env_one(self, fresh_embedder, monkeypatch):
        monkeypatch.setenv("EMBEDDER_FORCE_CPU", "1")
        assert fresh_embedder._resolve_device() == "cpu"

    def test_force_cpu_env_true(self, fresh_embedder, monkeypatch):
        monkeypatch.setenv("EMBEDDER_FORCE_CPU", "true")
        assert fresh_embedder._resolve_device() == "cpu"

    def test_mps_available(self, fresh_embedder, monkeypatch):
        monkeypatch.delenv("EMBEDDER_FORCE_CPU", raising=False)
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": mock_torch}):
            assert fresh_embedder._resolve_device() == "mps"

    def test_cuda_available(self, fresh_embedder, monkeypatch):
        monkeypatch.delenv("EMBEDDER_FORCE_CPU", raising=False)
        mock_torch = MagicMock()
        mock_torch.backends.mps.is_available.return_value = False
        mock_torch.cuda.is_available.return_value = True
        with patch.dict("sys.modules", {"torch": mock_torch}):
            assert fresh_embedder._resolve_device() == "cuda"

    def test_no_torch_falls_back_to_cpu(self, fresh_embedder, monkeypatch):
        monkeypatch.delenv("EMBEDDER_FORCE_CPU", raising=False)
        with patch.dict("sys.modules", {"torch": None}):
            assert fresh_embedder._resolve_device() == "cpu"


class TestEmbed:
    def test_empty_texts_raises_value_error(self, fresh_embedder):
        fresh_embedder._model = MagicMock()
        with pytest.raises(ValueError, match="must not be empty"):
            fresh_embedder.embed([])

    def test_without_loaded_model_raises_runtime(self, fresh_embedder):
        fresh_embedder._model = None
        with pytest.raises(RuntimeError, match="not loaded"):
            fresh_embedder.embed(["text"])

    def test_embed_calls_encode_with_normalize(self, fresh_embedder, monkeypatch):
        # numpy.ndarray с .tolist()
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        fresh_embedder._model = mock_model

        result = fresh_embedder.embed(["text one", "text two"])

        # Проверяем что encode вызван с правильными параметрами
        call_kwargs = mock_model.encode.call_args[1]
        assert call_kwargs["normalize_embeddings"] is True
        assert call_kwargs["show_progress_bar"] is False
        assert call_kwargs["convert_to_numpy"] is True

        # Результат — list of lists of floats
        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(v, list) for v in result)
        assert all(isinstance(x, float) for v in result for x in v)
        assert result[0] == [0.1, 0.2, 0.3]
        assert result[1] == [0.4, 0.5, 0.6]

    def test_embed_batch_size_from_env(self, fresh_embedder, monkeypatch):
        monkeypatch.setenv("EMBED_BATCH_SIZE", "16")
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.0, 0.0]])
        fresh_embedder._model = mock_model

        fresh_embedder.embed(["t"])
        assert mock_model.encode.call_args[1]["batch_size"] == 16

    def test_embed_default_batch_size_32(self, fresh_embedder, monkeypatch):
        monkeypatch.delenv("EMBED_BATCH_SIZE", raising=False)
        import numpy as np

        mock_model = MagicMock()
        mock_model.encode.return_value = np.array([[0.0, 0.0]])
        fresh_embedder._model = mock_model

        fresh_embedder.embed(["t"])
        assert mock_model.encode.call_args[1]["batch_size"] == 32


class TestIsLoaded:
    def test_false_when_model_none(self, fresh_embedder):
        fresh_embedder._model = None
        assert fresh_embedder.is_loaded() is False

    def test_true_when_model_set(self, fresh_embedder):
        fresh_embedder._model = MagicMock()
        assert fresh_embedder.is_loaded() is True


class TestLoadEmbedder:
    def test_idempotent(self, fresh_embedder, monkeypatch):
        existing = MagicMock()
        fresh_embedder._model = existing
        mock_st = MagicMock()
        with patch.dict("sys.modules", {"sentence_transformers": mock_st}):
            fresh_embedder.load_embedder()
        mock_st.SentenceTransformer.assert_not_called()
        assert fresh_embedder._model is existing