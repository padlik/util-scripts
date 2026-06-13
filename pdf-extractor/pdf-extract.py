#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "PyMuPDF",
#   "openai",
#   "python-dotenv",
#   "langdetect",
# ]
# ///
"""
pdf_vision_extract.py
─────────────────────
Extract text/data from PDFs — auto-detects text-based vs image-based,
uses native PyMuPDF extraction for text PDFs (fast, no API) and
any OpenAI-compatible vision API for scanned/image PDFs.

Designed for weak machines (≤8 GB RAM):
  • Pages are rendered one at a time — never held in memory together
  • PyMuPDF renders directly to JPEG bytes (no temp files)
  • Each page is sent to the API, result written to disk, then freed
  • DPI and JPEG quality are tunable to trade speed for accuracy
  • Supports resuming interrupted runs (skips pages already extracted)
  • Chunking for large PDFs: process chapter-by-chapter (--chunk-size)
  • Citation preservation: every page output is prefixed with [p.N]

Usage
------
  uv run pdf_vision_extract.py input.pdf [options]
  python pdf_vision_extract.py input.pdf [options]

Options
-------
  --pages       PAGE RANGE   e.g. "1-5", "3", "1,3,7" (default: all)
  --dpi         INT          Render DPI — 120 is fast, 200 is sharp (default: 150)
  --quality     INT          JPEG quality 1–95; lower = smaller payload (default: 75)
  --prompt      TEXT         Custom extraction prompt
  --output      PATH         Output file (default: <input_stem>_extracted.txt|.jsonl)
  --format      FORMAT       "text" or "json" (default: text)
  --model       MODEL        Vision model (default: gpt-4o)
  --api-base    URL          OpenAI-compatible API base URL (default: https://api.openai.com/v1)
  --api-key     KEY          API key (default: $OPENAI_API_KEY)
  --resume                  Skip pages whose output already exists in output file
  --force-vision            Always use vision API (skip auto-detection)
  --chunk-size  INT          Pages per chunk for large PDFs (default: 0 = no chunking)

Requirements
------------
  uv run pdf_vision_extract.py ...   (auto-installs deps via PEP 723 header)
  Or: pip install PyMuPDF openai python-dotenv
  Environment: OPENAI_API_KEY (or --api-key) must be set for image-based PDFs
"""

from __future__ import annotations

import argparse
import base64
import gc
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Generator

# ── Third-party ──────────────────────────────────────────────────────────────
try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("❌  PyMuPDF not found. Run: pip install PyMuPDF")

try:
    import openai
except ImportError:
    sys.exit("❌  openai not found. Run: pip install openai")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_DPI = 150          # safe balance: readable + low RAM
DEFAULT_QUALITY = 75       # JPEG quality — 75 keeps payload small
DEFAULT_MODEL = "gpt-4o"
DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_MAX_TOKENS = 8192  # increased to avoid truncation on dense pages
MAX_RETRIES = 3
RETRY_DELAY = 5            # seconds between API retries
AUTO_DETECT_SAMPLE = 5     # pages to sample for text/image detection
AUTO_DETECT_THRESHOLD = 0.6  # fraction of sampled pages with text → text-based
MIN_TEXT_CHARS = 50        # minimum chars to consider a page as having text

DEFAULT_PROMPT = (
    "Extract ALL text from this scanned document page exactly as it appears. "
    "Preserve paragraph structure, lists, tables (use plain-text alignment), "
    "and headings. If there are numbers, dates, or structured data, keep their "
    "original formatting. Output only the extracted content — no commentary."
)

JSON_PROMPT = (
    "You are a precise document extraction engine. Extract ALL content from this scanned document page. "
    "Do NOT summarize. Do NOT omit any text, tables, or headings.\n\n"
    "Return ONLY a valid JSON object with exactly these keys:\n"
    '  "page_text": "full extracted text as a single string. IMPORTANT: When tables are present '
    'in the tables array, do NOT repeat the table markdown/text inline in page_text — instead insert '
    'a marker like [TABLE 1] and remove the duplicate table text from page_text."\n'
    '  "tables": "list of tables found on the page, each as a list of row-lists (strings). '
    'Preserve merged cells by repeating the value."\n'
    '  "headings": "list of ALL headings and subheadings found on the page, in order, as strings. '
    'Include section titles, sub-section titles, and any visually prominent text blocks that act as headers."\n'
    '  "language": "detected language of the page content as an ISO 639-1 code (e.g., en, pl, de, fr)"\n'
    "\n"
    "Rules:\n"
    "- Output ONLY valid JSON — no markdown fences, no commentary.\n"
    "- Do not truncate; if the page is long, include everything.\n"
    "- If there are no tables, return an empty list [].\n"
    "- If there are no headings, return an empty list []."
)


# ─────────────────────────────────────────────────────────────────────────────
# Page range parsing
# ─────────────────────────────────────────────────────────────────────────────

def parse_page_range(spec: str, total_pages: int) -> list[int]:
    """
    Parse a page range spec into a sorted list of 0-based page indices.
    Spec examples: "1-5"  "3"  "1,3,7"  "2-4,8,10-12"
    Input is 1-based (user-facing); output is 0-based (fitz).
    """
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = max(1, int(start_s))
            end = min(total_pages, int(end_s))
            pages.update(range(start - 1, end))
        else:
            idx = int(part) - 1
            if 0 <= idx < total_pages:
                pages.add(idx)
    return sorted(pages)


# ─────────────────────────────────────────────────────────────────────────────
# PDF type auto-detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_pdf_type(doc: fitz.Document) -> str:
    """
    Sample up to AUTO_DETECT_SAMPLE pages and check if they contain
    extractable text. Returns "text" if most pages have text,
    "image" otherwise.
    """
    sample_count = min(AUTO_DETECT_SAMPLE, len(doc))
    text_pages = 0

    for i in range(sample_count):
        page = doc.load_page(i)
        text = page.get_text("text").strip()
        if len(text) >= MIN_TEXT_CHARS:
            text_pages += 1
        page = None

    ratio = text_pages / sample_count if sample_count > 0 else 0
    if ratio >= AUTO_DETECT_THRESHOLD:
        return "text"
    return "image"


# ─────────────────────────────────────────────────────────────────────────────
# Native text extraction (for text-based PDFs)
# ─────────────────────────────────────────────────────────────────────────────

def detect_language(text: str) -> str:
    """Detect language of the text; return ISO 639-1 code or empty string."""
    try:
        from langdetect import detect
        return detect(text[:2000]) if text else ""
    except Exception:
        return ""


def extract_text_native(doc: fitz.Document, page_idx: int) -> dict:
    """
    Extract text natively from a single page using PyMuPDF structured mode.
    Returns a dict with page_text, tables, headings, language.
    """
    page = doc.load_page(page_idx)

    # ── Tables (PyMuPDF native find_tables) ──────────────────────────
    tables: list[list[list[str]]] = []
    try:
        tab_list = page.find_tables()
        for tab in tab_list.tables:
            rows = []
            for row in tab.extract():
                # Replace None with empty string
                rows.append([str(cell) if cell is not None else "" for cell in row])
            if rows:
                tables.append(rows)
    except Exception:
        pass

    # ── Text with dict mode for heading detection ────────────────────
    blocks = page.get_text("dict")["blocks"]

    headings: list[str] = []
    body_lines: list[str] = []

    # Determine heading threshold from font sizes on this page
    sizes = []
    for block in blocks:
        if "lines" in block:
            for line in block["lines"]:
                for span in line["spans"]:
                    sizes.append(span["size"])

    if sizes:
        median_size = sorted(sizes)[len(sizes) // 2]
        heading_threshold = median_size + 1.5  # 1.5pt above median
    else:
        heading_threshold = 12  # fallback

    for block in blocks:
        if "lines" not in block:
            continue
        block_text = ""
        for line in block["lines"]:
            line_text = "".join(span["text"] for span in line["spans"]).strip()
            if not line_text:
                continue
            max_size = max((span["size"] for span in line["spans"]), default=0)
            is_bold = any("Bold" in span["font"] or span["flags"] & 2**4 for span in line["spans"])

            if max_size >= heading_threshold or is_bold:
                # Likely heading
                if line_text not in headings:
                    headings.append(line_text)
            else:
                body_lines.append(line_text)

        if body_lines and block_text:
            body_lines.append("")

    # Fallback: if no headings found, try a simple heuristic on raw text
    raw_text = page.get_text("text").strip()
    if not headings:
        for line in raw_text.splitlines():
            stripped = line.strip()
            if stripped and stripped.isupper() and len(stripped) < 100:
                headings.append(stripped)

    # Build page_text: if we used dict mode, rejoin body lines; otherwise raw
    page_text = "\n".join(body_lines) if body_lines else raw_text

    # Clean up repeated whitespace
    page_text = re.sub(r'\n{3,}', '\n\n', page_text)

    # Language detection
    language = detect_language(page_text) if page_text else ""

    page = None
    return {
        "page_text": page_text,
        "tables": tables,
        "headings": headings,
        "language": language,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Rendering — one page at a time, direct to JPEG bytes (no temp files)
# ─────────────────────────────────────────────────────────────────────────────

def render_page_to_jpeg(doc: fitz.Document, page_idx: int,
                         dpi: int, quality: int) -> bytes:
    """
    Render a single PDF page to JPEG bytes.
    Uses PyMuPDF's native JPEG encoder — no PIL/Pillow needed.
    Memory is freed immediately after the caller processes the bytes.
    """
    page = doc.load_page(page_idx)
    mat = fitz.Matrix(dpi / 72, dpi / 72)   # scale factor from 72 dpi base
    pix = page.get_pixmap(matrix=mat, alpha=False)

    # Convert to RGB if needed (e.g. CMYK PDFs)
    if pix.colorspace and pix.colorspace.name not in ("DeviceRGB",):
        pix = fitz.Pixmap(fitz.csRGB, pix)

    jpeg_bytes = pix.tobytes(output="jpeg", jpg_quality=quality)

    # Explicit cleanup — critical on low-RAM systems
    pix = None
    page = None
    gc.collect()

    return jpeg_bytes


# ─────────────────────────────────────────────────────────────────────────────
# Vision query — single page, with retry logic and truncation detection
# ─────────────────────────────────────────────────────────────────────────────

def is_truncated(text: str) -> bool:
    """Heuristic: check if the vision model likely truncated its output."""
    t = text.strip()
    # Ends with ellipsis, mid-word, or mid-sentence
    if t.endswith("..."):
        return True
    if t and t[-1].isalpha() and not t.endswith((".", "!", "?", "\"", "'", ")", "]")):
        return True
    return False

def vision_query(client: openai.OpenAI,
                 jpeg_bytes: bytes,
                 prompt: str,
                 model: str,
                 page_num: int,
                 max_tokens: int) -> str:
    """
    Send one JPEG image to an OpenAI-compatible vision API and return
    the extracted text. Retries up to MAX_RETRIES times on transient errors.
    Detects truncation and retries with higher max_tokens once.
    """
    b64 = base64.standard_b64encode(jpeg_bytes).decode("utf-8")
    payload_kb = len(b64) / 1024
    print(f"    → payload: {payload_kb:.0f} KB", end="", flush=True)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{b64}",
                                    "detail": "auto",
                                },
                            },
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
            )
            result = response.choices[0].message.content

            # Truncation detection
            if is_truncated(result):
                if max_tokens < 16384:
                    print(f"  ⚠ truncation detected → retrying with {max_tokens * 2} tokens")
                    return vision_query(
                        client, jpeg_bytes, prompt, model, page_num,
                        max_tokens=max_tokens * 2
                    )
                else:
                    print(f"  ⚠ truncation detected (max tokens reached)")
            else:
                print(f"  ✓ ({len(result)} chars)")
            return result

        except openai.RateLimitError:
            wait = RETRY_DELAY * attempt
            print(f"\n    ⚠  Rate limited — waiting {wait}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)

        except openai.APIStatusError as e:
            if attempt == MAX_RETRIES:
                print(f"\n    ✗  API error on page {page_num}: {e}")
                return f"[ERROR page {page_num}: {e}]"
            time.sleep(RETRY_DELAY)

        except openai.APIConnectionError as e:
            if attempt == MAX_RETRIES:
                print(f"\n    ✗  Connection error on page {page_num}: {e}")
                return f"[ERROR page {page_num}: {e}]"
            time.sleep(RETRY_DELAY)

        except Exception as e:
            print(f"\n    ✗  Unexpected error on page {page_num}: {e}")
            return f"[ERROR page {page_num}: {e}]"

    return f"[FAILED page {page_num}: max retries exceeded]"


# ─────────────────────────────────────────────────────────────────────────────
# Resume support — read already-processed page numbers from output file
# ─────────────────────────────────────────────────────────────────────────────

def load_done_pages(output_path: Path, fmt: str) -> set[int]:
    """Return set of 1-based page numbers already present in the output file."""
    done: set[int] = set()
    if not output_path.exists():
        return done
    text = output_path.read_text(encoding="utf-8", errors="replace")

    if fmt == "json":
        # JSONL: scan for "_citation": "[p.N]"
        pattern = re.compile(r'"_citation"\s*:\s*"\[p\.(\d+)\]"')
        for m in pattern.finditer(text):
            done.add(int(m.group(1)))
    else:
        # Text: scan for "--- Page N ---" or "## Page N"
        pattern = re.compile(r"^(?:---|##)\s*Page\s+(\d+)", re.IGNORECASE | re.MULTILINE)
        for m in pattern.finditer(text):
            done.add(int(m.group(1)))
    return done


# ─────────────────────────────────────────────────────────────────────────────
# Citation marker + JSON formatting
# ─────────────────────────────────────────────────────────────────────────────

def format_page_output(page_num: int, content: str | dict, fmt: str, pdf_type: str) -> str:
    """
    Wrap page content with a citation marker [p.N].
    When fmt == "json", emit one compact JSON Lines row.
    When fmt == "text", emit plain text with a page separator.
    content can be a string (vision) or dict (native extraction with tables/headings/language).
    """
    if fmt == "json":
        record: dict = {}
        if isinstance(content, dict):
            # Native extraction already returned a structured dict
            record = dict(content)
            record["_citation"] = f"[p.{page_num}]"
        elif pdf_type == "text":
            # Native extraction returned plain text (fallback)
            record = {
                "_citation": f"[p.{page_num}]",
                "page_text": content,
                "tables": [],
                "headings": [],
                "language": "",
            }
        else:
            # Vision extraction returned raw text (may be JSON or plain text)
            # Try to parse as JSON first, then fall back
            try:
                clean = content.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
                parsed = json.loads(clean)
                parsed["_citation"] = f"[p.{page_num}]"
                record = parsed
            except (json.JSONDecodeError, TypeError):
                record = {
                    "_citation": f"[p.{page_num}]",
                    "page_text": content,
                    "tables": [],
                    "headings": [],
                    "language": "",
                }
        return json.dumps(record, ensure_ascii=False) + "\n"
    else:
        # Plain text mode
        if isinstance(content, dict):
            text = content.get("page_text", "")
        else:
            text = content
        return f"\n--- Page {page_num} ---\n[p.{page_num}] {text}\n"


# ─────────────────────────────────────────────────────────────────────────────
# Chunked page iterator
# ─────────────────────────────────────────────────────────────────────────────

def chunked_pages(page_indices: list[int], chunk_size: int) -> Generator[list[int], None, None]:
    """Yield page index lists in chunks of chunk_size. chunk_size=0 means no chunking."""
    if chunk_size <= 0:
        yield page_indices
        return
    for i in range(0, len(page_indices), chunk_size):
        yield page_indices[i:i + chunk_size]


# ─────────────────────────────────────────────────────────────────────────────
# Main extraction loop
# ─────────────────────────────────────────────────────────────────────────────

def extract_pdf(
    pdf_path: Path,
    output_path: Path,
    pages_spec: str | None,
    dpi: int,
    quality: int,
    prompt: str,
    model: str,
    fmt: str,
    resume: bool,
    force_vision: bool,
    chunk_size: int,
    api_base: str,
    api_key: str,
    max_tokens: int,
) -> None:

    print(f"\n📄 Opening: {pdf_path.name}")
    doc = fitz.open(str(pdf_path))
    total = len(doc)
    print(f"   {total} pages  |  DPI={dpi}  JPEG quality={quality}  model={model}")

    # ── Auto-detect PDF type ──────────────────────────────────────────────────
    if force_vision:
        pdf_type = "image"
        print("   🔍  PDF type: image (forced via --force-vision)")
    else:
        pdf_type = detect_pdf_type(doc)
        label = "text-based (native extraction)" if pdf_type == "text" else "image-based (vision API)"
        print(f"   🔍  PDF type: {label}")

    # ── API client setup ───────────────────────────────────────────────────────
    client = None
    if pdf_type == "image":
        if not api_key:
            sys.exit("❌  No API key. Set OPENAI_API_KEY env var or use --api-key.")
        client = openai.OpenAI(base_url=api_base, api_key=api_key)
        print(f"   🔗  API base: {api_base}")

    # ── Resolve page list ─────────────────────────────────────────────────────
    if pages_spec:
        page_indices = parse_page_range(pages_spec, total)
    else:
        page_indices = list(range(total))

    # ── Resume: skip already-done pages ────────────────────────────────────────
    done_pages: set[int] = set()
    if resume:
        done_pages = load_done_pages(output_path, fmt)
        skipped = [i + 1 for i in page_indices if (i + 1) in done_pages]
        if skipped:
            print(f"   ↩  Resuming — skipping {len(skipped)} already-done pages: {skipped[:10]}{'…' if len(skipped) > 10 else ''}")
        page_indices = [i for i in page_indices if (i + 1) not in done_pages]

    if not page_indices:
        print("   ✅  All requested pages already extracted. Nothing to do.")
        doc.close()
        return

    # ── Chunking info ──────────────────────────────────────────────────────────
    if chunk_size > 0 and len(page_indices) > chunk_size:
        num_chunks = (len(page_indices) + chunk_size - 1) // chunk_size
        print(f"   📦  Chunking: {num_chunks} chunk(s) of ≤{chunk_size} pages each")
    else:
        chunk_size = 0  # disable chunking for small sets

    print(f"   Processing {len(page_indices)} page(s) → {output_path.name}\n")

    mode = "a" if (resume and output_path.exists()) else "w"
    with open(output_path, mode, encoding="utf-8") as out:

        if mode == "w":
            # In JSON mode we skip text headers — the file is JSONL.
            if fmt != "json":
                out.write(f"# Extracted: {pdf_path.name}\n")
                out.write(f"# PDF type: {pdf_type}  |  Model: {model}  |  DPI: {dpi}  |  JPEG quality: {quality}\n")
                out.write(f"# API base: {api_base}\n")
                out.write(f"# Format: {fmt}\n\n")

        for chunk in chunked_pages(page_indices, chunk_size):
            chunk_label = ""
            if chunk_size > 0:
                chunk_start = chunk[0] + 1
                chunk_end = chunk[-1] + 1
                chunk_label = f"  [chunk {chunk_start}-{chunk_end}]"
                print(f"  ── Chunk pages {chunk_start}–{chunk_end} ──")

            for page_idx in chunk:
                page_num = page_idx + 1
                print(f"  Page {page_num:>4}/{total}{chunk_label}", end="  ", flush=True)

                if pdf_type == "text":
                    # ── Native text extraction ─────────────────────────────────
                    try:
                        result = extract_text_native(doc, page_idx)
                        char_count = len(result.get("page_text", ""))
                        print(f"  ✓ ({char_count} chars)")
                    except Exception as e:
                        print(f"  ✗ extract error: {e}")
                        result = f"[EXTRACT ERROR: {e}]"

                else:
                    # ── Render + Vision query ──────────────────────────────────
                    try:
                        jpeg_bytes = render_page_to_jpeg(doc, page_idx, dpi, quality)
                    except Exception as e:
                        print(f"  ✗ render error: {e}")
                        out.write(format_page_output(page_num, f"[RENDER ERROR: {e}]", fmt, pdf_type))
                        out.flush()
                        continue

                    result = vision_query(client, jpeg_bytes, prompt, model, page_num, max_tokens=max_tokens)
                    jpeg_bytes = None

                # ── Write result with citation marker ──────────────────────────
                out.write(format_page_output(page_num, result, fmt, pdf_type))
                out.flush()

                # ── Free memory ────────────────────────────────────────────────
                result = None
                gc.collect()

            # ── End-of-chunk flush and GC ──────────────────────────────────────
            if chunk_size > 0:
                out.flush()
                gc.collect()
                print()

    doc.close()
    print(f"\n✅  Done. Output written to: {output_path}")
    size_kb = output_path.stat().st_size / 1024
    print(f"   Output size: {size_kb:.1f} KB")


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Extract text from PDFs — auto-detects text vs image, uses OpenAI-compatible vision API for scans",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("pdf", help="Path to input PDF file")
    p.add_argument("--pages",   default=None,
                   help='Page range, e.g. "1-5", "3", "1,3,7" (default: all)')
    p.add_argument("--dpi",     type=int, default=DEFAULT_DPI,
                   help=f"Render DPI (default: {DEFAULT_DPI}). Lower = faster + less RAM")
    p.add_argument("--quality", type=int, default=DEFAULT_QUALITY,
                   help=f"JPEG quality 1-95 (default: {DEFAULT_QUALITY}). Lower = smaller payload")
    p.add_argument("--prompt",  default=None,
                   help="Custom extraction prompt (overrides default)")
    p.add_argument("--output",  default=None,
                   help="Output file path (default: <stem>_extracted.txt or .jsonl)")
    p.add_argument("--format",  choices=["text", "json"], default="text",
                   help='Output format: "text" (default) or "json"')
    p.add_argument("--model",   default=DEFAULT_MODEL,
                   help=f"Vision model (default: {DEFAULT_MODEL})")
    p.add_argument("--api-base", default=DEFAULT_API_BASE,
                   help=f"OpenAI-compatible API base URL (default: {DEFAULT_API_BASE})")
    p.add_argument("--api-key",  default=None,
                   help="API key (default: $OPENAI_API_KEY)")
    p.add_argument("--resume",  action="store_true",
                   help="Skip pages already present in output file")
    p.add_argument("--force-vision", action="store_true",
                   help="Always use vision API even for text-based PDFs")
    p.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                   help=f"Max tokens per vision API call (default: {DEFAULT_MAX_TOKENS})")
    p.add_argument("--chunk-size", type=int, default=0,
                   help="Pages per chunk for large PDFs (default: 0 = no chunking)")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        sys.exit(f"❌  File not found: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        print(f"⚠  Warning: file does not have .pdf extension ({pdf_path.suffix})")

    # Output path
    if args.output:
        output_path = Path(args.output).expanduser().resolve()
    else:
        suffix = "_extracted.jsonl" if args.format == "json" else "_extracted.txt"
        output_path = pdf_path.with_name(pdf_path.stem + suffix)

    # Prompt selection
    if args.prompt:
        prompt = args.prompt
    elif args.format == "json":
        prompt = JSON_PROMPT
    else:
        prompt = DEFAULT_PROMPT

    # API key: CLI arg takes precedence, then env var
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
    # API base: CLI arg takes precedence, then env var, then default
    api_base = args.api_base or os.environ.get("OPENAI_API_BASE", DEFAULT_API_BASE)

    extract_pdf(
        pdf_path=pdf_path,
        output_path=output_path,
        pages_spec=args.pages,
        dpi=args.dpi,
        quality=args.quality,
        prompt=prompt,
        model=args.model,
        fmt=args.format,
        resume=args.resume,
        force_vision=args.force_vision,
        chunk_size=args.chunk_size,
        api_base=api_base,
        api_key=api_key,
        max_tokens=args.max_tokens,
    )


if __name__ == "__main__":
    main()
