"""
Парсер PDF через unstructured (hi_res, OCR-ready, GPU-aware на Apple Silicon).

Возвращает ту же структуру, что исходный pdf_parser.py в rag-indexer:
{
    "pages":    [{"text": str, "page_number": int}, ...],
    "headings": [{"text": str, "page_number": int, "y0": float, "font_size": float}, ...],
    "metadata": {"source": str, "parser": str},
    "page_count": int
}

Стратегия:
  1. unstructured hi_res (detectron2 layout + tesseract OCR с rus+eng)
  2. При отказе hi_res → fast (только pdfminer, без OCR)
  3. При отказе fast → tesseract OCR через pdf2image + pytesseract (точно такой же
     фоллбэк, что был в исходном pdf_parser.py)
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Минимальный размер шрифта, считающийся заголовком (в пунктах)
# unstructured не всегда даёт font_size — используем category + эвристику
_HEADING_CATEGORIES = {"Title", "Header", "SectionHeader"}

# unstructured element types, которые явно являются текстом параграфа/таблицы
_TEXT_CATEGORIES = {
    "NarrativeText", "Text", "ListItem", "Table", "FigureCaption",
    "Footer", "EmailAddress", "UncategorizedText", "Formula",
}


def parse_pdf_unstructured(path: str, source_name: str = "") -> dict[str, Any]:
    """
    Основная точка входа. Пробует парсеры в порядке предпочтения.
    """
    source_name = source_name or path

    try:
        result = _parse_hi_res(path, source_name)
        if _has_content(result):
            return result
        logger.warning("[hi_res] Empty result for %s, falling back to fast", source_name)
    except Exception as exc:
        logger.warning("[hi_res] Failed for %s: %s — falling back to fast", source_name, exc)

    try:
        result = _parse_fast(path, source_name)
        if _has_content(result):
            return result
        logger.warning("[fast] Empty result for %s, falling back to OCR", source_name)
    except Exception as exc:
        logger.warning("[fast] Failed for %s: %s — falling back to OCR", source_name, exc)

    return _parse_ocr_fallback(path, source_name)


# ---------------------------------------------------------------------------
# hi_res via unstructured
# ---------------------------------------------------------------------------

def _parse_hi_res(path: str, source_name: str) -> dict[str, Any]:
    """
    unstructured partition_pdf с strategy='hi_res'.
    Использует detectron2 для layout analysis и tesseract для OCR.
    На Apple M-series MPS ускоряет detectron2 автоматически через PyTorch MPS backend.
    """
    from unstructured.partition.pdf import partition_pdf  # type: ignore[import]

    logger.info("[hi_res] Partitioning %s", source_name)
    elements = partition_pdf(
        filename=path,
        strategy="hi_res",
        languages=["rus", "eng"],
        infer_table_structure=True,
        extract_images_in_pdf=False,
    )
    return _elements_to_result(elements, source_name, parser="unstructured-hi_res")


def _parse_fast(path: str, source_name: str) -> dict[str, Any]:
    """
    unstructured partition_pdf с strategy='fast' (pdfminer, без OCR).
    Используется как второй эшелон если hi_res упал.
    """
    from unstructured.partition.pdf import partition_pdf  # type: ignore[import]

    logger.info("[fast] Partitioning %s", source_name)
    elements = partition_pdf(
        filename=path,
        strategy="fast",
        languages=["rus", "eng"],
        infer_table_structure=False,
        extract_images_in_pdf=False,
    )
    return _elements_to_result(elements, source_name, parser="unstructured-fast")


# ---------------------------------------------------------------------------
# Конвертация unstructured elements → унифицированный формат
# ---------------------------------------------------------------------------

def _elements_to_result(elements: list[Any], source_name: str, parser: str) -> dict[str, Any]:
    """
    Преобразует список unstructured Element в унифицированный dict.
    Группирует элементы по page_number, формирует headings.
    """
    pages_text: dict[int, list[str]] = defaultdict(list)
    headings: list[dict[str, Any]] = []

    for el in elements:
        meta = getattr(el, "metadata", None)
        page_number = 1
        if meta is not None:
            page_number = getattr(meta, "page_number", None) or 1

        category = getattr(el, "category", "")
        text = str(el).strip()

        if not text:
            continue

        if category in _HEADING_CATEGORIES:
            # Нормализация заголовка
            normalized = re.sub(r"\s+", " ", text).strip()
            if 0 < len(normalized) <= 300:
                headings.append({
                    "text": normalized,
                    "page_number": page_number,
                    # y0 недоступен напрямую в metadata — ставим 0.0
                    # rag-indexer использует y0 только для сортировки внутри страницы
                    "y0": _extract_y0(el),
                    "font_size": 0.0,
                })
            pages_text[page_number].append(f"## {normalized}")
        elif category == "Table":
            # Таблицы конвертируем в Markdown если доступен html representation
            table_md = _table_to_markdown(el)
            pages_text[page_number].append(table_md)
        else:
            pages_text[page_number].append(text)

    # Собираем страницы
    pages: list[dict[str, Any]] = []
    for page_number in sorted(pages_text.keys()):
        page_text = "\n\n".join(pages_text[page_number])
        if page_text.strip():
            pages.append({"text": page_text, "page_number": page_number})

    return {
        "pages": pages,
        "headings": headings,
        "metadata": {"source": source_name, "parser": parser},
        "page_count": len(pages),
    }


def _extract_y0(element: Any) -> float:
    """Пытается получить y0 из coordinates metadata unstructured."""
    try:
        meta = getattr(element, "metadata", None)
        if meta is None:
            return 0.0
        coords = getattr(meta, "coordinates", None)
        if coords is None:
            return 0.0
        points = getattr(coords, "points", None)
        if points and len(points) >= 1:
            # points — список кортежей (x, y); берём минимальный y как y0
            return float(min(p[1] for p in points))
    except Exception:
        pass
    return 0.0


def _table_to_markdown(element: Any) -> str:
    """
    Конвертирует Table-элемент в Markdown-таблицу.
    Если HTML-представление недоступно — возвращает plain text.
    """
    try:
        meta = getattr(element, "metadata", None)
        if meta is not None:
            html = getattr(meta, "text_as_html", None)
            if html:
                return _html_table_to_md(html)
    except Exception:
        pass
    return str(element).strip()


def _html_table_to_md(html: str) -> str:
    """
    Конвертирует HTML-таблицу в Markdown.
    Минималистичный парсер: работает без beautifulsoup4.
    """
    try:
        from html.parser import HTMLParser  # stdlib

        class _TableParser(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.rows: list[list[str]] = []
                self._current_row: list[str] = []
                self._current_cell: list[str] = []
                self._in_cell = False

            def handle_starttag(self, tag: str, attrs: list) -> None:
                if tag in ("tr",):
                    self._current_row = []
                elif tag in ("td", "th"):
                    self._current_cell = []
                    self._in_cell = True

            def handle_endtag(self, tag: str) -> None:
                if tag in ("td", "th"):
                    self._current_row.append(" ".join(self._current_cell).strip())
                    self._in_cell = False
                elif tag == "tr":
                    if self._current_row:
                        self.rows.append(self._current_row)

            def handle_data(self, data: str) -> None:
                if self._in_cell:
                    self._current_cell.append(data.strip())

        parser = _TableParser()
        parser.feed(html)

        if not parser.rows:
            return re.sub(r"<[^>]+>", " ", html).strip()

        lines: list[str] = []
        header = parser.rows[0]
        lines.append("| " + " | ".join(header) + " |")
        lines.append("| " + " | ".join(["---"] * len(header)) + " |")
        for row in parser.rows[1:]:
            # Выравниваем количество ячеек
            while len(row) < len(header):
                row.append("")
            lines.append("| " + " | ".join(row[: len(header)]) + " |")
        return "\n".join(lines)

    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()


# ---------------------------------------------------------------------------
# OCR fallback (pdf2image + pytesseract) — идентично rag-indexer
# ---------------------------------------------------------------------------

def _parse_ocr_fallback(path: str, source_name: str) -> dict[str, Any]:
    """
    Последний резерв: рендеринг страниц в изображения + tesseract OCR.
    Heading detection недоступен.
    """
    logger.info("[ocr-fallback] Starting OCR for %s", source_name)
    try:
        from pdf2image import convert_from_path  # type: ignore[import]
        import pytesseract  # type: ignore[import]
    except ImportError as exc:
        logger.error("[ocr-fallback] Missing dependency: %s", exc)
        return {
            "pages": [],
            "headings": [],
            "metadata": {"source": source_name, "parser": "ocr-unavailable"},
            "page_count": 0,
        }

    try:
        images = convert_from_path(path, dpi=300)
    except Exception as exc:
        logger.error("[ocr-fallback] Image conversion failed: %s", exc)
        return {
            "pages": [],
            "headings": [],
            "metadata": {"source": source_name, "parser": "ocr-failed"},
            "page_count": 0,
        }

    pages: list[dict[str, Any]] = []
    for i, img in enumerate(images, start=1):
        text = pytesseract.image_to_string(img, lang="rus+eng").strip()
        if text:
            pages.append({"text": text, "page_number": i})

    return {
        "pages": pages,
        "headings": [],
        "metadata": {"source": source_name, "parser": "pdf2image+pytesseract"},
        "page_count": len(pages),
    }


# ---------------------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------------------

def _has_content(result: dict[str, Any]) -> bool:
    """Проверяет, что результат содержит хотя бы одну непустую страницу."""
    return any(
        p.get("text", "").strip()
        for p in result.get("pages", [])
    )
