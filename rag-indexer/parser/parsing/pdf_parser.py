from __future__ import annotations

import json
import logging
from io import StringIO
from pathlib import Path
from typing import Any

import httpx
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage


logger = logging.getLogger(__name__)


def parse_pdf(
    file_path: str,
    sidecar_url: str,
    timeout_seconds: float = 180.0,
    fallback_to_pdfminer: bool = True,
) -> dict[str, Any]:
    try:
        result = _parse_via_sidecar_stream(file_path, sidecar_url, timeout_seconds)
        if not _has_content(result):
            logger.warning("PDF sidecar returned empty result for %s", file_path)
        return result
    except Exception as exc:
        if not fallback_to_pdfminer or not _is_sidecar_failure(exc):
            raise
        logger.warning("PDF sidecar unavailable, falling back to pdfminer for %s", file_path, exc_info=True)
        return _parse_with_pdfminer(file_path)


def _parse_via_sidecar_stream(file_path: str, sidecar_url: str, timeout_seconds: float) -> dict[str, Any]:
    if not sidecar_url:
        raise RuntimeError("pdf_sidecar.url is not configured")

    pdf_bytes = Path(file_path).read_bytes()
    filename = Path(file_path).name
    timeout = httpx.Timeout(
        connect=min(timeout_seconds, 30.0),
        read=timeout_seconds,
        write=min(timeout_seconds, 60.0),
        pool=10.0,
    )

    logger.info("Sending '%s' (%d bytes) to sidecar %s/parse/stream", filename, len(pdf_bytes), sidecar_url)

    with httpx.Client(timeout=timeout) as client:
        with client.stream(
            "POST",
            f"{sidecar_url.rstrip('/')}/parse/stream",
            files={"file": (filename, pdf_bytes, "application/pdf")},
        ) as response:
            response.raise_for_status()
            result: dict[str, Any] | None = None
            for line in response.iter_lines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Sidecar stream returned invalid JSON line: %r", line[:200])
                    continue
                event_type = event.get("type")
                if event_type == "progress":
                    logger.info(
                        "[sidecar] Page %s/%s, elements=%s, elapsed=%s",
                        event.get("page", "?"),
                        event.get("total", "?"),
                        event.get("elements", 0),
                        event.get("elapsed", 0),
                    )
                elif event_type == "result":
                    result = event
                    result.pop("type", None)
                elif event_type == "error":
                    raise RuntimeError(f"Sidecar returned error: {event.get('detail', 'unknown error')}")
            if result is None:
                raise RuntimeError("Sidecar stream ended without result event")
            return result


def _parse_with_pdfminer(file_path: str) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    with open(file_path, "rb") as fh:
        for index, page in enumerate(PDFPage.get_pages(fh), start=1):
            output = StringIO()
            resource_manager = PDFResourceManager()
            converter = TextConverter(resource_manager, output, laparams=LAParams())
            interpreter = PDFPageInterpreter(resource_manager, converter)
            try:
                interpreter.process_page(page)
                pages.append({"page_number": index, "text": output.getvalue()})
            finally:
                converter.close()
                output.close()
    return {
        "pages": pages,
        "headings": [],
        "metadata": {"source": file_path, "parser": "pdfminer"},
        "page_count": len(pages),
    }


def _is_sidecar_failure(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException, httpx.NetworkError, httpx.RequestError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, RuntimeError)


def _has_content(result: dict[str, Any]) -> bool:
    return any(page.get("text", "").strip() for page in result.get("pages", []))
