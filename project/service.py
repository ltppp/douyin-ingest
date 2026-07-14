from __future__ import annotations

from urllib.parse import urlparse

from loguru import logger

from project.api import AuthenticationExpiredError, DouyinApiClient
from project.cache import load_cached_result
from project.capture import CaptureError, NetworkCapture
from project.config import Settings
from project.filtering import ContentFilters
from project.login import storage_state_has_session
from project.models import (
    CapturedEndpoint,
    CapturedVideo,
    CollectedWorks,
    CrawlResult,
    ResolvedTarget,
)
from project.parser import build_result, extract_video_user_profile, save_result
from project.utils import resolve_target


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
        min_duration_seconds: float | None = None,
        max_duration_seconds: float | None = None,
        min_digg_count: int = 0,
    ) -> CrawlResult:
        content_filters = ContentFilters(
            min_duration_seconds=min_duration_seconds,
            max_duration_seconds=max_duration_seconds,
            min_digg_count=min_digg_count,
        )
        target = await resolve_target(
            user_input, request_timeout=self.settings.request_timeout_seconds
        )
        requested_limit = 1 if target.mode == "single_video" else top_limit
        if not force_login and not refresh:
            cached = load_cached_result(
                self.settings.output_path,
                target.url,
                requested_limit=requested_limit,
                ttl_seconds=cache_ttl_seconds,
                content_filters=content_filters,
            )
            if cached is not None:
                save_result(cached, self.settings.output_path)
                return cached

        if target.mode == "single_video":
            result = await self._crawl_single_video(
                target,
                force_login=force_login,
                content_filters=content_filters,
            )
        else:
            result = await self._crawl_profile(
                target,
                force_login=force_login,
                top_limit=top_limit,
                content_filters=content_filters,
            )
        save_result(result, self.settings.output_path)
        return result

    async def _crawl_profile(
        self,
        target: ResolvedTarget,
        *,
        force_login: bool,
        top_limit: int | None,
        content_filters: ContentFilters,
    ) -> CrawlResult:
        user_url = target.url
        sec_user_id = urlparse(user_url).path.rsplit("/", 1)[-1]
        logger.info("目标用户 sec_user_id: {}", sec_user_id)

        had_saved_state = not force_login and storage_state_has_session(
            self.settings.storage_state_path, self.settings.auth_cookie_names
        )
        try:
            endpoint, collection = await self._collect(
                user_url,
                force_login=force_login,
                top_limit=top_limit,
                content_filters=content_filters,
            )
        except (AuthenticationExpiredError, CaptureError) as exc:
            if not had_saved_state or self.settings.browser_headless:
                raise
            logger.warning("已有登录状态可能失效，将自动重新扫码后重试一次: {}", exc)
            self.settings.storage_state_path.unlink(missing_ok=True)
            endpoint, collection = await self._collect(
                user_url,
                force_login=True,
                top_limit=top_limit,
                content_filters=content_filters,
            )

        result = build_result(
            user_url,
            sec_user_id,
            collection.items,
            user_hint=endpoint.user_hint,
            download_user_agent=endpoint.headers.get("user-agent"),
            total_works=collection.total_count,
            selection_limit=top_limit or 0,
            content_filters=content_filters,
        )
        return result

    async def _crawl_single_video(
        self,
        target: ResolvedTarget,
        *,
        force_login: bool,
        content_filters: ContentFilters,
    ) -> CrawlResult:
        logger.info("目标单视频 aweme_id: {}", target.target_id)
        had_saved_state = not force_login and storage_state_has_session(
            self.settings.storage_state_path, self.settings.auth_cookie_names
        )
        if force_login:
            captured = await self._capture_single_video(
                target,
                force_login=True,
                anonymous=False,
            )
        else:
            captured = await self._capture_single_video_with_fallback(
                target,
                had_saved_state=had_saved_state,
            )

        profile = extract_video_user_profile(captured.item)
        return build_result(
            target.url,
            profile.sec_user_id,
            [captured.item],
            user_hint=profile,
            download_user_agent=captured.headers.get("user-agent"),
            total_works=1,
            selection_limit=1,
            collection_mode="single_video",
            content_filters=content_filters,
        )

    async def _capture_single_video_with_fallback(
        self,
        target: ResolvedTarget,
        *,
        had_saved_state: bool,
    ) -> CapturedVideo:
        try:
            return await self._capture_single_video(
                target,
                force_login=False,
                anonymous=True,
            )
        except CaptureError as exc:
            if had_saved_state:
                logger.warning("匿名单视频采集失败，将使用已有登录状态重试一次: {}", exc)
                try:
                    return await self._capture_single_video(
                        target,
                        force_login=False,
                        anonymous=False,
                    )
                except CaptureError:
                    if self.settings.browser_headless:
                        raise
                    logger.warning("已有登录状态也无法采集，将重新扫码后再试一次")
                    self.settings.storage_state_path.unlink(missing_ok=True)
                    return await self._capture_single_video(
                        target,
                        force_login=True,
                        anonymous=False,
                    )
            if self.settings.browser_headless:
                raise
            logger.warning("匿名单视频采集失败，将扫码登录后重试一次: {}", exc)
            return await self._capture_single_video(
                target,
                force_login=True,
                anonymous=False,
            )

    async def _capture_single_video(
        self,
        target: ResolvedTarget,
        *,
        force_login: bool,
        anonymous: bool,
    ) -> CapturedVideo:
        return await NetworkCapture(self.settings, debug=self.debug).capture_video(
            target.url,
            target.target_id,
            force_login=force_login,
            anonymous=anonymous,
        )

    async def _collect(
        self,
        user_url: str,
        *,
        force_login: bool,
        top_limit: int | None,
        content_filters: ContentFilters,
    ) -> tuple[CapturedEndpoint, CollectedWorks]:
        endpoint = await NetworkCapture(self.settings, debug=self.debug).capture(
            user_url, force_login=force_login
        )
        collection = await DouyinApiClient(self.settings).fetch_all(
            endpoint,
            top_limit=top_limit,
            content_filters=content_filters,
        )
        return endpoint, collection
