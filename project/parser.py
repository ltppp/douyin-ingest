from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger

from project.filtering import ContentFilters, raw_duration_seconds
from project.models import CrawlResult, JsonObject, UserProfile, Video
from project.utils import normalize_scalar_text, write_json


def build_result(
    source_url: str,
    sec_user_id: str,
    raw_items: list[JsonObject],
    *,
    user_hint: UserProfile | None = None,
    download_user_agent: str | None = None,
    total_works: int | None = None,
    selection_limit: int | None = None,
    collection_mode: Literal["profile", "single_video"] = "profile",
    content_filters: ContentFilters | None = None,
) -> CrawlResult:
    filters = content_filters or ContentFilters()
    videos = [video for video in parse_videos(raw_items) if filters.matches_video(video)]
    ranked = sorted(
        videos,
        key=lambda video: (
            video.digg_count,
            video.publish_time or datetime.min.replace(tzinfo=UTC),
        ),
        reverse=True,
    )
    profile = extract_user_profile(raw_items, sec_user_id, user_hint=user_hint)
    return CrawlResult(
        source_url=source_url,
        collection_mode=collection_mode,
        user=profile,
        total_works=total_works if total_works is not None else len(videos),
        top1=ranked[0] if ranked else None,
        top10=ranked[:10],
        videos=ranked,
        selection_limit=selection_limit if selection_limit is not None else len(ranked),
        min_duration_seconds=filters.min_duration_seconds,
        max_duration_seconds=filters.max_duration_seconds,
        min_digg_count=filters.min_digg_count,
        download_headers=_download_headers(download_user_agent),
        crawled_at=datetime.now(UTC),
    )


def find_aweme_item(value: Any, target_aweme_id: str) -> JsonObject | None:
    if isinstance(value, dict):
        aweme_id = _string(value.get("aweme_id"))
        if aweme_id == target_aweme_id and isinstance(value.get("video"), dict):
            return value
        for child in value.values():
            item = find_aweme_item(child, target_aweme_id)
            if item is not None:
                return item
    elif isinstance(value, list):
        for child in value:
            item = find_aweme_item(child, target_aweme_id)
            if item is not None:
                return item
    return None


def extract_video_user_profile(item: JsonObject) -> UserProfile:
    author = item.get("author")
    if not isinstance(author, dict):
        return UserProfile(nickname="未知用户", sec_user_id="unknown")
    return UserProfile(
        nickname=_first_string(author, "nickname", "unique_id", "short_id") or "未知用户",
        sec_user_id=_first_string(author, "sec_uid", "sec_user_id") or "unknown",
        reported_work_count=_first_integer(author, "aweme_count", "work_count", "works_count"),
    )


def parse_videos(raw_items: list[JsonObject]) -> list[Video]:
    videos: list[Video] = []
    for item in raw_items:
        aweme_id = _string(item.get("aweme_id"))
        if not aweme_id:
            logger.warning("跳过缺少 aweme_id 的作品记录")
            continue
        statistics = item.get("statistics")
        stats = statistics if isinstance(statistics, dict) else item
        video_download_url = _extract_video_download_url(item)
        audio_download_url = _extract_audio_download_url(item)
        audio_kind = _extract_audio_kind(item)
        audio_requires_cookie = _audio_requires_cookie(item)
        direct_speech_audio = (
            audio_download_url
            if audio_kind == "original_sound" and not audio_requires_cookie
            else None
        )
        videos.append(
            Video(
                aweme_id=aweme_id,
                title=_first_string(item, "desc", "title", "caption") or "",
                duration_seconds=raw_duration_seconds(item),
                publish_time=_parse_timestamp(item.get("create_time")),
                digg_count=_integer(stats.get("digg_count")),
                comment_count=_integer(stats.get("comment_count")),
                share_count=_integer(stats.get("share_count")),
                collect_count=_optional_integer(
                    stats.get("collect_count", stats.get("collect_count_v2"))
                ),
                video_url=f"https://www.douyin.com/video/{aweme_id}",
                video_download_url=video_download_url,
                audio_download_url=audio_download_url,
                audio_title=_extract_audio_title(item),
                audio_requires_cookie=audio_requires_cookie,
                audio_kind=audio_kind,
                speech_audio_download_url=direct_speech_audio,
                speech_audio_source_url=video_download_url,
                speech_audio_requires_extraction=direct_speech_audio is None,
                cover_url=_extract_cover(item),
            )
        )
    return videos


def extract_user_profile(
    raw_items: list[JsonObject],
    sec_user_id: str,
    *,
    user_hint: UserProfile | None = None,
) -> UserProfile:
    if user_hint is not None and user_hint.sec_user_id == sec_user_id:
        return user_hint
    for item in raw_items:
        author = item.get("author")
        if not isinstance(author, dict):
            continue
        author_sec_id = _first_string(author, "sec_uid", "sec_user_id")
        if author_sec_id and author_sec_id != sec_user_id:
            continue
        nickname = _first_string(author, "nickname", "unique_id", "short_id")
        if nickname:
            return UserProfile(
                nickname=nickname,
                sec_user_id=author_sec_id or sec_user_id,
                reported_work_count=_first_integer(
                    author, "aweme_count", "work_count", "works_count"
                ),
            )
    logger.warning("无法从接口响应识别昵称，将使用“未知用户”占位")
    return UserProfile(nickname="未知用户", sec_user_id=sec_user_id)


def find_user_profile(value: Any, target_sec_user_id: str) -> UserProfile | None:
    if isinstance(value, dict):
        sec_user_id = _first_string(value, "sec_uid", "sec_user_id")
        nickname = _first_string(value, "nickname")
        if sec_user_id == target_sec_user_id and nickname:
            return UserProfile(
                nickname=nickname,
                sec_user_id=sec_user_id,
                reported_work_count=_first_integer(
                    value, "aweme_count", "work_count", "works_count"
                ),
            )
        for child in value.values():
            profile = find_user_profile(child, target_sec_user_id)
            if profile is not None:
                return profile
    elif isinstance(value, list):
        for child in value:
            profile = find_user_profile(child, target_sec_user_id)
            if profile is not None:
                return profile
    return None


def save_result(result: CrawlResult, path: Path) -> None:
    write_json(path, result.model_dump(mode="json"))
    logger.info("结果已保存: {}", path)


def _extract_cover(item: JsonObject) -> str | None:
    video = item.get("video")
    if not isinstance(video, dict):
        return None
    for key in ("cover", "origin_cover", "dynamic_cover"):
        image = video.get(key)
        if not isinstance(image, dict):
            continue
        url = _first_url(image)
        if url:
            return url
    return None


def _extract_video_download_url(item: JsonObject) -> str | None:
    video = item.get("video")
    if not isinstance(video, dict):
        return None
    for key in ("download_addr", "play_addr_h264", "play_addr", "play_addr_265"):
        address = video.get(key)
        if isinstance(address, dict):
            url = _first_url(address)
            if url:
                return url
    return None


def _extract_audio_download_url(item: JsonObject) -> str | None:
    music = item.get("music")
    if not isinstance(music, dict):
        return None
    play_url = music.get("play_url")
    return _first_url(play_url) if isinstance(play_url, dict) else None


def _extract_audio_title(item: JsonObject) -> str | None:
    music = item.get("music")
    if not isinstance(music, dict):
        return None
    return _first_string(music, "title", "author")


def _audio_requires_cookie(item: JsonObject) -> bool:
    music = item.get("music")
    return bool(music.get("is_audio_url_with_cookie")) if isinstance(music, dict) else False


def _extract_audio_kind(item: JsonObject) -> Literal["original_sound", "music", "unknown"]:
    music = item.get("music")
    if not isinstance(music, dict):
        return "unknown"
    return "original_sound" if music.get("is_original_sound") is True else "music"


def _first_url(value: dict[str, Any]) -> str | None:
    urls = value.get("url_list")
    if not isinstance(urls, list):
        return None
    return next((entry for entry in urls if isinstance(entry, str) and entry), None)


def _download_headers(user_agent: str | None) -> dict[str, str]:
    headers = {"Referer": "https://www.douyin.com/"}
    if user_agent:
        headers["User-Agent"] = user_agent
    return headers


def _parse_timestamp(value: Any) -> datetime | None:
    timestamp = _optional_integer(value)
    if timestamp is None or timestamp <= 0:
        return None
    if timestamp > 10_000_000_000:
        timestamp //= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _first_string(mapping: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = _string(mapping.get(key))
        if value:
            return value
    return None


def _first_integer(mapping: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _optional_integer(mapping.get(key))
        if value is not None and value >= 0:
            return value
    return None


def _string(value: Any) -> str | None:
    return normalize_scalar_text(value)


def _integer(value: Any) -> int:
    return _optional_integer(value) or 0


def _optional_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
