from __future__ import annotations

import json
from time import time

from project.login import storage_state_has_session

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
