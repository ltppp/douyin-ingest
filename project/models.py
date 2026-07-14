from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

type PathPart = str | int
type JsonObject = dict[str, Any]


def _is_none(value: object) -> bool:
    return value is None


class Cookie(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    value: str
    domain: str = ""
    path: str = "/"


class PaginationDescriptor(BaseModel):
    list_path: tuple[PathPart, ...]
    has_more_path: tuple[PathPart, ...] | None = None
    cursor_path: tuple[PathPart, ...] | None = None
    cursor_query_key: str | None = None


class ResolvedTarget(BaseModel):
    mode: Literal["profile", "single_video"]
    url: str
    target_id: str


class UserProfile(BaseModel):
    nickname: str
    sec_user_id: str
    reported_work_count: int | None = Field(default=None, ge=0, exclude=True)


class CapturedEndpoint(BaseModel):
    url: str
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    query: dict[str, list[str]] = Field(default_factory=dict)
    pagination: PaginationDescriptor
    signature_query_keys: tuple[str, ...] = ()
    response_sample: JsonObject = Field(default_factory=dict)
    user_hint: UserProfile | None = None


class CapturedVideo(BaseModel):
    url: str
    item: JsonObject
    headers: dict[str, str] = Field(default_factory=dict)


class RawPage(BaseModel):
    items: list[JsonObject] = Field(default_factory=list)
    has_more: bool = False
    next_cursor: str | int | None = None


class CollectedWorks(BaseModel):
    items: list[JsonObject] = Field(default_factory=list)
    total_count: int = Field(ge=0)


class TranscriptionSegment(BaseModel):
    id: int = Field(ge=0)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    text: str


class Transcription(BaseModel):
    text: str
    language: str
    duration: float = Field(ge=0)
    model: str
    segments: list[TranscriptionSegment] = Field(default_factory=list)
    transcript_file: str
    segments_file: str


class Video(BaseModel):
    aweme_id: str
    title: str = ""
    duration_seconds: float | None = Field(default=None, ge=0)
    publish_time: datetime | None = None
    digg_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    collect_count: int | None = None
    video_url: str | None = None
    video_download_url: str | None = None
    audio_download_url: str | None = None
    audio_title: str | None = None
    audio_requires_cookie: bool = False
    audio_kind: Literal["original_sound", "music", "unknown"] = "unknown"
    speech_audio_download_url: str | None = None
    speech_audio_source_url: str | None = None
    speech_audio_requires_extraction: bool = True
    speech_audio_file: str | None = None
    transcription: Transcription | None = Field(default=None, exclude_if=_is_none)
    cover_url: str | None = None


class CrawlResult(BaseModel):
    source_url: str
    collection_mode: Literal["profile", "single_video"] = "profile"
    user: UserProfile
    total_works: int
    top1: Video | None = None
    top10: list[Video] = Field(default_factory=list)
    videos: list[Video] = Field(default_factory=list)
    selection_limit: int = Field(default=10, ge=0)
    min_duration_seconds: float | None = Field(default=None, ge=0)
    max_duration_seconds: float | None = Field(default=None, ge=0)
    min_digg_count: int = Field(default=0, ge=0)
    cache_hit: bool = False
    download_headers: dict[str, str] = Field(default_factory=dict)
    crawled_at: datetime


class AgentVideo(BaseModel):
    aweme_id: str
    name: str
    duration_seconds: float | None = Field(default=None, ge=0)
    digg_count: int
    comment_count: int
    share_count: int
    collect_count: int | None = None
    publish_time: datetime | None = None
    page_url: str | None = None
    video_download_url: str | None = None
    audio_download_url: str | None = None
    audio_title: str | None = None
    audio_requires_cookie: bool = False
    audio_kind: Literal["original_sound", "music", "unknown"] = "unknown"
    speech_audio_download_url: str | None = None
    speech_audio_source_url: str | None = None
    speech_audio_requires_extraction: bool = True
    speech_audio_file: str | None = None
    transcription: Transcription | None = Field(default=None, exclude_if=_is_none)
    cover_url: str | None = None


class AgentSuccessOutput(BaseModel):
    schema_version: str = "1.0"
    ok: Literal[True] = True
    collection_mode: Literal["profile", "single_video"] = "profile"
    user: UserProfile
    total_works: int
    returned_videos: int
    selection_limit: int
    cache_hit: bool
    result_file: str
    media_urls_are_temporary: bool = True
    download_headers: dict[str, str] = Field(default_factory=dict)
    crawled_at: datetime
    videos: list[AgentVideo] = Field(default_factory=list)


class AgentErrorDetail(BaseModel):
    type: str
    message: str
    fix_command: str | None = None


class AgentErrorOutput(BaseModel):
    schema_version: str = "1.0"
    ok: Literal[False] = False
    error: AgentErrorDetail
