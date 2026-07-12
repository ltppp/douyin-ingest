from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import httpx
from anyio import open_file
from loguru import logger

from project.models import CrawlResult, Video


class MediaExtractionError(RuntimeError):
    """Raised when a selected work cannot produce a usable speech-audio file."""


async def materialize_speech_audio(
    result: CrawlResult,
    output_dir: Path,
    *,
    request_timeout: float,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)
    ffprobe = shutil.which("ffprobe")
    async with httpx.AsyncClient(
        headers=result.download_headers,
        follow_redirects=True,
        timeout=request_timeout,
        transport=transport,
    ) as client:
        for index, video in enumerate(result.videos, start=1):
            if video.speech_audio_file:
                existing = await asyncio.to_thread(_resolve_path, video.speech_audio_file)
                if await asyncio.to_thread(_file_ready, existing):
                    video.speech_audio_file = str(existing)
                    video.speech_audio_requires_extraction = False
                    continue
            if ffprobe is None:
                raise MediaExtractionError("需要 FFprobe 验证新生成的口播音频文件")
            target = (output_dir / f"{video.aweme_id}.speech.mp3").resolve()
            if await _probe_audio(ffprobe, target):
                video.speech_audio_file = str(target)
                video.speech_audio_requires_extraction = False
                continue
            await asyncio.to_thread(target.unlink, missing_ok=True)
            logger.info("准备 Top{} 口播音频: {}", index, video.aweme_id)
            await _materialize_video_audio(client, video, target, ffprobe)
            video.speech_audio_file = str(target)
            video.speech_audio_requires_extraction = False


async def _materialize_video_audio(
    client: httpx.AsyncClient, video: Video, target: Path, ffprobe: str
) -> None:
    direct_url = video.speech_audio_download_url
    if direct_url and not video.audio_requires_cookie:
        try:
            await _download(client, direct_url, target, expected_kind="audio")
            if not await _probe_audio(ffprobe, target):
                raise MediaExtractionError("原声直链未返回有效音频流")
            return
        except (httpx.HTTPError, MediaExtractionError) as exc:
            logger.warning("原声直链下载失败，回退到视频音轨提取: {}", exc)

    source_url = video.speech_audio_source_url or video.video_download_url
    if not source_url:
        raise MediaExtractionError(f"作品 {video.aweme_id} 没有可用的音频或视频源")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise MediaExtractionError("需要 FFmpeg 才能从视频提取口播音轨")

    video_temp = target.with_suffix(".video.tmp")
    try:
        await _download(client, source_url, video_temp, expected_kind="video")
        await _run_ffmpeg(ffmpeg, video_temp, target)
        if not await _probe_audio(ffprobe, target):
            raise MediaExtractionError("FFmpeg 输出未包含有效音频流")
    finally:
        await asyncio.to_thread(video_temp.unlink, missing_ok=True)


async def _download(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    *,
    expected_kind: str,
) -> None:
    temporary = target.with_suffix(f"{target.suffix}.tmp")
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if not _content_type_matches(content_type, expected_kind):
                raise MediaExtractionError(f"{expected_kind} 地址返回了非媒体类型: {content_type}")
            async with await open_file(temporary, "wb") as file:
                async for chunk in response.aiter_bytes():
                    await file.write(chunk)
        if not await asyncio.to_thread(_file_ready, temporary):
            raise MediaExtractionError(f"媒体下载为空: {url}")
        await asyncio.to_thread(temporary.replace, target)
    finally:
        await asyncio.to_thread(temporary.unlink, missing_ok=True)


async def _run_ffmpeg(ffmpeg: str, source: Path, target: Path) -> None:
    process = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(target),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    target_ready = await asyncio.to_thread(_file_ready, target)
    if process.returncode != 0 or not target_ready:
        await asyncio.to_thread(target.unlink, missing_ok=True)
        detail = stderr.decode("utf-8", errors="replace")[-500:]
        raise MediaExtractionError(f"FFmpeg 提取音轨失败: {detail}")


async def _probe_audio(ffprobe: str, path: Path) -> bool:
    if not await asyncio.to_thread(_file_ready, path):
        return False
    process = await asyncio.create_subprocess_exec(
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name:format=format_name",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await process.communicate()
    if process.returncode != 0:
        return False
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    streams = payload.get("streams")
    media_format = payload.get("format")
    if not isinstance(streams, list) or not isinstance(media_format, dict):
        return False
    has_mp3_stream = any(
        isinstance(stream, dict) and stream.get("codec_name") == "mp3" for stream in streams
    )
    format_name = media_format.get("format_name")
    formats = set(format_name.split(",")) if isinstance(format_name, str) else set()
    return has_mp3_stream and "mp3" in formats


def _content_type_matches(content_type: str, expected_kind: str) -> bool:
    media_type = content_type.split(";", 1)[0].strip()
    if media_type in {"", "application/octet-stream", "binary/octet-stream"}:
        return True
    if expected_kind == "audio":
        return media_type.startswith("audio/")
    if expected_kind == "video":
        return media_type.startswith("video/") or media_type == "application/mp4"
    return False


def _file_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _resolve_path(value: str) -> Path:
    return Path(value).expanduser().resolve()
