from __future__ import annotations

import json
from time import time

import pytest

from project.config import Settings
from project.login import create_authenticated_context, storage_state_has_session

AUTH_COOKIES = ("sessionid", "sessionid_ss")


def test_storage_state_has_session(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "sessionid_ss",
                        "value": "token",
                        "domain": ".douyin.com",
                        "expires": time() + 3600,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert storage_state_has_session(state_path, AUTH_COOKIES)


def test_storage_state_rejects_invalid_or_anonymous_state(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("not-json", encoding="utf-8")
    assert not storage_state_has_session(state_path, AUTH_COOKIES)

    state_path.write_text(json.dumps({"cookies": []}), encoding="utf-8")
    assert not storage_state_has_session(state_path, AUTH_COOKIES)


def test_storage_state_rejects_expired_or_foreign_cookie(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    for cookie in (
        {
            "name": "sessionid",
            "value": "token",
            "domain": ".douyin.com",
            "expires": time() - 1,
        },
        {
            "name": "sessionid",
            "value": "token",
            "domain": ".example.com",
            "expires": time() + 3600,
        },
    ):
        state_path.write_text(json.dumps({"cookies": [cookie]}), encoding="utf-8")
        assert not storage_state_has_session(state_path, AUTH_COOKIES)


@pytest.mark.asyncio
async def test_single_video_anonymous_context_ignores_saved_login_state(tmp_path) -> None:
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

    class FakeContext:
        pass

    context = FakeContext()

    class FakeBrowser:
        async def new_context(self, **kwargs):
            assert "storage_state" not in kwargs
            return context

    created = await create_authenticated_context(
        FakeBrowser(),  # type: ignore[arg-type]
        settings,
        allow_anonymous=True,
    )

    assert created is context
