from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qs, unquote, urlparse

from loguru import logger
from playwright.async_api import BrowserContext, Page, Response, async_playwright

from project.config import Settings
from project.detector import (
    detect_pagination,
    detect_signature_keys,
    make_response_sample,
    response_matches_user,
)
from project.login import create_authenticated_context, save_storage_state
from project.models import CapturedEndpoint, CapturedVideo, JsonObject, UserProfile
from project.parser import find_aweme_item, find_user_profile
from project.utils import write_json


class CaptureError(RuntimeError):
    """Raised when no suitable work-list endpoint is observed."""


class NetworkCapture:
    def __init__(self, settings: Settings, *, debug: bool = False) -> None:
        self.settings = settings
        self.debug = debug

    async def capture(self, user_url: str, *, force_login: bool = False) -> CapturedEndpoint:
        found: asyncio.Future[CapturedEndpoint] = asyncio.get_running_loop().create_future()
        profile_candidates: list[UserProfile] = []
        tasks: set[asyncio.Task[None]] = set()
        task_errors: list[BaseException] = []
        target_sec_user_id = urlparse(user_url).path.rsplit("/", 1)[-1]

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.settings.browser_headless)
            context = await create_authenticated_context(
                browser, self.settings, force_login=force_login
            )
            page = await context.new_page()
            page.set_default_navigation_timeout(self.settings.navigation_timeout_ms)

            def handle_response(response: Response) -> None:
                task = asyncio.create_task(
                    self._inspect_response(
                        response, context, found, profile_candidates, target_sec_user_id
                    )
                )
                tasks.add(task)
                task.add_done_callback(
                    lambda completed: _record_task_result(completed, tasks, task_errors)
                )

            page.on("response", handle_response)
            try:
                logger.info("打开用户主页并监听作品接口: {}", user_url)
                await page.goto(user_url, wait_until="domcontentloaded")
                endpoint = await asyncio.wait_for(
                    asyncio.shield(found), timeout=self.settings.capture_timeout_seconds
                )
                if self.settings.page_settle_seconds:
                    await asyncio.sleep(self.settings.page_settle_seconds)
                await _drain_tasks(tasks, self.settings.response_drain_timeout_seconds)
                if profile_candidates:
                    endpoint.user_hint = profile_candidates[0]
                await save_storage_state(context, self.settings.storage_state_path)
            except TimeoutError as exc:
                if task_errors:
                    raise CaptureError(
                        f"作品接口识别失败，响应处理出现异常: {task_errors[-1]}"
                    ) from task_errors[-1]
                raise CaptureError(
                    "未在限定时间内识别到作品列表接口；请确认登录有效且主页可正常展示作品"
                ) from exc
            finally:
                page.remove_listener("response", handle_response)
                await _cancel_tasks(tasks)
                await context.close()
                await browser.close()

        if self.debug:
            save_debug_capture(endpoint, self.settings)
        return endpoint

    async def capture_video(
        self,
        video_url: str,
        aweme_id: str,
        *,
        force_login: bool = False,
        anonymous: bool = False,
    ) -> CapturedVideo:
        found: asyncio.Future[CapturedVideo] = asyncio.get_running_loop().create_future()
        tasks: set[asyncio.Task[None]] = set()
        task_errors: list[BaseException] = []

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=self.settings.browser_headless)
            context = await create_authenticated_context(
                browser,
                self.settings,
                force_login=force_login,
                allow_anonymous=anonymous,
            )
            page = await context.new_page()
            page.set_default_navigation_timeout(self.settings.navigation_timeout_ms)

            def handle_response(response: Response) -> None:
                task = asyncio.create_task(
                    self._inspect_video_response(response, found, video_url, aweme_id)
                )
                tasks.add(task)
                task.add_done_callback(
                    lambda completed: _record_task_result(completed, tasks, task_errors)
                )

            page.on("response", handle_response)
            try:
                logger.info("打开单视频页面并监听详情接口: {}", video_url)
                await page.goto(video_url, wait_until="domcontentloaded")
                if self.debug:
                    current = urlparse(page.url)
                    logger.debug(
                        "单视频页面导航结果: domain={} path={}", current.netloc, current.path
                    )
                try:
                    captured = await asyncio.wait_for(
                        asyncio.shield(found), timeout=self.settings.capture_timeout_seconds
                    )
                except TimeoutError as exc:
                    item = await _find_video_in_page(page, aweme_id)
                    if item is None:
                        if task_errors:
                            raise CaptureError(
                                f"视频详情识别失败，响应处理出现异常: {task_errors[-1]}"
                            ) from task_errors[-1]
                        raise CaptureError(
                            "未在限定时间内识别到目标视频详情；请确认链接有效且登录状态可用"
                        ) from exc
                    user_agent = await page.evaluate("navigator.userAgent")
                    captured = CapturedVideo(
                        url=video_url,
                        item=item,
                        headers={"user-agent": str(user_agent)},
                    )
                await _drain_tasks(tasks, self.settings.response_drain_timeout_seconds)
            finally:
                page.remove_listener("response", handle_response)
                await _cancel_tasks(tasks)
                await context.close()
                await browser.close()

        if self.debug:
            save_debug_video_capture(captured, self.settings)
        return captured

    async def _inspect_video_response(
        self,
        response: Response,
        found: asyncio.Future[CapturedVideo],
        video_url: str,
        aweme_id: str,
    ) -> None:
        if self.debug:
            parsed = urlparse(response.url)
            content_type = response.headers.get("content-type", "").split(";", 1)[0]
            if "json" in content_type.lower() or response.request.resource_type == "document":
                logger.debug(
                    "单视频响应候选: status={} type={} domain={} path={}",
                    response.status,
                    content_type or "unknown",
                    parsed.netloc,
                    parsed.path,
                )
        if found.done() or not response.ok:
            return
        if "json" not in response.headers.get("content-type", "").lower():
            return
        try:
            payload = await response.json()
        except Exception as exc:
            logger.debug("忽略无法解析的视频 JSON 响应 {}: {}", response.url, exc)
            return
        item = find_aweme_item(payload, aweme_id)
        if item is None:
            return
        headers = {
            key.lower(): value for key, value in (await response.request.all_headers()).items()
        }
        logger.info("已识别目标视频详情接口: {}", urlparse(response.url).path)
        if not found.done():
            found.set_result(CapturedVideo(url=video_url, item=item, headers=headers))

    async def _inspect_response(
        self,
        response: Response,
        context: BrowserContext,
        found: asyncio.Future[CapturedEndpoint],
        profile_candidates: list[UserProfile],
        target_sec_user_id: str,
    ) -> None:
        if not response.ok:
            return
        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type:
            return
        try:
            payload = await response.json()
        except Exception as exc:
            logger.debug("忽略无法解析的 JSON 响应 {}: {}", response.url, exc)
            return
        if not isinstance(payload, dict):
            return

        profile = find_user_profile(payload, target_sec_user_id)
        if profile is not None:
            _store_profile_candidate(profile_candidates, profile)
        if found.done():
            return

        request = response.request
        if request.method.upper() != "GET":
            return
        query = parse_qs(urlparse(request.url).query, keep_blank_values=True)
        pagination = detect_pagination(payload, query)
        if pagination is None:
            return
        if not response_matches_user(payload, query, pagination, target_sec_user_id):
            return

        headers = {key.lower(): value for key, value in (await request.all_headers()).items()}
        cookies = {
            str(cookie["name"]): str(cookie["value"])
            for cookie in await context.cookies(request.url)
        }
        endpoint = CapturedEndpoint(
            url=request.url,
            method=request.method,
            headers=headers,
            cookies=cookies,
            query=query,
            pagination=pagination,
            signature_query_keys=detect_signature_keys(query),
            response_sample=make_response_sample(
                payload, max_items=self.settings.response_sample_items
            ),
            user_hint=profile_candidates[0] if profile_candidates else None,
        )
        logger.info("已自动识别作品接口: {}", urlparse(request.url).path)
        if endpoint.signature_query_keys:
            logger.warning(
                "请求包含疑似签名参数 {}；若签名绑定游标，直接 HTTP 翻页可能被拒绝",
                ", ".join(endpoint.signature_query_keys),
            )
        if not found.done():
            found.set_result(endpoint)


def save_debug_capture(endpoint: CapturedEndpoint, settings: Settings) -> None:
    write_json(settings.debug_dir / "request_headers.json", endpoint.headers, mode=0o600)
    write_json(settings.debug_dir / "request_cookie.json", endpoint.cookies, mode=0o600)
    write_json(settings.debug_dir / "request_query.json", endpoint.query, mode=0o600)
    write_json(settings.debug_dir / "response_sample.json", endpoint.response_sample, mode=0o600)
    logger.info("Debug 请求样本已保存到 {}", settings.debug_dir)


def save_debug_video_capture(captured: CapturedVideo, settings: Settings) -> None:
    write_json(settings.debug_dir / "request_headers.json", captured.headers, mode=0o600)
    write_json(settings.debug_dir / "video_response.json", captured.item, mode=0o600)
    logger.info("Debug 视频详情样本已保存到 {}", settings.debug_dir)


async def _find_video_in_page(page: Page, aweme_id: str) -> JsonObject | None:
    scripts = await page.locator("script").all_text_contents()
    for raw_text in scripts:
        for text in (raw_text, unquote(raw_text)):
            try:
                payload = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                continue
            item = find_aweme_item(payload, aweme_id)
            if item is not None:
                return item
    return None


def _store_profile_candidate(candidates: list[UserProfile], profile: UserProfile) -> None:
    if not candidates:
        candidates.append(profile)
    elif candidates[0].reported_work_count is None and profile.reported_work_count is not None:
        candidates[0] = profile


async def _drain_tasks(tasks: set[asyncio.Task[None]], drain_timeout: float) -> None:
    if not tasks:
        return
    _, pending = await asyncio.wait(tuple(tasks), timeout=drain_timeout)
    if pending:
        logger.debug("取消 {} 个超时的响应解析任务", len(pending))
        await _cancel_tasks(set(pending))


def _record_task_result(
    task: asyncio.Task[None],
    tasks: set[asyncio.Task[None]],
    errors: list[BaseException],
) -> None:
    tasks.discard(task)
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        errors.append(exception)
        logger.debug("响应解析任务异常: {}", exception)


async def _cancel_tasks(tasks: set[asyncio.Task[None]]) -> None:
    if not tasks:
        return
    for task in tuple(tasks):
        task.cancel()
    await asyncio.gather(*tuple(tasks), return_exceptions=True)
