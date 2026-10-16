from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


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
