from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from time import monotonic
from time import time as epoch_time
from typing import Any

from loguru import logger
from playwright.async_api import Browser, BrowserContext
from playwright.async_api import Error as PlaywrightError

from project.config import Settings


class AuthenticationError(RuntimeError):
    """Raised when an authenticated browser context cannot be established."""


def storage_state_has_session(path: Path, auth_cookie_names: tuple[str, ...]) -> bool:
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("登录状态文件不可读，将重新登录: {}", path)
        return False
    cookies = payload.get("cookies", []) if isinstance(payload, dict) else []
    return _cookies_have_session(cookies, auth_cookie_names)


async def create_authenticated_context(
    browser: Browser,
    settings: Settings,
    *,
    force_login: bool = False,
    allow_anonymous: bool = False,
) -> BrowserContext:
    state_path = settings.storage_state_path
    use_saved_state = not force_login and not allow_anonymous and storage_state_has_session(
        state_path, settings.auth_cookie_names
    )
    try:
        context = await _new_context(browser, state_path if use_saved_state else None)
    except PlaywrightError as exc:
        if not use_saved_state:
            raise
        logger.warning("加载登录状态失败，将重新登录: {}", exc)
        use_saved_state = False
        context = await _new_context(browser, None)

    if use_saved_state:
        logger.info("已加载登录状态: {}", state_path)
        return context

    if allow_anonymous and not force_login:
        logger.info("没有有效登录状态，将先尝试匿名访问单视频页面")
        return context

    if settings.browser_headless:
        await context.close()
        raise AuthenticationError("没有有效登录状态；首次登录必须使用有头浏览器")

    try:
        await _perform_interactive_login(context, settings)
        await save_storage_state(context, state_path)
    except Exception:
        await context.close()
        raise
    return context


async def _new_context(browser: Browser, state_path: Path | None) -> BrowserContext:
    kwargs: dict[str, Any] = {
        "viewport": {"width": 1440, "height": 900},
        "locale": "zh-CN",
    }
    if state_path is not None:
        kwargs["storage_state"] = str(state_path)
    return await browser.new_context(**kwargs)


async def _perform_interactive_login(context: BrowserContext, settings: Settings) -> None:
    page = await context.new_page()
    page.set_default_navigation_timeout(settings.navigation_timeout_ms)
    logger.info("首次运行：请在打开的抖音页面中完成扫码登录")
    await page.goto(settings.home_url, wait_until="domcontentloaded")

    deadline = monotonic() + settings.login_timeout_seconds
    while monotonic() < deadline:
        cookies = await context.cookies()
        if _cookies_have_session(cookies, settings.auth_cookie_names):
            logger.info("检测到登录 cookie，登录成功")
            await page.close()
            return
        await asyncio.sleep(1.0)

    await page.close()
    raise AuthenticationError(
        f"等待扫码登录超时（{settings.login_timeout_seconds:.0f} 秒），请重新运行"
    )


def _cookies_have_session(cookies: Any, auth_cookie_names: tuple[str, ...]) -> bool:
    if not isinstance(cookies, list):
        return False
    expected = {name.lower() for name in auth_cookie_names}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name", "")).lower()
        value = cookie.get("value")
        domain = str(cookie.get("domain", "")).lower().lstrip(".")
        expires = cookie.get("expires")
        domain_valid = domain == "douyin.com" or domain.endswith(".douyin.com")
        expiry_valid = (
            not isinstance(expires, (int, float)) or expires <= 0 or expires > epoch_time()
        )
        if name in expected and isinstance(value, str) and value and domain_valid and expiry_valid:
            return True
    return False


async def save_storage_state(context: BrowserContext, state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_path.with_suffix(f"{state_path.suffix}.tmp")
    await context.storage_state(path=temporary)
    temporary.replace(state_path)
    os.chmod(state_path, 0o600)
    logger.info("登录状态已保存: {}", state_path)
