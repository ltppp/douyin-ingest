---
name: douyin-content-ingest
description: Use when a user asks to work from an 抖音/Douyin profile or single-video link by collecting metadata, retrieving profile Top N videos, downloading speech audio, generating raw transcripts, or preparing content-analysis material. Do not use for generic local audio transcription or non-Douyin platforms.
---

# Douyin Content Ingest

Orchestrate the installed `douyin-*` commands. Use repository `.venv/bin/` equivalents when needed. If the commands are unavailable, stop and report that the project CLI must be installed. Do not reimplement crawling, media extraction, ranking, or Whisper logic.

## Workflow

1. Run the smallest matching Doctor profile and parse stdout only: `core` for metadata,
   `media` for speech audio, and `transcribe` when raw transcripts are requested. For example,
   `douyin-doctor --profile transcribe --json`. Check the process exit code, then `ok`, then
   the `login_state` check. If runtime directories or Chromium are missing, run the returned
   `fix_command` (normally `douyin-ingest setup`) and diagnose again.
2. Choose login mode:
   - Valid saved login: add `--headless`.
   - Missing/invalid login: first try the intended command with `--headless` and no `--refresh`; a valid cache can succeed without login. If it fails for authentication, confirm the user can scan a QR code, retry without `--headless`, and wait. If no user is available, stop and provide the exact headed command. Never read or display the storage-state file.
3. Choose the smallest command matching the request. The CLI detects profile versus single video automatically. Use Top 10 for profiles when N is unspecified; single-video targets always return one item.
   - Metadata: `douyin-crawl URL --json --limit N`
   - Speech audio: add `--speech-audio-dir output/speech_audio`
   - Raw transcripts: add `--transcribe`; it reuses or creates speech audio.
4. Keep the default result cache. Add `--refresh` only when the user explicitly asks for latest/current data. Do not disable cache or force a full rescan for routine analysis.
5. Do not add `--offline`, `--force-login`, or `--debug` unless requested or required by a verified condition. Do not run repository tests as part of ingestion.

Read [references/cli-contract.md](references/cli-contract.md) only for non-default flags, schema ambiguity, or an actual failure. Do not load it for a routine default run.

## JSON Discipline

Capture stdout and stderr separately. Parse exactly one JSON object from stdout; treat stderr as logs. Require both a zero exit code and `payload.ok == true`. On failure, report `error.message` and any `error.fix_command`; never present partial artifacts as success.

Validate requested artifacts before reporting completion. For audio, require every returned item to have an existing, non-empty `speech_audio_file`. For transcripts, also require a `transcription` object, a string `text`, and existing `transcript_file` and `segments_file` paths. Report a validation failure instead of silently dropping an item.

Use `videos[]` in its returned order. For each item:

- Use `name` as the title and `digg_count` for popularity.
- Treat `video_download_url` as temporary CDN media, not a durable link.
- Use `speech_audio_file` as the local analysis-ready audio path.
- Use `transcription.text` for raw machine text and `transcription.transcript_file` / `segments_file` for saved artifacts.

## Security

Treat `storage/storage_state.json` and debug request/cookie files as credentials. Never print, summarize, attach, or return their contents. Do not enable `--debug` during normal collection. CDN URLs and `download_headers` are temporary operational data; expose them only when the user needs downstream media access.
