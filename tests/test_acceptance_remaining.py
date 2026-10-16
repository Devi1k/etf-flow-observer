"""Dot 复核剩余阻断：旧库迁移、易方达唯一日期、坏结构、HTML 单元格。"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from email.message import Message
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from etf_flow_observer.adapters.nav_chinaamc import parse_chinaamc
from etf_flow_observer.adapters.nav_efunds import collect_efunds, parse_efunds
from etf_flow_observer.adapters.nav_jsfund import parse_jsfund
from etf_flow_observer.adapters.sse_shares import collect_sse, parse_sse
from etf_flow_observer.http_client import HttpClient
from etf_flow_observer.pipeline import finish_batch, mark_checkpoint
from etf_flow_observer.storage import Store
from tests.conftest import shanghai

SH = ZoneInfo("Asia/Shanghai")
NOW = shanghai(2026, 10, 16, 9, 0)

OLD_SCHEMA = """
CREATE TABLE raw_fetches (
    id INTEGER PRIMARY KEY,
    source_name TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    method TEXT NOT NULL,
    url TEXT NOT NULL,
    request_body TEXT,
    http_status INTEGER,
    body_path TEXT,
    fetched_at TEXT NOT NULL,
    from_cache INTEGER NOT NULL,
    error TEXT
);

CREATE TABLE observations (
    id INTEGER PRIMARY KEY,
    fund_code TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    series TEXT NOT NULL,
    source_name TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    revised_at TEXT,
    authoritative INTEGER NOT NULL,
    lookahead_free INTEGER NOT NULL,
    latest_version_no INTEGER NOT NULL,
    UNIQUE (fund_code, as_of_date, series, source_name)
);

CREATE TABLE observation_versions (
    id INTEGER PRIMARY KEY,
    observation_id INTEGER NOT NULL REFERENCES observations(id),
    version_no INTEGER NOT NULL,
    fund_code TEXT NOT NULL,
    as_of_date TEXT NOT NULL,
    series TEXT NOT NULL,
    source_name TEXT NOT NULL,
    original_value TEXT NOT NULL,
    original_unit TEXT NOT NULL,
    standardized_value TEXT,
    standardized_unit TEXT,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    revised_at TEXT,
    snapshot_phase TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    quality_status TEXT NOT NULL,
    quality_flags TEXT NOT NULL,
    raw_fetch_id INTEGER,
    note TEXT NOT NULL DEFAULT '',
    UNIQUE (observation_id, version_no)
);
"""


def _client(store, transport):
    return HttpClient(
        store,
        user_agent="test",
        min_interval_seconds=0,
        timeout_seconds=5,
        max_retries=1,
        cache_ttl_seconds=0,
        max_http_requests=20,
        sleeper=lambda _seconds: None,
        clock=lambda: NOW,
        transport=transport,
    )


def test_old_schema_sqlite_migrates_without_deleting(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    raw_dir = tmp_path / "raw"
    conn = sqlite3.connect(db_path)
    conn.executescript(OLD_SCHEMA)
    body_file = tmp_path / "legacy-body.bin"
    body_file.write_bytes(b"legacy-raw-body")
    conn.execute(
        """
        INSERT INTO raw_fetches (
            source_name, fingerprint, method, url, request_body, http_status,
            body_path, fetched_at, from_cache, error
        ) VALUES (?, ?, ?, ?, NULL, 200, ?, ?, 0, NULL)
        """,
        (
            "sse_shares",
            "legacy-fp",
            "GET",
            "https://example.test/legacy",
            str(body_file),
            "2026-10-10T09:00:00+08:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO observations (
            fund_code, as_of_date, series, source_name, first_seen_at, revised_at,
            authoritative, lookahead_free, latest_version_no
        ) VALUES ('510300', '2026-10-09', 'shares', 'sse_shares',
                  '2026-10-10T09:00:00+08:00', NULL, 1, 1, 1)
        """
    )
    conn.execute(
        """
        INSERT INTO observation_versions (
            observation_id, version_no, fund_code, as_of_date, series, source_name,
            original_value, original_unit, standardized_value, standardized_unit,
            source_url, fetched_at, first_seen_at, revised_at, snapshot_phase,
            content_hash, quality_status, quality_flags, raw_fetch_id, note
        ) VALUES (
            1, 1, '510300', '2026-10-09', 'shares', 'sse_shares',
            '10', '万份', '100000', '份',
            'https://example.test/legacy', '2026-10-10T09:00:00+08:00',
            '2026-10-10T09:00:00+08:00', NULL, 'morning',
            'hash-legacy', 'ok', '[]', 1, 'kept'
        )
        """
    )
    conn.commit()
    conn.close()

    store = Store(db_path, raw_dir)
    assert db_path.exists()
    raw_cols = {row[1] for row in store.conn.execute("PRAGMA table_info(raw_fetches)")}
    ver_cols = {row[1] for row in store.conn.execute("PRAGMA table_info(observation_versions)")}
    for col in (
        "network_fetched_at",
        "cache_accessed_at",
        "request_started_at",
        "attempt_no",
        "content_sha256",
    ):
        assert col in raw_cols
    for col in ("network_fetched_at", "cache_accessed_at", "observation_available_at"):
        assert col in ver_cols
    version = store.conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
    assert int(version["version"]) == Store.SCHEMA_VERSION
    kept = store.conn.execute("SELECT content_hash FROM observation_versions").fetchone()
    assert kept["content_hash"] == "hash-legacy"
    assert Path(store.conn.execute("SELECT body_path FROM raw_fetches").fetchone()["body_path"]).read_bytes() == b"legacy-raw-body"

    raw_id = store.save_raw(
        source_name="sse_shares",
        fingerprint="new-fp",
        method="GET",
        url="https://example.test/new",
        request_body=None,
        http_status=200,
        body=b"new-body",
        fetched_at=NOW,
        from_cache=False,
        error=None,
        network_fetched_at=NOW,
        request_started_at=NOW - timedelta(seconds=1),
        attempt_no=1,
    )
    assert raw_id >= 2
    result = store.upsert_version(
        fund_code="510300",
        as_of_date="2026-10-15",
        series="shares",
        source_name="sse_shares",
        original_value="11",
        original_unit="万份",
        standardized_value="110000",
        standardized_unit="份",
        source_url="https://example.test/new",
        fetched_at=NOW,
        snapshot_phase="morning",
        content_hash="hash-new",
        quality_status="ok",
        quality_flags=[],
        authoritative=True,
        lookahead_free=True,
        raw_fetch_id=raw_id,
        note="migrated",
        network_fetched_at=NOW,
        observation_available_at=NOW,
    )
    assert result.action == "created"
    assert store.raw_count() == 2
    assert store.version_count() == 2
    assert Path(store.conn.execute("SELECT body_path FROM raw_fetches WHERE id = 1").fetchone()["body_path"]).read_bytes() == b"legacy-raw-body"
    store.close()


def test_efunds_duplicate_pages_do_not_count_as_complete(store):
    """3 页 × 20 行但第 2 页重复第 1 页：物理 60、唯一 40，不能完成。"""
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(40)]
    seen = []

    def transport(method, url, headers, body):
        payload = json.loads(body)
        page = payload["pageIndex"]
        seen.append(page)
        if page == 0:
            chunk = days[:20]
        elif page == 1:
            chunk = days[:20]  # duplicate of page 0
        else:
            chunk = days[20:40]
        rows = [
            {"navDate": day.isoformat(), "netValue": "4.0000", "totalNetValue": "2.0000"}
            for day in chunk
        ]
        data = {
            "status": 1,
            "message": "success",
            "data": {"pageSize": 20, "pageIndex": page, "total": 60, "data": rows},
        }
        return 200, Message(), json.dumps(data).encode()

    batch = collect_efunds(
        _client(store, transport),
        date(2025, 1, 1),
        date(2026, 12, 31),
        page_size=150,
        use_cache=False,
    )
    assert any("日期重复" in item for item in batch.errors)
    dates = {item.as_of_date for item in batch.points if item.series == "unit_nav"}
    assert len(dates) <= 40
    # Physical row counting must not declare success when unique dates < total.
    assert batch.errors


def test_efunds_total_shrinking_mid_pagination_is_incomplete(store):
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(60)]

    def transport(method, url, headers, body):
        page = json.loads(body)["pageIndex"]
        chunk = days[page * 20 : (page + 1) * 20]
        rows = [
            {"navDate": day.isoformat(), "netValue": "4.0000", "totalNetValue": "2.0000"}
            for day in chunk
        ]
        total = 60 if page == 0 else 20
        data = {
            "status": 1,
            "data": {"pageSize": 20, "pageIndex": page, "total": total, "data": rows},
        }
        return 200, Message(), json.dumps(data).encode()

    batch = collect_efunds(
        _client(store, transport),
        date(2025, 1, 1),
        date(2026, 12, 31),
        page_size=150,
        use_cache=False,
    )
    assert any("metadata 不一致" in item for item in batch.errors)


def test_null_rows_do_not_crash_collect(store):
    points, page_no, page_count, errs = parse_sse(
        {"pageHelp": {"pageNo": 1, "pageCount": 1}, "result": [None, {"SEC_CODE": "510300"}]},
        "https://query.sse.com.cn/",
    )
    assert errs
    assert page_no == 1

    ef_points, *_rest = parse_efunds(
        {
            "status": 1,
            "data": {
                "pageSize": 2,
                "pageIndex": 0,
                "total": 2,
                "data": [None, {"navDate": "2026-10-15", "netValue": "4.1", "totalNetValue": "2.1"}],
            },
        },
        "https://api.efunds.com.cn/nav",
    )
    assert any(item.as_of_date == "2026-10-15" for item in ef_points)
    assert _rest[-1]  # row_errors

    def transport(method, url, headers, body):
        payload = {
            "pageHelp": {"pageNo": 1, "pageCount": 1},
            "result": [None, {"STAT_DATE": "2026-10-15", "SEC_CODE": "510300", "SEC_NAME": "a", "TOT_VOL": "10"}],
        }
        return 200, Message(), json.dumps(payload).encode()

    batch = collect_sse(_client(store, transport), [date(2026, 10, 15)], page_size=1000, use_cache=False)
    assert any("不是对象" in item for item in batch.errors)
    assert any(item.fund_code == "510300" for item in batch.points)
    summary = finish_batch(
        store,
        batch,
        now=NOW,
        phase_override=None,
        closures=set(),
        abnormal_ratio=__import__("decimal").Decimal("0.20"),
        split_ratio=__import__("decimal").Decimal("0.50"),
        morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0),
        expected_days=[date(2026, 10, 15)],
        expected_funds=["510300"],
        expected_series=["shares"],
    )
    mark_checkpoint(
        store,
        "sse_shares",
        "null-rows",
        summary,
        NOW,
        start=date(2026, 10, 15),
        end=date(2026, 10, 15),
        closures=set(),
    )
    assert summary["checkpoint"] == "incomplete"


def test_html_keeps_unit_when_cumulative_is_na_and_blank_unit_is_missing():
    china_na = parse_chinaamc(
        "<tr><td>2026-10-15</td><td><span>4.4176</span></td><td><span>N/A</span></td></tr>",
        "https://www.chinaamc.com/product/fundLishijingzhi.do",
    )[0]
    unit = next(item for item in china_na if item.series == "unit_nav")
    assert unit.original_value == "4.4176"
    assert unit.conflict is False
    assert all(item.series != "cumulative_nav" for item in china_na)

    china_blank = parse_chinaamc(
        "<tr><td>2026-10-15</td><td></td><td><span>2.1522</span></td></tr>",
        "https://www.chinaamc.com/product/fundLishijingzhi.do",
    )[0]
    missed = next(item for item in china_blank if item.series == "unit_nav")
    assert missed.conflict is True
    assert missed.original_value == ""
    cum = next(item for item in china_blank if item.series == "cumulative_nav")
    assert cum.original_value == "2.1522"

    jiashi_na = parse_jsfund(
        "<tr><td>2026-10-15</td><td>4.4226</td><td>N/A</td></tr>",
        "https://www.jsfund.cn/nav",
        used_fallback=False,
    )
    assert jiashi_na[0].original_value == "4.4226"
    assert all(item.series != "cumulative_nav" for item in jiashi_na)

    jiashi_blank = parse_jsfund(
        "<tr><td>2026-10-15</td><td></td><td>2.0499</td></tr>",
        "https://www.jsfund.cn/nav",
        used_fallback=False,
    )
    assert jiashi_blank[0].conflict is True
    assert jiashi_blank[0].original_value == ""
    assert jiashi_blank[0].original_value != "2.0499"
