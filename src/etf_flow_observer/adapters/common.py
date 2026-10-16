from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class RawPoint:
    fund_code: str
    as_of_date: str
    series: str
    original_value: str
    original_unit: str
    source_name: str
    source_url: str
    note: str = ""
    conflict: bool = False
    flags: list[str] = field(default_factory=list)
    raw_fetch_id: int | None = None
    network_fetched_at: datetime | None = None
    cache_accessed_at: datetime | None = None
    observation_available_at: datetime | None = None


@dataclass
class FetchBatch:
    source_name: str
    points: list[RawPoint]
    errors: list[str]
    notes: list[str]
    request_urls: list[str]


def in_window(as_of: str, start: date, end: date) -> bool:
    day = date.fromisoformat(as_of)
    return start <= day <= end


def attach_fetch(points: list[RawPoint], result) -> list[RawPoint]:
    """把这一次 HTTP 的真实 id 和时间贴到解析结果上。不用任务开始时的同一个 now。"""
    for point in points:
        point.raw_fetch_id = result.raw_id
        point.network_fetched_at = result.network_fetched_at
        point.cache_accessed_at = result.cache_accessed_at
        point.observation_available_at = result.network_fetched_at
    return points


def filter_window(points: list[RawPoint], start: date, end: date, errors: list[str], label: str) -> list[RawPoint]:
    kept: list[RawPoint] = []
    for item in points:
        try:
            day = date.fromisoformat(item.as_of_date)
        except ValueError:
            errors.append(f"{label} 行日期无效: {item.as_of_date}")
            continue
        if start <= day <= end:
            kept.append(item)
    return kept
