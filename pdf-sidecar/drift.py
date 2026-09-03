"""
drift.py — POST /drift endpoint для pdf-sidecar (Phase 2a context-engine).

Использует локальную QVikhr-3-1.7B-Instruct-noreasoning (Q4_K_M, GGUF) через
``llama-cpp-python``. Модель лениво загружается при первом запросе
и кэшируется в глобальном ``_state``. При отсутствии ``.gguf`` файла
эндпоинт возвращает ``503 Service Unavailable`` с подсказкой про
``DRIFT_MODEL_PATH``. На macOS M-серии по умолчанию используется Metal
GPU (``DRIFT_FORCE_CPU=0``); fallback на CPU — через env-флаг.

Контракт:
  POST /drift
  {
    "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
    "messages": [{"role": "user"|"assistant", "content": "..."}],
    "current_state": "<compiled campaign state block>",
    "schema_hint": "<optional field description>"
  }

  200 → {"hints": [{"fact": "...", "contradicts_field": "..."|null, ...}]}
  503 → {"detail": "Drift model not loaded: ..."}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()
# Алиас для app.py — он импортирует ``drift_router`` по имени.
# Тесты по-прежнему могут использовать ``drift.router``.
drift_router = router


_SYSTEM_PROMPT = (
    "You are a context drift detector. Given recent chat messages and the current "
    "campaign state, identify facts that:\n"
    "1. Contradict the current state (something happened that makes existing state wrong)\n"
    "2. Add to the current state (new entity, location, event not in state)\n"
    "3. Are relevant for active list-items (new list item appears)\n\n"
    'Output JSON: {"hints": [{"fact": "...", "contradicts_field": "key_or_null", '
    '"adds_field": "key_or_null", "msg_ref": "msg_index_or_null", '
    '"confidence": 0.0-1.0}]}\n\n'
    "Only include hints with confidence >= 0.5. Be conservative — false positives "
    "are worse than missed drift."
)


class DriftRequest(BaseModel):
    model: str = Field(default_factory=lambda: os.getenv(
        "DRIFT_MODEL_NAME", "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m"
    ))
    messages: list[dict[str, str]]
    current_state: str
    schema_hint: str | None = None


class DriftHint(BaseModel):
    fact: str
    contradicts_field: str | None = None
    adds_field: str | None = None
    # QVikhr-3-1.7B отдаёт msg_ref как int (1, 2, …), Qwen2.5 — как str ("msg-1").
    # Принимаем оба варианта — нормализуем в str ниже в detect_drift().
    msg_ref: str | int | None = None
    confidence: float = 0.0


class DriftResponse(BaseModel):
    hints: list[DriftHint] = Field(default_factory=list)


# --- Состояние загрузки модели -------------------------------------------------

_state: dict[str, Any] = {
    "model": None,
    "path": None,
}


def _resolve_model_path() -> Path:
    """Resolve drift model .gguf path.

    Порядок поиска:
      1. ``DRIFT_MODEL_PATH`` env (если задан и существует)
      2. ``<sidecar_dir>/models/<DRIFT_MODEL_NAME>.gguf``
    """
    explicit = os.getenv("DRIFT_MODEL_PATH")
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.is_file():
            return p
        logger.warning(
            "DRIFT_MODEL_PATH points to non-existent file: %s — falling back to default", p
        )

    name = os.getenv("DRIFT_MODEL_NAME", "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m")
    default = Path(__file__).parent / "models" / f"{name}.gguf"
    return default.resolve()


def _model_loaded() -> bool:
    return _state["model"] is not None


def _load_model_sync() -> None:
    """Синхронная загрузка llama-cpp модели (запускается через ``to_thread``)."""
    from llama_cpp import Llama  # импортируется лениво — pакет может отсутствовать

    path = _resolve_model_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Drift model file not found at {path}. "
            "Set DRIFT_MODEL_PATH to a .gguf file or place it under pdf-sidecar/models/."
        )

    logger.info("Loading drift model from %s", path)
    n_ctx = int(os.getenv("DRIFT_MODEL_CTX", "4096"))
    n_threads = int(os.getenv("DRIFT_MODEL_THREADS", str(os.cpu_count() or 4)))
    use_gpu = os.getenv("DRIFT_FORCE_CPU", "0") != "1"
    n_gpu_layers = -1 if use_gpu else 0
    logger.info(
        "Drift model config: n_ctx=%d n_threads=%d n_gpu_layers=%d",
        n_ctx, n_threads, n_gpu_layers,
    )
    _state["model"] = Llama(
        model_path=str(path),
        n_ctx=n_ctx,
        n_threads=n_threads,
        n_gpu_layers=n_gpu_layers,
        verbose=False,
    )
    _state["path"] = str(path)
    logger.info("Drift model loaded: %s", path.name)


async def _ensure_loaded() -> None:
    if _state["model"] is not None:
        return
    try:
        await asyncio.to_thread(_load_model_sync)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to load drift model")
        raise HTTPException(status_code=503, detail=f"Drift model load failed: {exc}") from exc


def _complete_sync(model, messages: list[dict[str, str]], max_tokens: int) -> str:
    response = model.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        # 0.3 — рекомендация model card QVikhr-3-1.7B-Instruct-noreasoning
        # (https://huggingface.co/Vikhrmodels/QVikhr-3-1.7B-Instruction-noreasoning).
        # response_format={"type":"json_object"} стабилизирует структуру
        # вывода; небольшая вариативность внутри JSON-полей для drift-хинтов
        # приемлема (хинты не парсятся по regex).
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return response["choices"][0]["message"]["content"] or ""


@router.post("/drift", response_model=DriftResponse)
async def detect_drift(req: DriftRequest) -> DriftResponse:
    await _ensure_loaded()
    model = _state["model"]

    user_prompt = (
        f"## Campaign State:\n{req.current_state}\n\n"
        + (f"## Schema:\n{req.schema_hint}\n\n" if req.schema_hint else "")
        + "## Recent Messages:\n"
        + "\n".join(f"[{m.get('role', '?')}] {m.get('content', '')}" for m in req.messages)
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        raw = await asyncio.to_thread(_complete_sync, model, messages, 512)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Drift inference failed")
        raise HTTPException(status_code=500, detail=f"Drift inference failed: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        logger.warning("Drift model returned non-JSON content: %s", raw[:200])
        raise HTTPException(
            status_code=502, detail=f"Drift model returned non-JSON: {exc}"
        ) from exc

    hints_raw = parsed.get("hints", [])
    if not isinstance(hints_raw, list):
        raise HTTPException(status_code=502, detail="Drift JSON has no 'hints' list")

    hints: list[DriftHint] = []
    for h in hints_raw:
        if not isinstance(h, dict):
            continue
        try:
            hint = DriftHint(**h)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Drift hint rejected: %s (%r)", exc, h)
            continue
        # Нормализация: msg_ref может быть int (QVikhr) или str (Qwen2.5).
        # Downstream (rag-backend/drift.py:222) ожидает строковый role/content,
        # поэтому приводим к str для единообразия в JSON-ответе.
        if hint.msg_ref is not None and not isinstance(hint.msg_ref, str):
            hint.msg_ref = str(hint.msg_ref)
        hints.append(hint)

    logger.info("DRIFT hints=%d model=%s", len(hints), req.model)
    return DriftResponse(hints=hints)
