#!/usr/bin/env python3
"""Unit tests for pdf-extract.py helpers."""

import json
import os
import sys
import tempfile
from pathlib import Path

# Allow importing the script as a module.
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# Import the script module using a valid Python identifier. The source file
# contains a hyphen in its name, so we load it via importlib.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("pdf_extract", str(SCRIPT_DIR / "pdf-extract.py"))
_pdf_extract_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pdf_extract_mod)
pe = _pdf_extract_mod

import fitz
import pytest


def _make_text_pdf(tmp_path: Path, pages: list[list[str]]) -> Path:
    """Create a simple text-only PDF for testing native extraction."""
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    for page_lines in pages:
        page = doc.new_page()
        y = 50
        for line in page_lines:
            page.insert_text((50, y), line, fontsize=11)
            y += 20
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestParsePageRange:
    def test_single_page(self):
        assert pe.parse_page_range("3", total_pages=10) == [2]

    def test_range(self):
        assert pe.parse_page_range("2-5", total_pages=10) == [1, 2, 3, 4]

    def test_mixed(self):
        assert pe.parse_page_range("1,3,5-7", total_pages=10) == [0, 2, 4, 5, 6]

    def test_clipped_to_total(self):
        assert pe.parse_page_range("8-15", total_pages=10) == [7, 8, 9]

    def test_out_of_bounds_single(self):
        with pytest.raises(pe.PageRangeError):
            pe.parse_page_range("11", total_pages=10)

    def test_zero_rejected(self):
        with pytest.raises(pe.PageRangeError):
            pe.parse_page_range("0-3", total_pages=10)

    def test_inverted_range(self):
        with pytest.raises(pe.PageRangeError):
            pe.parse_page_range("5-2", total_pages=10)

    def test_non_numeric(self):
        with pytest.raises(pe.PageRangeError):
            pe.parse_page_range("foo", total_pages=10)

    def test_empty_pdf(self):
        with pytest.raises(pe.PageRangeError):
            pe.parse_page_range("1", total_pages=0)


class TestIsTruncated:
    def test_ellipsis(self):
        assert pe.is_truncated("hello world...") is True

    def test_mid_word(self):
        assert pe.is_truncated("hello worl") is True

    def test_sentence_end(self):
        assert pe.is_truncated("hello world.") is False

    def test_whitespace_only(self):
        assert pe.is_truncated("   ") is False


class TestFormatPageOutput:
    def test_text_mode(self):
        out = pe.format_page_output(5, "body", "text", "text")
        assert "--- Page 5 ---" in out
        assert "[p.5] body" in out

    def test_json_native_dict(self):
        record = {
            "page_text": "body",
            "tables": [["a", "b"]],
            "headings": ["H1"],
            "language": "en",
        }
        out = pe.format_page_output(2, record, "json", "text")
        parsed = json.loads(out)
        assert parsed["_citation"] == "[p.2]"
        assert parsed["page_text"] == "body"
        assert parsed["tables"] == [["a", "b"]]

    def test_json_vision_with_fences(self):
        raw = "```json\n{\"page_text\": \"x\"}\n```"
        out = pe.format_page_output(1, raw, "json", "image")
        parsed = json.loads(out)
        assert parsed["_citation"] == "[p.1]"
        assert parsed["page_text"] == "x"

    def test_json_vision_invalid_json(self):
        raw = "just plain text"
        out = pe.format_page_output(1, raw, "json", "image")
        parsed = json.loads(out)
        assert parsed["page_text"] == "just plain text"


class TestNativeExtraction:
    def test_basic_text_extraction(self, tmp_path: Path):
        pdf_path = _make_text_pdf(tmp_path, [
            ["Heading line", "First body line.", "Second body line."],
        ])
        doc = fitz.open(str(pdf_path))
        result = pe.extract_text_native(doc, 0)
        doc.close()
        assert "First body line." in result["page_text"]
        assert "Second body line." in result["page_text"]
        # With identical font sizes the heuristic cannot distinguish the
        # heading, and the fallback ALL-CAPS rule does not apply either.
        # We simply verify body text is preserved.

    def test_large_heading_detection(self, tmp_path: Path):
        pdf_path = tmp_path / "large_heading.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Title", fontsize=20)
        page.insert_text((50, 90), "Body", fontsize=11)
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        result = pe.extract_text_native(doc, 0)
        doc.close()
        assert "Title" in result["headings"]
        assert "Body" in result["page_text"]
        assert "Body" not in result["headings"]

    def test_paragraph_separation(self, tmp_path: Path):
        pdf_path = _make_text_pdf(tmp_path, [
            ["Line one.", "Line two.", "", "Line three.", "Line four."],
        ])
        doc = fitz.open(str(pdf_path))
        result = pe.extract_text_native(doc, 0)
        doc.close()
        # Body blocks should be separated by at least one blank line.
        assert "\n\n" in result["page_text"]

    def test_heading_deduplication(self, tmp_path: Path):
        pdf_path = tmp_path / "dedup.pdf"
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((50, 50), "Section A", fontsize=20)
        page.insert_text((50, 90), "body one", fontsize=11)
        page.insert_text((50, 120), "Section A", fontsize=20)
        page.insert_text((50, 150), "body two", fontsize=11)
        doc.save(str(pdf_path))
        doc.close()

        doc = fitz.open(str(pdf_path))
        result = pe.extract_text_native(doc, 0)
        doc.close()
        # Repeated exact heading should appear once.
        assert result["headings"].count("Section A") == 1


class TestLoadDonePages:
    def test_text_markers(self, tmp_path: Path):
        out = tmp_path / "out.txt"
        out.write_text("--- Page 1 ---\n[p.1] x\n--- Page 3 ---\n[p.3] y\n")
        assert pe.load_done_pages(out, "text") == {1, 3}

    def test_jsonl_markers(self, tmp_path: Path):
        out = tmp_path / "out.jsonl"
        out.write_text(
            json.dumps({"_citation": "[p.2]", "page_text": "x"}) + "\n"
            + json.dumps({"_citation": "[p.5]", "page_text": "y"}) + "\n"
        )
        assert pe.load_done_pages(out, "json") == {2, 5}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
