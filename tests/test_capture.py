from __future__ import annotations

import asyncio
import stat

import pytest

from project.capture import _drain_tasks, _record_task_result, save_debug_capture
from project.config import Settings
from project.detector import (
    detect_pagination,
    detect_signature_keys,
    make_response_sample,
    response_matches_user,
)
from project.models import CapturedEndpoint, PaginationDescriptor


def test_detects_douyin_style_work_page() -> None:
    payload = {
        "aweme_list": [
            {
                "aweme_id": "one",
                "statistics": {"digg_count": 12, "comment_count": 2},
            }
        ],
        "has_more": 1,
        "max_cursor": 12345,
    }
    descriptor = detect_pagination(payload, {"max_cursor": ["0"], "count": ["18"]})

    assert descriptor is not None
    assert descriptor.list_path == ("aweme_list",)
    assert descriptor.has_more_path == ("has_more",)
    assert descriptor.cursor_path == ("max_cursor",)
    assert descriptor.cursor_query_key == "max_cursor"


def test_prefers_pagination_fields_near_work_list() -> None:
    payload = {
        "metadata": {"has_more": 0, "cursor": "wrong"},
        "data": {
            "works": [{"aweme_id": "one", "digg_count": 9}],
            "page": {"has_more": True, "cursor": "next"},
        },
    }
    descriptor = detect_pagination(payload, {"cursor": ["first"]})

    assert descriptor is not None
    assert descriptor.list_path == ("data", "works")
    assert descriptor.has_more_path == ("data", "page", "has_more")
    assert descriptor.cursor_path == ("data", "page", "cursor")


def test_rejects_json_without_work_statistics_or_pagination() -> None:
    assert detect_pagination({"items": [{"id": "one"}], "has_more": True}, {}) is None
    assert detect_pagination({"aweme_list": [], "status": "ok"}, {}) is None


def test_truncates_response_sample_and_detects_signatures() -> None:
    payload = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
    assert make_response_sample(payload, max_items=2) == {"items": [{"id": 1}, {"id": 2}]}
    assert detect_signature_keys({"a_bogus": ["x"], "cursor": ["0"]}) == ("a_bogus",)


def test_response_must_match_target_user() -> None:
    payload = {
        "aweme_list": [
            {
                "aweme_id": "one",
                "statistics": {"digg_count": 12},
                "author": {"sec_uid": "target"},
            }
        ],
        "has_more": 0,
    }
    descriptor = detect_pagination(payload, {})
    assert descriptor is not None

    assert response_matches_user(payload, {}, descriptor, "target")
    assert not response_matches_user(payload, {}, descriptor, "someone-else")
    assert not response_matches_user(
        payload, {"sec_user_id": ["someone-else"]}, descriptor, "someone-else"
    )


def test_query_only_matching_is_limited_to_empty_user_work_lists() -> None:
    payload = {"aweme_list": [], "has_more": 0}
    descriptor = detect_pagination(payload, {"sec_user_id": ["target"]})
    assert descriptor is not None

    assert response_matches_user(payload, {"sec_user_id": ["target"]}, descriptor, "target")
    assert not response_matches_user(payload, {"keyword": ["target"]}, descriptor, "target")


@pytest.mark.asyncio
async def test_response_task_drain_is_bounded() -> None:
    task = asyncio.create_task(asyncio.Event().wait())
    await _drain_tasks({task}, drain_timeout=0.01)
    assert task.cancelled()


@pytest.mark.asyncio
async def test_response_task_exception_is_retrieved() -> None:
    async def fail() -> None:
        raise RuntimeError("broken response")

    errors: list[BaseException] = []
    task = asyncio.create_task(fail())
    tasks = {task}
    task.add_done_callback(lambda done: _record_task_result(done, tasks, errors))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert not tasks
    assert isinstance(errors[0], RuntimeError)


def test_debug_capture_files_are_private(tmp_path) -> None:
    settings = Settings(
        storage_state_path=tmp_path / "storage.json",
        output_path=tmp_path / "result.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    endpoint = CapturedEndpoint(
        url="https://example.test/works?cursor=0",
        headers={"cookie": "secret"},
        cookies={"sessionid": "secret"},
        query={"cursor": ["0"]},
        pagination=PaginationDescriptor(list_path=("items",)),
        response_sample={"items": []},
    )
    save_debug_capture(endpoint, settings)

    for path in settings.debug_dir.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_debug_write_repairs_stale_temporary_file_permissions(tmp_path) -> None:
    settings = Settings(debug_dir=tmp_path / "debug")
    settings.debug_dir.mkdir()
    temporary = settings.debug_dir / "request_cookie.json.tmp"
    temporary.write_text("stale", encoding="utf-8")
    temporary.chmod(0o644)
    endpoint = CapturedEndpoint(
        url="https://example.test/works",
        cookies={"sessionid": "secret"},
        pagination=PaginationDescriptor(list_path=("items",)),
    )

    save_debug_capture(endpoint, settings)

    assert not temporary.exists()
    assert stat.S_IMODE((settings.debug_dir / "request_cookie.json").stat().st_mode) == 0o600
