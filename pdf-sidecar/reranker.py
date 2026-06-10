"""
reranker.py — CrossEncoder-реранкер для pdf-sidecar.

Загружает модель CrossEncoder (напр. BAAI/bge-reranker-v2-m3) один раз при старте
и держит её в памяти. Вызывается из lifespan-хука app.py.

Device-автоопределение:
  - Apple Silicon (MPS) → torch.backends.mps.is_available()
  - CUDA              → torch.cuda.is_available()
  - Фоллбэк         → cpu

Переопределение модели через env RERANKER_MODEL_ID без перезапуска.
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = os.getenv("RERANKER_MODEL_ID", "BAAI/bge-reranker-v2-m3")

# Глобальный холдер модели — загружается один раз, используется всеми запросами.
_model: Any = None
_loaded_model_id: str | None = None


def _detect_device() -> str:
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        pass
    return "cpu"


def load_reranker(model_id: str | None = None) -> None:
    """
    Загружает CrossEncoder в глобальный _model.
    Безопасно вызывать несколько раз — повторные вызовы игнорируются если model_id не изменился.
    """
    global _model, _loaded_model_id

    target_id = model_id or DEFAULT_MODEL_ID
    if _model is not None and _loaded_model_id == target_id:
        logger.info("Reranker already loaded: %s", target_id)
        return

    device = _detect_device()
    logger.info("Loading reranker model '%s' on device='%s'", target_id, device)

    from sentence_transformers import CrossEncoder
    _model = CrossEncoder(target_id, device=device)
    _loaded_model_id = target_id
    logger.info("Reranker model loaded: %s", target_id)


def rerank(query: str, documents: list[str]) -> list[dict]:
    """
    Реранжирует документы относительно запроса.

    Возвращает список диктов вида:
        [{"index": <оригинальный индекс>, "relevance_score": <float>}, ...]
    Отсортированы по убыванию relevance_score.

    Ответ совместим с openai_compatible /rerank провайдерами в retrieval.py.
    """
    if _model is None:
        raise RuntimeError("Reranker model is not loaded. Call load_reranker() first.")

    if not documents:
        return []

    pairs = [[query, doc] for doc in documents]
    scores = _model.predict(pairs)

    results = [
        {"index": i, "relevance_score": float(scores[i])}
        for i in range(len(documents))
    ]
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    return results


def is_loaded() -> bool:
    return _model is not None
