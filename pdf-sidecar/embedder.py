"""
embedder.py — загрузка BAAI/bge-m3 через sentence-transformers
и вычисление нормализованных L2-эмбеддингов.

Аналог reranker.py: модель загружается один раз в lifespan,
все вызовы потокобезопасны (GIL + torch без состояния).

Environment variables:
  EMBEDDER_MODEL_ID    — HuggingFace model id (default: BAAI/bge-m3)
  EMBEDDER_FORCE_CPU   — "1" чтобы принудительно использовать CPU
  EMBED_BATCH_SIZE     — размер батча при encode() (default: 32)
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_model = None  # SentenceTransformer instance


def _resolve_device() -> str:
    if os.getenv("EMBEDDER_FORCE_CPU", "") in ("1", "true", "yes"):
        logger.info("Embedder: forcing CPU (EMBEDDER_FORCE_CPU is set)")
        return "cpu"
    try:
        import torch
        if torch.backends.mps.is_available():
            logger.info("Embedder: using MPS (Apple Silicon)")
            return "mps"
        if torch.cuda.is_available():
            logger.info("Embedder: using CUDA")
            return "cuda"
    except Exception:
        pass
    logger.info("Embedder: using CPU")
    return "cpu"


def load_embedder() -> None:
    """
    Загружает модель в память. Вызывается один раз из lifespan FastAPI.
    Повторный вызов — no-op.
    """
    global _model
    if _model is not None:
        return

    from sentence_transformers import SentenceTransformer

    model_id = os.getenv("EMBEDDER_MODEL_ID", "BAAI/bge-m3")
    device = _resolve_device()

    logger.info("Loading embedder model: %s on device=%s", model_id, device)
    _model = SentenceTransformer(model_id, device=device)
    logger.info(
        "Embedder ready: model=%s dim=%d device=%s",
        model_id, _model.get_sentence_embedding_dimension(), device,
    )


def is_loaded() -> bool:
    return _model is not None


def embed(texts: list[str]) -> list[list[float]]:
    """
    Вычисляет нормализованные L2-эмбеддинги для списка текстов.

    Весь батч обрабатывается за ОДИН forward pass — главное
    преимущество перед Ollama, который делает N HTTP-запросов.

    Args:
        texts: список строк (не пустой)

    Returns:
        list[list[float]] — по одному вектору на текст

    Raises:
        RuntimeError: если модель не загружена
        ValueError: если texts пустой
    """
    if _model is None:
        raise RuntimeError("Embedder model is not loaded. Call load_embedder() first.")
    if not texts:
        raise ValueError("texts must not be empty")

    batch_size = int(os.getenv("EMBED_BATCH_SIZE", "32"))

    # normalize_embeddings=True → L2-norm, совместимо с cosine-similarity
    # и с тем, как bge-m3 индексировался через Ollama
    vectors = _model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return vectors.tolist()
