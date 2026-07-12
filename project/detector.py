from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from project.models import JsonObject, PaginationDescriptor, PathPart
from project.utils import get_by_path


def detect_pagination(
    payload: JsonObject, query: dict[str, list[str]]
) -> PaginationDescriptor | None:
    has_more_paths = [
        path
        for path, value in _walk(payload)
        if path and _normalized(path[-1]) == "hasmore" and _is_scalar(value)
    ]
    if not has_more_paths:
        return None

    list_candidates = _find_work_lists(payload)
    if not list_candidates:
        return None

    list_path = max(
        list_candidates,
        key=lambda candidate: (
            candidate[1] + max(_shared_prefix_length(candidate[0], path) for path in has_more_paths)
        ),
    )[0]
    has_more_path = max(has_more_paths, key=lambda path: _shared_prefix_length(list_path, path))
    cursor_query_key = _find_cursor_query_key(query)
    cursor_path = _find_cursor_path(payload, list_path, cursor_query_key)
    return PaginationDescriptor(
        list_path=list_path,
        has_more_path=has_more_path,
        cursor_path=cursor_path,
        cursor_query_key=cursor_query_key or _path_key(cursor_path),
    )


def response_matches_user(
    payload: JsonObject,
    query: dict[str, list[str]],
    pagination: PaginationDescriptor,
    target_sec_user_id: str,
) -> bool:
    try:
        items = get_by_path(payload, pagination.list_path)
    except (KeyError, IndexError):
        return False
    if not isinstance(items, list):
        return False
    if not items:
        return _query_targets_user(query, target_sec_user_id)

    author_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        author = item.get("author")
        if not isinstance(author, dict):
            continue
        author_id = author.get("sec_uid") or author.get("sec_user_id")
        if isinstance(author_id, str) and author_id:
            author_ids.append(author_id)
    return bool(author_ids) and all(author_id == target_sec_user_id for author_id in author_ids)


def _query_targets_user(query: dict[str, list[str]], target_sec_user_id: str) -> bool:
    user_keys = {"secuserid", "secuid"}
    return any(
        _normalized(key) in user_keys and target_sec_user_id in values
        for key, values in query.items()
    )


def make_response_sample(value: Any, *, max_items: int) -> Any:
    if isinstance(value, dict):
        return {
            key: make_response_sample(child, max_items=max_items) for key, child in value.items()
        }
    if isinstance(value, list):
        return [make_response_sample(child, max_items=max_items) for child in value[:max_items]]
    return value


def detect_signature_keys(query: dict[str, list[str]]) -> tuple[str, ...]:
    markers = ("bogus", "signature", "x-gorgon", "x_khronos", "x-khronos")
    return tuple(sorted(key for key in query if any(marker in key.lower() for marker in markers)))


def _find_work_lists(payload: JsonObject) -> list[tuple[tuple[PathPart, ...], int]]:
    candidates: list[tuple[tuple[PathPart, ...], int]] = []
    for path, value in _walk(payload):
        if not path or not isinstance(value, list):
            continue
        items = [item for item in value if isinstance(item, dict)]
        matching = sum(_looks_like_work(item) for item in items)
        path_hint = "aweme" in _normalized(path[-1]) or "work" in _normalized(path[-1])
        if matching:
            candidates.append((path, matching * 10 + int(path_hint)))
        elif not value and path_hint:
            candidates.append((path, 1))
    return candidates


def _looks_like_work(item: dict[str, Any]) -> bool:
    if not item.get("aweme_id"):
        return False
    statistics = item.get("statistics")
    if isinstance(statistics, dict) and "digg_count" in statistics:
        return True
    return "digg_count" in item


def _find_cursor_query_key(query: dict[str, list[str]]) -> str | None:
    candidates = [key for key in query if _is_cursor_key(key)]
    if not candidates:
        return None
    return max(candidates, key=lambda key: (key.lower() == "max_cursor", "max" in key.lower()))


def _find_cursor_path(
    payload: JsonObject,
    list_path: tuple[PathPart, ...],
    query_key: str | None,
) -> tuple[PathPart, ...] | None:
    candidates = [
        path
        for path, value in _walk(payload)
        if path and _is_cursor_key(str(path[-1])) and _is_scalar(value)
    ]
    if not candidates:
        return None
    normalized_query = _normalized(query_key) if query_key else ""
    return max(
        candidates,
        key=lambda path: (
            _normalized(path[-1]) == normalized_query,
            _shared_prefix_length(list_path, path),
        ),
    )


def _walk(
    value: Any, path: tuple[PathPart, ...] = ()
) -> Iterator[tuple[tuple[PathPart, ...], Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*path, index))


def _normalized(value: PathPart | None) -> str:
    return str(value or "").lower().replace("_", "").replace("-", "")


def _is_cursor_key(key: str) -> bool:
    normalized = _normalized(key)
    return "cursor" in normalized or normalized in {"offset", "nextpagetoken"}


def _is_scalar(value: Any) -> bool:
    return isinstance(value, (str, int, bool)) or value is None


def _shared_prefix_length(left: tuple[PathPart, ...], right: tuple[PathPart, ...]) -> int:
    count = 0
    for left_part, right_part in zip(left, right, strict=False):
        if left_part != right_part:
            break
        count += 1
    return count


def _path_key(path: tuple[PathPart, ...] | None) -> str | None:
    return str(path[-1]) if path else None
