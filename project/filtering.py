from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from project.models import JsonObject, Video


@dataclass(frozen=True, slots=True)
class ContentFilters:
    """Filter works before their popularity ranking is evaluated."""

    min_duration_seconds: float | None = None
    max_duration_seconds: float | None = None
    min_digg_count: int = 0

    def __post_init__(self) -> None:
        if self.min_duration_seconds is not None and (
            not math.isfinite(self.min_duration_seconds) or self.min_duration_seconds < 0
        ):
            raise ValueError("最短内容时长必须是有限的非负数")
        if self.max_duration_seconds is not None and (
            not math.isfinite(self.max_duration_seconds) or self.max_duration_seconds < 0
        ):
            raise ValueError("最长内容时长必须是有限的非负数")
        if (
            self.min_duration_seconds is not None
            and self.max_duration_seconds is not None
            and self.min_duration_seconds > self.max_duration_seconds
        ):
            raise ValueError("最短内容时长不能大于最长内容时长")
        if self.min_digg_count < 0:
            raise ValueError("最低点赞数必须是非负整数")

    @property
    def active(self) -> bool:
        return (
            self.min_duration_seconds is not None
            or self.max_duration_seconds is not None
            or self.min_digg_count > 0
        )

    def matches_raw(self, item: JsonObject) -> bool:
        if not self._matches_duration(raw_duration_seconds(item)):
            return False
        return raw_digg_count(item) >= self.min_digg_count

    def matches_video(self, video: Video) -> bool:
        if not self._matches_duration(video.duration_seconds):
            return False
        return video.digg_count >= self.min_digg_count

    def _matches_duration(self, duration_seconds: float | None) -> bool:
        if self.min_duration_seconds is None and self.max_duration_seconds is None:
            return True
        if duration_seconds is None:
            return False
        if self.min_duration_seconds is not None and duration_seconds < self.min_duration_seconds:
            return False
        return self.max_duration_seconds is None or duration_seconds <= self.max_duration_seconds


def raw_duration_seconds(item: JsonObject) -> float | None:
    video = item.get("video")
    containers = (item, video if isinstance(video, dict) else {})
    for container in containers:
        duration = _non_negative_float(container.get("duration"))
        if duration is not None:
            return duration / 1000.0
    return None


def raw_digg_count(item: JsonObject) -> int:
    statistics = item.get("statistics")
    stats = statistics if isinstance(statistics, dict) else item
    return _integer(stats.get("digg_count"))


def _non_negative_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0
