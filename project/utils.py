from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, parse_qs, urljoin, urlparse

import httpx
from loguru import logger

from project.models import PathPart, ResolvedTarget

URL_PATTERN = re.compile(r"https?://[^\s]+")


class InvalidUserUrlError(ValueError):
    """Raised when input cannot be normalized to a Douyin user page."""


def setup_logging(log_path: Path, debug: bool = False) -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if debug else "INFO",
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )
    logger.add(
        log_path,
        level="DEBUG",
        rotation="10 MB",
        retention="14 days",
        encoding="utf-8",
    )


def extract_url(value: str) -> str:
    match = URL_PATTERN.search(value.strip())
    if match is None:
        raise InvalidUserUrlError("输入中未找到 HTTP(S) 链接")
    return match.group(0).rstrip(".,，。;；!！?？")


def normalize_scalar_text(value: Any) -> str | None:
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        result = str(value).strip()
        return result or None
    return None


async def resolve_target(
    value: str,
    request_timeout: float = 15.0,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ResolvedTarget:
    input_url = extract_url(value)
    target = _target_from_url(input_url)
    if target is not None:
        return target

    current_url = input_url
    async with httpx.AsyncClient(
        follow_redirects=False,
        timeout=request_timeout,
        transport=transport,
    ) as client:
        for _ in range(6):
            response = await client.get(current_url, headers={"User-Agent": "Mozilla/5.0"})
            target = _target_from_url(str(response.url))
            if target is not None:
                return target

            location = response.headers.get("location")
            if response.is_redirect and location:
                current_url = urljoin(str(response.url), location)
                target = _target_from_url(current_url)
                if target is not None:
                    return target
                continue
            response.raise_for_status()
            break

    raise InvalidUserUrlError(f"链接未解析到抖音用户主页或单视频: {current_url}")


async def resolve_user_url(value: str, request_timeout: float = 15.0) -> str:
    target = await resolve_target(value, request_timeout=request_timeout)
    if target.mode != "profile":
        raise InvalidUserUrlError(f"链接目标不是用户主页: {target.url}")
    return target.url


def _target_from_url(value: str) -> ResolvedTarget | None:
    parsed = urlparse(value)
    domain = parsed.netloc.lower().split(":", 1)[0]
    if domain not in {"douyin.com", "www.douyin.com", "www.iesdouyin.com", "iesdouyin.com"}:
        return None
    sec_user_id = _extract_sec_user_id(parsed)
    if sec_user_id:
        return ResolvedTarget(
            mode="profile",
            url=_canonical_user_url(sec_user_id),
            target_id=sec_user_id,
        )
    aweme_id = _extract_aweme_id(parsed)
    if aweme_id:
        return ResolvedTarget(
            mode="single_video",
            url=_canonical_video_url(aweme_id),
            target_id=aweme_id,
        )
    return None


def _extract_sec_user_id(parsed: ParseResult) -> str | None:
    if "/user/" in parsed.path:
        value = parsed.path.split("/user/", 1)[1].split("/", 1)[0]
        if value:
            return value
    query = parse_qs(parsed.query)
    for key in ("sec_uid", "sec_user_id"):
        if query.get(key):
            return query[key][0]
    return None


def _extract_aweme_id(parsed: ParseResult) -> str | None:
    parts = [part for part in parsed.path.split("/") if part]
    for marker in ("video",):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts) and parts[index + 1].isdigit():
                return parts[index + 1]
    query = parse_qs(parsed.query)
    for key in ("aweme_id", "item_id", "modal_id"):
        values = query.get(key)
        if values and values[0].isdigit():
            return values[0]
    return None


def _canonical_user_url(sec_user_id: str) -> str:
    if not sec_user_id:
        raise InvalidUserUrlError("用户链接缺少 sec_user_id")
    return f"https://www.douyin.com/user/{sec_user_id}"


def _canonical_video_url(aweme_id: str) -> str:
    if not aweme_id:
        raise InvalidUserUrlError("视频链接缺少 aweme_id")
    return f"https://www.douyin.com/video/{aweme_id}"


def get_by_path(value: Any, path: tuple[PathPart, ...]) -> Any:
    current = value
    for part in path:
        if isinstance(part, int) and isinstance(current, list):
            current = current[part]
        elif isinstance(part, str) and isinstance(current, dict):
            current = current[part]
        else:
            raise KeyError(path)
    return current


def write_json(path: Path, value: Any, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    if mode is not None:
        temporary.touch(mode=mode, exist_ok=True)
        temporary.chmod(mode)
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)
    if mode is not None:
        path.chmod(mode)
