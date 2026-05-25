"""
pdf-sidecar — FastAPI HTTP-сервер для парсинга PDF через unstructured (hi_res).

Принимает PDF-файл по HTTP multipart POST /parse, возвращает JSON:
{
    "pages":    [{"text": str, "page_number": int}, ...],
    "headings": [{"text": str, "page_number": int, "y0": float, "font_size": float}, ...],
    "metadata": {"source": str, "parser": str},
    "page_count": int
}

Препроцессинг текста каждой страницы выполняется внутри сайдкара
через тот же preprocessor.py что использует rag-indexer.

FIX v2:
  - Логирование настроено через dictConfig чтобы не дублировать сообщения.
    Uvicorn получает propagate=False, FileHandler добавляется только к root.
  - /warmup endpoint: прогрев spaCy + YOLO + Table Transformer при старте.
  - on_startup hook: автоматически вызывает /warmup при запуске сервера.
"""
from __future__ import annotations

import json
import logging
import logging.config
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from parser import parse_pdf_unstructured, warmup_models
from preprocessor import preprocess

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PORT = int(os.getenv("PDF_SIDECAR_PORT", "8765"))

_LOG_FILE = Path(__file__).parent / "logs" / "sidecar.log"

# ---------------------------------------------------------------------------
# Настройка логирования — ОДИН раз, без дублей
# ---------------------------------------------------------------------------
# Проблема: uvicorn.run() вызывает logging.basicConfig() и добавляет свои
# handlers к root logger. Затем наш basicConfig добавляет ещё handlers.
# Итог — каждое сообщение идёт через 2-4 handler → дубли в логе.
#
# Решение: настраиваем всё через dictConfig ДО создания app/uvicorn.
# uvicorn.loggers (uvicorn, uvicorn.access, uvicorn.error) получают
# propagate=False чтобы не всплывать к root.
# ---------------------------------------------------------------------------
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.FileHandler",
            "formatter": "default",
            "filename": str(_LOG_FILE),
            "encoding": "utf-8",
        },
    },
    "loggers": {
        # Uvicorn управляет своими логгерами сам — отключаем propagate
        # чтобы они НЕ шли к root handler (иначе дубли)
        "uvicorn": {"handlers": [], "propagate": False},
        "uvicorn.error": {"handlers": ["console", "file"], "propagate": False},
        "uvicorn.access": {"handlers": ["console", "file"], "propagate": False},
    },
    "root": {
        "handlers": ["console", "file"],
        "level": LOG_LEVEL,
    },
})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: прогрев моделей при старте
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Прогреваем модели один раз при старте чтобы первый запрос не ждал."""
    import asyncio
    logger.info("=== PDF Sidecar starting up — warming up models ===")
    try:
        await asyncio.to_thread(warmup_models)
        logger.info("=== Warmup complete — ready to accept requests ===")
    except Exception as exc:
        logger.warning("Warmup failed (non-fatal): %s", exc)
    yield
    logger.info("=== PDF Sidecar shutting down ===")


app = FastAPI(title="PDF Sidecar", version="2.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "pdf-sidecar"}


@app.post("/parse")
async def parse_pdf(file: UploadFile = File(...)) -> JSONResponse:
    """
    Принимает PDF multipart/form-data, парсит через unstructured hi_res,
    возвращает постраничный текст с заголовками.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file received.")

    logger.info("Received PDF: %s (%d bytes)", file.filename, len(pdf_bytes))

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        result = parse_pdf_unstructured(tmp_path, source_name=file.filename)
    except Exception as exc:
        logger.error("Parsing failed for %s: %s", file.filename, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Parse error: {exc}") from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # Препроцессинг текста каждой страницы
    for page in result.get("pages", []):
        source_hint = f"{file.filename}:page_{page.get('page_number', '?')}"
        page["text"] = preprocess(page["text"], source_hint)

    logger.info(
        "Parsed %s → %d pages, %d headings",
        file.filename,
        result.get("page_count", 0),
        len(result.get("headings", [])),
    )
    return JSONResponse(content=result)


@app.post("/parse/stream")
async def parse_pdf_stream(file: UploadFile = File(...)) -> StreamingResponse:
    """
    Streaming-версия /parse.

    Возвращает NDJSON-поток (Newline-Delimited JSON):
      {"type":"progress","page":N,"total":M,"elapsed":X}   — по мере парсинга страниц
      {"type":"result", ...полный результат...}             — в конце

    Это решает проблему таймаутов: клиент получает данные непрерывно
    во время парсинга, а не ждёт полного завершения.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file received.")

    logger.info("Received PDF (stream): %s (%d bytes)", file.filename, len(pdf_bytes))

    filename = file.filename

    async def _generate():
        import asyncio
        import time

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        progress_events: list[dict] = []
        result_holder: list[dict] = []
        error_holder: list[Exception] = []
        t_start = time.monotonic()

        def _progress_callback(page_num: int, total_pages: int, n_elements: int, has_table: bool):
            """Вызывается из parser.py при завершении каждой страницы."""
            elapsed = time.monotonic() - t_start
            progress_events.append({
                "type": "progress",
                "page": page_num,
                "total": total_pages,
                "elapsed": round(elapsed, 1),
                "elements": n_elements,
                "has_table": has_table,
            })

        def _run_parse():
            try:
                res = parse_pdf_unstructured(tmp_path, source_name=filename,
                                             progress_callback=_progress_callback)
                result_holder.append(res)
            except Exception as exc:
                error_holder.append(exc)

        parse_future = asyncio.get_event_loop().run_in_executor(None, _run_parse)

        last_sent_idx = 0
        # Пока парсинг идёт — шлём прогресс-события по мере их появления
        while not parse_future.done():
            await asyncio.sleep(0.5)
            while last_sent_idx < len(progress_events):
                ev = progress_events[last_sent_idx]
                yield json.dumps(ev, ensure_ascii=False) + "\n"
                last_sent_idx += 1

        # Убеждаемся что future завершился (поднимает исключение если было)
        await parse_future

        # Отправляем оставшиеся события прогресса
        while last_sent_idx < len(progress_events):
            ev = progress_events[last_sent_idx]
            yield json.dumps(ev, ensure_ascii=False) + "\n"
            last_sent_idx += 1

        Path(tmp_path).unlink(missing_ok=True)

        if error_holder:
            logger.error("Parsing failed for %s: %s", filename, error_holder[0], exc_info=True)
            yield json.dumps({"type": "error", "detail": str(error_holder[0])},
                             ensure_ascii=False) + "\n"
            return

        result = result_holder[0]

        # Препроцессинг
        for page in result.get("pages", []):
            source_hint = f"{filename}:page_{page.get('page_number', '?')}"
            page["text"] = preprocess(page["text"], source_hint)

        logger.info(
            "Parsed (stream) %s → %d pages, %d headings",
            filename,
            result.get("page_count", 0),
            len(result.get("headings", [])),
        )

        result["type"] = "result"
        yield json.dumps(result, ensure_ascii=False) + "\n"

    return StreamingResponse(
        _generate(),
        media_type="application/x-ndjson",
        headers={"X-Content-Type-Options": "nosniff"},
    )


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        # Отключаем uvicorn access log formatter — он добавляет свой handler
        # к uvicorn.access логгеру поверх нашего dictConfig
        log_config=None,
    )
