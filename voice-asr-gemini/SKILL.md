---
name: voice-asr-gemini
description: |
  Perform automatic speech recognition (ASR / Speech to Text) on audio files using the local
  `voice_to_text.py` script and the Google Gemini API. Use this skill when the user asks to
  convert audio to text, run speech-to-text on an audio or video file, perform ASR, identify
  speakers, add timestamps, detect emotion, translate recognized speech, or summarize audio.
  Triggers on phrases like "speech to text", "ASR", "convert audio to text",
  "speaker diarization", "add timestamps", "translate audio", "emotion detection",
  "summarize audio", "process this audio file", "speech recognition", etc.
---

# Voice ASR Gemini

## Overview

This skill wraps the local `@voice-asr-gemini/voice_to_text.py` script. It uses the Google Gemini
API to convert local audio files to text using Speech-to-Text (ASR).

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
| `--translate <lang>` | Auto-detect source language and translate recognized text to `<lang>` |
| `--emotion` | Detect primary emotion per segment |
| `--summary` | Include a summary of the whole audio (default: off) |
| `--output <file>` | Save output to a file instead of stdout |
| `--format {json,txt,srt}` | Output format (default: `json`) |
| `--model <model>` | Override the Gemini model (default: `gemini-3.1-flash-lite`) |

## Workflow

### 1. Verify the API key

Make sure `GEMINI_API_KEY` is set. If not, ask the user to provide one or create one at
https://aistudio.google.com/apikey.

### 2. Determine the input type

- **Local audio/video file**: validate the extension is supported. If the user provides a
  video file, note that only the audio track can be processed, and the script supports
  the audio formats listed above. Convert the file first if necessary.

### 3. Choose the right options

Select options based on the user's request:

- Plain Speech-to-Text output → no extra flags.
- Add timestamps → `--timestamps`.
- Identify speakers → `--diarize`.
- Translate recognized speech to English/Spanish/etc. → `--translate en` / `--translate es`.
- Detect emotion → `--emotion`.
- Include a summary → `--summary`.
- Save to file → `--output <path>`.
- Subtitle file → `--format srt --timestamps --output <file>.srt`.

### 4. Run the script

Execute from the `voice-asr-gemini` directory:

```bash
uv run voice_to_text.py <input> [options]
```

For local files the script uploads via the Gemini Files API.

### 5. Handle the output

- Default output is JSON with a `segments` array of recognized speech. When `--summary` is enabled,
  a `summary` field is also included.
- If `--output` is provided, the result is written to the file; otherwise it goes to stdout.
- Return the text to the user, or summarize the contents if the user only wants a
  high-level overview (use `--summary` for that).

## Examples

### Speech to Text on a local audio file

```bash
uv run voice_to_text.py recording.mp3
```

### Speech to Text with timestamps and speakers

```bash
uv run voice_to_text.py meeting.wav --timestamps --diarize --output meeting.json
```

### Translate recognized speech from a non-English audio file to English

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

## Notes and limitations

- This script uses the **free tier** of the Gemini API by default. Free tier limits vary by
  model and project; typical values are around 10 RPM / 250K TPM / ~1,500 RPD for
  `gemini-3.1-flash-lite`.
- Audio is tokenized at roughly **32 tokens per second**.
- Free-tier inputs/outputs may be used by Google to improve models. Avoid sending sensitive or
  PII data through the free tier.
- The script has built-in exponential backoff for rate limits (`429`) and transient errors.
- Long audio (near or over 9.5 hours) may need to be split externally before processing.
