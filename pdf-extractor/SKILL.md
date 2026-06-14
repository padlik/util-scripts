---
name: pdf-to-json
description: Convert PDF documents (text-based or scanned/image-based) to structured JSON using the pdf-extract.py script. Use when the user asks to extract text from PDF, convert PDF to JSON, OCR a scanned PDF, extract data from PDF documents, or process PDF files for structured output. Triggers on phrases like "PDF to JSON", "extract PDF text", "OCR PDF", "scan PDF to JSON", "convert PDF document", or "structured PDF extraction".
---

# PDF to JSON Extractor

Convert any PDF — text-based or scanned/image-based — into structured JSON using `pdf-extract.py` with OpenAI-compatible vision models.

## Key Capabilities

| Feature | Description |
|---|---|
| **Auto-detect** | Automatically detects text-based vs image-based PDFs. Text PDFs use fast native PyMuPDF extraction; image/scanned PDFs use vision API. Override with `--force-vision` or `--force-text` |
| **Native extraction** | For text PDFs: font-size heading detection, native table extraction (`find_tables`), and language auto-detection |
| **OpenAI-compatible** | Works with OpenAI, Groq, Ollama, LM Studio, or any OpenAI-compatible endpoint |
| **Truncation detection** | Detects when vision model output is truncated and auto-retries with doubled token limit |
| **Chunking** | Process large PDFs (100+ pages) in configurable chunks to keep memory low |
| **Citation markers** | Every page output includes `[p.N]` for verifiability |
| **Resume** | `--resume` skips already-processed pages in interrupted runs. Page-range syntax errors are reported clearly. |
| **Vision prompt** | Custom extraction prompts supported via `--prompt` |
| **JSON output** | `--format json` returns structured JSON with `page_text`, `tables`, `headings`, `language` |

## Script Location

```
scripts/pdf-extract.py          # PEP 723 inline-script-metadata for uv run
scripts/.env                    # Optional: OPENAI_API_KEY, API_BASE, etc.
```

## Usage

### Quick start (auto-installs deps via PEP 723)

```bash
# Text-based PDF → native extraction (no API calls)
uv run scripts/pdf-extract.py report.pdf --format json -o report.json

# Scanned/image PDF → vision API (requires API key)
uv run scripts/pdf-extract.py scan.pdf --format json -o scan.json

# With custom OpenAI-compatible endpoint
uv run scripts/pdf-extract.py scan.pdf --format json \
  --api-base http://localhost:11434/v1 \
  --api-key ollama \
  --model gemma3:4b \
  -o scan.json
```

### Full option list

```bash
uv run scripts/pdf-extract.py input.pdf [options]

--pages       PAGE_RANGE    # e.g. "1-5", "3", "1,3,7" (default: all)
--dpi         INT           # Render DPI — 120 is fast, 200 is sharp (default: 150)
--quality     INT           # JPEG quality 1–95 (default: 75)
--prompt      TEXT          # Custom extraction prompt (overrides default)
--output      PATH          # Output file (default: <stem>_extracted.txt)
--format      FORMAT        # "text" or "json" (default: text)
--model       MODEL         # Vision model (default: gpt-4o)
--api-base    URL           # OpenAI-compatible API base (default: https://api.openai.com/v1)
--api-key     KEY           # API key (default: $OPENAI_API_KEY)
--max-tokens  INT           # Max tokens per vision API call (default: 8192)
--resume                    # Skip pages already present in output file
--force-vision              # Always use vision API (skip auto-detection)
--force-text                # Always use native extraction (skip auto-detection)
--chunk-size  INT           # Pages per chunk for large PDFs (default: 0 = no chunking)
```

## Examples

### Extract a scanned contract to JSON with Groq

```bash
uv run scripts/pdf-extract.py contract.pdf --format json \
  --api-base https://api.groq.com/openai/v1 \
  --api-key "$GROQ_API_KEY" \
  --model meta-llama/llama-4-scout-17b-16e-instruct \
  -o contract.json
```

### Extract only pages 10–50, chunked for memory safety

```bash
uv run scripts/pdf-extract.py big-report.pdf --pages 10-50 \
  --chunk-size 20 --format json -o big-report.json
```

### Resume an interrupted extraction

```bash
uv run scripts/pdf-extract.py thesis.pdf --format json --resume -o thesis.json
```

### Force vision mode on a text PDF (e.g. for table extraction)

```bash
uv run scripts/pdf-extract.py table-heavy.pdf --force-vision --format json -o tables.json
```

### Force native extraction on a PDF that auto-detects as image

```bash
uv run scripts/pdf-extract.py scan-with-ocr-layer.pdf --force-text --format json -o text.json
```

### Handle dense pages that may get truncated

```bash
uv run scripts/pdf-extract.py dense-report.pdf --format json --max-tokens 16384 -o report.json
```

## JSON Output Format

```json
{
  "_citation": "[p.15]",
  "page_text": "Full extracted text of this page...",
  "tables": [
    ["Header1", "Header2", "Header3"],
    ["Row1Col1", "Row1Col2", "Row1Col3"]
  ],
  "headings": ["Introduction", "Methodology"],
  "language": "en"
}
```

**Field notes:**
- **`tables`**: Extracted natively via PyMuPDF for text PDFs; extracted via vision for image PDFs.
- **`headings`**: Detected via font-size heuristics (native) or explicit prompt instructions (vision).
- **`language`**: ISO 639-1 code; auto-detected via `langdetect` for native extraction or vision model for scanned pages.
- **Table deduplication**: In vision mode, the model is instructed to insert `[TABLE N]` markers in `page_text` instead of repeating table markdown inline.

## Environment / .env

The script reads `OPENAI_API_KEY` from the environment or a `.env` file (via `python-dotenv`):

```bash
OPENAI_API_KEY=sk-xxx
# Optional:
OPENAI_API_BASE=http://localhost:11434/v1
```

## Notes

- **Auto-detection**: The script samples the first 5 pages. If ≥60% have extractable text, it uses native extraction (fast, no API). Otherwise it uses the vision API. Override with `--force-vision` or `--force-text`.
- **Native extraction quality**: For text PDFs, headings are detected via font-size heuristics and bold flags, tables via PyMuPDF `find_tables()`, and language via `langdetect`. Repeated headings across a page are deduplicated.
- **Truncation detection**: In vision mode, if the model response appears truncated, the script retries with double the token limit (up to 16,384 tokens). API calls use a 120-second timeout.
- **Weak machine friendly**: Pages are rendered one at a time and freed immediately. JPEG bytes are sent directly to the API without temp files.
- **Chunking**: For PDFs with 100+ pages, use `--chunk-size 20` to process in batches and keep memory pressure low.
- **Resume**: `--resume` scans the output file for existing `--- Page N ---` markers and skips those pages.
- **Citation preservation**: Every page output is prefixed with `[p.N]` so extracted content can be traced back to its source page.
