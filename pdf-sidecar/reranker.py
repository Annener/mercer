"""
reranker.py — CrossEncoder-реранкер для pdf-sidecar.

Загружает модель CrossEncoder (напр. BAAI/bge-reranker-v2-m3) один раз при старте
и держит её в памяти. Вызывается из lifespan-хука app.py.

Device-автоопределение:
  - RERANKER_FORCE_CPU=1  → всегда cpu (рекомендуется для macOS — MPS даёт
                            тихий fallback на CPU для большинства ops в bge-reranker,
                            что хуже чистого CPU из-за оверхеда передачи данных)
  - Apple Silicon (MPS)   → torch.backends.mps.is_available()
  - CUDA                  → torch.cuda.is_available()
  - Фоллбэк              → cpu

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
    # Явный оверрайд — рекомендуется на macOS где MPS даёт тихий CPU-fallback
    if os.getenv("RERANKER_FORCE_CPU", "0") == "1":
        logger.info("Device selected: CPU (forced via RERANKER_FORCE_CPU=1)")
        return "cpu"

    try:
        import torch
        if torch.backends.mps.is_available():
            logger.info(
                "Device selected: MPS (Apple Silicon) — "
                "note: bge-reranker ops may silently fall back to CPU. "
                "Set RERANKER_FORCE_CPU=1 if system freezes occur."
            )
            return "mps"
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            mem_gb = torch.cuda.get_device_properties(0).total_memory // 1024 ** 3
            logger.info("Device selected: CUDA — %s (%d GB VRAM)", name, mem_gb)
            return "cuda"
    except Exception as e:
        logger.warning("Device detection failed: %s", e)

    logger.warning("⚠️  Reranker running on CPU — no GPU device available or detected")
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

    # Для MPS включаем явный фоллбэк чтобы неподдерживаемые ops не падали с ошибкой
    if device == "mps":
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        logger.info("PYTORCH_ENABLE_MPS_FALLBACK=1 set for MPS device")

    logger.info("Loading reranker model '%s' on device='%s'", target_id, device)

    from sentence_transformers import CrossEncoder
    _model = CrossEncoder(target_id, device=device, max_length=512)
    _loaded_model_id = target_id

    # Верифицируем реальное устройство параметров модели
    try:
        import torch  # noqa: F401 — уже импортирован выше, но на случай cpu-only окружения
        actual_device = next(_model.model.parameters()).device
        logger.info("Reranker model loaded: %s | parameters confirmed on device: %s", target_id, actual_device)
    except Exception:
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

    # batch_size=8 снижает пиковое потребление памяти и оверхед на MPS/CPU
    scores = _model.predict(pairs, batch_size=8, show_progress_bar=False)

    results = [
        {"index": i, "relevance_score": float(scores[i])}
        for i in range(len(documents))
    ]
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    return results


def is_loaded() -> bool:
    return _model is not None
