"""
PDF-парсер для rag-indexer.

Делегирует парсинг pdf-sidecar через HTTP (unstructured hi_res, GPU macOS).
Fallback на pdfminer УДАЛЁН — sidecar обязателен.

Если PDF_SIDECAR_URL не задан — поднимается RuntimeError при первом вызове.
Это заставляет оператора явно настроить окружение, а не скрывает проблему.

Возвращаемый формат неизменён:
{
    "pages":      [{"text": str, "page_number": int}, ...],
    "headings":   [{"text": str, "page_number": int, "y0": float, "font_size": float}, ...],
    "metadata":   {"source": str, "parser": str},
    "page_count": int,
}
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# URL sidecar берётся из env (инжектируется docker-compose или задаётся вручную).
_SIDECAR_URL: str = os.getenv("PDF_SIDECAR_URL", "").rstrip("/")
_SIDECAR_TIMEOUT: float = float(os.getenv("PDF_SIDECAR_TIMEOUT", "180"))


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def parse_pdf(path: str) -> dict[str, Any]:
    """
    Точка входа для rag-indexer (сигнатура не изменилась).

    Отправляет PDF в pdf-sidecar (/parse) и возвращает распарсенный результат.
    Sidecar применяет unstructured hi_res (detectron2 + tesseract OCR) и
    внутри себя прогоняет каждую страницу через preprocessor перед возвратом.

    Raises:
        RuntimeError: если PDF_SIDECAR_URL не задан в окружении.
        httpx.HTTPStatusError: при ошибке HTTP от сидкара.
        httpx.TimeoutException: если парсинг превысил PDF_SIDECAR_TIMEOUT секунд.
    """
    if not _SIDECAR_URL:
        raise RuntimeError(
            "PDF_SIDECAR_URL environment variable is not set. "
            "Start pdf-sidecar and set PDF_SIDECAR_URL=http://host.docker.internal:8765 "
            "in the rag-indexer environment (docker-compose)."
        )

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
# Sidecar client
# ---------------------------------------------------------------------------

def _parse_via_sidecar(path: str) -> dict[str, Any]:
    """
    POST multipart/form-data к pdf-sidecar /parse.
    Возвращает распарсенный JSON напрямую — sidecar уже применил preprocessor.
    """
    pdf_bytes = Path(path).read_bytes()
    filename = Path(path).name

    logger.debug(
        "Sending '%s' (%d bytes) to sidecar %s/parse (timeout=%.0fs)",
        filename,
        len(pdf_bytes),
        _SIDECAR_URL,
        _SIDECAR_TIMEOUT,
    )

    with httpx.Client(timeout=_SIDECAR_TIMEOUT) as client:
        response = client.post(
            f"{_SIDECAR_URL}/parse",
            files={"file": (filename, pdf_bytes, "application/pdf")},
        )
        response.raise_for_status()

    result: dict[str, Any] = response.json()
    return result


def _has_content(result: dict[str, Any]) -> bool:
    return any(p.get("text", "").strip() for p in result.get("pages", []))
