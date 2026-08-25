"""Unit-тесты для чистых хелперов pdf-sidecar/parser.py.

Реальный unstructured / partition_pdf НЕ вызывается — только pure-функции.
pypdfium2 мокается для тестов _count_pdf_pages.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from parser import (
    _fix_ocr_hyphenation,
    _html_table_to_md,
    _is_pdfium_error,
    _make_batches,
)


class TestFixOcrHyphenation:
    def test_simple_hyphen_with_newline(self):
        assert _fix_ocr_hyphenation("выва-\nливается") == "вываливается"

    def test_simple_hyphen_with_spaces_and_newline(self):
        assert _fix_ocr_hyphenation("едино-  \n  рог") == "единорог"

    def test_no_hyphen_unchanged(self):
        text = "обычный текст без переносов"
        assert _fix_ocr_hyphenation(text) == text

    def test_word_with_hyphen_inside_unchanged(self):
        # «что-то» не должно склеиться (нет \n после дефиса)
        assert _fix_ocr_hyphenation("что-то") == "что-то"


class TestIsPdfiumError:
    def test_pdfium_substring_detected(self):
        exc = Exception("PDFium: Data format error")
        assert _is_pdfium_error(exc) is True

    def test_data_format_error_substring_detected(self):
        exc = Exception("Something: Data format error here")
        assert _is_pdfium_error(exc) is True

    def test_other_exception_not_pdfium(self):
        exc = Exception("YOLO model failed to load")
        assert _is_pdfium_error(exc) is False

    def test_empty_message(self):
        assert _is_pdfium_error(Exception("")) is False


class TestMakeBatches:
    def test_small_doc_no_batching(self, monkeypatch):
        # total_pages < MIN_BATCH_SIZE → 1 батч
        monkeypatch.setattr("parser._MIN_BATCH_SIZE", 8)
        monkeypatch.setattr("parser._MAX_BATCH_SIZE", 30)
        monkeypatch.setattr("parser._MAX_WORKERS", 4)
        # 5 страниц, 4 workers → ceil(5/4)=2 → зажато в [8,30] = 8 → 1 батч [1-5]
        batches = _make_batches(5)
        assert batches == [(1, 5)]

    def test_medium_doc_multi_batch(self, monkeypatch):
        monkeypatch.setattr("parser._MIN_BATCH_SIZE", 8)
        monkeypatch.setattr("parser._MAX_BATCH_SIZE", 30)
        monkeypatch.setattr("parser._MAX_WORKERS", 4)
        # 50 страниц, 4 workers → ceil(50/4)=13 → батчи [1-13, 14-26, 27-39, 40-50]
        batches = _make_batches(50)
        assert batches == [(1, 13), (14, 26), (27, 39), (40, 50)]

    def test_large_doc_clamped_to_max(self, monkeypatch):
        monkeypatch.setattr("parser._MIN_BATCH_SIZE", 8)
        monkeypatch.setattr("parser._MAX_BATCH_SIZE", 30)
        monkeypatch.setattr("parser._MAX_WORKERS", 4)
        # 100 страниц, 4 workers → ceil(100/4)=25 → в диапазоне → 25 не превышает 30
        batches = _make_batches(100)
        assert len(batches) == 4
        assert all(end - start + 1 <= 30 for start, end in batches)

    def test_very_large_doc(self, monkeypatch):
        monkeypatch.setattr("parser._MIN_BATCH_SIZE", 8)
        monkeypatch.setattr("parser._MAX_BATCH_SIZE", 30)
        monkeypatch.setattr("parser._MAX_WORKERS", 4)
        # 200 страниц, 4 workers → ceil(200/4)=50 → зажато в 30 → 7 батчей
        batches = _make_batches(200)
        # Каждый батч ≤ 30 страниц
        for start, end in batches:
            assert end - start + 1 <= 30
        # Покрыты все страницы
        assert batches[0][0] == 1
        assert batches[-1][1] == 200

    def test_batches_are_contiguous(self, monkeypatch):
        monkeypatch.setattr("parser._MIN_BATCH_SIZE", 8)
        monkeypatch.setattr("parser._MAX_BATCH_SIZE", 30)
        monkeypatch.setattr("parser._MAX_WORKERS", 4)
        batches = _make_batches(80)
        from itertools import pairwise
        for prev, curr in pairwise(batches):
            assert curr[0] == prev[1] + 1


class TestExtractY0:
    def test_no_metadata_returns_zero(self):
        from parser import _extract_y0

        class FakeElement:
            metadata = None

        assert _extract_y0(FakeElement()) == 0.0

    def test_no_coordinates_returns_zero(self):
        from parser import _extract_y0

        class FakeMeta:
            coordinates = None

        class FakeElement:
            metadata = FakeMeta()

        assert _extract_y0(FakeElement()) == 0.0

    def test_with_coordinates_returns_min_y(self):
        from parser import _extract_y0

        class FakePoints:
            points = ((10.0, 5.0), (10.0, 50.0), (100.0, 50.0), (100.0, 5.0))

        class FakeCoords:
            coordinates = FakePoints()

        class FakeElement:
            metadata = FakeCoords()

        # min y = 5.0
        assert _extract_y0(FakeElement()) == 5.0


class TestHtmlTableToMd:
    def test_simple_table(self):
        html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
        result = _html_table_to_md(html)
        assert "| A | B |" in result
        assert "| --- | --- |" in result
        assert "| 1 | 2 |" in result

    def test_uneven_rows_padded_with_empty(self):
        html = "<table><tr><th>A</th><th>B</th><th>C</th></tr><tr><td>1</td></tr></table>"
        result = _html_table_to_md(html)
        # Не-хватающие ячейки должны быть заполнены пустыми строками
        lines = result.split("\n")
        assert lines[2] == "| 1 |  |  |"

    def test_invalid_html_falls_back_to_text(self):
        html = "просто текст без таблицы"
        result = _html_table_to_md(html)
        # Fallback: regex вырезает теги (их нет) → возвращает текст как есть
        assert result.strip() == "просто текст без таблицы"

    def test_html_with_inline_tags_inside_cells(self):
        html = "<table><tr><th><b>Bold</b></th></tr><tr><td><i>italic</i></td></tr></table>"
        result = _html_table_to_md(html)
        assert "| Bold |" in result
        assert "| italic |" in result


class TestCountPdfPages:
    def test_pypdfium2_success(self):
        from parser import _count_pdf_pages

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=42)
        mock_doc.close = MagicMock()

        mock_pdfium = MagicMock()
        mock_pdfium.PdfDocument.return_value = mock_doc

        with patch.dict("sys.modules", {"pypdfium2": mock_pdfium}):
            count = _count_pdf_pages("dummy.pdf")

        assert count == 42
        mock_doc.close.assert_called_once()

    def test_pypdfium2_fails_returns_zero(self):
        # Если обе стратегии упали — возвращаем 0
        from parser import _count_pdf_pages

        with patch.dict("sys.modules", {"pypdfium2": None}), \
             patch("builtins.__import__", side_effect=ImportError("nothing works")):
            count = _count_pdf_pages("dummy.pdf")
        assert count == 0