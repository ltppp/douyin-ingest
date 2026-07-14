from __future__ import annotations

import httpx
import pytest

from project.api import (
    AuthenticationExpiredError,
    DouyinApiClient,
    PaginationError,
    SignatureRejectedError,
)
from project.config import Settings
from project.filtering import ContentFilters
from project.models import CapturedEndpoint, PaginationDescriptor, UserProfile


def make_endpoint(*, signed: bool = False, expected_count: int | None = None) -> CapturedEndpoint:
    return CapturedEndpoint(
        url="https://example.test/works?sec_user_id=user&max_cursor=0&count=2"
        + ("&a_bogus=stale" if signed else ""),
        headers={"user-agent": "browser", "cookie": "ignored=1", "accept-encoding": "br"},
        cookies={"sessionid": "token"},
        query={"sec_user_id": ["user"], "max_cursor": ["0"], "count": ["2"]},
        pagination=PaginationDescriptor(
            list_path=("aweme_list",),
            has_more_path=("has_more",),
            cursor_path=("max_cursor",),
            cursor_query_key="max_cursor",
        ),
        signature_query_keys=("a_bogus",) if signed else (),
        user_hint=(
            UserProfile(nickname="用户", sec_user_id="user", reported_work_count=expected_count)
            if expected_count is not None
            else None
        ),
    )


@pytest.mark.asyncio
async def test_fetches_all_pages_and_deduplicates() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        cursor = request.url.params["max_cursor"]
        if cursor == "0":
            return httpx.Response(
                200,
                json={
                    "aweme_list": [{"aweme_id": "1"}, {"aweme_id": "2"}],
                    "has_more": 1,
                    "max_cursor": 10,
                    "status_code": 0,
                },
            )
        return httpx.Response(
            200,
            json={
                "aweme_list": [{"aweme_id": "2"}, {"aweme_id": "3"}],
                "has_more": 0,
                "max_cursor": 20,
                "status_code": 0,
            },
        )

    client = DouyinApiClient(
        Settings(retry_backoff_seconds=0), transport=httpx.MockTransport(handler)
    )
    collection = await client.fetch_all(make_endpoint())

    assert [item["aweme_id"] for item in collection.items] == ["3", "2", "1"]
    assert collection.total_count == 3
    assert [request.url.params["max_cursor"] for request in requests] == ["0", "10"]
    assert requests[0].headers["user-agent"] == "browser"
    assert requests[0].headers["cookie"] == "sessionid=token"


@pytest.mark.asyncio
async def test_retries_timeout() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary", request=request)
        return httpx.Response(200, json={"aweme_list": [], "has_more": 0})

    client = DouyinApiClient(
        Settings(request_retries=1, retry_backoff_seconds=0),
        transport=httpx.MockTransport(handler),
    )
    collection = await client.fetch_all(make_endpoint())
    assert collection.items == []
    assert collection.total_count == 0
    assert attempts == 2


@pytest.mark.asyncio
async def test_detects_expired_cookie_on_first_request() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(403, request=request))
    client = DouyinApiClient(Settings(request_retries=0), transport=transport)

    with pytest.raises(AuthenticationExpiredError):
        await client.fetch_all(make_endpoint())


@pytest.mark.asyncio
async def test_reports_stale_signature_on_later_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["max_cursor"] == "0":
            return httpx.Response(
                200,
                json={"aweme_list": [{"aweme_id": "1"}], "has_more": 1, "max_cursor": 10},
            )
        return httpx.Response(403)

    client = DouyinApiClient(Settings(request_retries=0), transport=httpx.MockTransport(handler))
    with pytest.raises(SignatureRejectedError):
        await client.fetch_all(make_endpoint(signed=True))


@pytest.mark.asyncio
async def test_rejects_cursor_that_does_not_advance() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"aweme_list": [{"aweme_id": "1"}], "has_more": 1, "max_cursor": 0},
            request=request,
        )
    )
    client = DouyinApiClient(Settings(request_retries=0), transport=transport)

    with pytest.raises(PaginationError, match="游标重复"):
        await client.fetch_all(make_endpoint())


@pytest.mark.asyncio
async def test_rejects_empty_terminal_page_after_has_more() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["max_cursor"] == "0":
            return httpx.Response(
                200,
                json={"aweme_list": [{"aweme_id": "1"}], "has_more": 1, "max_cursor": 10},
            )
        return httpx.Response(200, json={"aweme_list": [], "has_more": 0, "max_cursor": 20})

    client = DouyinApiClient(Settings(request_retries=0), transport=httpx.MockTransport(handler))
    with pytest.raises(PaginationError, match="空列表提前终止"):
        await client.fetch_all(make_endpoint())


@pytest.mark.asyncio
async def test_rejects_result_below_reported_work_count() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"aweme_list": [{"aweme_id": "1"}], "has_more": 0},
            request=request,
        )
    )
    client = DouyinApiClient(Settings(request_retries=0), transport=transport)

    with pytest.raises(PaginationError, match="少于主页报告"):
        await client.fetch_all(make_endpoint(expected_count=2))


@pytest.mark.asyncio
async def test_records_without_aweme_id_do_not_satisfy_expected_count() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "aweme_list": [{"aweme_id": "1"}, {"desc": "invalid work"}],
                "has_more": 0,
            },
            request=request,
        )
    )
    client = DouyinApiClient(Settings(request_retries=0), transport=transport)

    with pytest.raises(PaginationError, match="仅返回 1 条"):
        await client.fetch_all(make_endpoint(expected_count=2))


@pytest.mark.asyncio
async def test_retains_only_exact_top_n_while_counting_all_works() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "aweme_list": [
                    {"aweme_id": "low", "statistics": {"digg_count": 1}},
                    {"aweme_id": "high", "statistics": {"digg_count": 100}},
                    {"aweme_id": "middle", "statistics": {"digg_count": 50}},
                ],
                "has_more": 0,
            },
            request=request,
        )
    )
    client = DouyinApiClient(Settings(request_retries=0), transport=transport)

    collection = await client.fetch_all(make_endpoint(), top_limit=2)

    assert collection.total_count == 3
    assert [item["aweme_id"] for item in collection.items] == ["high", "middle"]


@pytest.mark.asyncio
async def test_filters_duration_then_digg_count_before_popularity_ranking() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "aweme_list": [
                    {
                        "aweme_id": "too-short",
                        "duration": 10_000,
                        "statistics": {"digg_count": 1_000},
                    },
                    {
                        "aweme_id": "eligible-high",
                        "duration": 60_000,
                        "statistics": {"digg_count": 100},
                    },
                    {
                        "aweme_id": "below-digg",
                        "duration": 80_000,
                        "statistics": {"digg_count": 9},
                    },
                    {
                        "aweme_id": "eligible-low",
                        "video": {"duration": 120_000},
                        "statistics": {"digg_count": 50},
                    },
                    {
                        "aweme_id": "missing-duration",
                        "statistics": {"digg_count": 2_000},
                    },
                ],
                "has_more": 0,
            },
            request=request,
        )
    )
    client = DouyinApiClient(Settings(request_retries=0), transport=transport)

    collection = await client.fetch_all(
        make_endpoint(),
        top_limit=2,
        content_filters=ContentFilters(
            min_duration_seconds=30,
            max_duration_seconds=120,
            min_digg_count=10,
        ),
    )

    assert collection.total_count == 5
    assert [item["aweme_id"] for item in collection.items] == [
        "eligible-high",
        "eligible-low",
    ]


@pytest.mark.asyncio
async def test_later_complete_duplicate_can_pass_duration_filter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["max_cursor"] == "0":
            return httpx.Response(
                200,
                json={
                    "aweme_list": [
                        {"aweme_id": "overlap", "statistics": {"digg_count": 100}},
                        {
                            "aweme_id": "other",
                            "duration": 60_000,
                            "statistics": {"digg_count": 10},
                        },
                    ],
                    "has_more": 1,
                    "max_cursor": 10,
                },
            )
        return httpx.Response(
            200,
            json={
                "aweme_list": [
                    {
                        "aweme_id": "overlap",
                        "duration": 90_000,
                        "statistics": {"digg_count": 100},
                    }
                ],
                "has_more": 0,
                "max_cursor": 20,
            },
        )

    client = DouyinApiClient(
        Settings(retry_backoff_seconds=0), transport=httpx.MockTransport(handler)
    )

    collection = await client.fetch_all(
        make_endpoint(),
        top_limit=2,
        content_filters=ContentFilters(min_duration_seconds=30),
    )

    assert collection.total_count == 2
    assert [item["aweme_id"] for item in collection.items] == ["overlap", "other"]


@pytest.mark.asyncio
async def test_invalid_aweme_ids_do_not_count_or_displace_top_n() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={
                "aweme_list": [
                    {"aweme_id": None, "statistics": {"digg_count": 999}},
                    {"aweme_id": True, "statistics": {"digg_count": 998}},
                    {"aweme_id": "   ", "statistics": {"digg_count": 997}},
                    {"aweme_id": [], "statistics": {"digg_count": 996}},
                    {"aweme_id": "first", "statistics": {"digg_count": 10}},
                    {"aweme_id": 2, "statistics": {"digg_count": 9}},
                ],
                "has_more": 0,
            },
            request=request,
        )
    )
    client = DouyinApiClient(Settings(request_retries=0), transport=transport)

    collection = await client.fetch_all(make_endpoint(), top_limit=2)

    assert collection.total_count == 2
    assert [item["aweme_id"] for item in collection.items] == ["first", 2]
