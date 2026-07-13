from __future__ import annotations

from pathlib import Path

from project.models import (
    AgentErrorDetail,
    AgentErrorOutput,
    AgentSuccessOutput,
    AgentVideo,
    CrawlResult,
    Video,
)


def success_json(
    result: CrawlResult,
    result_path: Path,
    *,
    limit: int,
    min_digg_count: int,
) -> str:
    videos = [video for video in result.videos if video.digg_count >= min_digg_count]
    if limit > 0:
        videos = videos[:limit]
    output = AgentSuccessOutput(
        collection_mode=result.collection_mode,
        user=result.user,
        total_works=result.total_works,
        returned_videos=len(videos),
        selection_limit=result.selection_limit,
        cache_hit=result.cache_hit,
        result_file=str(result_path),
        download_headers=result.download_headers,
        crawled_at=result.crawled_at,
        videos=[_agent_video(video) for video in videos],
    )
    return output.model_dump_json()


def error_json(
    error: BaseException,
    message: str | None = None,
    *,
    fix_command: str | None = None,
) -> str:
    output = AgentErrorOutput(
        error=AgentErrorDetail(
            type=type(error).__name__,
            message=message or str(error),
            fix_command=fix_command,
        )
    )
    return output.model_dump_json(exclude_none=True)


def _agent_video(video: Video) -> AgentVideo:
    return AgentVideo(
        aweme_id=video.aweme_id,
        name=video.title,
        digg_count=video.digg_count,
        comment_count=video.comment_count,
        share_count=video.share_count,
        collect_count=video.collect_count,
        publish_time=video.publish_time,
        page_url=video.video_url,
        video_download_url=video.video_download_url,
        audio_download_url=video.audio_download_url,
        audio_title=video.audio_title,
        audio_requires_cookie=video.audio_requires_cookie,
        audio_kind=video.audio_kind,
        speech_audio_download_url=video.speech_audio_download_url,
        speech_audio_source_url=video.speech_audio_source_url,
        speech_audio_requires_extraction=video.speech_audio_requires_extraction,
        speech_audio_file=video.speech_audio_file,
        transcription=video.transcription,
        cover_url=video.cover_url,
    )
