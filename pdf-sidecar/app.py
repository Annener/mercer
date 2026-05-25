"""
pdf-sidecar — FastAPI HTTP-сервер для парсинга PDF через unstructured (hi_res).

Принимает PDF-файл по HTTP multipart POST /parse или /parse/stream.

/parse         — синхронный, возвращает JSON после полного завершения
/parse/stream  — NDJSON-поток с прогресс-событиями по страницам и финальным результатом

FIX v3:
  - Логирование через dictConfig (нет дублей)
  - Прогрев моделей при старте (lifespan hook)
  - streaming адаптирован под параллельный батч-парсинг:
    прогресс приходит из дочерних процессов через thread-safe callback

FIX v3.1:
  - _generate() переписан: asyncio.Queue вместо queue.SimpleQueue+run_in_executor.
    Старая схема приводила к утечке потоков при TimeoutError: каждая истёкшая
    итерация оставляла висячий поток заблокированный на progress_q.get().
    Один из этих потоков перехватывал sentinel None раньше основного цикла,
    и цикл уже никогда не получал сигнал завершения → зависание на 50+ минут.
"""
from __future__ import annotations

import asyncio
import json
import logging
import logging.config
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from parser import parse_pdf_unstructured, warmup_models
from preprocessor import preprocess

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PORT = int(os.getenv("PDF_SIDECAR_PORT", "8765"))

_LOG_FILE = Path(__file__).parent / "logs" / "sidecar.log"

# ---------------------------------------------------------------------------
# Логирование — без дублей
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
        # propagate=True → сообщения идут в root (console + file).
        # handlers=[] → НЕ добавляем своих хендлеров, иначе uvicorn
        # при log_config=None добавит ещё один и будет дубль.
        "uvicorn": {"handlers": [], "propagate": True},
        "uvicorn.error": {"handlers": [], "propagate": True},
        "uvicorn.access": {"handlers": [], "propagate": True},
    },
    "root": {
        "handlers": ["console", "file"],
        "level": LOG_LEVEL,
    },
})

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan: прогрев моделей
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== PDF Sidecar starting up — warming up models ===")
    try:
        await asyncio.to_thread(warmup_models)
        logger.info("=== Warmup complete — ready to accept requests ===")
    except Exception as exc:
        logger.warning("Warmup failed (non-fatal): %s", exc)
    yield
    logger.info("=== PDF Sidecar shutting down ===")


app = FastAPI(title="PDF Sidecar", version="3.1.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "pdf-sidecar"}


@app.post("/parse")
async def parse_pdf(file: UploadFile = File(...)) -> JSONResponse:
    """Синхронный парсинг — возвращает JSON после полного завершения."""
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
        result = await asyncio.to_thread(
            parse_pdf_unstructured, tmp_path, file.filename
        )
    except Exception as exc:
        logger.error("Parsing failed for %s: %s", file.filename, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Parse error: {exc}") from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    for page in result.get("pages", []):
        source_hint = f"{file.filename}:page_{page.get('page_number', '?')}"
        page["text"] = preprocess(page["text"], source_hint)

    logger.info(
        "Parsed %s → %d pages, %d headings",
        file.filename, result.get("page_count", 0), len(result.get("headings", [])),
    )
    return JSONResponse(content=result)


@app.post("/parse/stream")
async def parse_pdf_stream(file: UploadFile = File(...)) -> StreamingResponse:
    """
    Streaming парсинг — NDJSON поток:
      {"type":"progress","page":N,"total":M,"elapsed":X,"elements":K,"has_table":bool}
      {"type":"result", ...полный результат...}
      {"type":"error",  "detail":"..."}

    Прогресс-события генерируются:
      - В single-pass режиме (маленькие PDF): по одной после каждой страницы
      - В параллельном режиме: пачками после завершения каждого батча

    Таймаут клиента: применяется только к каждому read-chunk,
    а не ко всему запросу. Heartbeat держит соединение живым.

    ВАЖНО: используем asyncio.Queue (не queue.SimpleQueue + run_in_executor).
    Схема с SimpleQueue приводила к утечке потоков при TimeoutError — каждый
    истёкший wait_for оставлял поток висеть на progress_q.get(). Один из них
    перехватывал sentinel None, и основной цикл никогда не получал сигнал
    завершения → бесконечное зависание.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file received.")

    logger.info("Received PDF (stream): %s (%d bytes)", file.filename, len(pdf_bytes))
    filename = file.filename

    async def _generate():
        import time

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        # asyncio.Queue — единственный безопасный способ передавать события
        # из потока (run_in_executor) в async-генератор без утечки потоков.
        #
        # Почему НЕ queue.SimpleQueue + run_in_executor:
        #   При TimeoutError wait_for отменяет future-обёртку, но НЕ сам поток
        #   заблокированный на SimpleQueue.get(). Эти потоки накапливаются и
        #   могут перехватить sentinel None раньше основного цикла.
        #
        # asyncio.Queue.get() — корутина, отменяется cleanly при TimeoutError,
        # никаких лишних потоков не создаётся.
        progress_q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()
        t_start = time.monotonic()

        def _on_progress(page_num: int, total_pages: int, n_elements: int, has_table: bool):
            # Вызывается из потока executor — кладём событие в asyncio.Queue
            # через thread-safe call_soon_threadsafe.
            loop.call_soon_threadsafe(
                progress_q.put_nowait,
                {
                    "type": "progress",
                    "page": page_num,
                    "total": total_pages,
                    "elapsed": round(time.monotonic() - t_start, 1),
                    "elements": n_elements,
                    "has_table": has_table,
                },
            )

        result_holder: list[dict] = []
        error_holder: list[Exception] = []

        def _run_parse():
            try:
                res = parse_pdf_unstructured(
                    tmp_path,
                    source_name=filename,
                    progress_callback=_on_progress,
                )
                result_holder.append(res)
            except Exception as exc:
                error_holder.append(exc)
            finally:
                # Sentinel — сигнал завершения парсинга.
                # call_soon_threadsafe гарантирует порядок: sentinel встанет
                # в очередь ПОСЛЕ всех progress-событий.
                loop.call_soon_threadsafe(progress_q.put_nowait, None)

        parse_task = asyncio.ensure_future(
            asyncio.to_thread(_run_parse)
        )

        # Читаем очередь и стримим прогресс клиенту.
        # asyncio.Queue.get() — корутина, отменяется без утечки потоков.
        try:
            while True:
                try:
                    event = await asyncio.wait_for(progress_q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Парсинг ещё идёт, очередь пуста — keepalive пустая строка
                    yield "\n"
                    continue

                if event is None:
                    # Sentinel — парсинг завершён
                    break

                yield json.dumps(event, ensure_ascii=False) + "\n"
        finally:
            # Дожидаемся завершения потока парсинга в любом случае
            await parse_task
            Path(tmp_path).unlink(missing_ok=True)

        if error_holder:
            logger.error("Parsing failed for %s: %s", filename, error_holder[0], exc_info=True)
            yield json.dumps(
                {"type": "error", "detail": str(error_holder[0])},
                ensure_ascii=False,
            ) + "\n"
            return

        result = result_holder[0]

        # Препроцессинг — выносим в to_thread чтобы не блокировать event loop
        # на больших документах
        def _preprocess_pages(pages: list[dict]) -> list[dict]:
            for page in pages:
                source_hint = f"{filename}:page_{page.get('page_number', '?')}"
                page["text"] = preprocess(page["text"], source_hint)
            return pages

        result["pages"] = await asyncio.to_thread(_preprocess_pages, result.get("pages", []))

        logger.info(
            "Parsed (stream) %s → %d pages, %d headings",
            filename, result.get("page_count", 0), len(result.get("headings", [])),
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
        log_config=None,
    )
