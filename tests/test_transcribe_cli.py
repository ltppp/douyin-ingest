from __future__ import annotations

import json

from project.transcribe_cli import build_argument_parser, execute
from project.transcription import (
    TRANSCRIBE_INSTALL_COMMAND,
    TranscriptionDependencyError,
    TranscriptionService,
)
from tests.test_transcription import FakeBackend


def test_standalone_json_transcribes_audio_with_configurable_options(
    tmp_path, capsys
) -> None:
    audio = tmp_path / "speech.mp3"
    audio.write_bytes(b"audio")
    backend = FakeBackend()
    captured_options = []

    def service_factory(options):
        captured_options.append(options)
        return TranscriptionService(options, backend_factory=lambda unused: backend)

    args = build_argument_parser().parse_args(
        [
            str(audio),
            "--json",
            "--model",
            "small",
            "--device",
            "cuda",
            "--compute-type",
            "float16",
            "--language",
            "auto",
            "--beam-size",
            "3",
            "--no-vad",
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert execute(
        args,
        service_factory=service_factory,
        dependency_checker=lambda: None,
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["audio_file"] == str(audio)
    assert payload["transcription"]["model"] == "small"
    assert payload["transcription"]["language"] == "zh"
    assert payload["transcription"]["segments"][0]["start"] == 0.0
    options = captured_options[0]
    assert options.device == "cuda"
    assert options.resolved_compute_type == "float16"
    assert options.language is None
    assert options.beam_size == 3
    assert options.vad_filter is False


def test_standalone_missing_dependency_returns_structured_error(tmp_path, capsys) -> None:
    audio = tmp_path / "speech.mp3"
    audio.write_bytes(b"audio")

    def fail_dependency() -> None:
        raise TranscriptionDependencyError("missing faster-whisper")

    args = build_argument_parser().parse_args([str(audio), "--json"])

    assert execute(args, dependency_checker=fail_dependency) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema_version": "1.0",
        "ok": False,
        "error": {
            "type": "TranscriptionDependencyError",
            "message": "missing faster-whisper",
            "fix_command": TRANSCRIBE_INSTALL_COMMAND,
        },
    }
