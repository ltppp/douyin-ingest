from __future__ import annotations

import asyncio
import random
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from loguru import logger

from project.config import Settings
from project.filtering import ContentFilters
from project.models import CapturedEndpoint, CollectedWorks, JsonObject, RawPage
from project.ranking import TopWorkCollector
from project.utils import get_by_path


class ApiError(RuntimeError):
    """Base error for HTTP collection failures."""


class AuthenticationExpiredError(ApiError):
    """Raised when the captured browser session is no longer accepted."""


class SignatureRejectedError(ApiError):
    """Raised when a captured anti-bot signature cannot be reused after pagination."""


class ResponseSchemaError(ApiError):
    """Raised when a previously discovered response shape changes."""


class PaginationError(ApiError):
    """Raised when pagination says more data exists but provides no usable cursor."""


class DouyinApiClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    async def fetch_all(
        self,
        endpoint: CapturedEndpoint,
        *,
        top_limit: int | None = None,
        content_filters: ContentFilters | None = None,
    ) -> CollectedWorks:
        headers = _prepare_headers(endpoint.headers)
        timeout = httpx.Timeout(self.settings.request_timeout_seconds)
        collector = TopWorkCollector(top_limit, content_filters=content_filters)
        seen_cursors = _initial_cursors(endpoint)
        request_url = endpoint.url

        async with httpx.AsyncClient(
            headers=headers,
            cookies=endpoint.cookies,
            timeout=timeout,
            follow_redirects=True,
            http2=True,
            transport=self.transport,
        ) as client:
            for page_index in range(self.settings.max_pages):
                payload = await self._request_json(client, request_url, endpoint, page_index)
                page = _parse_page(payload, endpoint)
                added = collector.add(page.items)
                logger.info(
                    "HTTP 第 {} 页：返回 {} 条，新增 {} 条，累计 {} 条，保留 Top {}",
                    page_index + 1,
                    len(page.items),
                    added,
                    collector.total_count,
                    collector.retained_count,
                )

                if not page.has_more:
                    _validate_completion(collector.total_count, page, endpoint, page_index)
                    return collector.finish()
                cursor_key = endpoint.pagination.cursor_query_key
                if cursor_key is None or page.next_cursor in (None, ""):
                    raise PaginationError("接口声明 has_more=true，但未发现下一页游标")
                cursor_token = str(page.next_cursor)
                if cursor_token in seen_cursors:
                    raise PaginationError(f"分页游标重复，已停止以避免死循环: {cursor_token}")
                seen_cursors.add(cursor_token)
                request_url = _replace_query_value(endpoint.url, cursor_key, cursor_token)
                await self._page_delay()

        raise PaginationError(f"达到最大分页数 {self.settings.max_pages}，结果可能不完整")

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        request_url: str,
        endpoint: CapturedEndpoint,
        page_index: int,
    ) -> JsonObject:
        retries = self.settings.request_retries
        for attempt in range(retries + 1):
            try:
                response = await client.get(request_url)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= retries:
                    raise ApiError(f"请求在 {retries + 1} 次尝试后失败: {exc}") from exc
                await self._backoff(attempt, f"网络错误: {exc}")
                continue

            if response.status_code in {429} or response.status_code >= 500:
                if attempt < retries:
                    await self._backoff(attempt, f"HTTP {response.status_code}")
                    continue
            _raise_for_rejection(response, endpoint, page_index)

            try:
                payload = response.json()
            except ValueError as exc:
                if _looks_like_login_response(response):
                    raise AuthenticationExpiredError("响应跳转到登录页，cookie 已失效") from exc
                raise ApiError("作品接口未返回 JSON，可能触发了风控或接口已变化") from exc
            if not isinstance(payload, dict):
                raise ResponseSchemaError("作品接口 JSON 顶层不是对象")
            _raise_for_business_error(payload, endpoint, page_index)
            return payload
        raise AssertionError("unreachable")

    async def _backoff(self, attempt: int, reason: str) -> None:
        delay = self.settings.retry_backoff_seconds * (2**attempt)
        logger.warning("{}，{:.1f} 秒后重试", reason, delay)
        if delay:
            await asyncio.sleep(delay)

    async def _page_delay(self) -> None:
        if self.transport is not None:
            return
        delay = random.uniform(
            self.settings.page_delay_min_seconds,
            self.settings.page_delay_max_seconds,
        )
        if delay:
            logger.debug("分页节流等待 {:.2f} 秒", delay)
            await asyncio.sleep(delay)


def _parse_page(payload: JsonObject, endpoint: CapturedEndpoint) -> RawPage:
    pagination = endpoint.pagination
    try:
        raw_items = get_by_path(payload, pagination.list_path)
    except (KeyError, IndexError) as exc:
        raise ResponseSchemaError(f"作品列表路径已失效: {pagination.list_path}") from exc
    if not isinstance(raw_items, list):
        raise ResponseSchemaError(f"作品列表路径不再指向数组: {pagination.list_path}")

    items = [item for item in raw_items if isinstance(item, dict)]
    has_more = False
    if pagination.has_more_path is not None:
        try:
            has_more = _as_bool(get_by_path(payload, pagination.has_more_path))
        except (KeyError, IndexError) as exc:
            raise ResponseSchemaError(f"分页标记路径已失效: {pagination.has_more_path}") from exc

    next_cursor: str | int | None = None
    if pagination.cursor_path is not None:
        try:
            value = get_by_path(payload, pagination.cursor_path)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                next_cursor = value
        except (KeyError, IndexError) as exc:
            if has_more:
                raise ResponseSchemaError(f"分页游标路径已失效: {pagination.cursor_path}") from exc
    return RawPage(items=items, has_more=has_more, next_cursor=next_cursor)


def _prepare_headers(headers: Mapping[str, str]) -> dict[str, str]:
    blocked = {"accept-encoding", "connection", "content-length", "cookie", "host", "priority"}
    clean = {
        key: value
        for key, value in headers.items()
        if key.lower() not in blocked and not key.startswith(":")
    }
    clean.setdefault("accept", "application/json, text/plain, */*")
    return clean


def _validate_completion(
    total_count: int,
    page: RawPage,
    endpoint: CapturedEndpoint,
    page_index: int,
) -> None:
    if page_index > 0 and not page.items:
        raise PaginationError("后续分页以空列表提前终止，结果可能被风控截断")
    expected = endpoint.user_hint.reported_work_count if endpoint.user_hint else None
    if expected is not None and total_count < expected:
        raise PaginationError(f"接口仅返回 {total_count} 条，少于主页报告的 {expected} 条")


def _initial_cursors(endpoint: CapturedEndpoint) -> set[str]:
    key = endpoint.pagination.cursor_query_key
    if key is None:
        return set()
    return {str(value) for value in endpoint.query.get(key, [])}


def _replace_query_value(url: str, key: str, value: str) -> str:
    parsed = urlsplit(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    replaced = False
    updated: list[tuple[str, str]] = []
    for existing_key, existing_value in pairs:
        if existing_key == key:
            if not replaced:
                updated.append((key, value))
                replaced = True
            continue
        updated.append((existing_key, existing_value))
    if not replaced:
        updated.append((key, value))
    return urlunsplit(parsed._replace(query=urlencode(updated)))


def _raise_for_rejection(
    response: httpx.Response, endpoint: CapturedEndpoint, page_index: int
) -> None:
    if response.status_code in {401, 403}:
        if page_index > 0 and endpoint.signature_query_keys:
            raise SignatureRejectedError(
                "分页请求被拒绝：捕获的签名可能与原始游标绑定，无法直接复用"
            )
        raise AuthenticationExpiredError("请求被拒绝，登录 cookie 可能已失效")
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ApiError(f"作品接口返回 HTTP {response.status_code}") from exc


def _raise_for_business_error(
    payload: JsonObject, endpoint: CapturedEndpoint, page_index: int
) -> None:
    status = payload.get("status_code")
    if status in (None, 0, "0"):
        return
    message = _business_message(payload)
    lowered = message.lower()
    if any(marker in lowered for marker in ("login", "cookie", "passport", "登录", "过期")):
        raise AuthenticationExpiredError(f"登录状态失效: {message or status}")
    if page_index > 0 and endpoint.signature_query_keys:
        raise SignatureRejectedError(f"分页签名被服务端拒绝: {message or status}")
    raise ApiError(f"作品接口业务错误 {status}: {message}")


def _business_message(payload: JsonObject) -> str:
    for key in ("status_msg", "message", "msg", "description"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def _looks_like_login_response(response: httpx.Response) -> bool:
    url = str(response.url).lower()
    content = response.text[:500].lower()
    return any(marker in url or marker in content for marker in ("login", "passport", "登录"))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "none", "null"}
    return bool(value)
