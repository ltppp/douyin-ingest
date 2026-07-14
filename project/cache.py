from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import ValidationError

from project.filtering import ContentFilters
from project.models import CrawlResult


def load_cached_result(
    path: Path,
    source_url: str,
    *,
    requested_limit: int | None,
    ttl_seconds: float,
    content_filters: ContentFilters | None = None,
) -> CrawlResult | None:
    filters = content_filters or ContentFilters()
    if ttl_seconds <= 0 or not path.is_file():
        return None
    try:
        result = CrawlResult.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        logger.warning("忽略不可用的结果缓存 {}: {}", path, exc)
        return None
    if result.source_url != source_url:
        return None
    age = (datetime.now(UTC) - result.crawled_at).total_seconds()
    if age < 0 or age > ttl_seconds:
        return None
    if not _cache_matches_filters(result, filters):
        return None
    if not _cache_covers_limit(result, requested_limit, filters_active=filters.active):
        return None
    _trim_to_requested_limit(result, requested_limit)
    result.cache_hit = True
    logger.info("命中 {:.0f} 秒内的结果缓存，不再启动浏览器或请求作品分页", age)
    return result


def _cache_matches_filters(result: CrawlResult, filters: ContentFilters) -> bool:
    return (
        result.min_duration_seconds == filters.min_duration_seconds
        and result.max_duration_seconds == filters.max_duration_seconds
        and result.min_digg_count == filters.min_digg_count
    )


def _cache_covers_limit(
    result: CrawlResult, requested_limit: int | None, *, filters_active: bool
) -> bool:
    requested = requested_limit or 0
    cached = result.selection_limit
    if cached > 0 and len(result.videos) > cached:
        return False
    if requested == 0:
        return cached == 0 and (filters_active or len(result.videos) == result.total_works)
    if filters_active:
        return cached == 0 or cached >= requested
    required_items = min(requested, result.total_works)
    if len(result.videos) < required_items:
        return False
    return cached == 0 or cached >= requested


def _trim_to_requested_limit(result: CrawlResult, requested_limit: int | None) -> None:
    if requested_limit is not None and requested_limit > 0:
        result.videos = result.videos[:requested_limit]
        result.selection_limit = requested_limit
    result.top1 = result.videos[0] if result.videos else None
    result.top10 = result.videos[:10]
