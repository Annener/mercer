"""
PDF-парсер для rag-indexer.

Делегирует парсинг pdf-sidecar через HTTP (unstructured hi_res, GPU macOS).
При недоступности sidecar — fallback на встроенный pdfminer-парсер.

Возвращаемый формат неизменен:
{
    "pages":      [{"text": str, "page_number": int}, ...],
    "headings":   [{"text": str, "page_number": int, "y0": float, "font_size": float}, ...],
    "metadata":   {"source": str, "parser": str},
    "page_count": int,
}
"""
from __future__ import annotations

import io
import logging
import os
import re
import statistics
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# URL sidecar берётся из env (инжектируется docker-compose или задаётся вручную).
# Если env не задана — sidecar отключён, используется pdfminer.
_SIDECAR_URL = os.getenv("PDF_SIDECAR_URL", "").rstrip("/")
_SIDECAR_TIMEOUT = float(os.getenv("PDF_SIDECAR_TIMEOUT", "180"))
_SIDECAR_FALLBACK = os.getenv("PDF_SIDECAR_FALLBACK", "true").lower() != "false"


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------

def parse_pdf(path: str) -> dict[str, Any]:
    """
    Точка входа для rag-indexer (сигнатура не изменилась).

    1. Если PDF_SIDECAR_URL задан → пробуем sidecar (unstructured hi_res).
    2. При ошибке или недоступности sidecar → pdfminer (если FALLBACK=true).
    3. При пустом тексте после pdfminer → OCR-фоллбэк (pdf2image + pytesseract).
    """
    if _SIDECAR_URL:
        try:
            result = _parse_via_sidecar(path)
            if _has_content(result):
                logger.info(
                    "Sidecar parsed %s → %d pages via %s",
                    path,
                    result.get("page_count", 0),
                    result.get("metadata", {}).get("parser", "?"),
                )
                return result
            logger.warning(
                "Sidecar returned empty result for %s, falling back to pdfminer", path
            )
        except Exception as exc:
            if _SIDECAR_FALLBACK:
                logger.warning(
                    "Sidecar unavailable (%s), falling back to pdfminer for %s", exc, path
                )
            else:
                logger.error("Sidecar failed and fallback disabled: %s", exc)
                raise
    else:
        logger.debug("PDF_SIDECAR_URL not set, using pdfminer directly for %s", path)

    # --- pdfminer path ---
    try:
        pages, headings, parser_name = _extract_pdf_pages(path)
        if not pages or all(not p["text"].strip() for p in pages):
            logger.info("pdfminer returned empty text for %s, trying OCR", path)
            pages, headings, parser_name = _ocr_pdf_pages(path)
    except Exception:
        logger.error("pdfminer extraction failed for %s", path, exc_info=True)
        raise

    return {
        "pages": pages,
        "headings": headings,
        "metadata": {"source": path, "parser": parser_name},
        "page_count": len(pages),
    }


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

    with httpx.Client(timeout=_SIDECAR_TIMEOUT) as client:
        response = client.post(
            f"{_SIDECAR_URL}/parse",
            files={"file": (filename, pdf_bytes, "application/pdf")},
        )
        response.raise_for_status()

    result: dict[str, Any] = response.json()
    return result


# ---------------------------------------------------------------------------
# pdfminer (оригинальная реализация, сохранена без изменений)
# ---------------------------------------------------------------------------

try:
    from pdfminer.converter import PDFConverter
    from pdfminer.layout import LAParams, LTChar, LTPage, LTTextBox, LTTextLine
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    _PDFMINER_AVAILABLE = True
except ImportError:
    _PDFMINER_AVAILABLE = False
    logger.warning("pdfminer.six not installed — pdfminer fallback unavailable")


class _HeadingAwareConverter:  # pragma: no cover — экранирован если pdfminer нет
    """Heading-aware pdfminer converter. Используется только как fallback."""

    if _PDFMINER_AVAILABLE:
        from pdfminer.converter import PDFConverter as _Base

        class _Inner(PDFConverter):  # type: ignore[misc]
            def __init__(self, rsrcmgr: Any, laparams: Any = None) -> None:
                super().__init__(rsrcmgr, outfp=io.StringIO(), laparams=laparams)
                self.pages_data: list[dict[str, Any]] = []
                self._current_page_number: int = 0

            def set_page_number(self, page_number: int) -> None:
                self._current_page_number = page_number

            def receive_layout(self, ltpage: Any) -> None:
                text_boxes: list[dict[str, Any]] = []
                try:
                    for item in ltpage:
                        if not isinstance(item, LTTextBox):
                            continue
                        box_text = item.get_text()
                        if not box_text.strip():
                            continue
                        font_sizes: list[float] = []
                        for line in item:
                            if not isinstance(line, LTTextLine):
                                continue
                            for char in line:
                                if isinstance(char, LTChar) and char.size > 0:
                                    font_sizes.append(char.size)
                        max_font_size = max(font_sizes) if font_sizes else 0.0
                        text_boxes.append({
                            "text": box_text,
                            "y0": float(getattr(item, "y0", 0.0)),
                            "y1": float(getattr(item, "y1", 0.0)),
                            "x0": float(getattr(item, "x0", 0.0)),
                            "x1": float(getattr(item, "x1", 0.0)),
                            "font_size": max_font_size,
                        })
                except Exception:
                    logger.warning("pdfminer layout analysis failed p%d", self._current_page_number, exc_info=True)
                    self.pages_data.append({"text": "", "page_number": self._current_page_number, "headings": []})
                    return

                if not text_boxes:
                    self.pages_data.append({"text": "", "page_number": self._current_page_number, "headings": []})
                    return

                all_sizes = [b["font_size"] for b in text_boxes if b["font_size"] > 0]
                median_size = statistics.median(all_sizes) if all_sizes else 0.0
                heading_threshold = median_size * 1.3 if median_size > 0 else float("inf")

                page_headings: list[dict[str, Any]] = []
                for box in text_boxes:
                    stripped = box["text"].strip()
                    if not stripped:
                        continue
                    if box["font_size"] >= heading_threshold and 0 < len(stripped) <= 200:
                        page_headings.append({
                            "text": re.sub(r"\s+", " ", stripped).strip(),
                            "page_number": self._current_page_number,
                            "y0": box["y0"],
                            "font_size": box["font_size"],
                        })

                text_boxes.sort(key=lambda b: (-b["y1"], b["x0"]))
                page_text = "\n\n".join(b["text"].strip() for b in text_boxes if b["text"].strip())
                self.pages_data.append({
                    "text": page_text,
                    "page_number": self._current_page_number,
                    "headings": page_headings,
                })


def _extract_pdf_pages(path: str) -> tuple[list[dict], list[dict], str]:
    if not _PDFMINER_AVAILABLE:
        return [], [], "pdfminer-unavailable"

    resource_manager = PDFResourceManager()
    laparams = LAParams()
    converter = _HeadingAwareConverter._Inner(resource_manager, laparams=laparams)
    interpreter = PDFPageInterpreter(resource_manager, converter)

    try:
        with open(path, "rb") as f:
            for i, page in enumerate(PDFPage.get_pages(f), start=1):
                converter.set_page_number(i)
                interpreter.process_page(page)

        pages: list[dict] = []
        all_headings: list[dict] = []
        for page_data in converter.pages_data:
            if page_data["text"].strip():
                pages.append({"text": page_data["text"], "page_number": page_data["page_number"]})
                all_headings.extend(page_data.get("headings", []))
        return pages, all_headings, "pdfminer"
    except Exception as exc:
        logger.warning("pdfminer extraction failed, trying high-level fallback: %s", exc)
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(path)
            if text.strip():
                return [{"text": text, "page_number": 1}], [], "pdfminer-fallback"
        except Exception as fallback_err:
            logger.error("pdfminer high-level fallback also failed: %s", fallback_err)
        return [], [], "pdfminer-failed"


def _ocr_pdf_pages(path: str) -> tuple[list[dict], list[dict], str]:
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        logger.error("OCR dependencies not installed (pdf2image, pytesseract)")
        return [], [], "ocr-unavailable"

    try:
        images = convert_from_path(path)
    except Exception as exc:
        logger.error("OCR image conversion failed: %s", exc)
        return [], [], "ocr-failed"

    pages: list[dict] = []
    for i, img in enumerate(images, start=1):
        text = pytesseract.image_to_string(img, lang="rus+eng").strip()
        if text:
            pages.append({"text": text, "page_number": i})
    return pages, [], "pdf2image+pytesseract"


def _has_content(result: dict[str, Any]) -> bool:
    return any(p.get("text", "").strip() for p in result.get("pages", []))
