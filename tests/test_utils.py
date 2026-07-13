from __future__ import annotations

import httpx
import pytest

from project.utils import InvalidUserUrlError, resolve_target, resolve_user_url


@pytest.mark.asyncio
async def test_resolve_target_accepts_direct_video_url() -> None:
    target = await resolve_target("https://www.douyin.com/video/7637452863689461026")

    assert target.mode == "single_video"
    assert target.target_id == "7637452863689461026"
    assert target.url == "https://www.douyin.com/video/7637452863689461026"


@pytest.mark.asyncio
async def test_resolve_target_follows_short_link_to_shared_video() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://v.douyin.com/example/"
        return httpx.Response(
            302,
            headers={
                "location": "https://www.iesdouyin.com/share/video/7637452863689461026/"
            },
            request=request,
        )

    target = await resolve_target(
        "复制打开抖音 https://v.douyin.com/example/",
        transport=httpx.MockTransport(handler),
    )

    assert target.mode == "single_video"
    assert target.target_id == "7637452863689461026"


@pytest.mark.asyncio
async def test_resolve_user_url_rejects_video_target() -> None:
    with pytest.raises(InvalidUserUrlError, match="不是用户主页"):
        await resolve_user_url("https://www.douyin.com/video/7637452863689461026")


@pytest.mark.asyncio
async def test_resolve_target_does_not_treat_note_as_video() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request)

    with pytest.raises(InvalidUserUrlError, match="用户主页或单视频"):
        await resolve_target(
            "https://www.douyin.com/note/7637452863689461026",
            transport=httpx.MockTransport(handler),
        )
