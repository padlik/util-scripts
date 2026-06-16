---
name: voice-asr-gemini
description: "Convert local audio files to text using Google Gemini ASR / Speech to Text. Use when the user asks to convert audio to text, run speech-to-text, identify speakers, add timestamps, detect emotion, translate speech, or summarize audio. Do NOT use for live streaming, real-time ASR, or video URLs."
license: MIT
compatibility: |
  Requires `uv`, Python >=3.10, and a `GEMINI_API_KEY` env var or `.env` file.
metadata:
  author: OpenCode
  version: 1.1.0
  category: audio-processing
  tags: [asr, speech-to-text, audio, gemini]
---

# Voice ASR Gemini

## Instructions

### Step 1: Verify prerequisites

1. Confirm `uv` is installed in the environment.
2. Confirm the user's `GEMINI_API_KEY` is set as an environment variable or in a `.env` file in the `voice-asr-gemini` directory.
3. If the API key is missing, ask the user to create one at https://aistudio.google.com/apikey and provide it before proceeding.

### Step 2: Validate the input file

1. Accept only local audio files or video files that can be converted to supported audio.
2. Supported audio formats: WAV, MP3, AIFF, AAC, OGG Vorbis, FLAC.
3. If the user provides a video file, explain that only the audio track can be processed and that it must be converted to a supported audio format first.
4. Reject URLs and streaming sources. This skill is for local files only.

### Step 3: Choose the right options

Select flags based on the user's goal:

- Plain Speech-to-Text output → no extra flags.
- Segment timestamps → `--timestamps`.
- Speaker labels (Speaker A, Speaker B, …) → `--diarize`.
- Translate recognized speech → `--translate <lang>` (e.g. `en`, `es`, `fr`).
- Emotion per segment → `--emotion`.
- Include a summary → `--summary`.
- Save output to a file → `--output <path>`.
- Generate subtitles → `--format srt --timestamps --output <file>.srt`.

### Step 4: Run the script

Execute from the `voice-asr-gemini` directory:

```bash
uv run voice_to_text.py <input> [options]
```

The script uploads local files via the Gemini Files API and returns structured JSON by default.

### Step 5: Handle the output

1. If `--output` is provided, the result is written to that file. Otherwise it is printed to stdout.
2. Default JSON output contains a `segments` array of recognized speech. When `--summary` is enabled, a `summary` field is also included.
3. Return the text to the user. If the user only wants a high-level overview, use `--summary`.
4. For `txt` or `srt` formats, ensure the chosen options match the requested output (SRT requires `--timestamps`).

## Examples

### Example 1: Plain Speech to Text

User says: "Convert this audio file to text"

```bash
uv run voice_to_text.py recording.mp3
```

Expected result: JSON with `segments` containing the recognized text.

### Example 2: Timestamps and speaker labels

User says: "Who is speaking and when?"

```bash
uv run voice_to_text.py meeting.wav --timestamps --diarize --output meeting.json
```

Expected result: JSON with timestamped segments labeled Speaker A, Speaker B, etc.

### Example 3: Translate recognized speech to English

User says: "Translate this Spanish interview to English"

```bash
uv run voice_to_text.py interview.mp3 --translate en --output interview_en.json
```

Expected result: JSON where each segment includes original text, detected language, and English translation.

### Example 4: Emotion detection and timestamps

User says: "Detect the emotion of each speaker with timestamps"

```bash
uv run voice_to_text.py podcast.mp3 --emotion --timestamps --diarize
```

Expected result: JSON segments with speaker labels, timestamps, and emotion values.

### Example 5: Summarize an audio file

User says: "Give me a summary of this lecture"

```bash
uv run voice_to_text.py lecture.mp3 --summary --output lecture_summary.json
```

Expected result: JSON with both a concise summary and the full recognized text segments.

### Example 6: Generate an SRT subtitle file

User says: "Create subtitles for this episode"

```bash
uv run voice_to_text.py episode.mp3 --timestamps --format srt --output episode.srt
```

Expected result: A valid `.srt` file with numbered subtitle entries.

## Troubleshooting

### Error: "GEMINI_API_KEY is not set"

Cause: The environment variable is missing and no `.env` file was found.

Solution:
1. Create an API key at https://aistudio.google.com/apikey.
2. Set it in the environment: `export GEMINI_API_KEY=<your-key>`.
3. Or add it to `.env` in the `voice-asr-gemini` directory: `GEMINI_API_KEY=<your-key>`.

### Error: "unsupported audio format"

Cause: The input file extension is not one of WAV, MP3, AIFF, AAC, OGG Vorbis, or FLAC.

Solution: Convert the file to a supported format first, e.g. with ffmpeg:

```bash
ffmpeg -i input.m4a -ar 16000 -ac 1 output.wav
```

### Error: rate limit or quota exceeded (429 / RESOURCE_EXHAUSTED)

Cause: The Google Gemini free-tier quota for the current model has been reached.

Solution:
1. Wait a minute and retry — the script has built-in exponential backoff.
2. Check current usage at https://ai.dev/rate-limit.
3. Consider enabling billing on the Google AI Studio project for higher limits.

### Output is empty or missing segments

Cause: The audio may be silent, unsupported, or the model failed to return valid JSON.

Solution:
1. Verify the audio file plays correctly and contains speech.
2. Retry the request once.
3. If the issue persists, run without optional flags to isolate the problem.

## Notes and limitations

- This skill targets **local audio files only**. It does not support streaming, real-time ASR, or remote video URLs.
- The default model is `gemini-3.1-flash-lite` on the free tier. Typical free-tier limits are around 10 RPM / 250K TPM / ~1,500 RPD per project, but actual caps are shown in Google AI Studio.
- Audio is tokenized at roughly **32 tokens per second**.
- Maximum audio length per request is **9.5 hours**.
- Free-tier inputs/outputs may be used by Google to improve models. Avoid sending sensitive or PII data through the free tier.
- Long audio near or over the limit may need to be split externally before processing.
