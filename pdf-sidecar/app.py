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
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from parser import parse_pdf_unstructured
from preprocessor import preprocess

logger = logging.getLogger(__name__)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PORT = int(os.getenv("PDF_SIDECAR_PORT", "8765"))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "logs" / "sidecar.log"),
    ],
)

app = FastAPI(title="PDF Sidecar", version="1.0.0")


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

    # Сохраняем во временный файл — unstructured работает с путём на диск
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

    # Применяем препроцессинг к тексту каждой страницы
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


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=PORT, log_level=LOG_LEVEL.lower())
