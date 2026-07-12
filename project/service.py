from __future__ import annotations

from urllib.parse import urlparse

from loguru import logger

from project.api import AuthenticationExpiredError, DouyinApiClient
from project.cache import load_cached_result
from project.capture import CaptureError, NetworkCapture
from project.config import Settings
from project.login import storage_state_has_session
from project.models import CapturedEndpoint, CollectedWorks, CrawlResult
from project.parser import build_result, save_result
from project.utils import resolve_user_url


class DouyinCrawlerService:
    def __init__(self, settings: Settings, *, debug: bool = False) -> None:
        self.settings = settings
        self.debug = debug

    async def crawl(
        self,
        user_input: str,
        *,
        force_login: bool = False,
        top_limit: int | None = 10,
        cache_ttl_seconds: float = 1800.0,
        refresh: bool = False,
    ) -> CrawlResult:
        user_url = await resolve_user_url(
            user_input, request_timeout=self.settings.request_timeout_seconds
        )
        sec_user_id = urlparse(user_url).path.rsplit("/", 1)[-1]
        logger.info("目标用户 sec_user_id: {}", sec_user_id)

        if not force_login and not refresh:
            cached = load_cached_result(
                self.settings.output_path,
                user_url,
                requested_limit=top_limit,
                ttl_seconds=cache_ttl_seconds,
            )
            if cached is not None:
                save_result(cached, self.settings.output_path)
                return cached

        had_saved_state = not force_login and storage_state_has_session(
            self.settings.storage_state_path, self.settings.auth_cookie_names
        )
        try:
            endpoint, collection = await self._collect(
                user_url, force_login=force_login, top_limit=top_limit
            )
        except (AuthenticationExpiredError, CaptureError) as exc:
            if not had_saved_state or self.settings.browser_headless:
                raise
            logger.warning("已有登录状态可能失效，将自动重新扫码后重试一次: {}", exc)
            self.settings.storage_state_path.unlink(missing_ok=True)
            endpoint, collection = await self._collect(
                user_url, force_login=True, top_limit=top_limit
            )

        result = build_result(
            user_url,
            sec_user_id,
            collection.items,
            user_hint=endpoint.user_hint,
            download_user_agent=endpoint.headers.get("user-agent"),
            total_works=collection.total_count,
            selection_limit=top_limit or 0,
        )
        save_result(result, self.settings.output_path)
        return result

    async def _collect(
        self, user_url: str, *, force_login: bool, top_limit: int | None
    ) -> tuple[CapturedEndpoint, CollectedWorks]:
        endpoint = await NetworkCapture(self.settings, debug=self.debug).capture(
            user_url, force_login=force_login
        )
        collection = await DouyinApiClient(self.settings).fetch_all(endpoint, top_limit=top_limit)
        return endpoint, collection
