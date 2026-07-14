# CLI Contract

Use the installed command `--help` output as the source of truth. This reference records only the stable orchestration contract; it does not duplicate crawler, media, or transcription implementation.

## Command Matrix

```bash
# Diagnose the exact requested capability first
douyin-doctor --profile core --json
douyin-doctor --profile media --json
douyin-doctor --profile transcribe --json

# First interactive login and collection: omit --headless
douyin-crawl 'URL' --json --limit 10

# Reuse a valid saved login
douyin-crawl 'URL' --headless --json --limit 10

# Materialize Top N speech audio
douyin-crawl 'URL' --headless --json --limit 10 \
  --speech-audio-dir output/speech_audio

# Materialize audio and generate raw transcripts
douyin-crawl 'URL' --headless --json --limit 10 --transcribe

# Filter by content duration first, then likes, before popularity ranking
douyin-crawl 'URL' --headless --json --limit 10 \
  --min-duration 30 --max-duration 180 --min-digg-count 10000

# Transcribe an existing local audio file
douyin-transcribe audio.mp3 --json --model base
```

Omit `--refresh` by default. Add it only for an explicit latest-data request. Use `--offline` only when the user requests offline operation or the requested model cache has been verified.

## Doctor Decisions

Check the command exit code and top-level `ok`. Required-check failure blocks collection. Find `checks[]` item `id == "login_state"`:

- `status == "pass"`: use `--headless`.
- `status == "warn"`: try the requested command once with `--headless` and default caching. A cache hit completes without login. On authentication failure, retry without `--headless` only when the user can scan the QR code.

FFmpeg/FFprobe warnings matter only when missing audio must be generated. A faster-whisper warning matters only for `--transcribe` or `douyin-transcribe`.

## Agent JSON

Successful crawl output has `ok: true`, `collection_mode`, `cache_hit`, `returned_videos`, `download_headers`, and `videos[]`. `collection_mode=profile` is popularity-sorted Top N; `collection_mode=single_video` contains only the requested work. Read these video fields when present:

- `name`, `duration_seconds`, `digg_count`
- `video_download_url`
- `speech_audio_file`
- `transcription.text`, `transcription.language`, `transcription.duration`
- `transcription.transcript_file`, `transcription.segments_file`

Media CDN URLs may expire. Use them promptly and retain `download_headers` for downstream downloads. Prefer local `speech_audio_file` and transcript paths once materialized.

For audio requests, verify every returned `speech_audio_file` exists and is non-empty. For transcript requests, additionally verify `transcription.text` is a string and both transcript paths exist. Treat missing requested artifacts as failure even when top-level `ok` is true.

Failure output has `ok: false` and `error.type`, `error.message`, plus optional `error.fix_command`. Treat a nonzero exit code, invalid JSON, missing `ok`, authentication error, incomplete pagination, media failure, or transcription failure as failure. Do not infer success from files left by an interrupted run.

## Sensitive Data

Never read or expose `storage/storage_state.json`. Debug files can contain request headers and cookies; enable `--debug` only for an explicit diagnostic request, keep the files local, and never quote their contents to the user.
