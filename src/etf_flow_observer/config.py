"""读取 TOML 配置。相对路径按运行命令时的当前目录解析。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from etf_flow_observer.timing import parse_hhmm
from etf_flow_observer.universe import ensure_fixed_list


@dataclass(frozen=True)
class AppConfig:
    db_path: Path
    raw_dir: Path
    fund_codes: list[str]
    min_interval_seconds: float
    timeout_seconds: float
    max_retries: int
    cache_ttl_seconds: int
    user_agent: str
    max_sse_dates_per_run: int
    max_http_requests: int
    abnormal_share_jump_ratio: Decimal
    split_or_merge_ratio: Decimal
    stale_after_hours: int
    morning_start: time
    session_close: time
    closures: set[date]
    efunds_page_size: int
    huatai_page_size: int
    huatai_site_id: str
    sse_page_size: int
    jsfund_primary_url: str
    jsfund_fallback_url: str


def load_config(path: str | Path) -> AppConfig:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        raw = tomllib.load(handle)
    storage = raw["storage"]
    http = raw["http"]
    backfill = raw["backfill"]
    quality = raw["quality"]
    timing = raw["timing"]
    calendar = raw["calendar"]
    sources = raw["sources"]
    fund_codes = list(raw["universe"]["fund_codes"])
    ensure_fixed_list(fund_codes)
    closures = {date.fromisoformat(item) for item in calendar.get("closures", [])}
    return AppConfig(
        db_path=Path(storage["db_path"]),
        raw_dir=Path(storage["raw_dir"]),
        fund_codes=fund_codes,
        min_interval_seconds=float(http["min_interval_seconds"]),
        timeout_seconds=float(http["timeout_seconds"]),
        max_retries=int(http["max_retries"]),
        cache_ttl_seconds=int(http["cache_ttl_seconds"]),
        user_agent=str(http["user_agent"]),
        max_sse_dates_per_run=int(backfill["max_sse_dates_per_run"]),
        max_http_requests=int(backfill["max_http_requests"]),
        abnormal_share_jump_ratio=Decimal(str(quality["abnormal_share_jump_ratio"])),
        split_or_merge_ratio=Decimal(str(quality["split_or_merge_ratio"])),
        stale_after_hours=int(quality["stale_after_hours"]),
        morning_start=parse_hhmm(timing["morning_start"]),
        session_close=parse_hhmm(timing["session_close"]),
        closures=closures,
        efunds_page_size=int(sources["efunds"]["page_size"]),
        huatai_page_size=int(sources["huatai"]["page_size"]),
        huatai_site_id=str(sources["huatai"]["site_id"]),
        sse_page_size=int(sources["sse"]["page_size"]),
        jsfund_primary_url=str(sources["jsfund"]["primary_url"]),
        jsfund_fallback_url=str(sources["jsfund"]["fallback_url"]),
    )


def load_sim_config(path: str | Path) -> dict:
    with Path(path).open("rb") as handle:
        return tomllib.load(handle)
