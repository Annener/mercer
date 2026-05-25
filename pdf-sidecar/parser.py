"""
PDF-парсер для pdf-sidecar.

Использует unstructured partition_pdf с strategy='hi_res'.
Весь файл парсится за один вызов — постраничное разбиение не применяется,
чтобы не потерять контекст между страницами.

GPU-поддержка (Apple Silicon):
  - Table Transformer (PyTorch): monkey-patch load_agent → device='mps'.
  - YOLO layout detection (ONNX Runtime): CoreMLExecutionProvider если доступен
    (доступен при наличии onnxruntime>=1.17.0 на macOS arm64 с brew).

Прогресс:
  - Хук на PageLayout.from_image — вызывается после каждой страницы.
  - progress_callback(page_num, total_pages, n_elements, has_table) если передан.
  - INFO-логи по каждой странице: [hi_res] Page N/M — X elements.

Прогрев (warmup_models):
  - Вызывается при старте сервера.
  - Скачивает и инициализирует spaCy, YOLO, Table Transformer.
  - Первый запрос после прогрева не тратит время на инициализацию.

Таблицы:
  - infer_table_structure=True → table-transformer читает структуру.
  - text_as_html → конвертируем в Markdown через stdlib HTMLParser.
"""
from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Категории заголовков
_HEADING_CATEGORIES = {"Title", "Header", "SectionHeader"}

# Категории обычного текста
_TEXT_CATEGORIES = {
    "NarrativeText", "Text", "ListItem", "Table", "FigureCaption",
    "Footer", "EmailAddress", "UncategorizedText", "Formula",
}

# Глобальный флаг: были ли уже применены GPU-патчи
_GPU_PATCHES_APPLIED = False

# Глобальный флаг: был ли уже выполнен прогрев
_WARMUP_DONE = False


# ---------------------------------------------------------------------------
# GPU Monkey-patches
# ---------------------------------------------------------------------------

def _apply_mps_patches() -> str:
    """
    Патчит unstructured_inference для использования Apple Silicon MPS/CoreML.
    Применяется только один раз (идемпотентно).

    Возвращает строку с описанием применённых патчей (для лога).
    """
    global _GPU_PATCHES_APPLIED
    if _GPU_PATCHES_APPLIED:
        return "already applied"

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
                available,
            )
            self.model = onnxruntime.InferenceSession(
                model_path, providers=providers
            )
            self.layout_classes = label_map

        UnstructuredYoloXModel.initialize = _patched_yolo_initialize

        avail = _C.get_available_providers()
        if "CoreMLExecutionProvider" in avail:
            patches.append("YOLO→CoreML+CPU")
        else:
            patches.append("YOLO→CPU (CoreML unavailable)")

    except Exception as exc:
        logger.warning("CoreML patch for YOLO failed: %s", exc)
        patches.append(f"YOLO patch FAILED: {exc}")

    _GPU_PATCHES_APPLIED = True
    return ", ".join(patches)


# ---------------------------------------------------------------------------
# Прогрев моделей (вызывается при старте сервера)
# ---------------------------------------------------------------------------

def warmup_models() -> None:
    """
    Инициализирует все модели заранее чтобы первый запрос не тратил время на:
      - скачивание/инициализацию spaCy (en_core_web_sm)
      - скачивание/инициализацию YOLO ONNX модели
      - загрузку Table Transformer на MPS

    Вызывается один раз при старте через lifespan hook в app.py.
    """
    global _WARMUP_DONE
    if _WARMUP_DONE:
        logger.debug("warmup_models: already done, skipping")
        return

    t0 = time.monotonic()
    logger.info("[warmup] Starting model warmup...")

    # Применяем GPU-патчи до загрузки моделей
    patch_report = _apply_mps_patches()
    logger.info("[warmup] GPU patches: [%s]", patch_report)

    # 1. spaCy — скачивает en_core_web_sm если нет
    try:
        from unstructured.nlp.tokenize import get_tokenizer  # type: ignore[import]
        _ = get_tokenizer()
        logger.info("[warmup] spaCy tokenizer: OK (%.1fs)", time.monotonic() - t0)
    except Exception as exc:
        logger.warning("[warmup] spaCy warmup failed: %s", exc)

    # 2. YOLO ONNX модель — скачивает yolox_l0.05.onnx если нет
    try:
        from unstructured_inference.models.yolox import UnstructuredYoloXModel  # type: ignore[import]
        from unstructured_inference.models.base import get_model  # type: ignore[import]
        model = get_model()  # загружает дефолтную модель (YOLO)
        logger.info("[warmup] YOLO layout model: OK (%.1fs)", time.monotonic() - t0)
    except Exception as exc:
        logger.warning("[warmup] YOLO warmup failed: %s", exc)

    # 3. Table Transformer — загружает модель на MPS/CPU
    try:
        from unstructured_inference.models import tables as _tables_mod  # type: ignore[import]
        _tables_mod.load_agent()
        logger.info("[warmup] Table Transformer: OK (%.1fs)", time.monotonic() - t0)
    except Exception as exc:
        logger.warning("[warmup] Table Transformer warmup failed: %s", exc)

    elapsed = time.monotonic() - t0
    logger.info("[warmup] All models ready in %.1fs", elapsed)
    _WARMUP_DONE = True


# ---------------------------------------------------------------------------
# Публичная точка входа
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, int, int, bool], None]


def parse_pdf_unstructured(
    path: str,
    source_name: str = "",
    progress_callback: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """
    Парсит PDF через unstructured hi_res.
    Весь файл — одним вызовом partition_pdf (контекст между страницами не теряется).

    Args:
        path: путь к PDF файлу
        source_name: имя файла для логов/метаданных
        progress_callback: функция (page_num, total_pages, n_elements, has_table)
                           вызывается после каждой страницы (из потока парсинга)
    """
    source_name = source_name or path
    t_start = time.monotonic()

    # GPU-патчи применяются идемпотентно — можно вызывать сколько угодно раз
    patch_report = _apply_mps_patches()
    if patch_report != "already applied":
        logger.info("GPU patches applied: [%s]", patch_report)

    result = _parse_hi_res(path, source_name, t_start, progress_callback)

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

def _parse_hi_res(
    path: str,
    source_name: str,
    t_start: float,
    progress_callback: Optional[ProgressCallback],
) -> dict[str, Any]:
    from unstructured.partition.pdf import partition_pdf  # type: ignore[import]

    logger.info(
        "[hi_res] Starting partition_pdf: %s (file size: %.1f MB)",
        source_name,
        _file_size_mb(path),
    )

    # Устанавливаем прогресс-хук на PageLayout.from_image
    # (вызывается ровно один раз per страница в DocumentLayout.from_file)
    _install_page_progress_hook(source_name, t_start, progress_callback)

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
# Прогресс-хук: патчим PageLayout.from_image
# ---------------------------------------------------------------------------
# DocumentLayout.from_file итерирует страницы и для каждой вызывает
# PageLayout.from_image(image, number=i+1, ...).
# Это единственное надёжное место где можно перехватить завершение страницы.
# ---------------------------------------------------------------------------

_ORIGINAL_FROM_IMAGE = None
_HOOK_INSTALLED = False


def _install_page_progress_hook(
    source_name: str,
    t_start: float,
    progress_callback: Optional[ProgressCallback],
) -> None:
    global _ORIGINAL_FROM_IMAGE, _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return

    try:
        from unstructured_inference.inference.layout import PageLayout  # type: ignore[import]

        _ORIGINAL_FROM_IMAGE = PageLayout.from_image.__func__ if hasattr(
            PageLayout.from_image, '__func__') else None

        # Запоминаем оригинальный метод через __wrapped__ трюк
        _orig = PageLayout.from_image

        # Счётчик страниц — замыкание, т.к. total неизвестен заранее
        # (from_file сначала конвертирует все страницы в картинки, потом по одной)
        _state: dict[str, Any] = {"count": 0, "last_log": 0.0}

        @classmethod  # type: ignore[misc]
        def _hooked_from_image(cls, image, number=1, **kwargs):
            page = _orig.__func__(cls, image, number=number, **kwargs)

            _state["count"] += 1
            n_done = _state["count"]
            elapsed = time.monotonic() - t_start

            # Подсчёт элементов на странице
            elements = getattr(page, "elements", None) or []
            n_elements = len(list(elements))
            has_table = any(
                getattr(e, "category", "") == "Table"
                for e in (elements or [])
            )

            speed = n_done / elapsed if elapsed > 0 else 0
            logger.info(
                "[hi_res] Page %d done — %d elements%s — elapsed %.1fs (%.2f p/s)",
                number,
                n_elements,
                " [TABLE]" if has_table else "",
                elapsed,
                speed,
            )

            if progress_callback is not None:
                try:
                    # total_pages неизвестен здесь, передаём 0
                    progress_callback(number, 0, n_elements, has_table)
                except Exception as cb_exc:
                    logger.debug("progress_callback error: %s", cb_exc)

            return page

        PageLayout.from_image = _hooked_from_image
        _HOOK_INSTALLED = True
        logger.debug("Page progress hook installed on PageLayout.from_image")

    except Exception as exc:
        logger.debug("Could not install page progress hook: %s", exc)


def _remove_page_progress_hook() -> None:
    global _ORIGINAL_FROM_IMAGE, _HOOK_INSTALLED
    if not _HOOK_INSTALLED:
        return
    try:
        from unstructured_inference.inference.layout import PageLayout  # type: ignore[import]
        if _ORIGINAL_FROM_IMAGE is not None:
            PageLayout.from_image = classmethod(_ORIGINAL_FROM_IMAGE)
    except Exception:
        pass
    finally:
        _HOOK_INSTALLED = False
        _ORIGINAL_FROM_IMAGE = None


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
