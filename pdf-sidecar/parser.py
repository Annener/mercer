"""
PDF-парсер для pdf-sidecar.

Использует unstructured partition_pdf с strategy='hi_res'.
Весь файл парсится за один вызов — постраничное разбиение не применяется,
чтобы не потерять контекст между страницами (заголовки, продолжения текста).

GPU-поддержка (Apple Silicon MPS):
  - Table Transformer (PyTorch): патчится через monkey-patch load_agent,
    передавая device='mps' вместо дефолтного 'cpu'.
  - YOLO layout detection (ONNX Runtime): патчится провайдер-список:
    добавляется CoreMLExecutionProvider перед CPUExecutionProvider,
    что даёт ускорение на Apple Silicon через ANE/GPU.

Логирование:
  - Прогресс по страницам через callback на PageLayout.analyze (каждые N страниц).
  - Детальные INFO/DEBUG сообщения: размер файла, кол-во страниц, время на страницу,
    ETA, статистика элементов.

Таблицы:
  - infer_table_structure=True → table-transformer читает структуру.
  - text_as_html → конвертируем в Markdown через stdlib HTMLParser.
  - Fallback: plain text элемента если HTML недоступен.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# Минимальные категории заголовков
_HEADING_CATEGORIES = {"Title", "Header", "SectionHeader"}

# Категории обычного текста
_TEXT_CATEGORIES = {
    "NarrativeText", "Text", "ListItem", "Table", "FigureCaption",
    "Footer", "EmailAddress", "UncategorizedText", "Formula",
}


# ---------------------------------------------------------------------------
# GPU Monkey-patches
# ---------------------------------------------------------------------------

def _apply_mps_patches() -> str:
    """
    Патчит unstructured_inference для использования Apple Silicon MPS/CoreML.

    Возвращает строку с описанием применённых патчей (для лога).
    """
    patches: list[str] = []

    # --- 1. Table Transformer: передаём device='mps' ---
    try:
        import torch
        if torch.backends.mps.is_available():
            from unstructured_inference.models import tables as _tables_mod

            original_load_agent = _tables_mod.load_agent

            def _patched_load_agent():
                agent = _tables_mod.tables_agent
                if getattr(agent, "model", None) is None:
                    with agent._lock:
                        if getattr(agent, "model", None) is None:
                            logger.info(
                                "Loading table structure model to mps (patched) ..."
                            )
                            agent.initialize(_tables_mod.DEFAULT_MODEL, device="mps")
                return

            _tables_mod.load_agent = _patched_load_agent
            patches.append("TableTransformer→mps")
        else:
            patches.append("TableTransformer→cpu (MPS unavailable)")
    except Exception as exc:
        logger.warning("MPS patch for TableTransformer failed: %s", exc)
        patches.append(f"TableTransformer patch FAILED: {exc}")

    # --- 2. YOLO ONNX: добавляем CoreMLExecutionProvider ---
    try:
        import onnxruntime
        from onnxruntime.capi import _pybind_state as _C
        from unstructured_inference.models.yolox import UnstructuredYoloXModel

        original_yolo_init = UnstructuredYoloXModel.initialize

        def _patched_yolo_initialize(self, model_path: str, label_map: dict):
            self.model_path = model_path
            available = _C.get_available_providers()
            # CoreML = Apple ANE/GPU через ONNX Runtime
            ordered = [
                "TensorrtExecutionProvider",
                "CUDAExecutionProvider",
                "CoreMLExecutionProvider",
                "CPUExecutionProvider",
            ]
            providers = [p for p in ordered if p in available]
            logger.info(
                "YOLO ONNX providers selected: %s (available: %s)",
                providers,
                [p for p in available if "CPU" not in p or "CPU" == p],
            )
            self.model = onnxruntime.InferenceSession(
                model_path, providers=providers
            )
            self.layout_classes = label_map

        UnstructuredYoloXModel.initialize = _patched_yolo_initialize

        # Проверяем что CoreML доступен
        avail = _C.get_available_providers()
        if "CoreMLExecutionProvider" in avail:
            patches.append("YOLO→CoreML+CPU")
        else:
            patches.append("YOLO→CPU (CoreML unavailable, install onnxruntime-silicon)")

    except Exception as exc:
        logger.warning("CoreML patch for YOLO failed: %s", exc)
        patches.append(f"YOLO patch FAILED: {exc}")

    return ", ".join(patches)


# ---------------------------------------------------------------------------
# Публичная точка входа
# ---------------------------------------------------------------------------

def parse_pdf_unstructured(path: str, source_name: str = "") -> dict[str, Any]:
    """
    Парсит PDF через unstructured hi_res.
    Весь файл — одним вызовом partition_pdf (контекст между страницами не теряется).
    """
    source_name = source_name or path
    t_start = time.monotonic()

    # Применяем GPU-патчи до первого импорта unstructured
    patch_report = _apply_mps_patches()
    logger.info("GPU patches applied: [%s]", patch_report)

    result = _parse_hi_res(path, source_name, t_start)

    elapsed = time.monotonic() - t_start
    page_count = result.get("page_count", 0)
    pages_per_sec = page_count / elapsed if elapsed > 0 else 0
    logger.info(
        "Parsing complete: %s → %d pages, %d headings in %.1fs (%.2f pages/s)",
        source_name,
        page_count,
        len(result.get("headings", [])),
        elapsed,
        pages_per_sec,
    )
    return result


# ---------------------------------------------------------------------------
# hi_res парсинг
# ---------------------------------------------------------------------------

def _parse_hi_res(path: str, source_name: str, t_start: float) -> dict[str, Any]:
    from unstructured.partition.pdf import partition_pdf  # type: ignore[import]

    logger.info(
        "[hi_res] Starting partition_pdf: %s (file size: %.1f MB)",
        source_name,
        _file_size_mb(path),
    )

    # Патчим PageLayout.get_elements для получения прогресса постранично
    _install_page_progress_hook(source_name, t_start)

    try:
        elements = partition_pdf(
            filename=path,
            strategy="hi_res",
            languages=["rus", "eng"],
            infer_table_structure=True,
            extract_images_in_pdf=False,
        )
    finally:
        _remove_page_progress_hook()

    logger.info(
        "[hi_res] partition_pdf done: %d elements total in %.1fs",
        len(elements),
        time.monotonic() - t_start,
    )
    return _elements_to_result(elements, source_name, parser="unstructured-hi_res")


# ---------------------------------------------------------------------------
# Прогресс-хук на уровне PageLayout
# ---------------------------------------------------------------------------

_PROGRESS_HOOK_INSTALLED = False
_ORIGINAL_GET_ELEMENTS = None


def _install_page_progress_hook(source_name: str, t_start: float) -> None:
    """
    Monkey-patch PageLayout.get_elements чтобы логировать прогресс
    каждый раз когда unstructured заканчивает обработку очередной страницы.
    """
    global _PROGRESS_HOOK_INSTALLED, _ORIGINAL_GET_ELEMENTS
    if _PROGRESS_HOOK_INSTALLED:
        return
    try:
        from unstructured_inference.inference.layout import PageLayout

        _ORIGINAL_GET_ELEMENTS = PageLayout.get_elements
        _page_counters: dict[str, list] = {"count": [], "last_log": [0.0]}

        def _hooked_get_elements(self, *args, **kwargs):
            result = _ORIGINAL_GET_ELEMENTS(self, *args, **kwargs)

            page_num = getattr(self, "number", len(_page_counters["count"]) + 1)
            _page_counters["count"].append(page_num)
            n_done = len(_page_counters["count"])
            elapsed = time.monotonic() - t_start

            # Логируем каждую страницу — это важная информация о прогрессе
            n_elements = len(result) if result is not None else 0
            has_table = any(
                getattr(e, "category", "") == "Table"
                for e in (result or [])
            )
            speed = n_done / elapsed if elapsed > 0 else 0
            logger.info(
                "[hi_res] Page %d done — %d elements%s — elapsed %.1fs (%.2f p/s)",
                page_num,
                n_elements,
                " [TABLE]" if has_table else "",
                elapsed,
                speed,
            )

            return result

        PageLayout.get_elements = _hooked_get_elements
        _PROGRESS_HOOK_INSTALLED = True
        logger.debug("Page progress hook installed on PageLayout.get_elements")
    except Exception as exc:
        logger.debug("Could not install page progress hook: %s", exc)


def _remove_page_progress_hook() -> None:
    global _PROGRESS_HOOK_INSTALLED, _ORIGINAL_GET_ELEMENTS
    if not _PROGRESS_HOOK_INSTALLED or _ORIGINAL_GET_ELEMENTS is None:
        return
    try:
        from unstructured_inference.inference.layout import PageLayout
        PageLayout.get_elements = _ORIGINAL_GET_ELEMENTS
    except Exception:
        pass
    finally:
        _PROGRESS_HOOK_INSTALLED = False
        _ORIGINAL_GET_ELEMENTS = None


# ---------------------------------------------------------------------------
# Конвертация elements → unified dict
# ---------------------------------------------------------------------------

def _elements_to_result(elements: list[Any], source_name: str, parser: str) -> dict[str, Any]:
    pages_text: dict[int, list[str]] = defaultdict(list)
    headings: list[dict[str, Any]] = []

    tables_found = 0
    categories_seen: dict[str, int] = defaultdict(int)

    for el in elements:
        meta = getattr(el, "metadata", None)
        page_number = 1
        if meta is not None:
            page_number = getattr(meta, "page_number", None) or 1

        category = getattr(el, "category", "")
        text = str(el).strip()
        categories_seen[category] += 1

        if not text:
            continue

        if category in _HEADING_CATEGORIES:
            normalized = re.sub(r"\s+", " ", text).strip()
            if 0 < len(normalized) <= 300:
                headings.append({
                    "text": normalized,
                    "page_number": page_number,
                    "y0": _extract_y0(el),
                    "font_size": 0.0,
                })
            pages_text[page_number].append(f"## {normalized}")

        elif category == "Table":
            tables_found += 1
            table_md = _table_to_markdown(el, tables_found)
            pages_text[page_number].append(table_md)

        else:
            pages_text[page_number].append(text)

    # Статистика элементов
    logger.info(
        "Element categories: %s",
        ", ".join(f"{k}={v}" for k, v in sorted(categories_seen.items())),
    )
    if tables_found > 0:
        logger.info("Tables found and converted to Markdown: %d", tables_found)

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


# ---------------------------------------------------------------------------
# Вспомогательные
# ---------------------------------------------------------------------------

def _extract_y0(element: Any) -> float:
    try:
        meta = getattr(element, "metadata", None)
        if meta is None:
            return 0.0
        coords = getattr(meta, "coordinates", None)
        if coords is None:
            return 0.0
        points = getattr(coords, "points", None)
        if points and len(points) >= 1:
            return float(min(p[1] for p in points))
    except Exception:
        pass
    return 0.0


def _table_to_markdown(element: Any, table_index: int = 0) -> str:
    """
    Конвертирует Table-элемент в Markdown.
    Использует text_as_html если доступен (infer_table_structure=True).
    Fallback → plain text.
    """
    try:
        meta = getattr(element, "metadata", None)
        if meta is not None:
            html = getattr(meta, "text_as_html", None)
            if html:
                md = _html_table_to_md(html)
                logger.debug("Table #%d converted from HTML (%d chars)", table_index, len(md))
                return md
            else:
                logger.debug("Table #%d: text_as_html is empty, using plain text", table_index)
    except Exception as exc:
        logger.debug("Table #%d HTML extraction error: %s", table_index, exc)
    return str(element).strip()


def _html_table_to_md(html: str) -> str:
    """HTML <table> → Markdown. Без внешних зависимостей (stdlib HTMLParser)."""
    from html.parser import HTMLParser

    class _TableParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.rows: list[list[str]] = []
            self._current_row: list[str] = []
            self._current_cell: list[str] = []
            self._in_cell = False

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag == "tr":
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

    try:
        parser = _TableParser()
        parser.feed(html)

        if not parser.rows:
            return re.sub(r"<[^>]+>", " ", html).strip()

        header = parser.rows[0]
        lines: list[str] = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(["---"] * len(header)) + " |",
        ]
        for row in parser.rows[1:]:
            while len(row) < len(header):
                row.append("")
            lines.append("| " + " | ".join(row[: len(header)]) + " |")
        return "\n".join(lines)

    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()


def _has_content(result: dict[str, Any]) -> bool:
    return any(p.get("text", "").strip() for p in result.get("pages", []))


def _file_size_mb(path: str) -> float:
    try:
        from pathlib import Path
        return Path(path).stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0
