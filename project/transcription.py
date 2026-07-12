from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast

from loguru import logger

from project.models import Transcription, TranscriptionSegment, Video
from project.paths import default_runtime_root
from project.utils import write_json

TRANSCRIBE_INSTALL_COMMAND = "pip install -e '.[transcribe]'"
DEFAULT_MODEL_CACHE_DIR = default_runtime_root() / "models" / "faster-whisper"


class TranscriptionError(RuntimeError):
    """Base error for optional speech transcription."""


class TranscriptionDependencyError(TranscriptionError):
    """Raised when faster-whisper or its native dependencies cannot be imported."""


class TranscriptionModelError(TranscriptionError):
    """Raised when a Whisper model cannot be loaded."""


class TranscriptionInputError(TranscriptionError):
    """Raised when the requested audio input is unavailable."""


class BackendSegment(Protocol):
    id: int
    start: float
    end: float
    text: str


class BackendInfo(Protocol):
    language: str
    duration: float


class TranscriptionBackend(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        language: str | None,
        beam_size: int,
        vad_filter: bool,
    ) -> tuple[Iterable[BackendSegment], BackendInfo]: ...


@dataclass(frozen=True)
class TranscriptionOptions:
    model: str = "base"
    device: str = "cpu"
    compute_type: str | None = None
    language: str | None = "zh"
    beam_size: int = 5
    vad_filter: bool = True
    model_cache_dir: Path = field(default_factory=lambda: DEFAULT_MODEL_CACHE_DIR)
    offline: bool = False

    @property
    def resolved_compute_type(self) -> str:
        if self.compute_type:
            return self.compute_type
        return "int8" if self.device == "cpu" else "default"


BackendFactory = Callable[[TranscriptionOptions], TranscriptionBackend]


class TranscriptionService:
    def __init__(
        self,
        options: TranscriptionOptions | None = None,
        *,
        backend_factory: BackendFactory | None = None,
    ) -> None:
        self.options = options or TranscriptionOptions()
        self._backend_factory = backend_factory or _create_faster_whisper_backend
        self._backend: TranscriptionBackend | None = None

    def transcribe_file(
        self,
        audio_path: Path,
        output_dir: Path,
        *,
        stem: str | None = None,
    ) -> Transcription:
        audio = audio_path.expanduser().resolve()
        try:
            audio_ready = audio.is_file() and audio.stat().st_size > 0
        except OSError as exc:
            raise TranscriptionInputError(f"无法读取音频文件: {audio}: {exc}") from exc
        if not audio_ready:
            raise TranscriptionInputError(f"音频文件不存在或为空: {audio}")
        output_dir = output_dir.expanduser().resolve()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TranscriptionError(f"无法创建转写输出目录: {output_dir}: {exc}") from exc
        output_stem = stem or audio.stem
        transcript_path = output_dir / f"{output_stem}.txt"
        segments_path = output_dir / f"{output_stem}.segments.json"

        logger.info("开始转写音频: {}", audio)
        try:
            raw_segments, info = self._get_backend().transcribe(
                str(audio),
                language=self.options.language,
                beam_size=self.options.beam_size,
                vad_filter=self.options.vad_filter,
            )
            segments: list[TranscriptionSegment] = []
            text_parts: list[str] = []
            for segment in raw_segments:
                raw_text = str(segment.text)
                text_parts.append(raw_text)
                segments.append(
                    TranscriptionSegment(
                        id=segment.id,
                        start=float(segment.start),
                        end=float(segment.end),
                        text=raw_text.strip(),
                    )
                )
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"音频转写失败: {audio}: {exc}") from exc

        text = "".join(text_parts).strip()
        language = str(info.language or self.options.language or "unknown")
        duration = float(info.duration or 0.0)
        if duration <= 0 and segments:
            duration = max(segment.end for segment in segments)
        result = Transcription(
            text=text,
            language=language,
            duration=duration,
            model=self.options.model,
            segments=segments,
            transcript_file=str(transcript_path),
            segments_file=str(segments_path),
        )
        try:
            _write_text(transcript_path, result.text)
            write_json(
                segments_path,
                {
                    "schema_version": "1.0",
                    "audio_file": str(audio),
                    "language": result.language,
                    "duration": result.duration,
                    "model": result.model,
                    "segments": [
                        segment.model_dump(mode="json") for segment in result.segments
                    ],
                },
            )
        except OSError as exc:
            raise TranscriptionError(f"保存转写文件失败: {output_dir}: {exc}") from exc
        logger.info("原始转写已保存: {}", transcript_path)
        logger.info("时间戳片段已保存: {}", segments_path)
        return result

    def transcribe_videos(self, videos: Sequence[Video], output_dir: Path) -> None:
        for index, video in enumerate(videos, start=1):
            if not video.speech_audio_file:
                raise TranscriptionInputError(f"作品 {video.aweme_id} 缺少 speech_audio_file")
            logger.info("转写 Top{} 音频: {}", index, video.aweme_id)
            video.transcription = self.transcribe_file(
                Path(video.speech_audio_file),
                output_dir,
                stem=video.aweme_id,
            )

    def _get_backend(self) -> TranscriptionBackend:
        if self._backend is None:
            cache_dir = self.options.model_cache_dir.expanduser().resolve()
            logger.info(
                "加载 faster-whisper 模型 {}（device={}, compute_type={}, cache={}）",
                self.options.model,
                self.options.device,
                self.options.resolved_compute_type,
                cache_dir,
            )
            if self.options.offline:
                logger.info("离线模式已开启，仅使用本地模型缓存")
            elif _directory_has_entries(cache_dir):
                logger.info("检测到本地模型缓存；指定模型缺失或不完整时将联网补齐")
            else:
                logger.info("模型缓存为空，首次使用时将从 Hugging Face 下载")
            try:
                self._backend = self._backend_factory(self.options)
            except TranscriptionDependencyError:
                raise
            except Exception as exc:
                if self.options.offline:
                    message = f"离线加载模型失败，请确认缓存完整: {cache_dir}: {exc}"
                else:
                    message = f"模型加载失败，请检查网络或缓存目录 {cache_dir}: {exc}"
                logger.error("{}", message)
                raise TranscriptionModelError(message) from exc
        return self._backend


def ensure_transcription_dependency() -> None:
    try:
        importlib.import_module("faster_whisper")
    except Exception as exc:
        raise TranscriptionDependencyError(
            f"未安装或无法加载 faster-whisper；请运行 {TRANSCRIBE_INSTALL_COMMAND}"
        ) from exc


def _create_faster_whisper_backend(options: TranscriptionOptions) -> TranscriptionBackend:
    try:
        module = importlib.import_module("faster_whisper")
        model_class = vars(module)["WhisperModel"]
    except Exception as exc:
        raise TranscriptionDependencyError(
            f"未安装或无法加载 faster-whisper；请运行 {TRANSCRIBE_INSTALL_COMMAND}"
        ) from exc
    cache_dir = options.model_cache_dir.expanduser().resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    model = model_class(
        options.model,
        device=options.device,
        compute_type=options.resolved_compute_type,
        download_root=str(cache_dir),
        local_files_only=options.offline,
    )
    return cast(TranscriptionBackend, model)


def _write_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _directory_has_entries(path: Path) -> bool:
    try:
        return path.is_dir() and next(path.iterdir(), None) is not None
    except OSError:
        return False
