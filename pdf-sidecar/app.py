"""
pdf-sidecar — FastAPI HTTP-сервер для парсинга PDF через unstructured (hi_res),
реранжирования через CrossEncoder и эмбеддинга через SentenceTransformer.

/parse         — синхронный, возвращает JSON после полного завершения
/parse/stream  — NDJSON-поток с прогресс-событиями по страницам и финальным результатом
/rerank        — реранжирование документов через CrossEncoder (BAAI/bge-reranker-v2-m3)
/embed         — эмбеддинг текстов через SentenceTransformer (BAAI/bge-m3)
               Доверен выносу bge-m3 из Ollama в этот сервис для:
               - батчинг за один forward pass вместо N HTTP-запросов к Ollama
               - изоляция нагрузки индексации от LLM-запросов пользователей
               - детерминированные вектора (те же веса, не зависящие от версии Ollama)
               Ответ совместим с OpenAI /embeddings API:
               {"data": [{"index": 0, "embedding": [...]}, ...]}

FIX v3:
  - Логирование через dictConfig (нет дублей)
  - Прогрев моделей при старте (lifespan hook)
  - streaming адаптирован под параллельный батч-парсинг

FIX v3.1:
  - _generate() переписан: asyncio.Queue вместо queue.SimpleQueue+run_in_executor

FIX v3.2:
  - Передача exc_info=exc (объект) вместо exc_info=True

v4.0:
  - Добавлен эндпоинт POST /rerank и прогрев CrossEncoder в lifespan.

v5.0:
  - Добавлен эндпоинт POST /embed (OpenAI-compatible) и прогрев SentenceTransformer (bge-m3) в lifespan.
  - bge-m3 вынесен из Ollama в этот сервис.
  - /health дополнен флагом embedder_loaded.
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
from pydantic import BaseModel

from parser import parse_pdf_unstructured, warmup_models
from preprocessor import preprocess
from reranker import load_reranker, rerank, is_loaded as reranker_is_loaded
from embedder import load_embedder, embed as _embed, is_loaded as embedder_is_loaded

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

    # Прогрев PDF-парсера
    try:
        await asyncio.to_thread(warmup_models)
        logger.info("PDF parser warmup complete")
    except Exception as exc:
        logger.warning("PDF parser warmup failed (non-fatal): %s", exc)

    # Прогрев reranker — загрузка CrossEncoder один раз при старте
    try:
        await asyncio.to_thread(load_reranker)
        logger.info("Reranker warmup complete")
    except Exception as exc:
        logger.warning("Reranker warmup failed (non-fatal): %s", exc)

    # Прогрев embedder — загрузка SentenceTransformer (bge-m3) один раз при старте
    try:
        await asyncio.to_thread(load_embedder)
        logger.info("Embedder warmup complete")
    except Exception as exc:
        logger.warning("Embedder warmup failed (non-fatal): %s", exc)

    logger.info("=== Warmup complete — ready to accept requests ===")
    yield
    logger.info("=== PDF Sidecar shutting down ===")


app = FastAPI(title="PDF Sidecar", version="5.0.0", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "pdf-sidecar",
        "reranker_loaded": str(reranker_is_loaded()),
        "embedder_loaded": str(embedder_is_loaded()),
    }


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

        progress_q: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        loop = asyncio.get_event_loop()
        t_start = time.monotonic()

        def _on_progress(page_num: int, total_pages: int, n_elements: int, has_table: bool):
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
                loop.call_soon_threadsafe(progress_q.put_nowait, None)

        parse_task = asyncio.ensure_future(
            asyncio.to_thread(_run_parse)
        )

        try:
            while True:
                try:
                    event = await asyncio.wait_for(progress_q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    yield "\n"
                    continue

                if event is None:
                    break

                yield json.dumps(event, ensure_ascii=False) + "\n"
        finally:
            await parse_task
            Path(tmp_path).unlink(missing_ok=True)

        if error_holder:
            parse_exc = error_holder[0]
            logger.error("Parsing failed for %s: %s", filename, parse_exc, exc_info=parse_exc)
            yield json.dumps(
                {"type": "error", "detail": str(parse_exc)},
                ensure_ascii=False,
            ) + "\n"
            return

        result = result_holder[0]

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


class RerankRequest(BaseModel):
    model: str = "BAAI/bge-reranker-v2-m3"
    query: str
    documents: list[str]


@app.post("/rerank")
async def rerank_documents(req: RerankRequest) -> JSONResponse:
    """
    Реранжирует документы релятивно запроса через CrossEncoder.

    Формат ответа совместим с openai_compatible /rerank провайдерами:
      {"results": [{"index": 0, "relevance_score": 0.92}, ...]}
    """
    if not reranker_is_loaded():
        raise HTTPException(status_code=503, detail="Reranker model is not loaded yet.")
    if not req.documents:
        return JSONResponse(content={"results": []})

    logger.info(
        "RERANK query='%s' documents=%d",
        req.query[:80], len(req.documents),
    )

    try:
        results = await asyncio.to_thread(rerank, req.query, req.documents)
    except Exception as exc:
        logger.error("Rerank failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Rerank error: {exc}") from exc

    logger.info(
        "RERANK done: top_score=%.3f",
        results[0]["relevance_score"] if results else 0.0,
    )
    return JSONResponse(content={"results": results})


class EmbedRequest(BaseModel):
    model: str = "BAAI/bge-m3"
    input: list[str] | str


@app.post("/embeddings")
async def embed_texts(req: EmbedRequest) -> JSONResponse:
    """
    Вычисляет эмбеддинги через SentenceTransformer (bge-m3).

    Принимает как строку (один текст), так и список строк —
    совместимо с OpenAI POST /embeddings:
      - вход: {"model": "...", "input": "text"} или {"input": ["t1", "t2"]}
      - выход: {"data": [{"index": 0, "embedding": [...]}, ...], "model": "..."}

    Такой формат позволяет rag-indexer и rag-backend использовать
    существующий OpenAICompatibleProvider без изменения кода:
    достаточно сменить provider=openai_compatible + base_url=http://pdf-sidecar:8765
    в настройках модели vault'a.

    Батч обрабатывается за ОДИН forward pass — главное преимущество
    перед Ollama (который делает N HTTP-запросов последовательно / с semaphore).
    """
    if not embedder_is_loaded():
        raise HTTPException(status_code=503, detail="Embedder model is not loaded yet.")

    texts = [req.input] if isinstance(req.input, str) else req.input
    if not texts:
        return JSONResponse(content={"data": [], "model": req.model})

    logger.info("EMBED texts=%d model=%s", len(texts), req.model)

    try:
        vectors = await asyncio.to_thread(_embed, texts)
    except Exception as exc:
        logger.error("Embed failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Embed error: {exc}") from exc

    logger.info("EMBED done: texts=%d dim=%d", len(vectors), len(vectors[0]) if vectors else 0)

    return JSONResponse(content={
        "data": [
            {"index": i, "embedding": v}
            for i, v in enumerate(vectors)
        ],
        "model": req.model,
    })


if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        log_config=None,
    )
