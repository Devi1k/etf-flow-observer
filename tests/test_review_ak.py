"""A–K 的反例。阈值保持 0.20，不把未跑过的现场核对写成已完成。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, time
from decimal import Decimal
from email.message import Message
from pathlib import Path

import pytest

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, attach_fetch
from etf_flow_observer.adapters.nav_chinaamc import parse_chinaamc
from etf_flow_observer.adapters.nav_efunds import collect_efunds
from etf_flow_observer.adapters.nav_jsfund import parse_jsfund
from etf_flow_observer.adapters.sse_shares import collect_sse
from etf_flow_observer.http_client import HttpClient
from etf_flow_observer.pipeline import day_lines, finish_batch, mark_checkpoint, should_skip
from etf_flow_observer.signals import (
    aum_at_window_start,
    denominator_date,
    linear_percentile,
    percentile_80,
    percentile_80_chronological,
)
from etf_flow_observer.standardize import parse_decimal, to_nav_yuan, to_shares
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.timing import NATIONAL_DAY_2026_WEEKDAYS, applied_phase, assert_entry_after_data, national_day_history_block
from tests.conftest import ingest, shanghai

ROOT = Path(__file__).resolve().parents[1]
NOW = shanghai(2026, 10, 16, 9, 0)


def _share(day: str, value: str, fund: str = "510330") -> RawPoint:
    return RawPoint(
        fund_code=fund,
        as_of_date=day,
        series="shares",
        original_value=value,
        original_unit="万份",
        source_name="sse_shares",
        source_url="https://query.sse.com.cn/commonQuery.do",
    )


def _client(store, transport, *, interval=0, retries=1, ttl=0, clock=None, sleeper=None):
    return HttpClient(
        store,
        user_agent="test",
        min_interval_seconds=interval,
        timeout_seconds=5,
        max_retries=retries,
        cache_ttl_seconds=ttl,
        max_http_requests=20,
        sleeper=sleeper or (lambda _seconds: None),
        clock=clock or (lambda: NOW),
        transport=transport,
    )


def test_raw_body_is_immutable_and_versions_link_the_network_fetch(store):
    bodies = [b'{"result":"one"}', b'{"result":"two"}']
    calls = {"n": 0}

    def transport(method, url, headers, body):
        payload = bodies[min(calls["n"], 1)]
        calls["n"] += 1
        return 200, Message(), payload

    client = _client(store, transport, ttl=0)
    first = client.send("GET", "https://query.sse.com.cn/commonQuery.do?a=1", source_name="sse_shares")
    first_path = Path(store.conn.execute("SELECT body_path FROM raw_fetches WHERE id = ?", (first.raw_id,)).fetchone()["body_path"])
    assert first_path.read_bytes() == bodies[0]
    second = client.send("GET", "https://query.sse.com.cn/commonQuery.do?a=1", source_name="sse_shares", use_cache=False)
    assert first_path.read_bytes() == bodies[0]
    second_path = Path(store.conn.execute("SELECT body_path FROM raw_fetches WHERE id = ?", (second.raw_id,)).fetchone()["body_path"])
    assert second_path != first_path
    assert second_path.read_bytes() == bodies[1]
    point = _share("2026-10-15", "10")
    point.raw_fetch_id = second.raw_id
    point.network_fetched_at = second.network_fetched_at
    point.observation_available_at = second.network_fetched_at
    ingest(store, [point], shanghai(2026, 10, 16, 8, 0), phase="morning")
    row = store.latest_join("510330", "2026-10-15", "shares", "sse_shares")
    assert row["raw_fetch_id"] == second.raw_id
    assert row["observation_available_at"].startswith("2026-10-16T09:00")
    assert not row["observation_available_at"].startswith("2026-10-16T08:00")


def test_cache_hit_does_not_rewrite_body_or_extend_ttl(store):
    clock = {"now": shanghai(2026, 10, 16, 9, 0)}
    calls = {"n": 0}

    def transport(method, url, headers, body):
        calls["n"] += 1
        return 200, Message(), b"cached-body"

    client = _client(
        store,
        transport,
        ttl=100,
        clock=lambda: clock["now"],
    )
    url = "https://example.test/nav"
    client.send("GET", url, source_name="efunds_nav")
    path = Path(store.conn.execute("SELECT body_path FROM raw_fetches WHERE from_cache = 0").fetchone()["body_path"])
    clock["now"] = shanghai(2026, 10, 16, 9, 0) + timedelta(seconds=50)
    cached = client.send("GET", url, source_name="efunds_nav", use_cache=True)
    assert cached.from_cache is True
    assert path.read_bytes() == b"cached-body"
    assert calls["n"] == 1
    original = store.conn.execute(
        "SELECT network_fetched_at FROM raw_fetches WHERE from_cache = 0"
    ).fetchone()["network_fetched_at"]
    assert original.startswith("2026-10-16T09:00")
    clock["now"] = shanghai(2026, 10, 16, 9, 0) + timedelta(seconds=120)
    client.send("GET", url, source_name="efunds_nav", use_cache=True)
    assert calls["n"] == 2



def test_http_client_records_response_arrival_not_request_start(store):
    """transport 内推进时钟时，network_fetched_at 必须是响应完整到达，不是发请求前。"""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    sh = ZoneInfo("Asia/Shanghai")
    start = datetime(2026, 10, 16, 9, 0, 0, tzinfo=sh)
    arrive = datetime(2026, 10, 16, 9, 0, 5, tzinfo=sh)
    clock = {"now": start}

    def transport(method, url, headers, body):
        clock["now"] = arrive
        return 200, Message(), b'{"ok":true}'

    client = _client(
        store,
        transport,
        ttl=0,
        clock=lambda: clock["now"],
    )
    result = client.send("GET", "https://query.sse.com.cn/commonQuery.do?t=clock", source_name="sse_shares")
    assert result.request_started_at == start
    assert result.network_fetched_at == arrive
    assert result.network_fetched_at > result.request_started_at
    row = store.conn.execute(
        "SELECT request_started_at, network_fetched_at FROM raw_fetches WHERE id = ?",
        (result.raw_id,),
    ).fetchone()
    assert row["request_started_at"].startswith("2026-10-16T09:00:00")
    assert row["network_fetched_at"].startswith("2026-10-16T09:00:05")


def test_cache_hit_across_0800_keeps_overnight_not_morning(store):
    """07:50 网络正文、08:01 缓存命中入库：阶段仍是 overnight，不能误升 morning/权威。"""
    body_at = shanghai(2026, 10, 16, 7, 50)
    batch_at = shanghai(2026, 10, 16, 8, 1)
    point = _share("2026-10-15", "10")
    point.network_fetched_at = body_at
    point.observation_available_at = body_at
    point.cache_accessed_at = batch_at
    # 批次意图是 morning，但钟点按正文可得时间仍是 overnight
    result = ingest(store, [point], batch_at, phase="morning")
    assert result["actions"] == ["created"]
    row = store.latest_join("510330", "2026-10-15", "shares", "sse_shares")
    assert row["snapshot_phase"] == "overnight"
    assert row["authoritative"] == 0
    assert row["quality_status"] == "overnight_provisional"
    assert row["observation_available_at"].startswith("2026-10-16T07:50")


def test_cache_hit_e2e_http_adapter_ingest_keeps_overnight_across_0800(store):
    """真正走 HttpClient 缓存 → collect_sse/attach_fetch → ingest：跨 08:00 仍 overnight。"""
    day = date(2026, 10, 15)
    payload = {
        "pageHelp": {"pageNo": 1, "pageCount": 1, "total": 3},
        "result": [
            {"STAT_DATE": "2026-10-15", "SEC_CODE": "510330", "SEC_NAME": "华夏", "TOT_VOL": "10"},
            {"STAT_DATE": "2026-10-15", "SEC_CODE": "510300", "SEC_NAME": "华泰", "TOT_VOL": "11"},
            {"STAT_DATE": "2026-10-15", "SEC_CODE": "510310", "SEC_NAME": "易方达", "TOT_VOL": "12"},
        ],
    }
    body = json.dumps(payload).encode()
    clock = {"now": shanghai(2026, 10, 16, 7, 50)}
    calls = {"n": 0}

    def transport(method, url, headers, request_body):
        calls["n"] += 1
        return 200, Message(), body

    client = _client(store, transport, ttl=3600, clock=lambda: clock["now"])
    first = collect_sse(client, [day], page_size=1000, use_cache=True)
    assert calls["n"] == 1
    assert not first.errors
    assert first.points
    assert all(p.network_fetched_at == shanghai(2026, 10, 16, 7, 50) for p in first.points)
    assert all(p.observation_available_at == shanghai(2026, 10, 16, 7, 50) for p in first.points)

    clock["now"] = shanghai(2026, 10, 16, 8, 1)
    cached = collect_sse(client, [day], page_size=1000, use_cache=True)
    assert calls["n"] == 1
    assert not cached.errors
    assert cached.points
    for point in cached.points:
        assert point.network_fetched_at == shanghai(2026, 10, 16, 7, 50)
        assert point.observation_available_at == shanghai(2026, 10, 16, 7, 50)
        assert point.cache_accessed_at == shanghai(2026, 10, 16, 8, 1)
        assert point.raw_fetch_id is not None

    batch_at = shanghai(2026, 10, 16, 8, 1)
    result = ingest(store, cached.points, batch_at, phase="morning")
    assert result["actions"]
    assert all(action == "created" for action in result["actions"])
    row = store.latest_join("510330", "2026-10-15", "shares", "sse_shares")
    assert row["snapshot_phase"] == "overnight"
    assert row["authoritative"] == 0
    assert row["quality_status"] == "overnight_provisional"
    assert row["observation_available_at"].startswith("2026-10-16T07:50")
    assert row["cache_accessed_at"].startswith("2026-10-16T08:01")


def test_request_crossing_0935_cannot_schedule_entry_at_0935(store):
    """09:34:59 发请求、09:35:10 响应到达：可得时间是到达时刻；09:35:00 入场被拒。"""
    from zoneinfo import ZoneInfo

    sh = ZoneInfo("Asia/Shanghai")
    start = datetime(2026, 10, 16, 9, 34, 59, tzinfo=sh)
    arrive = datetime(2026, 10, 16, 9, 35, 10, tzinfo=sh)
    clock = {"now": start}

    def transport(method, url, headers, body):
        clock["now"] = arrive
        return 200, Message(), b'{"ok":true}'

    client = _client(store, transport, ttl=0, clock=lambda: clock["now"])
    result = client.send(
        "GET",
        "https://query.sse.com.cn/commonQuery.do?t=entry-gate",
        source_name="sse_shares",
        use_cache=False,
    )
    assert result.request_started_at == start
    assert result.network_fetched_at == arrive
    assert result.network_fetched_at != result.request_started_at

    points = attach_fetch([_share("2026-10-15", "10")], result)
    assert points[0].network_fetched_at == arrive
    assert points[0].observation_available_at == arrive

    as_of = date(2026, 10, 15)
    executable = datetime(2026, 10, 16, 9, 35, 0, tzinfo=sh)
    # 若误用发请求时刻，09:35:00 会错误地晚于 09:34:59 而通过
    assert executable > start
    with pytest.raises(ObserverError, match="早于或等于"):
        assert_entry_after_data(executable, result.network_fetched_at, as_of)
    with pytest.raises(ObserverError, match="早于或等于"):
        assert_entry_after_data(executable, points[0].observation_available_at, as_of)


def test_legacy_cache_row_without_network_fetched_at_forces_refresh(store):
    """旧库 network_fetched_at=NULL：即使 fetched_at 仍在 TTL 内也不得当缓存命中，必须重新请求；不回填旧戳。"""
    import hashlib

    url = "https://example.test/legacy-null-arrival"
    method = "GET"
    fingerprint = hashlib.sha256(b"\n".join([method.encode(), url.encode(), b""])).hexdigest()
    body = b"legacy-body"
    digest = hashlib.sha256(body).hexdigest()
    path = store.raw_dir / "by-hash" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    recent = shanghai(2026, 10, 16, 9, 0).isoformat(timespec="seconds")
    cursor = store.conn.execute(
        """
        INSERT INTO raw_fetches (
            source_name, fingerprint, method, url, request_body, http_status,
            body_path, content_sha256, fetched_at, network_fetched_at, cache_accessed_at,
            request_started_at, attempt_no, from_cache, error
        ) VALUES (?, ?, ?, ?, NULL, 200, ?, ?, ?, NULL, NULL, NULL, 1, 0, NULL)
        """,
        ("sse_shares", fingerprint, method, url, str(path), digest, recent),
    )
    legacy_id = int(cursor.lastrowid)
    store.conn.commit()
    legacy = store.conn.execute(
        "SELECT network_fetched_at, fetched_at FROM raw_fetches WHERE id = ?",
        (legacy_id,),
    ).fetchone()
    assert legacy["network_fetched_at"] is None
    assert legacy["fetched_at"] == recent

    calls = {"n": 0}

    def transport(method, url, headers, request_body):
        calls["n"] += 1
        return 200, Message(), b"fresh-body"

    client = _client(store, transport, ttl=3600, clock=lambda: shanghai(2026, 10, 16, 9, 5))
    result = client.send("GET", url, source_name="sse_shares", use_cache=True)
    assert calls["n"] == 1
    assert result.from_cache is False
    assert result.body == b"fresh-body"
    assert result.network_fetched_at == shanghai(2026, 10, 16, 9, 5)
    still = store.conn.execute(
        "SELECT network_fetched_at, fetched_at FROM raw_fetches WHERE id = ?",
        (legacy_id,),
    ).fetchone()
    assert still["network_fetched_at"] is None
    assert still["fetched_at"] == recent


def test_requested_morning_cannot_upgrade_clock_phase(store):
    early = shanghai(2026, 10, 16, 7, 59)
    phase, note = applied_phase(
        date(2026, 10, 15), early, "morning", morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0), closures=set(),
    )
    assert phase == "overnight"
    assert note
    ingest(store, [_share("2026-10-15", "10")], early, phase="morning")
    row = store.latest_join("510330", "2026-10-15", "shares", "sse_shares")
    assert row["snapshot_phase"] == "overnight"
    assert row["authoritative"] == 0

    on_cut = shanghai(2026, 10, 16, 8, 0)
    phase, _note = applied_phase(
        date(2026, 10, 15), on_cut, "morning", morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0), closures=set(),
    )
    assert phase == "morning"
    protocol = (ROOT / "docs" / "experiment-protocol.md").read_text(encoding="utf-8")
    assert "不是交易所保证" in protocol

    future = ingest(store, [_share("2026-10-17", "10")], NOW, phase="morning")
    assert future["actions"] == ["created"]
    future_row = store.latest_join("510330", "2026-10-17", "shares", "sse_shares")
    assert future_row["snapshot_phase"] == "future_invalid"
    assert future_row["authoritative"] == 0

    monday = shanghai(2026, 10, 19, 9, 0)
    phase, note = applied_phase(
        date(2026, 10, 16), monday, "morning", morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0), closures=set(),
    )
    assert phase == "backfill"
    assert "morning" in note
    holiday = shanghai(2026, 10, 17, 9, 0)
    phase, _note = applied_phase(
        date(2026, 10, 16), holiday, "morning", morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0), closures={date(2026, 10, 16)},
    )
    assert phase == "backfill"


def test_missing_adjacent_day_does_not_use_an_older_share(store):
    ingest(store, [_share("2026-10-13", "10")], NOW, phase="backfill")
    ingest(store, [_share("2026-10-15", "10.1")], NOW, phase="morning")
    ingest(
        store,
        [
            RawPoint(
                fund_code="510330",
                as_of_date="2026-10-15",
                series="unit_nav",
                original_value="4",
                original_unit="元",
                source_name="chinaamc_nav",
                source_url="https://www.chinaamc.com/product/fundLishijingzhi.do",
            )
        ],
        NOW,
        phase="morning",
    )
    text = "\n".join(day_lines(store, "2026-10-15", NOW, 36))
    assert "2026-10-14" in text
    assert "不能用更早的非空值" in text
    assert "4000" not in text
    row = store.latest_join("510330", "2026-10-15", "shares", "sse_shares")
    assert "no_adjacent_share" in json.loads(row["quality_flags"])


def test_abnormal_prior_blocks_delta_without_raising_the_threshold(store):
    ingest(store, [_share("2026-10-13", "10")], NOW, phase="backfill")
    ingest(store, [_share("2026-10-14", "13")], NOW, phase="backfill")
    ingest(store, [_share("2026-10-15", "13.1")], NOW, phase="morning")
    prior = store.latest_join("510330", "2026-10-14", "shares", "sse_shares")
    assert prior["quality_status"] == "abnormal_jump"
    text = "\n".join(day_lines(store, "2026-10-15", NOW, 36))
    assert "abnormal_jump" in text
    assert "不计算变化" in text
    assert "研究估计" not in text


def test_revising_an_earlier_day_appends_a_new_version_and_keeps_the_old_one(store):
    ingest(store, [_share("2026-10-14", "10")], NOW, phase="backfill")
    ingest(store, [_share("2026-10-15", "10.1")], NOW, phase="morning")
    before = store.conn.execute(
        """
        SELECT version_no, quality_status FROM observation_versions
        WHERE as_of_date = '2026-10-15' ORDER BY version_no
        """
    ).fetchall()
    assert before[0]["quality_status"] == "ok"
    ingest(store, [_share("2026-10-14", "5")], NOW, phase="backfill")
    versions = store.conn.execute(
        """
        SELECT version_no, quality_status FROM observation_versions
        WHERE as_of_date = '2026-10-15' ORDER BY version_no
        """
    ).fetchall()
    assert versions[0]["quality_status"] == "ok"
    assert versions[-1]["quality_status"] == "suspect_split_or_merge"
    assert versions[-1]["version_no"] > versions[0]["version_no"]
    event = store.conn.execute(
        "SELECT detail FROM quality_events WHERE status = 'dependent_recalc'"
    ).fetchone()
    assert event is not None
    assert "旧版本保留" in event["detail"]


def test_empty_closures_fail_national_day_history_acceptance(store):
    assert national_day_history_block(date(2026, 10, 1), date(2026, 10, 15), set())
    assert national_day_history_block(date(2026, 10, 1), date(2026, 10, 15), set(NATIONAL_DAY_2026_WEEKDAYS)) is None
    summary = {"errors": [], "notes": [], "stored": 1, "gaps": 0}
    mark_checkpoint(
        store, "sse_shares", "nd", summary, NOW,
        start=date(2026, 9, 30), end=date(2026, 10, 15), closures=set(),
    )
    assert summary["checkpoint"] == "incomplete"
    assert should_skip(store, "sse_shares", "nd", False) is False


def test_efunds_pages_follow_response_totals_for_sixty_dates(store):
    days = [date(2026, 1, 1) + timedelta(days=offset) for offset in range(60)]
    seen = []

    def transport(method, url, headers, body):
        payload = json.loads(body)
        seen.append(payload["pageIndex"])
        page = payload["pageIndex"]
        chunk = days[page * 20:(page + 1) * 20]
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
    assert batch.errors == []
    assert seen == [0, 1, 2]
    dates = {item.as_of_date for item in batch.points if item.series == "unit_nav"}
    assert len(dates) == 60
    assert len([item for item in batch.points if item.series == "unit_nav"]) * 2 == len(batch.points)


def test_efunds_empty_page_before_total_is_incomplete(store):
    def transport(method, url, headers, body):
        page = json.loads(body)["pageIndex"]
        if page == 0:
            rows = [
                {"navDate": f"2026-08-{day:02d}", "netValue": "4.1", "totalNetValue": "2.1"}
                for day in range(1, 21)
            ]
        else:
            rows = []
        data = {"status": 1, "data": {"pageSize": 20, "pageIndex": page, "total": 60, "data": rows}}
        return 200, Message(), json.dumps(data).encode()

    batch = collect_efunds(
        _client(store, transport),
        date(2026, 10, 1),
        date(2026, 10, 16),
        page_size=150,
        use_cache=False,
    )
    assert any("不完整" in item for item in batch.errors)


def test_gaps_without_http_errors_do_not_freeze_the_checkpoint(store):
    def run(points):
        batch = FetchBatch("sse_shares", points, [], [], ["https://query.sse.com.cn/"])
        summary = finish_batch(
            store,
            batch,
            now=NOW,
            phase_override=None,
            closures=set(),
            abnormal_ratio=Decimal("0.20"),
            split_ratio=Decimal("0.50"),
            morning_start=__import__("datetime").time(8, 0),
            session_close=__import__("datetime").time(15, 0),
            expected_days=[date(2026, 10, 14), date(2026, 10, 15)],
            expected_funds=["510300"],
            expected_series=["shares"],
        )
        mark_checkpoint(
            store, "sse_shares", "win", summary, NOW,
            start=date(2026, 10, 14), end=date(2026, 10, 15), closures=set(),
        )
        return summary

    first = run([_share("2026-10-15", "10", fund="510300")])
    assert first["errors"] == []
    assert first["gaps"] > 0
    assert first["checkpoint"] == "waiting_update"
    assert should_skip(store, "sse_shares", "win", False) is False
    second = run([_share("2026-10-14", "10", fund="510300"), _share("2026-10-15", "10.1", fund="510300")])
    assert second["checkpoint"] == "complete"
    assert should_skip(store, "sse_shares", "win", False) is True


def test_bad_numbers_and_pages_do_not_crash_or_count_as_complete(store):
    with pytest.raises(ObserverError):
        parse_decimal("NaN")
    with pytest.raises(ObserverError):
        parse_decimal("Infinity")
    with pytest.raises(ObserverError):
        to_nav_yuan(Decimal("0"), "元")
    with pytest.raises(ObserverError):
        to_nav_yuan(Decimal("-1"), "元")
    with pytest.raises(ObserverError):
        to_shares(Decimal("-2"), "万份")

    def bad_count(method, url, headers, body):
        payload = {"pageHelp": {"pageNo": 1, "pageCount": "bad"}, "result": []}
        return 200, Message(), json.dumps(payload).encode()

    assert collect_sse(
        _client(store, bad_count), [date(2026, 10, 15)], page_size=1000, use_cache=False
    ).errors

    def transport(method, url, headers, body):
        payload = {
            "pageHelp": {"pageNo": 1, "pageCount": 1},
            "result": [
                {"STAT_DATE": "2026-10-15", "SEC_CODE": "510300", "SEC_NAME": "a", "TOT_VOL": "10"},
                {"STAT_DATE": "not-a-date", "SEC_CODE": "510310", "SEC_NAME": "b", "TOT_VOL": "11"},
            ],
        }
        return 200, Message(), json.dumps(payload).encode()

    batch = collect_sse(_client(store, transport), [date(2026, 10, 15)], page_size=1000, use_cache=False)
    assert any("日期无效" in item for item in batch.errors)
    summary = finish_batch(
        store,
        batch,
        now=NOW,
        phase_override=None,
        closures=set(),
        abnormal_ratio=Decimal("0.20"),
        split_ratio=Decimal("0.50"),
        morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0),
        expected_days=[date(2026, 10, 15)],
        expected_funds=["510300"],
        expected_series=["shares"],
    )
    mark_checkpoint(
        store, "sse_shares", "bad", summary, NOW,
        start=date(2026, 10, 15), end=date(2026, 10, 15), closures=set(),
    )
    assert summary["checkpoint"] == "incomplete"


def test_retries_keep_evidence_and_wait_at_least_the_min_interval(store):
    sleeps = []
    state = {"n": 0}

    def transport(method, url, headers, body):
        state["n"] += 1
        if state["n"] == 1:
            return 503, Message(), b"busy"
        return 200, Message(), b"ok"

    client = _client(
        store,
        transport,
        interval=10,
        retries=2,
        sleeper=lambda seconds: sleeps.append(seconds),
    )
    result = client.send("GET", "https://example.test/a", source_name="sse_shares", use_cache=False)
    assert result.status == 200
    assert sleeps and min(sleeps) >= 10
    rows = store.conn.execute(
        "SELECT http_status, error, attempt_no, network_fetched_at, body_path FROM raw_fetches ORDER BY id"
    ).fetchall()
    assert [row["http_status"] for row in rows] == [503, 200]
    assert rows[0]["error"]
    assert rows[0]["network_fetched_at"]
    assert Path(rows[0]["body_path"]).read_bytes() == b"busy"
    assert Path(rows[1]["body_path"]).read_bytes() == b"ok"

    state2 = {"n": 0}

    def timeout_then_ok(method, url, headers, body):
        state2["n"] += 1
        if state2["n"] == 1:
            raise TimeoutError("timed out")
        return 200, Message(), b"later"

    client2 = _client(store, timeout_then_ok, interval=10, retries=2, sleeper=lambda seconds: None)
    result2 = client2.send("GET", "https://example.test/b", source_name="sse_shares", use_cache=False)
    assert result2.status == 200
    timeout_row = store.conn.execute(
        "SELECT error, http_status, network_fetched_at FROM raw_fetches WHERE url LIKE '%/b' ORDER BY id"
    ).fetchall()
    assert "TimeoutError" in timeout_row[0]["error"]
    assert timeout_row[0]["http_status"] is None
    assert timeout_row[0]["network_fetched_at"]
    assert timeout_row[1]["http_status"] == 200


def test_html_keeps_unit_nav_when_cumulative_is_missing():
    china = parse_chinaamc(
        "<tr><td>2026-10-15</td><td><span>4.4176</span></td><td><span>--</span></td></tr>",
        "https://www.chinaamc.com/product/fundLishijingzhi.do",
    )[0]
    unit = [item for item in china if item.series == "unit_nav"]
    cumulative = [item for item in china if item.series == "cumulative_nav"]
    assert unit[0].original_value == "4.4176"
    assert cumulative == []
    missing = parse_chinaamc(
        "<tr><td>2026-10-15</td><td><span>--</span></td><td><span>2.1522</span></td></tr>",
        "https://www.chinaamc.com/product/fundLishijingzhi.do",
    )[0]
    missed_unit = next(item for item in missing if item.series == "unit_nav")
    assert missed_unit.conflict is True
    assert missed_unit.original_value == ""
    assert missed_unit.original_value != "2.1522"

    jiashi = parse_jsfund(
        "<tr><td>2026-10-15</td><td>4.4226</td><td>--</td></tr>",
        "https://www.jsfund.cn/nav",
        used_fallback=False,
    )
    assert jiashi[0].series == "unit_nav"
    assert jiashi[0].original_value == "4.4226"
    assert all(item.series != "cumulative_nav" for item in jiashi)
    substituted = parse_jsfund(
        "<tr><td>2026-10-15</td><td>--</td><td>2.0499</td></tr>",
        "https://www.jsfund.cn/nav",
        used_fallback=False,
    )
    assert substituted[0].conflict is True
    assert substituted[0].original_value != "2.0499"


def test_denominator_is_the_trading_day_before_the_five_day_window():
    window_start = date(2026, 10, 12)
    assert denominator_date(window_start, set()) == date(2026, 10, 9)
    before_shares = {
        "510300": Decimal("100"),
        "510310": Decimal("200"),
        "510330": Decimal("300"),
        "159919": Decimal("400"),
    }
    before_nav = {
        "510300": Decimal("1"),
        "510310": Decimal("2"),
        "510330": Decimal("3"),
        "159919": Decimal("4"),
    }
    assert aum_at_window_start(before_shares, before_nav) == Decimal("3000")
    first_day_shares = {code: value + Decimal("50") for code, value in before_shares.items()}
    assert aum_at_window_start(first_day_shares, before_nav) != Decimal("3000")
    protocol = (ROOT / "docs" / "experiment-protocol.md").read_text(encoding="utf-8")
    assert "窗口第一天之前" in protocol


def test_percentile_window_stays_at_the_most_recent_120():
    recent = [Decimal(i) for i in range(120)]
    assert percentile_80([Decimal("-1000000")] + recent) == percentile_80(recent)
    wide = [Decimal(i) for i in range(240)]
    assert percentile_80(wide) == linear_percentile(wide[-120:], Decimal("0.8"))
    assert percentile_80(wide) != linear_percentile(wide, Decimal("0.8"))
    dated = [(date(2024, 1, 1) + timedelta(days=offset), Decimal(offset)) for offset in range(240)]
    shuffled = list(reversed(dated))
    assert percentile_80_chronological(shuffled) == percentile_80(wide[-120:])
    assert percentile_80_chronological(dated[:121]) == percentile_80([Decimal(i) for i in range(1, 121)])
