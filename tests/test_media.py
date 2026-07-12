from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

import project.media as media_module
from project.media import MediaExtractionError, _download, _probe_audio, materialize_speech_audio
from project.models import CrawlResult, UserProfile, Video


def make_result(video: Video) -> CrawlResult:
    return CrawlResult(
        source_url="https://www.douyin.com/user/user",
        user=UserProfile(nickname="用户", sec_user_id="user"),
        total_works=1,
        top1=video,
        top10=[video],
        videos=[video],
        selection_limit=1,
        crawled_at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_downloads_direct_original_sound(tmp_path) -> None:
    video = Video(
        aweme_id="1",
        speech_audio_download_url="https://media.test/audio.mp3",
        speech_audio_requires_extraction=False,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=b"audio", headers={"content-type": "audio/mpeg"}
        )
    )

    async def valid_audio(ffprobe, path) -> bool:
        return path.is_file() and path.read_bytes() == b"audio"

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(media_module, "_probe_audio", valid_audio)
    monkeypatch.setattr(media_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    await materialize_speech_audio(
        make_result(video),
        tmp_path,
        request_timeout=5,
        transport=transport,
    )

    assert video.speech_audio_file is not None
    assert (tmp_path / "1.speech.mp3").read_bytes() == b"audio"
    monkeypatch.undo()


@pytest.mark.asyncio
async def test_extracts_video_track_when_direct_speech_audio_is_missing(
    tmp_path, monkeypatch
) -> None:
    video = Video(
        aweme_id="2",
        video_download_url="https://media.test/video.mp4",
        speech_audio_source_url="https://media.test/video.mp4",
        speech_audio_requires_extraction=True,
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"video", headers={"content-type": "video/mp4"})
    )

    async def fake_ffmpeg(ffmpeg, source, target) -> None:
        assert source.read_bytes() == b"video"
        target.write_bytes(b"speech audio")

    async def valid_audio(ffprobe, path) -> bool:
        return path.is_file() and path.read_bytes() == b"speech audio"

    monkeypatch.setattr(media_module, "_run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(media_module, "_probe_audio", valid_audio)
    monkeypatch.setattr(media_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    await materialize_speech_audio(
        make_result(video),
        tmp_path,
        request_timeout=5,
        transport=transport,
    )

    assert video.speech_audio_file is not None
    assert (tmp_path / "2.speech.mp3").read_bytes() == b"speech audio"
    assert not video.speech_audio_requires_extraction
    assert not (tmp_path / "2.speech.video.tmp").exists()


@pytest.mark.asyncio
async def test_html_from_direct_audio_falls_back_to_video_extraction(tmp_path, monkeypatch) -> None:
    video = Video(
        aweme_id="3",
        speech_audio_download_url="https://media.test/audio.mp3",
        speech_audio_source_url="https://media.test/video.mp4",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("audio.mp3"):
            return httpx.Response(
                200, content=b"<html>blocked</html>", headers={"content-type": "text/html"}
            )
        return httpx.Response(200, content=b"video", headers={"content-type": "video/mp4"})

    async def fake_ffmpeg(ffmpeg, source, target) -> None:
        target.write_bytes(b"valid speech")

    async def valid_audio(ffprobe, path) -> bool:
        return path.is_file() and path.read_bytes() == b"valid speech"

    monkeypatch.setattr(media_module, "_run_ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(media_module, "_probe_audio", valid_audio)
    monkeypatch.setattr(media_module.shutil, "which", lambda name: f"/usr/bin/{name}")

    await materialize_speech_audio(
        make_result(video),
        tmp_path,
        request_timeout=5,
        transport=httpx.MockTransport(handler),
    )

    assert (tmp_path / "3.speech.mp3").read_bytes() == b"valid speech"


@pytest.mark.asyncio
async def test_audio_download_rejects_video_content_type(tmp_path) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            content=b"video payload",
            headers={"content-type": "video/mp4"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(MediaExtractionError, match="audio 地址返回了非媒体类型"):
            await _download(
                client,
                "https://media.test/not-audio.mp4",
                tmp_path / "speech.mp3",
                expected_kind="audio",
            )


@pytest.mark.asyncio
async def test_probe_rejects_non_mp3_audio_container(tmp_path, monkeypatch) -> None:
    target = tmp_path / "speech.mp3"
    target.write_bytes(b"not really mp3")

    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (
                b'{"streams":[{"codec_name":"aac"}],"format":{"format_name":"mov,mp4,m4a"}}',
                b"",
            )

    async def fake_subprocess(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(media_module.asyncio, "create_subprocess_exec", fake_subprocess)

    assert not await _probe_audio("ffprobe", target)


@pytest.mark.asyncio
async def test_materialize_reuses_existing_speech_audio_file(tmp_path, monkeypatch) -> None:
    existing = tmp_path / "existing.mp3"
    existing.write_bytes(b"existing audio")
    video = Video(
        aweme_id="existing",
        speech_audio_file=str(existing),
        speech_audio_requires_extraction=True,
    )

    async def unexpected_materialize(*args, **kwargs) -> None:
        raise AssertionError("existing speech audio should be reused")

    monkeypatch.setattr(media_module, "_materialize_video_audio", unexpected_materialize)
    monkeypatch.setattr(media_module.shutil, "which", lambda name: None)

    await materialize_speech_audio(
        make_result(video),
        tmp_path / "new-output",
        request_timeout=5,
    )

    assert video.speech_audio_file == str(existing.resolve())
    assert video.speech_audio_requires_extraction is False
