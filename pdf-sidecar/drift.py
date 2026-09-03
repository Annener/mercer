"""
drift.py — POST /drift и POST /drift/summarize endpoints для pdf-sidecar.

Использует локальную QVikhr-3-1.7B-Instruct-noreasoning (Q4_K_M, GGUF) через
``llama-cpp-python``. Модель лениво загружается при первом запросе
и кэшируется в глобальном ``_state``. При отсутствии ``.gguf`` файла
эндпоинт возвращает ``503 Service Unavailable`` с подсказкой про
``DRIFT_MODEL_PATH``. На macOS M-серии по умолчанию используется Metal
GPU (``DRIFT_FORCE_CPU=0``); fallback на CPU — через env-флаг.

Token-budget (адаптивный под n_ctx загруженной модели):

  Все вызовы модели прогоняются через ``_run_within_budget`` — утилиту,
  которая оценивает количество токенов во входе через ``model.tokenize``
  и при нехватке бюджета режет вход по кускам (chunked-loop), а не
  падает ``ValueError("Requested tokens exceed context window")``. Это
  позволяет одной и той же логике работать и на малом окне
  (QVikhr 4096), и на большом (Qwen2.5-32K), без изменений в клиентском
  коде rag-backend.

Контракт /drift:
  POST /drift
  {
    "model": "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m",
    "messages": [{"role": "user"|"assistant", "content": "..."}],
    "current_state": "<compiled campaign state block>",
    "schema_hint": "<optional field description>"
  }

  200 → {"hints": [{"fact": "...", "contradicts_field": "..."|null, ...}]}
  503 → {"detail": "Drift model not loaded: ..."}

Контракт /drift/summarize:
  POST /drift/summarize
  {
    "model": "...",
    "previous_summary": "<text>" | null,
    "messages_to_compress": [{"role": ..., "content": ...}, ...]
  }

  200 → {"summary": "<merged summary text>"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
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


# --- Token-budget утилиты -----------------------------------------------------
#
# Слой token-арифметики живёт ТОЛЬКО здесь: токенизировать текст умеет
# только ``Llama``, поэтому именно sidecar знает про ``n_ctx``. Rag-backend
# отправляет текст — sidecar сам решает, как его впихнуть в окно.


@dataclass(frozen=True)
class TokenBudget:
    """Доступный бюджет токенов на вход (без учёта выходных)."""

    n_ctx: int
    max_output_tokens: int
    safety_margin: int = 64  # BOS/EOS/chat-format служебные токены

    @property
    def available(self) -> int:
        return max(0, self.n_ctx - self.max_output_tokens - self.safety_margin)


def _estimate_tokens(model: Any, text: str) -> int:
    """Оценка количества токенов в строке через реальный токенизатор модели.

    ``add_bos=False`` — BOS учтён отдельно в safety_margin.
    ``special=True`` — на случай специальных токенов в тексте.
    """
    if not text:
        return 0
    try:
        return len(model.tokenize(text.encode("utf-8"), add_bos=False, special=True))
    except Exception:  # noqa: BLE001
        # Если токенизация упала (битый текст и т.п.) — fallback на грубую
        # оценку ~4 символа на токен. Не идеально, но лучше чем зависнуть.
        return max(1, len(text) // 4)


def _model_n_ctx(model: Any) -> int:
    """Реальное значение n_ctx из загруженной модели (может отличаться от
    запрошенного, если GGUF его не поддерживает)."""
    try:
        from llama_cpp import llama_cpp
        return int(llama_cpp.llama_n_ctx(model.ctx))
    except Exception:  # noqa: BLE001
        return int(getattr(model, "_n_ctx", 4096))


def _fit_text_to_budget(
    model: Any, text: str, budget: TokenBudget, *, marker: str = ""
) -> str:
    """Обрезает text справа так, чтобы он влезал в ``budget.available`` токенов.

    Режет **по символам** через бинарный поиск с пересчётом токенов.
    Это медленнее чем резать по строкам, но даёт точный результат для
    случая «один огромный блок текста». Используется как fallback когда
    резать по сообщениям нечего.

    Если ``marker`` задан — добавляется в конец как маркер усечения.
    Возвращает исходный текст если он уже влезает.
    """
    if not text:
        return text
    if _estimate_tokens(model, text) <= budget.available:
        return text

    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid]
        if _estimate_tokens(model, candidate) <= budget.available:
            lo = mid
        else:
            hi = mid - 1
    truncated = text[:lo]
    if marker:
        truncated = truncated.rstrip() + "\n\n" + marker
    return truncated


# --- Модели запросов/ответов -------------------------------------------------


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


class SummarizeRequest(BaseModel):
    model: str = Field(default_factory=lambda: os.getenv(
        "DRIFT_MODEL_NAME", "qvikhr-3-1.7b-instruct-noreasoning-q4_k_m"
    ))
    previous_summary: str | None = None
    messages_to_compress: list[dict[str, str]] = Field(min_length=1)


class SummarizeResponse(BaseModel):
    summary: str


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
    logger.info(
        "Drift model loaded: %s (effective n_ctx=%d)",
        path.name, _model_n_ctx(_state["model"]),
    )


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


# --- Внутренняя логика вызова модели -----------------------------------------

_SUMMARY_SYSTEM_PROMPT = (
    "You are a running-summary generator for a tabletop RPG campaign chat. "
    "You will receive:\n"
    "  - PREVIOUS SUMMARY (may be empty on first call): accumulated facts so far.\n"
    "  - NEW MESSAGES: a chronologically-ordered block of recent turns.\n\n"
    "Produce a NEW summary that:\n"
    "1. PRESERVES every entity, proper noun, location, item, relationship, and\n"
    "   ongoing goal from the previous summary verbatim when possible — these\n"
    "   are the campaign's continuity.\n"
    "2. INCORPORATES new facts from NEW MESSAGES: characters introduced, places\n"
    "   visited, decisions made, items gained/lost, plot developments.\n"
    "3. Keeps the same writing style and language as the chat (so names match).\n"
    "4. Stays under ~400 words. Be dense; drop pleasantries and meta-talk.\n"
    "5. Output ONLY the summary text — no preamble, no headers, no JSON.\n"
)


# Sentinel для «использовать JSON по умолчанию» в сигнатурах, где нам
# нужно отличить «default = JSON» от «explicit = free-text (None)».
# B006 (mutable default) запрещает использовать ``{"type": "json_object"}``
# прямо как default — поэтому оборачиваем в singleton-константу.
_DEFAULT_JSON_FORMAT: dict[str, str] = {"type": "json_object"}


def _complete_once(
    model: Any,
    messages: list[dict[str, str]],
    max_tokens: int,
    *,
    response_format: dict[str, str] | object | None = _DEFAULT_JSON_FORMAT,
) -> str:
    """Один вызов ``create_chat_completion`` без какой-либо обработки переполнения.

    Используется внутри ``_run_within_budget`` и в местах, где бюджет уже
    проверен заранее.

    ``response_format`` управляет режимом ответа:
      - ``{"type": "json_object"}`` (или любой другой dict) — передаётся
        в llama.cpp как JSON-формат.
      - ``None`` (explicit) — НЕ передаём ``response_format`` в llama.cpp
        вообще (free-text режим для ``/drift/summarize``).
      - default — JSON-формат (``_DEFAULT_JSON_FORMAT``).
    """
    kwargs: dict[str, Any] = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    if response_format is not _DEFAULT_JSON_FORMAT:
        if response_format is not None:
            kwargs["response_format"] = response_format  # type: ignore[assignment]
        # if None — поле не передаётся (free-text).
    else:
        kwargs["response_format"] = _DEFAULT_JSON_FORMAT
    response = model.create_chat_completion(**kwargs)
    return response["choices"][0]["message"]["content"] or ""


def _build_chat_messages(
    system: str, user: str
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _run_within_budget(
    model: Any,
    *,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    label: str,
    response_format: dict[str, str] | object | None = _DEFAULT_JSON_FORMAT,
) -> str:
    """Гарантирует, что вызов модели не упадёт из-за превышения n_ctx.

    Стратегия:
      1. Считаем бюджет на вход (n_ctx - max_output - safety).
      2. Токенизируем полный prompt; если влезает — обычный вызов.
      3. Если не влезает — режем user_prompt по строкам, отбрасывая
         самые старые строки (chunked-loop), пока не влезет. Каждый
         вызов возвращает итог; для /drift это полный JSON-hints, для
         /drift/summarize это summary, который мы потом мерджим с предыдущим.
      4. Если даже system_prompt + минимальный user (1 строка) не влезает —
         режем system_prompt через ``_fit_text_to_budget`` как last resort.
      5. Если совсем ничего не влезает — HTTPException(503).

    ``response_format`` управляет режимом ответа:
      - ``None`` (explicit) — free-text (для ``/drift/summarize``).
      - default — JSON-формат (``_DEFAULT_JSON_FORMAT``, для ``/drift``).
    """
    n_ctx = _model_n_ctx(model)
    # max_output_tokens не может быть больше половины окна — иначе на вход
    # не остаётся места. Это защита от кривых caller-ов (по умолчанию 512,
    # но вдруг кто-то прокинет max_tokens=n_ctx).
    effective_max_output = min(max_output_tokens, n_ctx // 2)
    budget = TokenBudget(n_ctx=n_ctx, max_output_tokens=effective_max_output)

    full_messages = _build_chat_messages(system_prompt, user_prompt)
    full_prompt = system_prompt + "\n" + user_prompt

    if _estimate_tokens(model, full_prompt) <= budget.available:
        logger.debug(
            "%s: prompt fits budget (%d <= %d tokens, n_ctx=%d)",
            label,
            _estimate_tokens(model, full_prompt),
            budget.available,
            n_ctx,
        )
        return _complete_once(
            model,
            full_messages,
            effective_max_output,
            response_format=response_format,
        )

    estimated = _estimate_tokens(model, user_prompt)
    logger.warning(
        "%s: prompt exceeds budget (%d > %d tokens, n_ctx=%d). Chunking…",
        label, estimated, budget.available, n_ctx,
    )

    # Разбиваем user_prompt на строки. Строки — естественная граница смысла
    # (каждое сообщение в drift обычно отдельная строка, в summarize —
    # отдельная строка на сообщение). Берём самые свежие (с конца).
    lines = user_prompt.split("\n")
    kept: list[str] = []
    truncated_system = system_prompt
    for line in reversed(lines):
        candidate = "\n".join([*kept, line][::-1])
        test_messages = _build_chat_messages(system_prompt, candidate)
        test_prompt = system_prompt + "\n" + candidate
        if _estimate_tokens(model, test_prompt) <= budget.available:
            kept.append(line)
        else:
            break

    if not kept:
        # Ни одна строка не влезла — пытаемся резать. Сначала пробуем
        # впихнуть хоть одну строку (самую свежую) с урезанным system.
        if lines:
            truncated_system = _fit_text_to_budget(
                model,
                system_prompt,
                TokenBudget(
                    n_ctx=n_ctx,
                    max_output_tokens=effective_max_output,
                    safety_margin=budget.safety_margin,
                ),
                marker="[...system prompt truncated...]",
            )
            # Пересчитываем бюджет с новым system.
            new_available = max(
                0,
                n_ctx - effective_max_output - budget.safety_margin
                - _estimate_tokens(model, truncated_system),
            )
            truncated_line = _fit_text_to_budget(
                model,
                lines[-1],
                TokenBudget(
                    n_ctx=n_ctx,
                    max_output_tokens=effective_max_output,
                    # safety уже учтён в урезанном system
                    safety_margin=budget.safety_margin
                    + _estimate_tokens(model, truncated_system),
                ),
                marker="[...single line truncated to fit remaining budget...]",
            )
            kept = [truncated_line]
        else:
            # user_prompt пустой — режем только system.
            truncated_system = _fit_text_to_budget(
                model,
                system_prompt,
                TokenBudget(
                    n_ctx=n_ctx,
                    max_output_tokens=effective_max_output,
                    safety_margin=budget.safety_margin,
                ),
                marker="[...system prompt truncated — user prompt empty...]",
            )
            kept = ["[user content empty]"]

    final_user = "\n".join(kept[::-1])
    logger.warning(
        "%s: chunked to %d/%d lines (kept_tail=%d chars, dropped_head=%d lines)",
        label, len(kept), len(lines), len(final_user), len(lines) - len(kept),
    )
    final_messages = _build_chat_messages(
        truncated_system,
        final_user,
    )
    return _complete_once(
        model,
        final_messages,
        effective_max_output,
        response_format=response_format,
    )


# --- Drift endpoint -----------------------------------------------------------


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
        raw = await asyncio.to_thread(
            _run_within_budget,
            model,
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=512,
            label="drift",
        )
    except HTTPException:
        raise
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


# --- Summarize endpoint -------------------------------------------------------


def _summarize_once(
    model: Any, previous_summary: str, chunk: list[dict[str, str]]
) -> str:
    """Один вызов summarization для блока сообщений + опционального prev summary.

    ``response_format=None`` — отключаем жёсткую форму JSON для llama.cpp:
    системный промпт просит prose, а не JSON; иначе модель выдаёт
    минимальный валидный объект (``{}``). См. git-log про bug с пустыми
    summary в rag-backend.
    """
    user_prompt_parts: list[str] = []
    if previous_summary:
        user_prompt_parts.append(f"## PREVIOUS SUMMARY:\n{previous_summary}")
    user_prompt_parts.append("## NEW MESSAGES:")
    for m in chunk:
        user_prompt_parts.append(f"[{m.get('role', '?')}] {m.get('content', '')}")
    user_prompt = "\n".join(user_prompt_parts)

    raw = _run_within_budget(
        model,
        system_prompt=_SUMMARY_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        max_output_tokens=512,
        label="summarize",
        response_format=None,
    )
    return raw.strip()


def _summarize_chunked(
    model: Any,
    messages_to_compress: list[dict[str, str]],
    previous_summary: str,
) -> str:
    """Итеративное сжатие списка сообщений в один running summary.

    Алгоритм: пока есть необработанные сообщения — берём столько, сколько
    влезает в бюджет (с учётом previous_summary), сжимаем, обновляем
    previous_summary. Размер «куска» не фиксированный — он адаптивный
    под n_ctx загруженной модели. На больших окнах summarize возьмёт
    сразу всё; на малых — будет итерировать по несколько сообщений.
    """
    n_ctx = _model_n_ctx(model)
    # Адаптивный clamp: если n_ctx маленький, max_output не может быть больше
    # половины окна (см. ``_run_within_budget``).
    effective_max_output = min(512, n_ctx // 2)
    pending = list(messages_to_compress)
    prev = previous_summary or ""
    iteration = 0

    while pending:
        iteration += 1
        budget = TokenBudget(n_ctx=n_ctx, max_output_tokens=effective_max_output)
        prev_tokens = _estimate_tokens(model, prev)
        room = max(1, budget.available - prev_tokens)

        # Жадно набираем сообщения с конца (самые свежие).
        # Считаем токены уже набранного чанка один раз перед каждой пробой.
        chunk: list[dict[str, str]] = []
        chunk_tokens_used = 0
        for m in reversed(pending):
            line = f"[{m.get('role', '?')}] {m.get('content', '')}"
            line_tokens = _estimate_tokens(model, line)
            if chunk_tokens_used + line_tokens > room:
                break
            chunk.append(m)
            chunk_tokens_used += line_tokens
        chunk.reverse()

        if not chunk:
            # Один-единственный message не влезает даже без prev — режем его.
            biggest = pending[-1]
            line = f"[{biggest.get('role', '?')}] {biggest.get('content', '')}"
            truncated = _fit_text_to_budget(
                model,
                line,
                TokenBudget(
                    n_ctx=n_ctx,
                    max_output_tokens=effective_max_output,
                    safety_margin=budget.safety_margin + prev_tokens,
                ),
                marker="[...single message truncated...]",
            )
            chunk = [{"role": biggest.get("role", "?"), "content": truncated}]
            prev = _summarize_once(model, prev, chunk)
            pending = pending[:-1]
            logger.warning(
                "summarize: chunked iteration=%d truncated single message (%d chars)",
                iteration, len(biggest.get("content", "")),
            )
            continue

        head = len(pending) - len(chunk)
        new_prev = _summarize_once(model, prev, chunk)
        logger.info(
            "summarize: iteration=%d compressed=%d remaining=%d summary_chars=%d->%d",
            iteration, len(chunk), head, len(prev), len(new_prev),
        )
        prev = new_prev
        pending = pending[:head]

    return prev


@router.post("/drift/summarize", response_model=SummarizeResponse)
async def summarize(req: SummarizeRequest) -> SummarizeResponse:
    await _ensure_loaded()
    model = _state["model"]

    try:
        summary = await asyncio.to_thread(
            _summarize_chunked,
            model,
            req.messages_to_compress,
            req.previous_summary or "",
        )
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        n_ctx = _model_n_ctx(model)
        logger.exception("Summarize inference failed")
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "summarize_failed",
                "message": str(exc),
                "n_ctx": n_ctx,
            },
        ) from exc

    return SummarizeResponse(summary=summary)
