"""Unit-тесты для chunking_pipeline.

Покрывают:
  - parse_file: роутинг по extension (.md / .pdf / unknown)
  - build_chunk_records: word_start/word_end, пустые чанки пропускаются
  - assign_page_numbers_and_headers: проставляет page_number и headers
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from chunking_pipeline import (
    assign_page_numbers_and_headers,
    build_chunk_records,
    parse_file,
)


def test_parse_file_md_routes_to_parse_markdown():
    """Расширение .md → parse_markdown."""
    with patch("chunking_pipeline.parse_markdown", return_value={"text": "x"}) as md:
        result = parse_file("/tmp/x.md", ".md", {})
    md.assert_called_once_with("/tmp/x.md")
    assert result == {"text": "x"}


def test_parse_file_pdf_routes_to_parse_pdf():
    """Расширение .pdf → parse_pdf с правильными аргументами."""
    settings = {
        "sidecar_url": "http://sidecar:8081",
        "timeout_seconds": "180",  # может прийти строкой
        "fallback_to_pdfminer": "true",
    }
    with patch("chunking_pipeline.parse_pdf", return_value={"pages": []}) as pdf:
        result = parse_file("/tmp/x.pdf", ".pdf", settings)
    pdf.assert_called_once_with(
        "/tmp/x.pdf",
        sidecar_url="http://sidecar:8081",
        timeout_seconds=180.0,
        fallback_to_pdfminer=True,
    )
    assert result == {"pages": []}


def test_parse_file_pdf_defaults():
    """Минимальные settings (только sidecar_url) — дефолты timeout=180, fallback=True."""
    with patch("chunking_pipeline.parse_pdf", return_value={}) as pdf:
        parse_file("/tmp/x.pdf", ".pdf", {"sidecar_url": "http://x"})
    _args, kwargs = pdf.call_args
    assert kwargs["timeout_seconds"] == 180.0
    assert kwargs["fallback_to_pdfminer"] is True


def test_parse_file_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported file extension"):
        parse_file("/tmp/x.txt", ".txt", {})


def test_build_chunk_records_assigns_word_offsets():
    raw = ["alpha bravo", "charlie delta echo"]
    records = build_chunk_records(raw, document_id="d1", vault_id="v1", base_metadata={})
    assert len(records) == 2
    assert records[0].metadata["word_start"] == 0
    assert records[0].metadata["word_end"] == 2
    assert records[1].metadata["word_start"] == 2
    assert records[1].metadata["word_end"] == 5


def test_build_chunk_records_skips_empty():
    raw = ["alpha bravo", "  ", "charlie"]
    records = build_chunk_records(raw, "d1", "v1", {})
    assert len(records) == 2
    assert records[0].text == "alpha bravo"
    assert records[1].text == "charlie"


def test_build_chunk_records_inherits_metadata():
    raw = ["x"]
    records = build_chunk_records(raw, "d1", "v1", base_metadata={"vault": "v1", "extra": "y"})
    assert records[0].metadata["vault"] == "v1"
    assert records[0].metadata["extra"] == "y"
    assert records[0].metadata["word_start"] == 0


def test_build_chunk_records_assigns_unique_chunk_ids():
    records = build_chunk_records(["a", "b", "c"], "d1", "v1", {})
    ids = {r.chunk_id for r in records}
    assert len(ids) == 3  # все уникальные
    for r in records:
        assert r.chunk_id.startswith("chk_")


def test_assign_page_numbers_and_headers_sets_page():
    chunks = [
        type("C", (), {"metadata": {"word_start": 0}})(),
        type("C", (), {"metadata": {"word_start": 40}})(),  # ~240 chars, на page1
    ]
    page_offsets = [(0, 1), (300, 2)]  # page1: 0-300, page2: 300-...
    placed_headings: list[dict] = []
    assign_page_numbers_and_headers(chunks, page_offsets, placed_headings)
    assert chunks[0].metadata["page_number"] == 1
    assert chunks[1].metadata["page_number"] == 1


def test_assign_page_numbers_and_headers_advances_page():
    chunks = [
        type("C", (), {"metadata": {"word_start": 100}})(),  # ~600 chars
    ]
    page_offsets = [(0, 1), (500, 2)]
    assign_page_numbers_and_headers(chunks, page_offsets, [])
    assert chunks[0].metadata["page_number"] == 2


def test_assign_page_numbers_and_headers_empty_page_offsets():
    chunks = [type("C", (), {"metadata": {"word_start": 0}})()]
    assign_page_numbers_and_headers(chunks, [], [])
    assert "page_number" not in chunks[0].metadata
