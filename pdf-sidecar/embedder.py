"""
embedder.py — sentence-transformers embedding для pdf-sidecar.

Загружает SentenceTransformer (BAAI/bge-m3) один раз при старте и держит в памяти.
Вызывается из lifespan-хука app.py.

Device-автоопределение (аналогично reranker.py):
  - EMBEDDER_FORCE_CPU=1  → всегда cpu (рекомендуется для macOS — MPS-оверхед на
                            передаче данных может быть хуже чистого CPU)
  - Apple Silicon (MPS)   → torch.backends.mps.is_available()
  - CUDA                  → torch.cuda.is_available()
  - Фоллбэк              → cpu

Эндпоинт POST /embed принимает список текстов и возвращает ответ в формате,
совместимом с OpenAI /embeddings API:
  {"data": [{"index": 0, "embedding": [...]}, ...]}

Это позволяет rag-indexer и rag-backend использовать существующий
OpenAICompatibleProvider без каких-либо изменений кода — достаточно
указать base_url=http://pdf-sidecar:8765 в конфиге модели.

Ключевое преимущество перед Ollama:
  - SentenceTransformer.encode(texts) обрабатывает весь батч за ОДИН forward pass
    вместо N последовательных HTTP-запросов → значительно быстрее при индексации
    больших документов.
  - Модель всегда горячая — нет cold start как у Ollama (OLLAMA_KEEP_ALIVE таймаут).
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = os.getenv("EMBEDDER_MODEL_ID", "BAAI/bge-m3")

_model: Any = None
_loaded_model_id: str | None = None


def _detect_device() -> str:
    if os.getenv("EMBEDDER_FORCE_CPU", "0") == "1":
        logger.info("Embedder device: CPU (forced via EMBEDDER_FORCE_CPU=1)")
        return "cpu"

    try:
        import torch
        if torch.backends.mps.is_available():
            logger.info(
                "Embedder device: MPS (Apple Silicon) — "
                "set EMBEDDER_FORCE_CPU=1 if performance is unexpectedly low."
            )
            return "mps"
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem_gb = torch.cuda.get_device_properties(0).total_memory // 1024 ** 3
            logger.info("Embedder device: CUDA — %s (%d GB VRAM)", name, mem_gb)
            return "cuda"
    except Exception as exc:
        logger.warning("Embedder device detection failed: %s", exc)

    logger.warning("⚠️  Embedder running on CPU — no GPU device detected")
    return "cpu"


def load_embedder(model_id: str | None = None) -> None:
    """
    Загружает SentenceTransformer в глобальный _model.
    Повторные вызовы игнорируются если model_id не изменился.
    """
    global _model, _loaded_model_id

    target_id = model_id or DEFAULT_MODEL_ID
    if _model is not None and _loaded_model_id == target_id:
        logger.info("Embedder already loaded: %s", target_id)
        return

    device = _detect_device()

    if device == "mps":
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        logger.info("PYTORCH_ENABLE_MPS_FALLBACK=1 set for MPS device")

    logger.info("Loading embedder model '%s' on device='%s'", target_id, device)

    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer(target_id, device=device)
    _loaded_model_id = target_id

    # Верифицируем реальное устройство параметров модели
    try:
        import torch  # noqa: F401
        actual_device = next(_model.parameters()).device
        logger.info(
            "Embedder model loaded: %s | parameters on device: %s",
            target_id, actual_device,
        )
    except Exception:
        logger.info("Embedder model loaded: %s", target_id)


def embed(texts: list[str], batch_size: int = 32) -> list[list[float]]:
    """
    Вычисляет эмбеддинги для списка текстов.

    Возвращает list[list[float]] — по одному вектору на каждый текст.
    Порядок сохраняется. При пустом inputs возвращает [].

    batch_size=32 — хороший баланс между throughput и пиковым потреблением памяти
    для bge-m3 (1024-мерный вектор, ~570 MB модель).
    normalize_embeddings=True обязателен для корректного cosine similarity в LanceDB.
    """
    if _model is None:
        raise RuntimeError("Embedder model is not loaded. Call load_embedder() first.")
    if not texts:
        return []

    import numpy as np
    vectors = _model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    # numpy array → list[list[float]]
    return vectors.tolist() if isinstance(vectors, np.ndarray) else [v.tolist() for v in vectors]


def is_loaded() -> bool:
    return _model is not None
