from __future__ import annotations

import io
import logging
import re
import statistics
from typing import Any

from pdfminer.converter import PDFConverter
from pdfminer.layout import LAParams, LTChar, LTPage, LTTextBox, LTTextLine
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage

logger = logging.getLogger(__name__)


class HeadingAwareConverter(PDFConverter):
    """
    Кастомный pdfminer converter, который:
    - Собирает текст страницы в естественном порядке чтения (сверху вниз, слева направо)
    - Детектит заголовки по размеру шрифта:
        font_size ≥ median × 1.3  И  длина текста ≤ 200 символов  →  heading
    - Не хранит все LTTextBox в памяти одновременно — обрабатывает страницу за страницей
      (graceful degradation: если анализ падает, страница пропускается).
    """

    def __init__(
        self,
        rsrcmgr: PDFResourceManager,
        laparams: LAParams | None = None,
    ) -> None:
        super().__init__(rsrcmgr, outfp=io.StringIO(), laparams=laparams)
        self.pages_data: list[dict[str, Any]] = []
        self._current_page_number: int = 0

    def set_page_number(self, page_number: int) -> None:
        self._current_page_number = page_number

    def receive_layout(self, ltpage: LTPage) -> None:
        """Анализирует LTPage: собирает текст и детектит headings."""
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
            logger.warning(
                "Failed to analyse layout for page %d, returning empty page",
                self._current_page_number,
                exc_info=True,
            )
            self.pages_data.append({
                "text": "",
                "page_number": self._current_page_number,
                "headings": [],
            })
            return

        if not text_boxes:
            self.pages_data.append({
                "text": "",
                "page_number": self._current_page_number,
                "headings": [],
            })
            return

        all_sizes = [b["font_size"] for b in text_boxes if b["font_size"] > 0]
        median_size = statistics.median(all_sizes) if all_sizes else 0.0
        heading_threshold = median_size * 1.3 if median_size > 0 else float("inf")

        page_headings: list[dict[str, Any]] = []
        for box in text_boxes:
            box_text_stripped = box["text"].strip()
            if not box_text_stripped:
                continue
            if (
                box["font_size"] >= heading_threshold
                and box["font_size"] > 0
                and 0 < len(box_text_stripped) <= 200
            ):
                # Нормализация пробелов: \n, \r, \t, множественные пробелы → один пробел
                normalized_text = re.sub(r"\s+", " ", box_text_stripped).strip()
                page_headings.append({
                    "text": normalized_text,
                    "page_number": self._current_page_number,
                    "y0": box["y0"],
                    "font_size": box["font_size"],
                })

        text_boxes.sort(key=lambda b: (-b["y1"], b["x0"]))
        page_text = "\n\n".join(
            b["text"].strip() for b in text_boxes if b["text"].strip()
        )

        self.pages_data.append({
            "text": page_text,
            "page_number": self._current_page_number,
            "headings": page_headings,
        })


def parse_pdf(path: str) -> dict[str, Any]:
    """
    Парсит PDF постранично с heading detection.
    Возвращает структуру:
        {
            "pages":     [{"text": str, "page_number": int}, ...],
            "headings":  [{"text", "page_number", "y0", "font_size"}, ...],
            "metadata":  {"source": path, "parser": "<parser_name>"},
            "page_count": int,
        }
    При неудаче pdfminer.six использует OCR-фоллбэк (headings = []).
    """
    try:
        pages, headings, parser_name = _extract_pdf_pages(path)

        if not pages or all(not p["text"].strip() for p in pages):
            pages, headings, parser_name = _ocr_pdf_pages(path)

        return {
            "pages": pages,
            "headings": headings,
            "metadata": {"source": path, "parser": parser_name},
            "page_count": len(pages),
        }
    except Exception:
        logger.error("Failed to parse PDF: %s", path, exc_info=True)
        raise


def _extract_pdf_pages(path: str) -> tuple[list[dict], list[dict], str]:
    """Извлекает страницы и headings через HeadingAwareConverter."""
    resource_manager = PDFResourceManager()
    laparams = LAParams()

    try:
        converter = HeadingAwareConverter(resource_manager, laparams=laparams)
        interpreter = PDFPageInterpreter(resource_manager, converter)

        with open(path, "rb") as f:
            for i, page in enumerate(PDFPage.get_pages(f), start=1):
                converter.set_page_number(i)
                interpreter.process_page(page)

        pages: list[dict] = []
        all_headings: list[dict] = []

        for page_data in converter.pages_data:
            text = page_data["text"]
            page_number = page_data["page_number"]
            if text.strip():
                pages.append({"text": text, "page_number": page_number})
                all_headings.extend(page_data.get("headings", []))

        return pages, all_headings, "pdfminer"

    except Exception as e:
        logger.warning("pdfminer extraction failed, falling back to full text: %s", e)
        try:
            from pdfminer.high_level import extract_text

            text = extract_text(path)
            if text.strip():
                return [{"text": text, "page_number": 1}], [], "pdfminer-fallback"
        except Exception as fallback_err:
            logger.error("PDF extraction fallback also failed: %s", fallback_err)

        return [], [], "pdfminer-failed"


def _ocr_pdf_pages(path: str) -> tuple[list[dict], list[dict], str]:
    """OCR-фоллбэк. Heading detection недоступен — возвращается пустой список."""
    from pdf2image import convert_from_path
    import pytesseract

    try:
        pages_images = convert_from_path(path)
    except Exception as e:
        logger.error("OCR image conversion failed: %s", e)
        return [], [], "ocr-failed"

    pages: list[dict] = []
    for i, img in enumerate(pages_images, start=1):
        text = pytesseract.image_to_string(img, lang="rus+eng").strip()
        if text:
            pages.append({"text": text, "page_number": i})

    return pages, [], "pdf2image+pytesseract"