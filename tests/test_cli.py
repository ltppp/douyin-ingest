from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from loguru import logger

import project.cli as cli_module
from project.api import ApiError
from project.cli import (
    build_argument_parser,
    create_settings,
    execute,
    format_result,
    parse_cli_arguments,
)
from project.config import Settings
from project.models import CrawlResult, Transcription, UserProfile, Video
from project.transcription import TranscriptionDependencyError


def test_cli_settings_and_rendering(tmp_path) -> None:
    output = tmp_path / "custom.json"
    args = build_argument_parser().parse_args(
        ["https://www.douyin.com/user/user", "--headless", "--output", str(output)]
    )
    settings = create_settings(args)
    assert settings.browser_headless
    assert settings.output_path == output

    video = Video(aweme_id="1", title="标题", digg_count=9, video_url="https://video.test/1")
    result = CrawlResult(
        source_url="https://www.douyin.com/user/user",
        user=UserProfile(nickname="用户", sec_user_id="user"),
        total_works=1,
        top1=video,
        top10=[video],
        crawled_at=datetime.now(UTC),
    )
    rendered = format_result(result)
    assert "用户昵称: 用户" in rendered
    assert "全部作品数量: 1" in rendered
    assert "点赞 Top1:" in rendered
    assert "点赞 9" in rendered


@pytest.mark.asyncio
async def test_json_mode_keeps_stdout_machine_readable(tmp_path, monkeypatch, capsys) -> None:
    settings = Settings(
        output_path=tmp_path / "result.json",
        storage_state_path=tmp_path / "state.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    videos = [
        Video(
            aweme_id="1",
            title="第一条",
            digg_count=20,
            video_url="https://www.douyin.com/video/1",
            video_download_url="https://video.test/1.mp4",
            audio_download_url="https://audio.test/1.mp3",
            audio_kind="original_sound",
            speech_audio_download_url="https://audio.test/1.mp3",
            speech_audio_source_url="https://video.test/1.mp4",
            speech_audio_requires_extraction=False,
        ),
        Video(aweme_id="2", title="第二条", digg_count=5),
    ]
    result = CrawlResult(
        source_url="https://www.douyin.com/user/user",
        user=UserProfile(nickname="用户", sec_user_id="user"),
        total_works=2,
        top1=videos[0],
        top10=videos,
        videos=videos,
        download_headers={"Referer": "https://www.douyin.com/"},
        crawled_at=datetime.now(UTC),
    )

    async def fake_crawl(
        self,
        user_input,
        *,
        force_login=False,
        top_limit=None,
        cache_ttl_seconds=1800.0,
        refresh=False,
    ):
        logger.info("this must stay on stderr")
        return result

    monkeypatch.setattr(cli_module, "create_settings", lambda args: settings)
    monkeypatch.setattr(cli_module.DouyinCrawlerService, "crawl", fake_crawl)
    args = build_argument_parser().parse_args(
        ["https://www.douyin.com/user/user", "--json", "--limit", "1"]
    )

    assert await execute(args) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["returned_videos"] == 1
    assert payload["selection_limit"] == 10
    assert payload["cache_hit"] is False
    assert payload["videos"][0]["name"] == "第一条"
    assert payload["videos"][0]["video_download_url"] == "https://video.test/1.mp4"
    assert payload["videos"][0]["audio_download_url"] == "https://audio.test/1.mp3"
    assert payload["videos"][0]["speech_audio_download_url"] == "https://audio.test/1.mp3"
    assert payload["videos"][0]["speech_audio_requires_extraction"] is False
    assert "transcription" not in payload["videos"][0]
    assert "this must stay on stderr" in captured.err


@pytest.mark.asyncio
async def test_json_mode_reports_single_video_collection(tmp_path, monkeypatch, capsys) -> None:
    settings = Settings(
        output_path=tmp_path / "result.json",
        storage_state_path=tmp_path / "state.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    video = Video(aweme_id="7637452863689461026", title="单视频", digg_count=48)
    result = CrawlResult(
        source_url="https://www.douyin.com/video/7637452863689461026",
        collection_mode="single_video",
        user=UserProfile(nickname="作者", sec_user_id="author"),
        total_works=1,
        top1=video,
        top10=[video],
        videos=[video],
        selection_limit=1,
        crawled_at=datetime.now(UTC),
    )

    async def fake_crawl(self, user_input, **kwargs):
        return result

    monkeypatch.setattr(cli_module, "create_settings", lambda args: settings)
    monkeypatch.setattr(cli_module.DouyinCrawlerService, "crawl", fake_crawl)
    args = build_argument_parser().parse_args(
        ["https://www.douyin.com/video/7637452863689461026", "--json"]
    )

    assert await execute(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["collection_mode"] == "single_video"
    assert payload["returned_videos"] == 1
    assert payload["selection_limit"] == 1
    assert payload["videos"][0]["aweme_id"] == "7637452863689461026"


@pytest.mark.asyncio
async def test_json_mode_emits_structured_error(tmp_path, monkeypatch, capsys) -> None:
    settings = Settings(
        output_path=tmp_path / "result.json",
        storage_state_path=tmp_path / "state.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )

    async def fail_crawl(self, user_input, **kwargs):
        raise ApiError("request failed")

    monkeypatch.setattr(cli_module, "create_settings", lambda args: settings)
    monkeypatch.setattr(cli_module.DouyinCrawlerService, "crawl", fail_crawl)
    args = build_argument_parser().parse_args(["https://www.douyin.com/user/user", "--json"])

    assert await execute(args) == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "schema_version": "1.0",
        "ok": False,
        "error": {"type": "ApiError", "message": "采集失败: request failed"},
    }


@pytest.mark.asyncio
async def test_json_mode_emits_configuration_error(tmp_path, monkeypatch, capsys) -> None:
    settings = Settings(
        output_path=tmp_path / "result.json",
        storage_state_path=tmp_path / "state.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
        browser_headless=True,
    )
    monkeypatch.setattr(cli_module, "create_settings", lambda args: settings)
    args = build_argument_parser().parse_args(
        ["https://www.douyin.com/user/user", "--json", "--headless", "--force-login"]
    )

    assert await execute(args) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ValueError"


def test_json_mode_emits_argument_parser_error(capsys) -> None:
    parser = build_argument_parser()

    with pytest.raises(SystemExit) as exc_info:
        parse_cli_arguments(
            parser,
            ["https://www.douyin.com/user/user", "--json", "--limit", "-1"],
        )

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ValueError"
    assert "必须是非负整数" in payload["error"]["message"]


@pytest.mark.asyncio
async def test_json_mode_wraps_settings_validation_error(capsys) -> None:
    args = build_argument_parser().parse_args(
        ["https://www.douyin.com/user/user", "--json", "--headless", "--max-pages", "0"]
    )

    assert await execute(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "ValidationError"


@pytest.mark.asyncio
async def test_json_mode_wraps_unexpected_runtime_error(tmp_path, monkeypatch, capsys) -> None:
    settings = Settings(
        output_path=tmp_path / "result.json",
        storage_state_path=tmp_path / "state.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )

    async def fail_crawl(self, user_input, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(cli_module, "create_settings", lambda args: settings)
    monkeypatch.setattr(cli_module.DouyinCrawlerService, "crawl", fail_crawl)
    args = build_argument_parser().parse_args(["https://www.douyin.com/user/user", "--json"])

    assert await execute(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"] == {
        "type": "RuntimeError",
        "message": "未预期错误: unexpected",
    }


@pytest.mark.asyncio
async def test_transcribe_mode_materializes_audio_and_adds_agent_output(
    tmp_path, monkeypatch, capsys
) -> None:
    settings = Settings(
        output_path=tmp_path / "result.json",
        storage_state_path=tmp_path / "state.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    video = Video(aweme_id="1", digg_count=10)
    result = CrawlResult(
        source_url="https://www.douyin.com/user/user",
        user=UserProfile(nickname="用户", sec_user_id="user"),
        total_works=1,
        top1=Video(aweme_id="1", digg_count=10),
        top10=[Video(aweme_id="1", digg_count=10)],
        videos=[video],
        crawled_at=datetime.now(UTC),
    )
    audio = tmp_path / "speech_audio" / "1.speech.mp3"

    async def fake_crawl(self, user_input, **kwargs):
        return result

    async def fake_materialize(crawl_result, output_dir, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        audio.write_bytes(b"audio")
        crawl_result.videos[0].speech_audio_file = str(audio)

    service_instances = []

    class FakeService:
        def __init__(self, options) -> None:
            service_instances.append(self)

        def transcribe_videos(self, videos, output_dir) -> None:
            videos[0].transcription = Transcription(
                text="原始转写",
                language="zh",
                duration=1.5,
                model="base",
                segments=[],
                transcript_file=str(output_dir / "1.txt"),
                segments_file=str(output_dir / "1.segments.json"),
            )

    monkeypatch.setattr(cli_module, "create_settings", lambda args: settings)
    monkeypatch.setattr(cli_module.DouyinCrawlerService, "crawl", fake_crawl)
    monkeypatch.setattr(cli_module, "materialize_speech_audio", fake_materialize)
    monkeypatch.setattr(cli_module, "ensure_transcription_dependency", lambda: None)
    monkeypatch.setattr(cli_module, "TranscriptionService", FakeService)
    args = build_argument_parser().parse_args(
        ["https://www.douyin.com/user/user", "--json", "--limit", "1", "--transcribe"]
    )

    assert await execute(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(service_instances) == 1
    assert payload["videos"][0]["transcription"]["text"] == "原始转写"
    assert payload["videos"][0]["transcription"]["model"] == "base"
    persisted = json.loads(settings.output_path.read_text(encoding="utf-8"))
    assert persisted["videos"][0]["transcription"]["text"] == "原始转写"
    assert persisted["top1"]["transcription"]["text"] == "原始转写"
    assert persisted["top10"][0]["transcription"]["text"] == "原始转写"


@pytest.mark.asyncio
async def test_transcribe_mode_missing_dependency_is_structured_and_skips_crawl(
    tmp_path, monkeypatch, capsys
) -> None:
    settings = Settings(
        output_path=tmp_path / "result.json",
        storage_state_path=tmp_path / "state.json",
        debug_dir=tmp_path / "debug",
        log_path=tmp_path / "crawler.log",
    )
    crawl_called = False

    async def fake_crawl(self, user_input, **kwargs):
        nonlocal crawl_called
        crawl_called = True
        raise AssertionError("crawl should not run")

    def fail_dependency() -> None:
        raise TranscriptionDependencyError("missing faster-whisper")

    monkeypatch.setattr(cli_module, "create_settings", lambda args: settings)
    monkeypatch.setattr(cli_module.DouyinCrawlerService, "crawl", fake_crawl)
    monkeypatch.setattr(cli_module, "ensure_transcription_dependency", fail_dependency)
    args = build_argument_parser().parse_args(
        ["https://www.douyin.com/user/user", "--json", "--transcribe"]
    )

    assert await execute(args) == 1
    payload = json.loads(capsys.readouterr().out)
    assert crawl_called is False
    assert payload["error"]["type"] == "TranscriptionDependencyError"
    assert payload["error"]["fix_command"] == "pip install -e '.[transcribe]'"
