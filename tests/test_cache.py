from __future__ import annotations

from datetime import UTC, datetime, timedelta

from project.cache import load_cached_result
from project.filtering import ContentFilters
from project.models import CrawlResult, UserProfile, Video


def make_result(*, selection_limit: int, video_count: int, age_seconds: int = 0) -> CrawlResult:
    videos = [Video(aweme_id=str(index), digg_count=100 - index) for index in range(video_count)]
    return CrawlResult(
        source_url="https://www.douyin.com/user/user",
        user=UserProfile(nickname="用户", sec_user_id="user"),
        total_works=100,
        top1=videos[0] if videos else None,
        top10=videos[:10],
        videos=videos,
        selection_limit=selection_limit,
        crawled_at=datetime.now(UTC) - timedelta(seconds=age_seconds),
    )


def write_result(path, result: CrawlResult) -> None:
    path.write_text(result.model_dump_json(), encoding="utf-8")


def test_uses_recent_cache_that_covers_requested_top_n(tmp_path) -> None:
    path = tmp_path / "result.json"
    write_result(path, make_result(selection_limit=10, video_count=10))

    cached = load_cached_result(
        path,
        "https://www.douyin.com/user/user",
        requested_limit=5,
        ttl_seconds=1800,
    )

    assert cached is not None and cached.cache_hit
    assert len(cached.videos) == 5
    assert cached.selection_limit == 5
    assert len(cached.top10) == 5


def test_rejects_stale_or_too_small_cache(tmp_path) -> None:
    path = tmp_path / "result.json"
    write_result(path, make_result(selection_limit=10, video_count=10, age_seconds=3600))
    assert (
        load_cached_result(
            path,
            "https://www.douyin.com/user/user",
            requested_limit=5,
            ttl_seconds=1800,
        )
        is None
    )

    write_result(path, make_result(selection_limit=10, video_count=10))
    assert (
        load_cached_result(
            path,
            "https://www.douyin.com/user/user",
            requested_limit=50,
            ttl_seconds=1800,
        )
        is None
    )


def test_all_items_request_requires_full_cache(tmp_path) -> None:
    path = tmp_path / "result.json"
    write_result(path, make_result(selection_limit=10, video_count=10))
    assert (
        load_cached_result(
            path,
            "https://www.douyin.com/user/user",
            requested_limit=None,
            ttl_seconds=1800,
        )
        is None
    )


def test_rejects_legacy_cache_larger_than_its_selection_limit(tmp_path) -> None:
    path = tmp_path / "result.json"
    write_result(path, make_result(selection_limit=10, video_count=20))

    assert (
        load_cached_result(
            path,
            "https://www.douyin.com/user/user",
            requested_limit=10,
            ttl_seconds=1800,
        )
        is None
    )


def test_cache_requires_identical_content_filters(tmp_path) -> None:
    path = tmp_path / "result.json"
    result = make_result(selection_limit=10, video_count=2)
    result.min_duration_seconds = 30
    result.max_duration_seconds = 180
    result.min_digg_count = 1_000
    write_result(path, result)

    filters = ContentFilters(
        min_duration_seconds=30,
        max_duration_seconds=180,
        min_digg_count=1_000,
    )
    cached = load_cached_result(
        path,
        "https://www.douyin.com/user/user",
        requested_limit=10,
        ttl_seconds=1800,
        content_filters=filters,
    )

    assert cached is not None
    assert len(cached.videos) == 2
    assert (
        load_cached_result(
            path,
            "https://www.douyin.com/user/user",
            requested_limit=10,
            ttl_seconds=1800,
            content_filters=ContentFilters(min_duration_seconds=60, max_duration_seconds=180),
        )
        is None
    )
