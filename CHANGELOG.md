# Changelog

All notable changes to this project are documented here.

## [0.3.0] - 2026-07-14

### Added

- Duration-first filtering with `--min-duration` and `--max-duration` before popularity ranking.
- Guided `setup` and profile-aware `doctor` commands for core, media, transcription, Word, and full Agent environments.
- A portable `douyin-script-rewriter` Agent Skill with transcript correction, original rewrites, and structurally verified fixed-template Word delivery.
- skills.sh catalog metadata, install badge, cross-agent Skills CLI validation, and search-intent regression coverage.
- Explicit untrusted-content boundaries for Douyin metadata and transcripts.

### Changed

- Public VCS installation examples are pinned to the auditable `v0.3.0` release.
- Skill metadata now covers common Chinese and English discovery queries and declares the official source repository.
- Doctor repair output is no longer treated as permission to execute arbitrary commands automatically.

## [0.2.0] - 2026-07-13

### Added

- Automatic single-video detection and collection for direct links, short links, and share text.
- Apache-2.0 licensing and explicit responsible-use guidance.

### Changed

- Single-video collection now tries an anonymous browser context before using saved login state.
- Agent JSON output now identifies `profile` and `single_video` collection modes.

## [0.1.0] - 2026-07-12

### Added

- Playwright login and network-response discovery for Douyin user profiles.
- HTTP pagination, Top-N ranking, result caching, and Agent-friendly JSON output.
- Speech-audio download/extraction with FFmpeg and FFprobe validation.
- Optional faster-whisper transcription with timestamped segment files.
- `douyin-doctor`, `douyin-crawl`, `douyin-ingest`, and `douyin-transcribe` commands.
- Distributable `douyin-content-ingest` Codex Skill.
