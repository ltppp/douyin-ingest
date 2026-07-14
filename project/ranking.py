from __future__ import annotations

import heapq
from typing import Any

from project.filtering import ContentFilters, raw_digg_count
from project.models import CollectedWorks, JsonObject
from project.utils import normalize_scalar_text

type RankingKey = tuple[int, int, str]
type HeapEntry = tuple[int, int, str, JsonObject]


class TopWorkCollector:
    """Count all unique works while retaining only the highest-ranked items."""

    def __init__(self, limit: int | None, *, content_filters: ContentFilters | None = None) -> None:
        self.limit = limit if limit is not None and limit > 0 else None
        self.content_filters = content_filters or ContentFilters()
        self.seen_aweme_ids: set[str] = set()
        self._accepted_aweme_ids: set[str] = set()
        self._heap: list[HeapEntry] = []
        self._all_items: list[JsonObject] = []

    @property
    def total_count(self) -> int:
        return len(self.seen_aweme_ids)

    @property
    def retained_count(self) -> int:
        return len(self._heap) if self.limit is not None else len(self._all_items)

    def add(self, incoming: list[JsonObject]) -> int:
        before = self.total_count
        for item in incoming:
            aweme_id = normalize_scalar_text(item.get("aweme_id"))
            if aweme_id is None:
                continue
            self.seen_aweme_ids.add(aweme_id)
            if aweme_id in self._accepted_aweme_ids:
                continue
            if not self.content_filters.matches_raw(item):
                continue
            self._accepted_aweme_ids.add(aweme_id)
            if self.limit is None:
                self._all_items.append(item)
                continue
            key = _ranking_key(item, aweme_id)
            entry = (*key, item)
            if len(self._heap) < self.limit:
                heapq.heappush(self._heap, entry)
            elif key > self._heap[0][:3]:
                heapq.heapreplace(self._heap, entry)
        return self.total_count - before

    def finish(self) -> CollectedWorks:
        if self.limit is None:
            items = sorted(
                self._all_items,
                key=lambda item: _ranking_key(
                    item, normalize_scalar_text(item.get("aweme_id")) or ""
                ),
                reverse=True,
            )
        else:
            items = [entry[3] for entry in sorted(self._heap, reverse=True)]
        return CollectedWorks(items=items, total_count=self.total_count)


def _ranking_key(item: JsonObject, aweme_id: str) -> RankingKey:
    return (
        raw_digg_count(item),
        _integer(item.get("create_time")),
        aweme_id,
    )


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0
