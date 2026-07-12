from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import ParseResult, parse_qs, urljoin, urlparse

import httpx
from loguru import logger

from project.models import PathPart

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


async def resolve_user_url(value: str, request_timeout: float = 15.0) -> str:
    input_url = extract_url(value)
    parsed = urlparse(input_url)
    if parsed.netloc.lower() in {"www.douyin.com", "douyin.com"} and parsed.path.startswith(
        "/user/"
    ):
        return _canonical_user_url(parsed.path.split("/user/", 1)[1].split("/", 1)[0])

    current_url = input_url
    async with httpx.AsyncClient(follow_redirects=False, timeout=request_timeout) as client:
        for _ in range(6):
            response = await client.get(current_url, headers={"User-Agent": "Mozilla/5.0"})
            sec_user_id = _extract_sec_user_id(urlparse(str(response.url)))
            if sec_user_id:
                return _canonical_user_url(sec_user_id)

            location = response.headers.get("location")
            if response.is_redirect and location:
                current_url = urljoin(str(response.url), location)
                sec_user_id = _extract_sec_user_id(urlparse(current_url))
                if sec_user_id:
                    return _canonical_user_url(sec_user_id)
                continue
            response.raise_for_status()
            break

    raise InvalidUserUrlError(f"链接未解析到抖音用户主页: {current_url}")


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


def _canonical_user_url(sec_user_id: str) -> str:
    if not sec_user_id:
        raise InvalidUserUrlError("用户链接缺少 sec_user_id")
    return f"https://www.douyin.com/user/{sec_user_id}"


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
