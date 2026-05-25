"""
PDF-парсер для pdf-sidecar.

Использует unstructured partition_pdf с strategy='hi_res'.

## Параллельный батч-парсинг

Документ разрезается на батчи по N страниц и обрабатывается параллельно
через ProcessPoolExecutor. Размер батча рассчитывается динамически:

    batch_size = ceil(total_pages / cpu_count)
    но не менее MIN_BATCH_SIZE и не более MAX_BATCH_SIZE страниц

Каждый батч запускается в отдельном процессе (не потоке!) потому что:
  - unstructured/ONNX Runtime держат GIL во время inference
  - процессы дают настоящий параллелизм на M-серии
  - CoreML и MPS инициализируются независимо в каждом процессе

После завершения всех батчей элементы сортируются по page_number и
склеиваются в единый результат. Контекст на границах батчей не теряется —
embedded модель обрабатывает чанки с overlap, который перекрывает любой шов.

## GPU-поддержка

  - Table Transformer (PyTorch): monkey-patch load_agent → device='mps'
  - YOLO layout detection: CoreMLExecutionProvider если доступен
  - Модель: yolox_quantized (INT8, ~1.5–2× быстрее yolox при сопоставимом качестве)

## DPI

Рендеринг страниц: PDF_RENDER_DPI=200 (дефолт unstructured 350 — избыточно).
YOLO сам ресайзит input до 640px, поэтому 200 DPI достаточно.
Для Tesseract OCR качество не деградирует — он получает вырезанный регион.

## Фильтрация

Image и FigureCaption элементы отбрасываются — они не нужны для RAG.

## Прогрев

warmup_models() вызывается при старте сервера (lifespan hook в app.py).
Инициализирует spaCy, YOLO, Table Transformer заранее.
"""
from __future__ import annotations

import logging
import math
import multiprocessing
import os
import re
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------------

# Категории которые включаем в результат
_HEADING_CATEGORIES = {"Title", "Header", "SectionHeader"}
_TEXT_CATEGORIES = {
    "NarrativeText", "Text", "ListItem", "Table",
    "Footer", "EmailAddress", "UncategorizedText", "Formula",
}
# Image и FigureCaption — намеренно НЕ включены

# Параметры батчинга
_MIN_BATCH_SIZE = 5     # минимум страниц в батче (меньше — overhead > выигрыш)
_MAX_BATCH_SIZE = 20    # максимум (больше — теряем параллелизм)

# DPI рендеринга — 200 достаточно для YOLO (640px) и Tesseract
_RENDER_DPI = int(os.getenv("PDF_RENDER_DPI", "200"))

# Модель YOLO — quantized быстрее при сопоставимом качестве
_YOLO_MODEL = os.getenv("UNSTRUCTURED_HI_RES_MODEL_NAME", "yolox_quantized")

# Глобальные флаги — применяются внутри каждого процесса
_GPU_PATCHES_APPLIED = False
_WARMUP_DONE = False

# ---------------------------------------------------------------------------
# Тип callback прогресса
# ---------------------------------------------------------------------------

ProgressCallback = Callable[[int, int, int, bool], None]


# ---------------------------------------------------------------------------
# GPU monkey-patches
# ---------------------------------------------------------------------------

def _apply_mps_patches() -> str:
    global _GPU_PATCHES_APPLIED
    if _GPU_PATCHES_APPLIED:
        return "already applied"

    patches: list[str] = []

    # Table Transformer → MPS
    try:
        import torch
        if torch.backends.mps.is_available():
            from unstructured_inference.models import tables as _tables_mod

            def _patched_load_agent():
                agent = _tables_mod.tables_agent
                if getattr(agent, "model", None) is None:
                    with agent._lock:
                        if getattr(agent, "model", None) is None:
                            logger.info("Loading table structure model to mps (patched) ...")
                            agent.initialize(_tables_mod.DEFAULT_MODEL, device="mps")

            _tables_mod.load_agent = _patched_load_agent
            patches.append("TableTransformer→mps")
        else:
            patches.append("TableTransformer→cpu")
    except Exception as exc:
        logger.warning("MPS patch failed: %s", exc)
        patches.append(f"TableTransformer-FAILED:{exc}")

    # YOLO → CoreML
    try:
        import onnxruntime
        from onnxruntime.capi import _pybind_state as _C
        from unstructured_inference.models.yolox import UnstructuredYoloXModel

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
            logger.info("YOLO ONNX providers: %s", providers)
            self.model = onnxruntime.InferenceSession(model_path, providers=providers)
            self.layout_classes = label_map

        UnstructuredYoloXModel.initialize = _patched_yolo_initialize

        avail = _C.get_available_providers()
        if "CoreMLExecutionProvider" in avail:
            patches.append("YOLO→CoreML+CPU")
        else:
            patches.append("YOLO→CPU")
    except Exception as exc:
        logger.warning("CoreML patch failed: %s", exc)
        patches.append(f"YOLO-FAILED:{exc}")

    _GPU_PATCHES_APPLIED = True
    return ", ".join(patches)


# ---------------------------------------------------------------------------
# Прогрев моделей (вызывается при старте сервера)
# ---------------------------------------------------------------------------

def warmup_models() -> None:
    global _WARMUP_DONE
    if _WARMUP_DONE:
        return

    t0 = time.monotonic()
    logger.info("[warmup] Starting model warmup...")

    patch_report = _apply_mps_patches()
    logger.info("[warmup] GPU patches: [%s]", patch_report)

    try:
        from unstructured.nlp.tokenize import get_tokenizer  # type: ignore[import]
        _ = get_tokenizer()
        logger.info("[warmup] spaCy: OK (%.1fs)", time.monotonic() - t0)
    except Exception as exc:
        logger.warning("[warmup] spaCy failed: %s", exc)

    try:
        from unstructured_inference.models.base import get_model  # type: ignore[import]
        _ = get_model(_YOLO_MODEL)
        logger.info("[warmup] YOLO (%s): OK (%.1fs)", _YOLO_MODEL, time.monotonic() - t0)
    except Exception as exc:
        logger.warning("[warmup] YOLO failed: %s", exc)

    try:
        from unstructured_inference.models import tables as _tables_mod  # type: ignore[import]
        _tables_mod.load_agent()
        logger.info("[warmup] Table Transformer: OK (%.1fs)", time.monotonic() - t0)
    except Exception as exc:
        logger.warning("[warmup] Table Transformer failed: %s", exc)

    logger.info("[warmup] Done in %.1fs", time.monotonic() - t0)
    _WARMUP_DONE = True


# ---------------------------------------------------------------------------
# Публичная точка входа
# ---------------------------------------------------------------------------

def parse_pdf_unstructured(
    path: str,
    source_name: str = "",
    progress_callback: Optional[ProgressCallback] = None,
) -> dict[str, Any]:
    """
    Парсит PDF через unstructured hi_res с параллельным батч-парсингом.

    Args:
        path: путь к PDF
        source_name: имя файла для логов/метаданных
        progress_callback(page_num, total_pages, n_elements, has_table):
            вызывается после завершения каждой страницы (из рабочих процессов)
    """
    source_name = source_name or path
    t_start = time.monotonic()

    patch_report = _apply_mps_patches()
    if patch_report != "already applied":
        logger.info("GPU patches: [%s]", patch_report)

    # Считаем страницы
    total_pages = _count_pdf_pages(path)
    logger.info(
        "[hi_res] %s — %d pages, DPI=%d, model=%s",
        source_name, total_pages, _RENDER_DPI, _YOLO_MODEL,
    )

    if total_pages == 0:
        logger.warning("Could not determine page count, falling back to single-pass parse")
        return _parse_single(path, source_name, 1, total_pages, t_start, progress_callback)

    # Определяем батчи
    batches = _make_batches(total_pages)
    n_workers = len(batches)

    if n_workers == 1:
        # Нет смысла в process overhead для маленьких документов
        logger.info("[hi_res] Single batch (%d pages) — skipping parallelism", total_pages)
        return _parse_single(path, source_name, 1, total_pages, t_start, progress_callback)

    logger.info(
        "[hi_res] Parallel parse: %d batches × ~%d pages, %d workers",
        n_workers, batches[0][1] - batches[0][0] + 1, n_workers,
    )

    return _parse_parallel(path, source_name, total_pages, batches, t_start, progress_callback)


# ---------------------------------------------------------------------------
# Расчёт батчей
# ---------------------------------------------------------------------------

def _make_batches(total_pages: int) -> list[tuple[int, int]]:
    """
    Возвращает список (first_page, last_page) 1-based.

    Размер батча: ceil(total_pages / cpu_count),
    зажатый в [MIN_BATCH_SIZE, MAX_BATCH_SIZE].

    Примеры для разных документов:
      10 страниц, 10 CPU → batch=5 → 2 батча [1-5, 6-10]
      98 страниц, 10 CPU → batch=10 → 10 батчей [1-10, 11-20, ..., 91-98]
     200 страниц, 10 CPU → batch=20 → 10 батчей [1-20, 21-40, ..., 181-200]
    """
    cpu_count = os.cpu_count() or 4
    raw_batch = math.ceil(total_pages / cpu_count)
    batch_size = max(_MIN_BATCH_SIZE, min(_MAX_BATCH_SIZE, raw_batch))

    batches: list[tuple[int, int]] = []
    page = 1
    while page <= total_pages:
        last = min(page + batch_size - 1, total_pages)
        batches.append((page, last))
        page = last + 1

    return batches


# ---------------------------------------------------------------------------
# Счётчик страниц
# ---------------------------------------------------------------------------

def _count_pdf_pages(path: str) -> int:
    """Быстро считает количество страниц без полного парсинга."""
    # pypdfium2 используется в unstructured-inference, точно есть в venv
    try:
        import pypdfium2 as pdfium  # type: ignore[import]
        doc = pdfium.PdfDocument(path)
        count = len(doc)
        doc.close()
        return count
    except Exception:
        pass

    # Fallback: pdfminer
    try:
        from pdfminer.high_level import extract_pages  # type: ignore[import]
        return sum(1 for _ in extract_pages(path))
    except Exception:
        pass

    return 0


# ---------------------------------------------------------------------------
# Разрезание PDF на временный файл для батча
# ---------------------------------------------------------------------------

def _extract_pdf_pages(src_path: str, first_page: int, last_page: int) -> str:
    """
    Создаёт временный PDF с указанными страницами (1-based).
    Возвращает путь к временному файлу (caller обязан удалить).
    """
    import pypdfium2 as pdfium  # type: ignore[import]

    src = pdfium.PdfDocument(src_path)
    dst = pdfium.PdfDocument.new()

    # import_pages принимает 0-based индексы
    pages_0based = list(range(first_page - 1, last_page))
    dst.import_pages(src, pages=pages_0based)

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.close()
    dst.save(tmp.name)

    src.close()
    dst.close()

    return tmp.name


# ---------------------------------------------------------------------------
# Парсинг одного батча (запускается в дочернем процессе)
# ---------------------------------------------------------------------------

def _parse_batch_worker(
    pdf_path: str,
    first_page: int,
    last_page: int,
    source_name: str,
    render_dpi: int,
    yolo_model: str,
) -> list[dict[str, Any]]:
    """
    Worker-функция для ProcessPoolExecutor.
    Парсит страницы [first_page..last_page] и возвращает список сериализуемых элементов.

    Запускается в отдельном процессе — GPU-патчи применяются независимо.
    Использует starting_page_number чтобы сохранить правильные номера страниц.
    """
    # Настройка логирования в дочернем процессе
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s [%(levelname)s] worker[{first_page}-{last_page}] %(name)s — %(message)s",
    )
    log = logging.getLogger(__name__)

    # Устанавливаем DPI через env (unstructured читает из ENV)
    os.environ["PDF_RENDER_DPI"] = str(render_dpi)
    os.environ["UNSTRUCTURED_HI_RES_MODEL_NAME"] = yolo_model

    # GPU патчи
    _apply_mps_patches()

    from unstructured.partition.pdf import partition_pdf  # type: ignore[import]

    t0 = time.monotonic()
    log.info("Batch [%d-%d] starting partition_pdf...", first_page, last_page)

    try:
        elements = partition_pdf(
            filename=pdf_path,
            strategy="hi_res",
            languages=["rus", "eng"],
            infer_table_structure=True,
            extract_images_in_pdf=False,
            hi_res_model_name=yolo_model,
            starting_page_number=first_page,
        )
    except Exception as exc:
        log.error("Batch [%d-%d] failed: %s", first_page, last_page, exc)
        raise

    elapsed = time.monotonic() - t0
    log.info(
        "Batch [%d-%d] done: %d elements in %.1fs",
        first_page, last_page, len(elements), elapsed,
    )

    # Сериализуем элементы в dict (чтобы можно было передать через process boundary)
    result = []
    for el in elements:
        meta = getattr(el, "metadata", None)
        page_number = 1
        if meta is not None:
            page_number = getattr(meta, "page_number", None) or first_page

        category = getattr(el, "category", "")
        text = str(el).strip()

        # Фильтрация: Image и FigureCaption не нужны
        if category in ("Image", "FigureCaption"):
            continue

        text_as_html: Optional[str] = None
        if category == "Table" and meta is not None:
            text_as_html = getattr(meta, "text_as_html", None)

        y0 = _extract_y0(el)

        result.append({
            "category": category,
            "text": text,
            "page_number": page_number,
            "text_as_html": text_as_html,
            "y0": y0,
        })

    return result


# ---------------------------------------------------------------------------
# Параллельный парсинг
# ---------------------------------------------------------------------------

def _parse_parallel(
    path: str,
    source_name: str,
    total_pages: int,
    batches: list[tuple[int, int]],
    t_start: float,
    progress_callback: Optional[ProgressCallback],
) -> dict[str, Any]:
    """
    Запускает батчи параллельно через ProcessPoolExecutor.
    Собирает результаты по мере завершения, сортирует по странице.
    """
    n_workers = len(batches)

    # Создаём временные PDF-файлы для каждого батча
    batch_files: list[tuple[int, int, str]] = []
    try:
        for first_page, last_page in batches:
            tmp_path = _extract_pdf_pages(path, first_page, last_page)
            batch_files.append((first_page, last_page, tmp_path))

        logger.info("[hi_res] Created %d batch PDF files, starting parallel inference...", n_workers)

        all_elements: list[dict[str, Any]] = []
        completed = 0

        with ProcessPoolExecutor(max_workers=n_workers) as executor:
            futures = {
                executor.submit(
                    _parse_batch_worker,
                    tmp_path,
                    first_page,
                    last_page,
                    source_name,
                    _RENDER_DPI,
                    _YOLO_MODEL,
                ): (first_page, last_page)
                for first_page, last_page, tmp_path in batch_files
            }

            for future in as_completed(futures):
                first_page, last_page = futures[future]
                completed += 1
                elapsed = time.monotonic() - t_start

                try:
                    batch_elements = future.result()
                    all_elements.extend(batch_elements)

                    pages_done = last_page  # приблизительно
                    speed = pages_done / elapsed if elapsed > 0 else 0
                    logger.info(
                        "[hi_res] Batch [%d-%d] collected: %d elements "
                        "(%d/%d batches done, %.1fs elapsed, %.2f p/s)",
                        first_page, last_page, len(batch_elements),
                        completed, n_workers, elapsed, speed,
                    )

                    # Прогресс callback — сообщаем о каждой завершённой странице батча
                    if progress_callback is not None:
                        for p in range(first_page, last_page + 1):
                            n_el = sum(1 for e in batch_elements if e["page_number"] == p)
                            has_tbl = any(
                                e["category"] == "Table" and e["page_number"] == p
                                for e in batch_elements
                            )
                            try:
                                progress_callback(p, total_pages, n_el, has_tbl)
                            except Exception:
                                pass

                except Exception as exc:
                    logger.error(
                        "[hi_res] Batch [%d-%d] error: %s", first_page, last_page, exc
                    )
                    raise

    finally:
        # Всегда удаляем временные файлы
        for _, _, tmp_path in batch_files:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # Сортируем все элементы по номеру страницы для корректной склейки
    all_elements.sort(key=lambda e: (e["page_number"], e.get("y0", 0.0)))

    elapsed = time.monotonic() - t_start
    logger.info(
        "[hi_res] All batches complete: %d elements in %.1fs",
        len(all_elements), elapsed,
    )

    return _serialized_elements_to_result(all_elements, source_name, t_start)


# ---------------------------------------------------------------------------
# Одиночный парсинг (маленькие документы / fallback)
# ---------------------------------------------------------------------------

def _parse_single(
    path: str,
    source_name: str,
    first_page: int,
    total_pages: int,
    t_start: float,
    progress_callback: Optional[ProgressCallback],
) -> dict[str, Any]:
    from unstructured.partition.pdf import partition_pdf  # type: ignore[import]

    os.environ["PDF_RENDER_DPI"] = str(_RENDER_DPI)

    logger.info(
        "[hi_res] Starting partition_pdf: %s (%.1f MB)",
        source_name, _file_size_mb(path),
    )

    _install_page_progress_hook(source_name, t_start, total_pages, progress_callback)
    try:
        elements = partition_pdf(
            filename=path,
            strategy="hi_res",
            languages=["rus", "eng"],
            infer_table_structure=True,
            extract_images_in_pdf=False,
            hi_res_model_name=_YOLO_MODEL,
        )
    finally:
        _remove_page_progress_hook()

    logger.info(
        "[hi_res] Done: %d elements in %.1fs",
        len(elements), time.monotonic() - t_start,
    )

    # Фильтруем Image/FigureCaption и сериализуем
    serialized = []
    for el in elements:
        category = getattr(el, "category", "")
        if category in ("Image", "FigureCaption"):
            continue
        meta = getattr(el, "metadata", None)
        page_number = 1
        if meta:
            page_number = getattr(meta, "page_number", None) or 1
        text_as_html = None
        if category == "Table" and meta:
            text_as_html = getattr(meta, "text_as_html", None)
        serialized.append({
            "category": category,
            "text": str(el).strip(),
            "page_number": page_number,
            "text_as_html": text_as_html,
            "y0": _extract_y0(el),
        })

    return _serialized_elements_to_result(serialized, source_name, t_start)


# ---------------------------------------------------------------------------
# Конвертация сериализованных элементов → unified result dict
# ---------------------------------------------------------------------------

def _serialized_elements_to_result(
    elements: list[dict[str, Any]],
    source_name: str,
    t_start: float,
) -> dict[str, Any]:
    pages_text: dict[int, list[str]] = defaultdict(list)
    headings: list[dict[str, Any]] = []
    tables_found = 0
    categories_seen: dict[str, int] = defaultdict(int)

    for el in elements:
        category = el["category"]
        text = el["text"]
        page_number = el["page_number"]
        categories_seen[category] += 1

        if not text:
            continue

        if category in _HEADING_CATEGORIES:
            normalized = re.sub(r"\s+", " ", text).strip()
            if 0 < len(normalized) <= 300:
                headings.append({
                    "text": normalized,
                    "page_number": page_number,
                    "y0": el.get("y0", 0.0),
                    "font_size": 0.0,
                })
            pages_text[page_number].append(f"## {normalized}")

        elif category == "Table":
            tables_found += 1
            html = el.get("text_as_html")
            table_md = _html_table_to_md(html) if html else text
            pages_text[page_number].append(table_md)

        else:
            pages_text[page_number].append(text)

    elapsed = time.monotonic() - t_start
    logger.info(
        "Element categories (filtered): %s",
        ", ".join(f"{k}={v}" for k, v in sorted(categories_seen.items())),
    )
    if tables_found:
        logger.info("Tables converted to Markdown: %d", tables_found)

    pages: list[dict[str, Any]] = []
    for page_number in sorted(pages_text.keys()):
        page_text = "\n\n".join(pages_text[page_number])
        if page_text.strip():
            pages.append({"text": page_text, "page_number": page_number})

    page_count = len(pages)
    pages_per_sec = page_count / elapsed if elapsed > 0 else 0
    logger.info(
        "Parsing complete: %s → %d pages, %d headings in %.1fs (%.2f pages/s)",
        source_name, page_count, len(headings), elapsed, pages_per_sec,
    )

    return {
        "pages": pages,
        "headings": headings,
        "metadata": {"source": source_name, "parser": f"unstructured-hi_res/{_YOLO_MODEL}"},
        "page_count": page_count,
    }


# ---------------------------------------------------------------------------
# Прогресс-хук на PageLayout.from_image (для single-pass режима)
# ---------------------------------------------------------------------------

_ORIGINAL_FROM_IMAGE = None
_HOOK_INSTALLED = False


def _install_page_progress_hook(
    source_name: str,
    t_start: float,
    total_pages: int,
    progress_callback: Optional[ProgressCallback],
) -> None:
    global _ORIGINAL_FROM_IMAGE, _HOOK_INSTALLED
    if _HOOK_INSTALLED:
        return
    try:
        from unstructured_inference.inference.layout import PageLayout  # type: ignore[import]

        _orig = PageLayout.from_image
        _state: dict[str, Any] = {"count": 0}

        @classmethod  # type: ignore[misc]
        def _hooked(cls, image, number=1, **kwargs):
            page = _orig.__func__(cls, image, number=number, **kwargs)
            _state["count"] += 1
            elapsed = time.monotonic() - t_start

            elements = list(getattr(page, "elements", None) or [])
            n_elements = len(elements)
            has_table = any(getattr(e, "category", "") == "Table" for e in elements)
            speed = _state["count"] / elapsed if elapsed > 0 else 0

            total_str = f"/{total_pages}" if total_pages else ""
            logger.info(
                "[hi_res] Page %d%s — %d elements%s — %.1fs (%.2f p/s)",
                number, total_str, n_elements,
                " [TABLE]" if has_table else "",
                elapsed, speed,
            )

            if progress_callback is not None:
                try:
                    progress_callback(number, total_pages, n_elements, has_table)
                except Exception:
                    pass
            return page

        PageLayout.from_image = _hooked
        _HOOK_INSTALLED = True
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


def _html_table_to_md(html: str) -> str:
    from html.parser import HTMLParser

    class _P(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows: list[list[str]] = []
            self._row: list[str] = []
            self._cell: list[str] = []
            self._in = False

        def handle_starttag(self, tag, attrs):
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell = []
                self._in = True

        def handle_endtag(self, tag):
            if tag in ("td", "th"):
                self._row.append(" ".join(self._cell).strip())
                self._in = False
            elif tag == "tr" and self._row:
                self.rows.append(self._row)

        def handle_data(self, data):
            if self._in:
                self._cell.append(data.strip())

    try:
        p = _P()
        p.feed(html)
        if not p.rows:
            return re.sub(r"<[^>]+>", " ", html).strip()
        h = p.rows[0]
        lines = [
            "| " + " | ".join(h) + " |",
            "| " + " | ".join(["---"] * len(h)) + " |",
        ]
        for row in p.rows[1:]:
            while len(row) < len(h):
                row.append("")
            lines.append("| " + " | ".join(row[:len(h)]) + " |")
        return "\n".join(lines)
    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()


def _file_size_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except Exception:
        return 0.0
