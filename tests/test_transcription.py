from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import project.transcription as transcription_module
from project.models import Video
from project.transcription import (
    TranscriptionDependencyError,
    TranscriptionModelError,
    TranscriptionOptions,
    TranscriptionService,
)


@dataclass
class FakeSegment:
    id: int
    start: float
    end: float
    text: str


@dataclass
class FakeInfo:
    language: str
    duration: float


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def transcribe(self, audio, *, language, beam_size, vad_filter):
        self.calls.append(
            {
                "audio": audio,
                "language": language,
                "beam_size": beam_size,
                "vad_filter": vad_filter,
            }
        )
        return (
            iter(
                [
                    FakeSegment(0, 0.0, 1.25, " 第一段"),
                    FakeSegment(1, 1.25, 2.5, "第二段 "),
                ]
            ),
            FakeInfo(language="zh", duration=2.5),
        )


def test_default_options_use_base_chinese_vad_and_cpu_int8() -> None:
    options = TranscriptionOptions()

    assert options.model == "base"
    assert options.device == "cpu"
    assert options.resolved_compute_type == "int8"
    assert options.language == "zh"
    assert options.beam_size == 5
    assert options.vad_filter is True


def test_service_loads_backend_once_and_reuses_it_for_all_videos(tmp_path) -> None:
    backend = FakeBackend()
    factory_calls: list[TranscriptionOptions] = []

    def backend_factory(options):
        factory_calls.append(options)
        return backend

    audio_one = tmp_path / "one.mp3"
    audio_two = tmp_path / "two.mp3"
    audio_one.write_bytes(b"audio one")
    audio_two.write_bytes(b"audio two")
    videos = [
        Video(aweme_id="1", speech_audio_file=str(audio_one)),
        Video(aweme_id="2", speech_audio_file=str(audio_two)),
    ]
    output_dir = tmp_path / "transcripts"
    service = TranscriptionService(backend_factory=backend_factory)

    service.transcribe_videos(videos, output_dir)

    assert len(factory_calls) == 1
    assert len(backend.calls) == 2
    assert all(call["language"] == "zh" for call in backend.calls)
    assert all(call["beam_size"] == 5 for call in backend.calls)
    assert all(call["vad_filter"] is True for call in backend.calls)
    assert videos[0].transcription is not None
    assert videos[0].transcription.text == "第一段第二段"
    assert videos[0].transcription.model == "base"
    assert videos[0].transcription.duration == 2.5
    assert (output_dir / "1.txt").read_text(encoding="utf-8") == "第一段第二段"
    segments_payload = json.loads(
        (output_dir / "1.segments.json").read_text(encoding="utf-8")
    )
    assert segments_payload["segments"][0] == {
        "id": 0,
        "start": 0.0,
        "end": 1.25,
        "text": "第一段",
    }


def test_service_wraps_offline_model_load_failure(tmp_path) -> None:
    def fail_factory(options):
        raise RuntimeError("cache miss")

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    service = TranscriptionService(
        TranscriptionOptions(offline=True, model_cache_dir=tmp_path / "models"),
        backend_factory=fail_factory,
    )

    with pytest.raises(TranscriptionModelError, match="离线加载模型失败"):
        service.transcribe_file(audio, tmp_path / "output")


def test_dependency_check_explains_optional_install(monkeypatch) -> None:
    def fail_import(name):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(transcription_module.importlib, "import_module", fail_import)

    with pytest.raises(TranscriptionDependencyError, match=r"\.\[transcribe\]"):
        transcription_module.ensure_transcription_dependency()


def test_faster_whisper_factory_receives_runtime_options(tmp_path, monkeypatch) -> None:
    captured = {}

    class FakeWhisperModel:
        def __init__(self, model, **kwargs) -> None:
            captured["model"] = model
            captured.update(kwargs)

    monkeypatch.setattr(
        transcription_module.importlib,
        "import_module",
        lambda name: SimpleNamespace(WhisperModel=FakeWhisperModel),
    )
    options = TranscriptionOptions(
        model="small",
        device="cuda",
        compute_type="float16",
        model_cache_dir=tmp_path / "models",
        offline=True,
    )

    transcription_module._create_faster_whisper_backend(options)

    assert captured == {
        "model": "small",
        "device": "cuda",
        "compute_type": "float16",
        "download_root": str((tmp_path / "models").resolve()),
        "local_files_only": True,
    }


@pytest.mark.smoke
def test_real_mp3_optional_smoke(tmp_path) -> None:
    audio_value = os.environ.get("DOUYIN_TRANSCRIBE_SMOKE_MP3")
    if not audio_value:
        pytest.skip("set DOUYIN_TRANSCRIBE_SMOKE_MP3 to run the real-model smoke test")
    pytest.importorskip("faster_whisper")
    audio = Path(audio_value).expanduser().resolve()
    if not audio.is_file():
        pytest.skip(f"smoke MP3 does not exist: {audio}")
    options = TranscriptionOptions(
        model=os.environ.get("DOUYIN_TRANSCRIBE_SMOKE_MODEL", "base"),
        offline=os.environ.get("DOUYIN_TRANSCRIBE_SMOKE_OFFLINE") == "1",
    )

    result = TranscriptionService(options).transcribe_file(audio, tmp_path)

    assert result.duration > 0
    assert result.text
    assert result.segments
    assert result.segments_file.endswith(".segments.json")
