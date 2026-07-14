from __future__ import annotations

import json

from project.models import UserProfile
from project.parser import (
    build_result,
    find_aweme_item,
    find_user_profile,
    parse_videos,
    save_result,
)


def raw_video(aweme_id: str, digg_count: int, nickname: str = "测试用户") -> dict:
    return {
        "aweme_id": aweme_id,
        "desc": f"视频 {aweme_id}",
        "duration": 90_500,
        "create_time": 1_700_000_000,
        "statistics": {
            "digg_count": digg_count,
            "comment_count": "3",
            "share_count": 2,
            "collect_count": 1,
        },
        "author": {"sec_uid": "user", "nickname": nickname},
        "video": {
            "cover": {"url_list": [f"https://img.test/{aweme_id}.jpg"]},
            "play_addr_h264": {"url_list": [f"https://video.test/{aweme_id}.mp4"]},
        },
        "music": {
            "title": f"音频 {aweme_id}",
            "play_url": {"url_list": [f"https://audio.test/{aweme_id}.mp3"]},
            "is_audio_url_with_cookie": True,
            "is_original_sound": True,
        },
    }


def test_finds_target_aweme_inside_detail_response() -> None:
    target = raw_video("7637452863689461026", 48)
    payload = {"aweme_detail": target, "status_code": 0}

    assert find_aweme_item(payload, "7637452863689461026") is target
    assert find_aweme_item(payload, "missing") is None


def test_parses_video_fields() -> None:
    video = parse_videos([raw_video("123", 99)])[0]

    assert video.aweme_id == "123"
    assert video.title == "视频 123"
    assert video.duration_seconds == 90.5
    assert video.digg_count == 99
    assert video.comment_count == 3
    assert video.collect_count == 1
    assert video.video_url == "https://www.douyin.com/video/123"
    assert video.video_download_url == "https://video.test/123.mp4"
    assert video.audio_download_url == "https://audio.test/123.mp3"
    assert video.audio_title == "音频 123"
    assert video.audio_requires_cookie
    assert video.audio_kind == "original_sound"
    assert video.speech_audio_download_url is None
    assert video.speech_audio_source_url == "https://video.test/123.mp4"
    assert video.speech_audio_requires_extraction
    assert video.cover_url == "https://img.test/123.jpg"
    assert video.publish_time is not None


def test_cookie_free_original_sound_is_reported_as_direct_speech_audio() -> None:
    item = raw_video("123", 99)
    item["music"]["is_audio_url_with_cookie"] = False

    video = parse_videos([item])[0]

    assert video.speech_audio_download_url == "https://audio.test/123.mp3"
    assert not video.speech_audio_requires_extraction


def test_builds_ranked_result_and_uses_profile_hint() -> None:
    items = [raw_video(str(index), index) for index in range(12)]
    hint = UserProfile(nickname="Hint 用户", sec_user_id="user")
    result = build_result(
        "https://www.douyin.com/user/user",
        "user",
        items,
        user_hint=hint,
        download_user_agent="Browser UA",
    )

    assert result.user.nickname == "Hint 用户"
    assert result.total_works == 12
    assert result.top1 is not None and result.top1.digg_count == 11
    assert [video.digg_count for video in result.top10] == list(range(11, 1, -1))
    assert [video.digg_count for video in result.videos] == list(range(11, -1, -1))
    assert result.download_headers == {
        "Referer": "https://www.douyin.com/",
        "User-Agent": "Browser UA",
    }


def test_prefers_download_addr_over_playback_fallback() -> None:
    item = raw_video("123", 99)
    item["video"]["download_addr"] = {"url_list": ["https://video.test/download.mp4"]}

    video = parse_videos([item])[0]

    assert video.video_download_url == "https://video.test/download.mp4"


def test_background_music_is_not_reported_as_speech_audio() -> None:
    item = raw_video("123", 99)
    item["music"]["is_original_sound"] = False

    video = parse_videos([item])[0]

    assert video.audio_kind == "music"
    assert video.audio_download_url == "https://audio.test/123.mp3"
    assert video.speech_audio_download_url is None
    assert video.speech_audio_source_url == "https://video.test/123.mp4"
    assert video.speech_audio_requires_extraction


def test_finds_nested_profile_and_saves_json(tmp_path) -> None:
    profile = find_user_profile(
        {"data": {"user": {"sec_uid": "user", "nickname": "嵌套用户", "aweme_count": 12}}},
        "user",
    )
    assert profile == UserProfile(nickname="嵌套用户", sec_user_id="user", reported_work_count=12)

    result = build_result("https://www.douyin.com/user/user", "user", [], user_hint=profile)
    output = tmp_path / "result.json"
    save_result(result, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["user"]["nickname"] == "嵌套用户"
    assert "reported_work_count" not in payload["user"]
    assert payload["top1"] is None
