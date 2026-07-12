from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from loguru import logger

from project import __version__
from project.agent_output import error_json
from project.transcription import (
    DEFAULT_MODEL_CACHE_DIR,
    TRANSCRIBE_INSTALL_COMMAND,
    TranscriptionDependencyError,
    TranscriptionError,
    TranscriptionOptions,
    TranscriptionService,
    ensure_transcription_dependency,
)

ServiceFactory = Callable[[TranscriptionOptions], TranscriptionService]
DependencyChecker = Callable[[], None]


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="douyin-transcribe",
        description="使用可选的 faster-whisper 后端保存原始机器转写。",
    )
    parser.add_argument("audio", type=Path, help="待转写的本地音频文件")
    parser.add_argument("--json", action="store_true", help="输出适合 Agent 解析的 JSON")
    parser.add_argument("--model", default="base", help="模型名称或本地模型路径（默认 base）")
    parser.add_argument("--device", default="cpu", help="推理设备（默认 cpu）")
    parser.add_argument(
        "--compute-type",
        help="CTranslate2 计算类型；CPU 未指定时默认 int8",
    )
    parser.add_argument("--language", default="zh", help="语言代码；使用 auto 自动检测")
    parser.add_argument("--beam-size", type=_positive_int, default=5, help="束搜索大小（默认 5）")
    parser.add_argument("--no-vad", action="store_true", help="关闭默认启用的 VAD")
    parser.add_argument("--offline", action="store_true", help="仅从本地缓存加载模型")
    parser.add_argument(
        "--model-cache-dir",
        type=Path,
        default=DEFAULT_MODEL_CACHE_DIR,
        help="模型下载与缓存目录",
    )
    parser.add_argument("--output-dir", type=Path, help="文本与 segments.json 输出目录")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def execute(
    args: argparse.Namespace,
    *,
    service_factory: ServiceFactory = TranscriptionService,
    dependency_checker: DependencyChecker = ensure_transcription_dependency,
) -> int:
    audio = args.audio.expanduser().resolve()
    output_dir = (
        args.output_dir.expanduser().resolve()
        if args.output_dir is not None
        else audio.parent / "transcripts"
    )
    options = TranscriptionOptions(
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=None if args.language == "auto" else args.language,
        beam_size=args.beam_size,
        vad_filter=not args.no_vad,
        model_cache_dir=args.model_cache_dir,
        offline=bool(args.offline),
    )
    try:
        dependency_checker()
        result = service_factory(options).transcribe_file(audio, output_dir)
    except TranscriptionDependencyError as exc:
        return _emit_error(args, exc, fix_command=TRANSCRIBE_INSTALL_COMMAND)
    except TranscriptionError as exc:
        return _emit_error(args, exc)
    if args.json:
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "ok": True,
                    "audio_file": str(audio),
                    "transcription": result.model_dump(mode="json"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    else:
        print(result.text)
        print(f"Transcript: {result.transcript_file}")
        print(f"Segments: {result.segments_file}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return execute(build_argument_parser().parse_args(argv))


def run() -> None:
    raise SystemExit(main())


def _emit_error(
    args: argparse.Namespace,
    error: BaseException,
    *,
    fix_command: str | None = None,
) -> int:
    logger.error("{}", error)
    if args.json:
        print(error_json(error, fix_command=fix_command))
    return 1


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


if __name__ == "__main__":
    run()
