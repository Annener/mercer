from __future__ import annotations

import bisect
import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

_PAGE_MARKER_RE = re.compile(r"<!--PAGE:\d+-->\n?")

_REAL_HEADER_KEYWORDS: tuple[str, ...] = (
    "глава", "chapter", "часть", "part", "книга", "book",
    "раздел", "section", "введение", "introduction",
    "приложение", "appendix", "эпилог", "epilogue", "пролог", "prologue",
)


def merge_pdf_pages(
    pages: list[dict[str, Any]],
    headings: list[dict[str, Any]] | None = None,
) -> tuple[str, list[tuple[int, int]], list[dict[str, Any]]]:
    """
    Склейка страниц PDF с удалением повторяющихся колонтитулов и вставкой
    заголовков как псевдо-markdown "## ..." (чтобы generic_chunker мог по ним резать).

    Args:
        pages: [{"text": str, "page_number": int}, ...]
        headings: [{"text": str, "page_number": int, "y0": float, "font_size": float}, ...]
                  (опционально; если None — склейка без заголовков)

    Returns:
        (merged_text, page_offsets, placed_headings)
        - merged_text: единый текст с маркерами <!--PAGE:N--> и "## " перед заголовками
        - page_offsets: [(char_offset, page_number), ...] для бинарного поиска page_number
        - placed_headings: тот же список headings, но с добавленным char_offset для каждого
    """
    if not pages:
        return "", [], []

    headings = headings or []

    headers_footers: set[str] = set()
    if len(pages) >= 3:
        headers_footers = _detect_headers_footers(pages)
        if headers_footers:
            logger.info(
                "Detected %d header/footer lines to strip: %s",
                len(headers_footers),
                [hf[:60] for hf in list(headers_footers)[:5]],
            )

    headings_by_page: dict[int, list[dict[str, Any]]] = {}
    for h in headings:
        pn = int(h.get("page_number", 0))
        headings_by_page.setdefault(pn, []).append(h)

    for pn in headings_by_page:
        headings_by_page[pn].sort(key=lambda x: float(x.get("y0", 0.0)), reverse=True)

    merged_parts: list[str] = []
    page_offsets: list[tuple[int, int]] = []
    placed_headings: list[dict[str, Any]] = []
    current_offset = 0

    for page in pages:
        page_number = int(page.get("page_number", 0))
        page_text = str(page.get("text", ""))

        if headers_footers:
            page_text = _strip_headers_footers(page_text, headers_footers)

        marker = f"<!--PAGE:{page_number}-->\n\n"
        merged_parts.append(marker)
        page_offsets.append((current_offset, page_number))
        current_offset += len(marker)

        for h in headings_by_page.get(page_number, []):
            heading_text = str(h.get("text", "")).strip()
            if not heading_text:
                continue
            # Нормализация: любые последовательности пробельных символов → один пробел
            heading_text = re.sub(r"\s+", " ", heading_text).strip()
            heading_block = f"## {heading_text}\n\n"
            merged_parts.append(heading_block)
            placed_headings.append({
                **h,
                "char_offset": current_offset,
            })
            current_offset += len(heading_block)

        page_text_stripped = page_text.strip()
        if page_text_stripped:
            block = page_text_stripped + "\n\n"
            merged_parts.append(block)
            current_offset += len(block)

    merged_text = "".join(merged_parts)

    placed_headings.sort(key=lambda x: int(x.get("char_offset", 0)))

    return merged_text, page_offsets, placed_headings


def _detect_headers_footers(pages: list[dict[str, Any]]) -> set[str]:
    """
    Частотный анализ: строки, встречающиеся как первые/последние непустые
    строки на ≥60% страниц и длиной ≤200 символов, считаются колонтитулами.
    """
    first_lines: Counter[str] = Counter()
    last_lines: Counter[str] = Counter()

    for page in pages:
        text = str(page.get("text", ""))
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        first_lines[lines[0]] += 1
        last_lines[lines[-1]] += 1

    threshold = len(pages) * 0.6
    result: set[str] = set()

    for counter in (first_lines, last_lines):
        for line, count in counter.items():
            if count >= threshold and len(line) <= 200:
                if not _looks_like_real_header(line):
                    result.add(line)

    return result


def _looks_like_real_header(line: str) -> bool:
    """
    Эвристика: если строка содержит слова "глава/chapter/..." — возможно,
    это настоящий заголовок. Но если строка выглядит как колонтитул вида
    "ГЛАВА 2 | Название" (содержит разделитель | или —) — это колонтитул,
    и её нужно удалять.
    """
    lower = line.lower()
    has_header_keyword = any(kw in lower for kw in _REAL_HEADER_KEYWORDS)
    if not has_header_keyword:
        return False
    # Колонтитул-признак: содержит '|', '—', '/', '\\' — типичный разделитель
    # в строках вида "ГЛАВА 2 | Сигил, ГОРОД ДВЕРЕЙ» или «Часть 1 / Введение"
    _HEADER_FOOTER_SEPARATORS = ('|', ' — ', ' / ', ' \\ ')
    if any(sep in line for sep in _HEADER_FOOTER_SEPARATORS):
        return False  # это колонтитул, не настоящий заголовок
    return True


def _strip_headers_footers(text: str, headers_footers: set[str]) -> str:
    """Удаляет строки-колонтитулы из текста страницы."""
    lines = text.splitlines()
    filtered = [ln for ln in lines if ln.strip() not in headers_footers]
    return "\n".join(filtered)


def page_number_for_offset(
    page_offsets: list[tuple[int, int]],
    char_offset: int,
) -> int | None:
    """
    Бинарный поиск: возвращает page_number для заданного char_offset.
    page_offsets должен быть отсортирован по char_offset (возрастание).
    """
    if not page_offsets:
        return None

    keys = [po[0] for po in page_offsets]
    idx = bisect.bisect_right(keys, char_offset) - 1
    if idx < 0:
        return page_offsets[0][1]
    return page_offsets[idx][1]


def resolve_headers_at_offset(
    placed_headings: list[dict[str, Any]],
    char_offset: int,
) -> dict[str, str]:
    """
    Возвращает активные заголовки (последний ##) для заданной позиции в merged_text.

    В V3.0 все PDF-headings вставляются как "## ...", то есть имеют один уровень.
    Возвращает dict вида {"section": "<text последнего заголовка перед чанком>"}.

    placed_headings должен быть отсортирован по char_offset (возрастание).
    """
    if not placed_headings:
        return {}

    keys = [int(h.get("char_offset", 0)) for h in placed_headings]
    idx = bisect.bisect_right(keys, char_offset) - 1
    if idx < 0:
        return {}

    heading = placed_headings[idx]
    text = str(heading.get("text", "")).strip()
    if not text:
        return {}
    # Нормализация пробелов на случай, если текст содержит \n, \r, \t
    text = re.sub(r"\s+", " ", text).strip()
    return {"section": text}


def strip_page_markers(text: str) -> str:
    """Удаляет маркеры <!--PAGE:N--> из текста (используется при необходимости)."""
    return _PAGE_MARKER_RE.sub("", text)