"""
PDF-парсер для rag-indexer.

Делегирует парсинг pdf-sidecar через HTTP (unstructured hi_res, GPU macOS).
Fallback на pdfminer УДАЛЁН — sidecar обязателен.

Если PDF_SIDECAR_URL не задан — поднимается RuntimeError при первом вызове.

v2: Поддержка streaming (/parse/stream) для решения проблемы таймаутов.

  Sidecar шлёт NDJSON-поток:
    {"type":"progress","page":N,"total":M,"elapsed":X}   — heartbeat каждую страницу
    {"type":"result", ...полный результат...}             — финальные данные
    {"type":"error", "detail": "..."}                     — если парсинг упал

  httpx.Client читает поток построчно. Благодаря этому:
    - Клиент НЕ ждёт полного завершения парсинга (нет timeout на весь ответ)
    - Таймаут применяется только к каждому отдельному чтению строки (connect+read)
    - Heartbeat от sidecar держит TCP-соединение живым
    - Indexer получает прогресс-логи в реальном времени

  Если PDF_SIDECAR_STREAM=false — используется старый /parse endpoint (для отладки).

Возвращаемый формат неизменён:
{
    "pages":      [{"text": str, "page_number": int}, ...],
    "headings":   [{"text": str, "page_number": int, "y0": float, "font_size": float}, ...],
    "metadata":   {"source": str, "parser": str},
    "page_count": int,
}
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# URL sidecar берётся из env
_SIDECAR_URL: str = os.getenv("PDF_SIDECAR_URL", "").rstrip("/")

# Таймаут на установку соединения и на каждый read-chunk (секунды).
# НЕ является таймаутом на весь парсинг — парсинг может длиться сколько угодно
# пока sidecar шлёт heartbeat-события.
_CONNECT_TIMEOUT: float = float(os.getenv("PDF_SIDECAR_CONNECT_TIMEOUT", "30"))
_READ_TIMEOUT: float = float(os.getenv("PDF_SIDECAR_READ_TIMEOUT", "120"))

# Использовать streaming endpoint (рекомендуется)
_USE_STREAM: bool = os.getenv("PDF_SIDECAR_STREAM", "true").lower() not in ("false", "0", "no")


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def parse_pdf(path: str) -> dict[str, Any]:
    """
    Точка входа для rag-indexer (сигнатура не изменилась).

    Отправляет PDF в pdf-sidecar и возвращает распарсенный результат.
    По умолчанию использует streaming endpoint /parse/stream.

    Raises:
        RuntimeError: если PDF_SIDECAR_URL не задан.
        httpx.HTTPStatusError: при ошибке HTTP от sidecar.
        httpx.TimeoutException: если heartbeat не приходил дольше READ_TIMEOUT секунд.
    """
    if not _SIDECAR_URL:
        raise RuntimeError(
            "PDF_SIDECAR_URL environment variable is not set. "
            "Start pdf-sidecar and set PDF_SIDECAR_URL=http://host.docker.internal:8765 "
            "in the rag-indexer environment (docker-compose)."
        )

    if _USE_STREAM:
        result = _parse_via_sidecar_stream(path)
    else:
        result = _parse_via_sidecar(path)

    if not _has_content(result):
        logger.warning(
            "Sidecar returned empty result for %s (parser=%s, pages=%d)",
            path,
            result.get("metadata", {}).get("parser", "?"),
            result.get("page_count", 0),
        )

    logger.info(
        "Sidecar parsed '%s' → %d pages via %s",
        path,
        result.get("page_count", 0),
        result.get("metadata", {}).get("parser", "?"),
    )
    return result


# ---------------------------------------------------------------------------
# Streaming client (v2 — рекомендуется)
# ---------------------------------------------------------------------------

def _parse_via_sidecar_stream(path: str) -> dict[str, Any]:
    """
    POST multipart к /parse/stream, читает NDJSON-поток построчно.

    Таймаут применяется к каждой строке отдельно, а не к всему запросу.
    Heartbeat-события от sidecar ({"type":"progress",...}) держат соединение живым.
    """
    pdf_bytes = Path(path).read_bytes()
    filename = Path(path).name

    logger.info(
        "Sending '%s' (%d bytes) to sidecar %s/parse/stream (connect=%.0fs, read=%.0fs)",
        filename, len(pdf_bytes), _SIDECAR_URL, _CONNECT_TIMEOUT, _READ_TIMEOUT,
    )

    timeout = httpx.Timeout(
        connect=_CONNECT_TIMEOUT,
        read=_READ_TIMEOUT,
        write=60.0,
        pool=10.0,
    )

    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST",
            f"{_SIDECAR_URL}/parse/stream",
            files={"file": (filename, pdf_bytes, "application/pdf")},
        ) as response:
            response.raise_for_status()

            result: dict[str, Any] | None = None

            for line in response.iter_lines():
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Sidecar stream: invalid JSON line: %r", line[:200])
                    continue

                event_type = event.get("type", "")

                if event_type == "progress":
                    page = event.get("page", "?")
                    total = event.get("total", 0)
                    elapsed = event.get("elapsed", 0)
                    n_elements = event.get("elements", 0)
                    has_table = event.get("has_table", False)
                    total_str = f"/{total}" if total else ""
                    logger.info(
                        "[sidecar] Page %s%s — %d elements%s — %.1fs elapsed",
                        page, total_str, n_elements,
                        " [TABLE]" if has_table else "",
                        elapsed,
                    )

                elif event_type == "result":
                    result = event
                    # Убираем служебное поле type
                    result.pop("type", None)

                elif event_type == "error":
                    detail = event.get("detail", "unknown error")
                    raise RuntimeError(f"Sidecar returned error: {detail}")

                else:
                    logger.debug("Sidecar stream: unknown event type %r", event_type)

    if result is None:
        raise RuntimeError("Sidecar stream ended without sending result event")

    return result


# ---------------------------------------------------------------------------
# Sync client (legacy — /parse endpoint без streaming)
# ---------------------------------------------------------------------------

def _parse_via_sidecar(path: str) -> dict[str, Any]:
    """
    POST multipart к /parse, ждёт полного ответа.
    Используется если PDF_SIDECAR_STREAM=false.

    ВНИМАНИЕ: таймаут здесь — это таймаут на ВЕСЬ парсинг.
    Для больших PDF (500+ секунд) нужен PDF_SIDECAR_READ_TIMEOUT=600+.
    """
    pdf_bytes = Path(path).read_bytes()
    filename = Path(path).name

    # В legacy-режиме используем большой фиксированный таймаут
    legacy_timeout = float(os.getenv("PDF_SIDECAR_TIMEOUT", "600"))

    logger.warning(
        "Using legacy /parse endpoint (no streaming). "
        "For large PDFs use PDF_SIDECAR_STREAM=true (default)."
    )
    logger.debug(
        "Sending '%s' (%d bytes) to sidecar %s/parse (timeout=%.0fs)",
        filename, len(pdf_bytes), _SIDECAR_URL, legacy_timeout,
    )

    with httpx.Client(timeout=legacy_timeout) as client:
        response = client.post(
            f"{_SIDECAR_URL}/parse",
            files={"file": (filename, pdf_bytes, "application/pdf")},
        )
        response.raise_for_status()

    result: dict[str, Any] = response.json()
    return result


def _has_content(result: dict[str, Any]) -> bool:
    return any(p.get("text", "").strip() for p in result.get("pages", []))
