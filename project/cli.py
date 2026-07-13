from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import httpx
from loguru import logger
from playwright.async_api import Error as PlaywrightError

from project import __version__
from project.agent_output import error_json, success_json
from project.api import ApiError
from project.capture import CaptureError
from project.config import DEFAULT_SETTINGS, Settings
from project.login import AuthenticationError
from project.media import MediaExtractionError, materialize_speech_audio
from project.models import CrawlResult, Video
from project.parser import save_result
from project.service import DouyinCrawlerService
from project.transcription import (
    DEFAULT_MODEL_CACHE_DIR,
    TRANSCRIBE_INSTALL_COMMAND,
    TranscriptionDependencyError,
    TranscriptionError,
    TranscriptionOptions,
    TranscriptionService,
    ensure_transcription_dependency,
)
from project.utils import InvalidUserUrlError, setup_logging


class AgentArgumentParser(argparse.ArgumentParser):
    _json_requested = False

    def error(self, message: str) -> NoReturn:
        if self._json_requested:
            print(error_json(ValueError(message), f"参数错误: {message}"))
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\n")


def build_argument_parser() -> AgentArgumentParser:
    parser = AgentArgumentParser(
        prog="douyin-ingest",
        description="自动识别用户主页或单视频，采集作品元数据与媒体地址。",
    )
    parser.add_argument("user", help="抖音用户主页、单视频、短链或包含链接的分享文案")
    parser.add_argument("--debug", action="store_true", help="保存请求与响应调试样本")
    parser.add_argument("--force-login", action="store_true", help="忽略已有状态并重新扫码登录")
    parser.add_argument(
        "--headless", action="store_true", help="使用无头浏览器（需要已有登录状态）"
    )
    parser.add_argument("--output", type=Path, help="结果 JSON 路径")
    parser.add_argument("--login-timeout", type=float, help="扫码登录超时秒数")
    parser.add_argument("--capture-timeout", type=float, help="Network 接口发现超时秒数")
    parser.add_argument("--max-pages", type=int, help="最大分页数")
    parser.add_argument("--page-delay-min", type=_non_negative_float, help="分页最小等待秒数")
    parser.add_argument("--page-delay-max", type=_non_negative_float, help="分页最大等待秒数")
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
        help="stdout 输出格式",
    )
    parser.add_argument(
        "--json",
        dest="output_format",
        action="store_const",
        const="json",
        help="等价于 --format json，供 Agent 调用",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=10,
        help="JSON 与结果文件保留的视频数，0 表示全部",
    )
    parser.add_argument(
        "--min-digg-count",
        type=_non_negative_int,
        default=0,
        help="JSON 仅返回不低于该点赞数的作品",
    )
    parser.add_argument(
        "--cache-ttl",
        type=_non_negative_float,
        default=1800.0,
        help="结果缓存秒数，0 表示禁用缓存",
    )
    parser.add_argument("--refresh", action="store_true", help="忽略结果缓存并重新扫描")
    parser.add_argument(
        "--speech-audio-dir",
        type=Path,
        help="下载/提取 Top N 的口播音轨到指定目录",
    )
    parser.add_argument("--transcribe", action="store_true", help="转写 Top N 的原始口播音频")
    parser.add_argument("--model", default="base", help="转写模型名称或本地路径（默认 base）")
    parser.add_argument("--device", default="cpu", help="转写推理设备（默认 cpu）")
    parser.add_argument("--compute-type", help="转写计算类型；CPU 未指定时默认 int8")
    parser.add_argument("--language", default="zh", help="转写语言代码；使用 auto 自动检测")
    parser.add_argument("--beam-size", type=_positive_int, default=5, help="转写束搜索大小")
    parser.add_argument("--no-vad", action="store_true", help="关闭转写默认启用的 VAD")
    parser.add_argument("--offline", action="store_true", help="转写模型仅从本地缓存加载")
    parser.add_argument(
        "--model-cache-dir",
        type=Path,
        default=DEFAULT_MODEL_CACHE_DIR,
        help="faster-whisper 模型缓存目录",
    )
    parser.add_argument("--transcript-dir", type=Path, help="原始文本与 segments.json 输出目录")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def parse_cli_arguments(
    parser: AgentArgumentParser, args: Sequence[str] | None = None
) -> argparse.Namespace:
    raw_args = list(args) if args is not None else sys.argv[1:]
    parser._json_requested = _arguments_request_json(raw_args)
    return parser.parse_args(raw_args)


def create_settings(args: argparse.Namespace) -> Settings:
    values = DEFAULT_SETTINGS.model_dump()
    values["browser_headless"] = bool(args.headless)
    if args.output is not None:
        values["output_path"] = args.output.expanduser().resolve()
    if args.login_timeout is not None:
        values["login_timeout_seconds"] = args.login_timeout
    if args.capture_timeout is not None:
        values["capture_timeout_seconds"] = args.capture_timeout
    if args.max_pages is not None:
        values["max_pages"] = args.max_pages
    if args.page_delay_min is not None:
        values["page_delay_min_seconds"] = args.page_delay_min
    if args.page_delay_max is not None:
        values["page_delay_max_seconds"] = args.page_delay_max
    return Settings.model_validate(values)


async def execute(args: argparse.Namespace) -> int:
    try:
        settings = create_settings(args)
        settings.ensure_directories()
        setup_logging(settings.log_path, debug=bool(args.debug))
        if args.force_login and args.headless:
            error = ValueError("--force-login 不能与 --headless 同时使用")
            return _emit_error(args, error, str(error), exit_code=2)
        if args.transcribe:
            ensure_transcription_dependency()

        result = await DouyinCrawlerService(settings, debug=bool(args.debug)).crawl(
            args.user,
            force_login=bool(args.force_login),
            top_limit=args.limit or None,
            cache_ttl_seconds=args.cache_ttl,
            refresh=bool(args.refresh),
        )
        if args.speech_audio_dir is not None or args.transcribe:
            audio_dir = (
                args.speech_audio_dir.expanduser().resolve()
                if args.speech_audio_dir is not None
                else settings.output_path.parent / "speech_audio"
            )
            await materialize_speech_audio(
                result,
                audio_dir,
                request_timeout=settings.request_timeout_seconds,
            )
        if args.transcribe:
            transcript_dir = (
                args.transcript_dir.expanduser().resolve()
                if args.transcript_dir is not None
                else settings.output_path.parent / "transcripts"
            )
            service = TranscriptionService(_transcription_options(args))
            await asyncio.to_thread(service.transcribe_videos, result.videos, transcript_dir)
            _sync_transcriptions(result)
        if args.speech_audio_dir is not None or args.transcribe:
            save_result(result, settings.output_path)
        if args.output_format == "json":
            print(
                success_json(
                    result,
                    settings.output_path,
                    limit=args.limit,
                    min_digg_count=args.min_digg_count,
                )
            )
        else:
            print(format_result(result))
        return 0
    except (
        InvalidUserUrlError,
        AuthenticationError,
        CaptureError,
        ApiError,
        MediaExtractionError,
    ) as exc:
        return _emit_error(args, exc, f"采集失败: {exc}")
    except PlaywrightError as exc:
        message = f"浏览器启动或执行失败: {exc}。首次安装请运行 playwright install chromium"
        return _emit_error(args, exc, message)
    except httpx.HTTPError as exc:
        return _emit_error(args, exc, f"解析用户链接失败: {exc}")
    except TranscriptionDependencyError as exc:
        return _emit_error(
            args,
            exc,
            f"转写不可用: {exc}",
            fix_command=TRANSCRIBE_INSTALL_COMMAND,
        )
    except TranscriptionError as exc:
        return _emit_error(args, exc, f"转写失败: {exc}")
    except KeyboardInterrupt:
        logger.warning("用户取消执行")
        return 130
    except Exception as exc:
        return _emit_error(args, exc, f"未预期错误: {exc}")


def _emit_error(
    args: argparse.Namespace,
    error: BaseException,
    message: str,
    *,
    exit_code: int = 1,
    fix_command: str | None = None,
) -> int:
    logger.error("{}", message)
    if args.output_format == "json":
        print(error_json(error, message, fix_command=fix_command))
    return exit_code


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是非负整数")
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("必须是非负数")
    return parsed


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return parsed


def _transcription_options(args: argparse.Namespace) -> TranscriptionOptions:
    return TranscriptionOptions(
        model=args.model,
        device=args.device,
        compute_type=args.compute_type,
        language=None if args.language == "auto" else args.language,
        beam_size=args.beam_size,
        vad_filter=not args.no_vad,
        model_cache_dir=args.model_cache_dir,
        offline=bool(args.offline),
    )


def _sync_transcriptions(result: CrawlResult) -> None:
    by_id = {video.aweme_id: video.transcription for video in result.videos}
    if result.top1 is not None:
        result.top1.transcription = by_id.get(result.top1.aweme_id)
    for video in result.top10:
        video.transcription = by_id.get(video.aweme_id)


def _arguments_request_json(args: Sequence[str]) -> bool:
    if "--json" in args or "--format=json" in args:
        return True
    return any(
        value == "--format" and index + 1 < len(args) and args[index + 1] == "json"
        for index, value in enumerate(args)
    )


def format_result(result: CrawlResult) -> str:
    selected = result.videos or result.top10
    if result.collection_mode == "single_video":
        lines = [
            "采集模式: 单视频",
            f"作者昵称: {result.user.nickname}",
            f"sec_user_id: {result.user.sec_user_id}",
            "",
            "目标视频:",
        ]
        lines.append(_format_video(1, selected[0]) if selected else "无作品")
        return "\n".join(lines)
    lines = [
        "采集模式: 用户主页",
        f"用户昵称: {result.user.nickname}",
        f"sec_user_id: {result.user.sec_user_id}",
        f"全部作品数量: {result.total_works}",
        "",
        "点赞最高的视频 (Top1):",
        _format_video(1, result.top1) if result.top1 else "无作品",
        "",
        f"点赞 Top{len(selected)}:",
    ]
    lines.extend(_format_video(index, video) for index, video in enumerate(selected, start=1))
    if not selected:
        lines.append("无作品")
    return "\n".join(lines)


def _format_video(rank: int, video: Video) -> str:
    published = video.publish_time.isoformat() if video.publish_time else "未知时间"
    return (
        f"{rank:>2}. 点赞 {video.digg_count:<10} | {published} | "
        f"{video.title or '(无标题)'} | {video.video_url}"
    )


def run() -> None:
    args = parse_cli_arguments(build_argument_parser())
    try:
        exit_code = asyncio.run(execute(args))
    except KeyboardInterrupt:
        exit_code = 130
    raise SystemExit(exit_code)
