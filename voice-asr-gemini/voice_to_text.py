# /// script
# dependencies = [
#   "google-genai",
#   "python-dotenv",
# ]
# requires-python = ">=3.10"
# ///
"""
Transcribe audio files using the Google Gemini API.

Supports:
- Local audio file upload via the Gemini Files API
- Direct YouTube URL input (hidden --youtube flag)
- Optional timestamps, speaker diarization, translation, emotion detection, and summary

Usage:
    uv run voice_to_text.py audio.mp3
    uv run voice_to_text.py audio.mp3 --timestamps --diarize --emotion
    uv run voice_to_text.py "https://www.youtube.com/watch?v=..." --youtube --timestamps --diarize
    uv run voice_to_text.py audio.mp3 --translate es --output transcript.json
    uv run voice_to_text.py audio.mp3 --summary

Free tier notes (Google AI Studio):
- No credit card required; limits are per project.
- Gemini 3.1 Flash Lite free tier is typically around 10 RPM / 250K TPM / ~1,500 RPD.
- Audio tokenization: ~32 tokens per second of audio.
- Maximum audio length per request: 9.5 hours.
- Supported audio formats: WAV, MP3, AIFF, AAC, OGG Vorbis, FLAC.
- Free tier inputs/outputs may be used by Google to improve models.
  Avoid sending sensitive/PII data through the free tier.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types
from google.genai import errors as genai_errors

DEFAULT_MODEL = "gemini-3.1-flash-lite"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

SUPPORTED_AUDIO_TYPES = {
    "audio/wav",
    "audio/mp3",
    "audio/mpeg",
    "audio/aiff",
    "audio/aac",
    "audio/ogg",
    "audio/flac",
}

EMOTIONS = ["neutral", "happy", "sad", "angry", "fearful", "surprised", "disgusted"]

YOUTUBE_PATTERNS = [
    re.compile(r"^https?://(www\.)?youtube\.com/watch\?v="),
    re.compile(r"^https?://(www\.)?youtube\.com/embed/"),
    re.compile(r"^https?://youtu\.be/"),
    re.compile(r"^https?://(www\.)?youtube\.com/shorts/"),
]


def looks_like_youtube(url: str) -> bool:
    return any(pattern.match(url) for pattern in YOUTUBE_PATTERNS)


def mime_type_from_path(path: str) -> str | None:
    """Best-effort MIME type detection based on file extension."""
    ext = Path(path).suffix.lower()
    mapping = {
        ".wav": "audio/wav",
        ".mp3": "audio/mp3",
        ".mpeg": "audio/mpeg",
        ".mpg": "audio/mpeg",
        ".aiff": "audio/aiff",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
    }
    return mapping.get(ext)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe audio with Google Gemini API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run voice_to_text.py audio.mp3
  uv run voice_to_text.py audio.mp3 --timestamps --diarize
  uv run voice_to_text.py audio.mp3 --translate es --emotion
  uv run voice_to_text.py audio.mp3 --summary
  uv run voice_to_text.py "https://www.youtube.com/watch?v=..." --youtube --timestamps --diarize

Get an API key: https://aistudio.google.com/apikey
Set GEMINI_API_KEY as an environment variable or in a .env file.
        """,
    )
    parser.add_argument("input", help="Path to local audio file, or a YouTube URL when --youtube is used.")
    parser.add_argument("--timestamps", action="store_true", help="Include segment timestamps.")
    parser.add_argument("--diarize", action="store_true", help="Identify speakers as Speaker A, Speaker B, etc.")
    parser.add_argument(
        "--translate",
        metavar="LANG",
        help="Auto-detect source language and translate transcript to the target language code (e.g. en, es, fr).",
    )
    parser.add_argument("--emotion", action="store_true", help="Detect the primary emotion per segment.")
    parser.add_argument("--summary", action="store_true", help="Include a summary of the whole audio (default: off).")
    parser.add_argument("--output", "-o", help="Write output to this file instead of stdout.")
    parser.add_argument(
        "--format",
        choices=["json", "txt", "srt"],
        default="json",
        help="Output format. Default: json",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Gemini model name. Default: {DEFAULT_MODEL}")
    parser.add_argument(
        "--youtube",
        action="store_true",
        help=argparse.SUPPRESS,  # hidden option
    )
    return parser.parse_args()


def validate_local_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Error: file not found: {path}")
    if not p.is_file():
        raise SystemExit(f"Error: not a file: {path}")

    mime = mime_type_from_path(path)
    if mime not in SUPPORTED_AUDIO_TYPES:
        raise SystemExit(
            f"Error: unsupported audio format: {mime or 'unknown'}\n"
            f"Supported formats: WAV, MP3, AIFF, AAC, OGG Vorbis, FLAC"
        )
    return mime


def build_prompt(
    *,
    timestamps: bool,
    diarize: bool,
    translate: str | None,
    emotion: bool,
    summary: bool,
) -> str:
    parts = [
        "Process the provided audio and generate a detailed transcription.",
        "Return the result as JSON matching the requested schema exactly.",
    ]

    if diarize:
        parts.append(
            "Identify distinct speakers and label them consistently as Speaker A, Speaker B, Speaker C, etc. "
            "Keep the same label for the same voice across the whole audio."
        )
    else:
        parts.append("Do not add speaker labels.")

    if timestamps:
        parts.append(
            "Provide accurate timestamps for each segment. Use the format MM:SS or HH:MM:SS when needed. "
            "Break the audio into natural segments such as sentences or short phrases."
        )
    else:
        parts.append("Do not include timestamps.")

    if translate:
        parts.append(
            f"Auto-detect the primary language of each segment. "
            f"Provide the original transcription in the 'content' field and a translation to '{translate}' in the 'translation' field. "
            f"Also include the detected language name in 'language' and ISO-639-1 code in 'language_code' when possible."
        )
    else:
        parts.append("Do not translate. Keep the content in the original language.")

    if emotion:
        parts.append(
            "Identify the primary emotion of the speaker in each segment. "
            "Choose exactly one of: neutral, happy, sad, angry, fearful, surprised, disgusted."
        )
    else:
        parts.append("Do not include emotion information.")

    if summary:
        parts.append(
            "Provide a concise 'summary' field summarizing the whole audio. "
            "The 'segments' array must contain the per-segment details described above."
        )
    else:
        parts.append(
            "Do not provide a 'summary' field. "
            "The 'segments' array must contain the per-segment details described above."
        )

    return "\n\n".join(parts)


def build_schema(
    *,
    timestamps: bool,
    diarize: bool,
    translate: str | None,
    emotion: bool,
    summary: bool,
) -> types.Schema:
    segment_props: dict[str, types.Schema] = {
        "content": types.Schema(
            type=types.Type.STRING,
            description="The transcribed text of this segment in the original language.",
        ),
    }
    segment_required = ["content"]

    if diarize:
        segment_props["speaker"] = types.Schema(
            type=types.Type.STRING,
            description="Speaker label, e.g. Speaker A, Speaker B.",
        )
        segment_required.append("speaker")

    if timestamps:
        segment_props["timestamp"] = types.Schema(
            type=types.Type.STRING,
            description="Start timestamp in MM:SS or HH:MM:SS format.",
        )
        segment_props["timestamp_end"] = types.Schema(
            type=types.Type.STRING,
            description="End timestamp in MM:SS or HH:MM:SS format (optional but preferred).",
        )
        segment_required.append("timestamp")

    if translate:
        segment_props["language"] = types.Schema(
            type=types.Type.STRING,
            description="Detected language name.",
        )
        segment_props["language_code"] = types.Schema(
            type=types.Type.STRING,
            description="ISO-639-1 language code.",
        )
        segment_props["translation"] = types.Schema(
            type=types.Type.STRING,
            description=f"Translation of the segment to {translate}.",
        )
        segment_required.extend(["language", "language_code", "translation"])

    if emotion:
        segment_props["emotion"] = types.Schema(
            type=types.Type.STRING,
            enum=EMOTIONS,
            description="Primary emotion of the speaker in this segment.",
        )
        segment_required.append("emotion")

    schema_props: dict[str, types.Schema] = {
        "segments": types.Schema(
            type=types.Type.ARRAY,
            description="List of transcribed segments.",
            items=types.Schema(
                type=types.Type.OBJECT,
                properties=segment_props,
                required=segment_required,
            ),
        ),
    }
    schema_required = ["segments"]

    if summary:
        schema_props["summary"] = types.Schema(
            type=types.Type.STRING,
            description="A concise summary of the audio content.",
        )
        schema_required.append("summary")

    return types.Schema(
        type=types.Type.OBJECT,
        properties=schema_props,
        required=schema_required,
    )


def _is_retryable_error(err: genai_errors.APIError) -> bool:
    """Check if a GenAI API error is retryable (rate limit or server-side/transient)."""
    status = getattr(err, "status", None)
    if status in {"429", "500", "502", "503", "504"}:
        return True
    if isinstance(err, genai_errors.ServerError):
        return True
    # Treat any APIError that mentions rate limit or server error as retryable.
    msg = str(getattr(err, "message", err)).lower()
    return any(k in msg for k in ["rate limit", "resource exhausted", "service unavailable", "internal server", "bad gateway", "gateway timeout"])


def generate_with_retry(client: genai.Client, model: str, contents, config, max_retries: int = 5):
    """Call generate_content with exponential backoff for rate limits / transient errors."""
    last_error = None
    for attempt in range(max_retries):
        try:
            return client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        except genai_errors.APIError as e:
            last_error = e
            if not _is_retryable_error(e):
                raise
            wait = min(2**attempt + 2, 60)
            status = getattr(e, "status", "?")
            print(f"API error {status}. Retrying in {wait}s... (attempt {attempt + 1}/{max_retries})", file=sys.stderr)
            time.sleep(wait)
    raise last_error or RuntimeError("Max retries exceeded")


def make_media_part(input_path_or_url: str, youtube_mode: bool) -> types.Part:
    if youtube_mode:
        if not looks_like_youtube(input_path_or_url):
            print(f"Warning: --youtube was used but the input does not look like a YouTube URL: {input_path_or_url}", file=sys.stderr)
        return types.Part(
            file_data=types.FileData(
                file_uri=input_path_or_url,
                mime_type="video/mp4",
            )
        )
    return types.Part(
        file_data=types.FileData(
            file_uri=input_path_or_url,
            mime_type="video/mp4",
        )
    )


def upload_local_file(client: genai.Client, path: str) -> genai.types.File:
    """Upload a local audio file via the Gemini Files API and return the File object."""
    mime = validate_local_file(path)
    print(f"Uploading to Gemini Files API ({mime})...", file=sys.stderr)
    uploaded = client.files.upload(file=path, config=types.UploadFileConfig(mime_type=mime))
    return uploaded


def parse_response_text(response_text: str) -> dict:
    text = response_text.strip()
    if text.startswith("```"):
        # Strip markdown code fences if present
        lines = text.splitlines()
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Error: model response is not valid JSON:\n{text[:500]}\n{e}") from e


def render_output(data: dict, fmt: str, timestamps: bool, diarize: bool, translate: bool, emotion: bool, summary: bool) -> str:
    if fmt == "json":
        return json.dumps(data, ensure_ascii=False, indent=2)

    segments = data.get("segments", [])
    if fmt == "srt":
        if not timestamps:
            raise SystemExit("Error: SRT output requires --timestamps.")
        lines = []
        for i, seg in enumerate(segments, start=1):
            start = seg.get("timestamp", "00:00")
            end = seg.get("timestamp_end", start)
            start_srt = _to_srt_time(start)
            end_srt = _to_srt_time(end)
            lines.append(str(i))
            lines.append(f"{start_srt} --> {end_srt}")
            lines.append(_segment_text_line(seg, diarize=diarize, translate=translate, emotion=emotion))
            lines.append("")
        return "\n".join(lines).strip()

    # txt
    lines = []
    summary_text = data.get("summary")
    if summary and summary_text:
        lines.append(f"Summary: {summary_text}")
        lines.append("")
    for seg in segments:
        prefix_parts = []
        if timestamps:
            prefix_parts.append(f"[{seg.get('timestamp', '')}]")
        if diarize:
            prefix_parts.append(seg.get("speaker", "Speaker"))
        if emotion:
            prefix_parts.append(f"({seg.get('emotion', '')})")
        prefix = " ".join(prefix_parts)
        if prefix:
            lines.append(f"{prefix}: {seg.get('content', '')}")
        else:
            lines.append(seg.get("content", ""))
        if translate and seg.get("translation"):
            lines.append(f"  [{seg.get('language_code', '')}] {seg.get('translation')}")
    return "\n".join(lines)


def _segment_text_line(seg: dict, diarize: bool, translate: bool, emotion: bool) -> str:
    parts = []
    if diarize and seg.get("speaker"):
        parts.append(f"{seg['speaker']}:")
    if emotion and seg.get("emotion"):
        parts.append(f"[{seg['emotion']}]")
    parts.append(seg.get("content", ""))
    if translate and seg.get("translation"):
        parts.append(f"({seg.get('language_code', '')}) {seg['translation']}")
    return " ".join(parts)


def _to_srt_time(ts: str) -> str:
    """Convert MM:SS or HH:MM:SS to SRT hh:mm:ss,mmm format (with zero milliseconds)."""
    ts = ts.strip()
    parts = ts.split(":")
    if len(parts) == 2:
        h, m, s = "00", parts[0], parts[1]
    elif len(parts) == 3:
        h, m, s = parts[0], parts[1], parts[2]
    else:
        h, m, s = "00", "00", ts
    return f"{h.zfill(2)}:{m.zfill(2)}:{s.zfill(2)},000"


def main() -> None:
    args = parse_args()

    if not GEMINI_API_KEY:
        raise SystemExit(
            "Error: GEMINI_API_KEY is not set.\n"
            "Get a key at https://aistudio.google.com/apikey and set it as an env var or in a .env file."
        )

    client = genai.Client(api_key=GEMINI_API_KEY)

    if args.youtube:
        print(f"Using direct YouTube URL input: {args.input}", file=sys.stderr)
        media_part = make_media_part(args.input, youtube_mode=True)
    else:
        print(f"Uploading local file: {args.input}", file=sys.stderr)
        uploaded_file = upload_local_file(client, args.input)
        media_part = types.Part(
            file_data=types.FileData(
                file_uri=uploaded_file.uri,
                mime_type=uploaded_file.mime_type,
            )
        )

    prompt = build_prompt(
        timestamps=args.timestamps,
        diarize=args.diarize,
        translate=args.translate,
        emotion=args.emotion,
        summary=args.summary,
    )
    schema = build_schema(
        timestamps=args.timestamps,
        diarize=args.diarize,
        translate=args.translate,
        emotion=args.emotion,
        summary=args.summary,
    )

    contents = [
        types.Content(
            parts=[
                media_part,
                types.Part(text=prompt),
            ]
        )
    ]

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )

    print("Transcribing with Gemini...", file=sys.stderr)
    response = generate_with_retry(client, args.model, contents, config)

    if not response or not response.text:
        raise SystemExit("Error: empty response from Gemini API.")

    data = parse_response_text(response.text)
    output = render_output(
        data,
        fmt=args.format,
        timestamps=args.timestamps,
        diarize=args.diarize,
        translate=bool(args.translate),
        emotion=args.emotion,
        summary=args.summary,
    )

    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"Saved output to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
