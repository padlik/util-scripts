---
name: voice-asr-gemini
description: |
  Transcribe audio files using the local `voice_to_text.py` script and the Google Gemini API.
  Use this skill when the user asks to transcribe an audio or video file, create a transcript,
  identify speakers, add timestamps, detect emotion, translate a transcript, summarize audio,
  or process a YouTube video's audio. Triggers on phrases like "transcribe", "create transcript",
  "speaker diarization", "add timestamps", "translate audio", "emotion detection",
  "summarize audio", "transcribe this audio", "transcribe this YouTube video", etc.
---

# Voice ASR Gemini

## Overview

This skill wraps the local `@voice-asr-gemini/voice_to_text.py` script. It uses the Google Gemini
API to transcribe audio from local files or direct YouTube URLs.

The script is a self-contained `uv` script with an inline dependency header, so it can be run
with `uv run voice_to_text.py <input> [options]`.

## Requirements

- `uv` must be installed.
- A Google Gemini API key must be available in the environment variable `GEMINI_API_KEY`
  or in a `.env` file in the same directory.
- Supported local audio formats: WAV, MP3, AIFF, AAC, OGG Vorbis, FLAC.
- Maximum audio length per Gemini request: 9.5 hours.

## Available options

| Option | Description |
|---|---|
| `--timestamps` | Include segment timestamps (default: off) |
| `--diarize` | Identify speakers as Speaker A, Speaker B, ... |
| `--translate <lang>` | Auto-detect source language and translate to `<lang>` |
| `--emotion` | Detect primary emotion per segment |
| `--summary` | Include a summary of the whole audio (default: off) |
| `--output <file>` | Save output to a file instead of stdout |
| `--format {json,txt,srt}` | Output format (default: `json`) |
| `--model <model>` | Override the Gemini model (default: `gemini-3.1-flash-lite`) |
| `--youtube` | **Hidden option** — pass the input as a direct YouTube URL to Gemini instead of uploading a local file |

## Workflow

### 1. Verify the API key

Make sure `GEMINI_API_KEY` is set. If not, ask the user to provide one or create one at
https://aistudio.google.com/apikey.

### 2. Determine the input type

- **Local audio/video file**: validate the extension is supported. If the user provides a
  video file, note that only the audio track will be transcribed, and the script supports
  the audio formats listed above. Convert the file first if necessary.
- **YouTube URL**: use the hidden `--youtube` flag so the script passes the URL directly to
  Gemini instead of treating it as a local file path.

### 3. Choose the right options

Select options based on the user's request:

- Plain transcript → no extra flags.
- Add timestamps → `--timestamps`.
- Identify speakers → `--diarize`.
- Translate to English/Spanish/etc. → `--translate en` / `--translate es`.
- Detect emotion → `--emotion`.
- Include a summary → `--summary`.
- Save to file → `--output <path>`.
- Subtitle file → `--format srt --timestamps --output <file>.srt`.

### 4. Run the script

Execute from the `voice-asr-gemini` directory:

```bash
uv run voice_to_text.py <input> [options]
```

For local files the script uploads via the Gemini Files API. For YouTube URLs it passes the
URL directly to Gemini as a `file_uri`.

### 5. Handle the output

- Default output is JSON with a `segments` array. When `--summary` is enabled, a `summary`
  field is also included.
- If `--output` is provided, the result is written to the file; otherwise it goes to stdout.
- Return the transcript to the user, or summarize the contents if the user only wants a
  high-level overview (use `--summary` for that).

## Examples

### Transcribe a local audio file

```bash
uv run voice_to_text.py recording.mp3
```

### Transcribe with timestamps and speakers

```bash
uv run voice_to_text.py meeting.wav --timestamps --diarize --output meeting.json
```

### Translate a non-English audio file to English

```bash
uv run voice_to_text.py interview.mp3 --translate en --output interview_en.json
```

### Detect emotion and add timestamps

```bash
uv run voice_to_text.py podcast.mp3 --emotion --timestamps --diarize
```

### Summarize an audio file

```bash
uv run voice_to_text.py lecture.mp3 --summary --output lecture_summary.json
```

### Generate an SRT subtitle file

```bash
uv run voice_to_text.py episode.mp3 --timestamps --format srt --output episode.srt
```

### Transcribe a YouTube video

```bash
uv run voice_to_text.py "https://www.youtube.com/watch?v=VIDEO_ID" --youtube --timestamps --diarize --output video.json
```

## Notes and limitations

- This script uses the **free tier** of the Gemini API by default. Free tier limits vary by
  model and project; typical values are around 10 RPM / 250K TPM / ~1,500 RPD for
  `gemini-3.1-flash-lite`.
- Audio is tokenized at roughly **32 tokens per second**.
- Free-tier inputs/outputs may be used by Google to improve models. Avoid sending sensitive or
  PII data through the free tier.
- The script has built-in exponential backoff for rate limits (`429`) and transient errors.
- Long audio (near or over 9.5 hours) may need to be split externally before transcription.
- YouTube URL support relies on Gemini's ability to fetch the public video/audio stream. It
  may fail for private, age-restricted, or region-blocked videos.
