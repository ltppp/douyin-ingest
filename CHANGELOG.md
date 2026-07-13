# Changelog

All notable changes to this project are documented here.

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
