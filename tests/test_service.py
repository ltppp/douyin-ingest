from __future__ import annotations

import json
from datetime import UTC, datetime
from time import time

import pytest

import project.service as service_module
from project.capture import CaptureError
from project.config import Settings
from project.models import (
    CapturedEndpoint,
    CapturedVideo,
    CollectedWorks,
    CrawlResult,
    PaginationDescriptor,
    ResolvedTarget,
    UserProfile,
    Video,
)
from project.service import DouyinCrawlerService


@pytest.mark.asyncio
async def test_service_collects_only_resolved_single_video(tmp_path, monkeypatch) -> None:
    settings = Settings(
        storage_state_path=tmp_path / "state.json",
        output_path=tmp_path / "result.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    raw_item = {
        "aweme_id": "7637452863689461026",
        "desc": "单视频",
        "statistics": {"digg_count": 48},
        "author": {"nickname": "小道叫麻瓜", "sec_uid": "author-sec-id"},
        "video": {"play_addr": {"url_list": ["https://video.test/single.mp4"]}},
    }
    capture_calls: list[tuple[str, str, bool, bool]] = []

    class FakeCapture:
        def __init__(self, settings, *, debug=False) -> None:
            pass

        async def capture(self, user_url, *, force_login=False):
            raise AssertionError("profile collection must not run for a video target")

        async def capture_video(
            self, video_url, aweme_id, *, force_login=False, anonymous=False
        ):
            capture_calls.append((video_url, aweme_id, force_login, anonymous))
            return CapturedVideo(
                url=video_url,
                item=raw_item,
                headers={"user-agent": "test-agent"},
            )

    async def fake_resolve(value, request_timeout=15.0):
        return ResolvedTarget(
            mode="single_video",
            url="https://www.douyin.com/video/7637452863689461026",
            target_id="7637452863689461026",
        )

    monkeypatch.setattr(service_module, "NetworkCapture", FakeCapture)
    monkeypatch.setattr(service_module, "resolve_target", fake_resolve)

    result = await DouyinCrawlerService(settings).crawl("short-video", top_limit=10)

    assert capture_calls == [
        (
            "https://www.douyin.com/video/7637452863689461026",
            "7637452863689461026",
            False,
            True,
        )
    ]
    assert result.collection_mode == "single_video"
    assert result.source_url == "https://www.douyin.com/video/7637452863689461026"
    assert result.total_works == 1
    assert result.selection_limit == 1
    assert [video.aweme_id for video in result.videos] == ["7637452863689461026"]
    assert result.user.nickname == "小道叫麻瓜"
    assert result.download_headers["User-Agent"] == "test-agent"


@pytest.mark.asyncio
async def test_single_video_can_be_excluded_by_duration_filter(tmp_path, monkeypatch) -> None:
    settings = Settings(
        storage_state_path=tmp_path / "state.json",
        output_path=tmp_path / "result.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )

    class FakeCapture:
        def __init__(self, settings, *, debug=False) -> None:
            pass

        async def capture_video(
            self, video_url, aweme_id, *, force_login=False, anonymous=False
        ):
            return CapturedVideo(
                url=video_url,
                item={
                    "aweme_id": aweme_id,
                    "duration": 15_000,
                    "author": {"nickname": "作者", "sec_uid": "author"},
                },
            )

    async def fake_resolve(value, request_timeout=15.0):
        return ResolvedTarget(
            mode="single_video",
            url="https://www.douyin.com/video/1",
            target_id="1",
        )

    monkeypatch.setattr(service_module, "NetworkCapture", FakeCapture)
    monkeypatch.setattr(service_module, "resolve_target", fake_resolve)

    result = await DouyinCrawlerService(settings).crawl(
        "short-video", min_duration_seconds=30
    )

    assert result.total_works == 1
    assert result.videos == []
    assert result.top1 is None
    assert result.min_duration_seconds == 30


@pytest.mark.asyncio
async def test_single_video_falls_back_to_saved_state_after_anonymous_failure(
    tmp_path, monkeypatch
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "sessionid",
                        "value": "saved",
                        "domain": ".douyin.com",
                        "expires": time() + 3600,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        browser_headless=True,
        storage_state_path=state_path,
        output_path=tmp_path / "result.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    attempts: list[tuple[bool, bool]] = []

    class FakeCapture:
        def __init__(self, settings, *, debug=False) -> None:
            pass

        async def capture_video(
            self, video_url, aweme_id, *, force_login=False, anonymous=False
        ):
            attempts.append((force_login, anonymous))
            if anonymous:
                raise CaptureError("anonymous blocked")
            return CapturedVideo(
                url=video_url,
                item={
                    "aweme_id": aweme_id,
                    "author": {"nickname": "作者", "sec_uid": "author"},
                    "video": {"play_addr": {"url_list": ["https://video.test/one.mp4"]}},
                },
            )

    async def fake_resolve(value, request_timeout=15.0):
        return ResolvedTarget(
            mode="single_video",
            url="https://www.douyin.com/video/1",
            target_id="1",
        )

    monkeypatch.setattr(service_module, "NetworkCapture", FakeCapture)
    monkeypatch.setattr(service_module, "resolve_target", fake_resolve)

    result = await DouyinCrawlerService(settings).crawl("short-video")

    assert attempts == [(False, True), (False, False)]
    assert result.collection_mode == "single_video"


@pytest.mark.asyncio
async def test_retries_once_with_forced_login_for_stale_saved_state(tmp_path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "sessionid",
                        "value": "old",
                        "domain": ".douyin.com",
                        "expires": time() + 3600,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        storage_state_path=state_path,
        output_path=tmp_path / "result.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    endpoint = CapturedEndpoint(
        url="https://example.test/works?cursor=0",
        query={"cursor": ["0"]},
        pagination=PaginationDescriptor(
            list_path=("items",), has_more_path=("has_more",), cursor_query_key="cursor"
        ),
        user_hint=UserProfile(nickname="用户", sec_user_id="user", reported_work_count=0),
    )
    force_login_values: list[bool] = []

    class FakeCapture:
        def __init__(self, settings, *, debug=False) -> None:
            pass

        async def capture(self, user_url, *, force_login=False):
            force_login_values.append(force_login)
            if len(force_login_values) == 1:
                raise CaptureError("expired")
            return endpoint

    class FakeApiClient:
        def __init__(self, settings) -> None:
            pass

        async def fetch_all(self, captured_endpoint, *, top_limit=None, content_filters=None):
            return CollectedWorks(items=[], total_count=0)

    async def fake_resolve(value, request_timeout=15.0):
        return ResolvedTarget(
            mode="profile",
            url="https://www.douyin.com/user/user",
            target_id="user",
        )

    monkeypatch.setattr(service_module, "NetworkCapture", FakeCapture)
    monkeypatch.setattr(service_module, "DouyinApiClient", FakeApiClient)
    monkeypatch.setattr(service_module, "resolve_target", fake_resolve)

    result = await DouyinCrawlerService(settings).crawl("short-url")

    assert force_login_values == [False, True]
    assert result.total_works == 0
    assert not state_path.exists()


@pytest.mark.asyncio
async def test_service_returns_recent_cache_without_browser(tmp_path, monkeypatch) -> None:
    settings = Settings(
        storage_state_path=tmp_path / "state.json",
        output_path=tmp_path / "result.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    videos = [
        Video(aweme_id=str(index), title=f"cached-{index}", digg_count=100 - index)
        for index in range(5)
    ]
    cached = CrawlResult(
        source_url="https://www.douyin.com/user/user",
        user=UserProfile(nickname="用户", sec_user_id="user"),
        total_works=100,
        top1=videos[0],
        top10=videos,
        videos=videos,
        selection_limit=5,
        crawled_at=datetime.now(UTC),
    )
    settings.output_path.write_text(cached.model_dump_json(), encoding="utf-8")

    class FailingCapture:
        def __init__(self, settings, *, debug=False) -> None:
            raise AssertionError("browser should not start on a cache hit")

    monkeypatch.setattr(service_module, "NetworkCapture", FailingCapture)

    result = await DouyinCrawlerService(settings).crawl(
        "https://www.douyin.com/user/user", top_limit=1
    )

    assert result.cache_hit
    assert result.videos[0].title == "cached-0"
    assert result.selection_limit == 1
    assert len(result.videos) == 1
    persisted = CrawlResult.model_validate_json(settings.output_path.read_text(encoding="utf-8"))
    assert persisted.selection_limit == 1
    assert len(persisted.videos) == 1
