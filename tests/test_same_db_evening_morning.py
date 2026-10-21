"""Same persistent SQLite: evening leg → natural next-morning append (Dot evidence A).

Cross-DB evening/morning snapshots (evidence/evening-20261016 + morning-20261017)
do NOT satisfy this pair. These tests keep one DB path across legs, including a
Store close/reopen restart between evening and morning.
"""

from __future__ import annotations

import json
from datetime import date, time
from decimal import Decimal
from pathlib import Path

from etf_flow_observer.adapters.common import FetchBatch, RawPoint
from etf_flow_observer.pipeline import (
    day_lines,
    finish_batch,
    mark_checkpoint,
    should_skip,
)
from etf_flow_observer.storage import Store
from etf_flow_observer.timing import classify_phase, morning_session
from tests.conftest import ingest, shanghai

DATA_DAY = "2026-10-21"
PRIOR_DAY = "2026-10-20"
EVENING = shanghai(2026, 10, 21, 20, 30)
MORNING = shanghai(2026, 10, 22, 8, 20)


def _share(fund: str, day: str, value: str, source: str | None = None) -> RawPoint:
    src = source or ("szse_shares" if fund.startswith("159") else "sse_shares")
    return RawPoint(
        fund_code=fund,
        as_of_date=day,
        series="shares",
        original_value=value,
        original_unit="万份",
        source_name=src,
        source_url="https://example.test/shares",
    )


def _nav(fund: str, day: str, value: str, source: str) -> RawPoint:
    return RawPoint(
        fund_code=fund,
        as_of_date=day,
        series="unit_nav",
        original_value=value,
        original_unit="元",
        source_name=source,
        source_url="https://example.test/nav",
    )


def test_same_db_evening_to_morning_preserves_first_seen_and_appends(tmp_path):
    db_path = tmp_path / "same.sqlite"
    raw_dir = tmp_path / "raw"
    evening_store = Store(db_path, raw_dir)
    evening = ingest(
        evening_store,
        [_share("510300", DATA_DAY, "100")],
        EVENING,
        phase="evening",
    )
    assert evening["actions"] == ["created"]
    first_seen = evening_store.get_observation("510300", DATA_DAY, "shares", "sse_shares")[
        "first_seen_at"
    ]
    assert first_seen.startswith("2026-10-21T20:30")
    v1 = evening_store.latest_join("510300", DATA_DAY, "shares", "sse_shares")
    assert v1["snapshot_phase"] == "evening"
    assert v1["quality_status"] == "provisional_evening"
    assert int(v1["authoritative"]) == 0
    evening_store.close()

    # Restart inheritance: reopen the same path for the morning leg.
    morning_store = Store(db_path, raw_dir)
    morning = ingest(
        morning_store,
        [_share("510300", DATA_DAY, "101")],
        MORNING,
        phase="morning",
    )
    assert morning["actions"] == ["revised"]
    observation = morning_store.get_observation("510300", DATA_DAY, "shares", "sse_shares")
    assert observation["first_seen_at"] == first_seen
    assert observation["revised_at"].startswith("2026-10-22T08:20")
    assert observation["authoritative"] == 1
    assert morning_store.count_versions("510300", DATA_DAY, "shares", "sse_shares") == 2
    versions = morning_store.conn.execute(
        """
        SELECT version_no, snapshot_phase, first_seen_at, standardized_value, quality_status
        FROM observation_versions
        WHERE fund_code = '510300' AND as_of_date = ? AND series = 'shares'
        ORDER BY version_no
        """,
        (DATA_DAY,),
    ).fetchall()
    assert versions[0]["snapshot_phase"] == "evening"
    assert versions[1]["snapshot_phase"] == "morning"
    assert versions[0]["first_seen_at"] == versions[1]["first_seen_at"] == first_seen
    assert versions[1]["standardized_value"] == "1010000"
    assert versions[1]["quality_status"] == "ok"
    morning_store.close()


def test_same_number_phase_change_still_appends_without_rewriting_first_seen(store):
    ingest(store, [_share("159919", DATA_DAY, "50")], EVENING, phase="evening")
    result = ingest(store, [_share("159919", DATA_DAY, "50")], MORNING, phase="morning")
    assert result["actions"] == ["phase_revised"]
    observation = store.get_observation("159919", DATA_DAY, "shares", "szse_shares")
    assert observation["first_seen_at"].startswith("2026-10-21T20:30")
    assert store.count_versions("159919", DATA_DAY, "shares", "szse_shares") == 2
    assert observation["authoritative"] == 1


def test_gap_checkpoint_evolves_waiting_update_to_complete_on_same_db(tmp_path):
    db_path = tmp_path / "gaps.sqlite"
    store = Store(db_path, tmp_path / "raw")

    def run(points, now, phase):
        batch = FetchBatch("sse_shares", points, [], [], ["https://query.sse.com.cn/"])
        summary = finish_batch(
            store,
            batch,
            now=now,
            phase_override=phase,
            closures=set(),
            abnormal_ratio=Decimal("0.20"),
            split_ratio=Decimal("0.50"),
            morning_start=time(8, 0),
            session_close=time(15, 0),
            expected_days=[date.fromisoformat(DATA_DAY)],
            expected_funds=["510300", "510310", "510330"],
            expected_series=["shares"],
        )
        mark_checkpoint(
            store,
            "sse_shares",
            f"{DATA_DAY}:{DATA_DAY}:{phase}",
            summary,
            now,
            start=date.fromisoformat(DATA_DAY),
            end=date.fromisoformat(DATA_DAY),
            closures=set(),
        )
        return summary

    # Evening: only 510300 present → gaps for the other two → waiting_update.
    first = run([_share("510300", DATA_DAY, "10")], EVENING, "evening")
    assert first["errors"] == []
    assert first["gaps"] == 2
    assert first["checkpoint"] == "waiting_update"
    assert should_skip(store, "sse_shares", f"{DATA_DAY}:{DATA_DAY}:evening", False) is False
    store.close()

    store = Store(db_path, tmp_path / "raw")
    second = run(
        [
            _share("510300", DATA_DAY, "10"),
            _share("510310", DATA_DAY, "11"),
            _share("510330", DATA_DAY, "12"),
        ],
        MORNING,
        "morning",
    )
    assert second["gaps"] == 0
    assert second["checkpoint"] == "complete"
    assert should_skip(store, "sse_shares", f"{DATA_DAY}:{DATA_DAY}:morning", False) is True
    # Evening checkpoint key stays as recorded; morning is a separate key.
    evening_cp = store.checkpoint("sse_shares", f"{DATA_DAY}:{DATA_DAY}:evening")
    assert evening_cp["status"] == "waiting_update"
    store.close()


def test_510310_jump_stays_isolated_and_blocks_four_fund_aggregate(store):
    # Prior trading day baselines for all four so jump detection has adjacency.
    for fund, value, src in (
        ("510300", "100", "sse_shares"),
        ("510310", "100", "sse_shares"),
        ("510330", "100", "sse_shares"),
        ("159919", "100", "szse_shares"),
    ):
        ingest(store, [_share(fund, PRIOR_DAY, value, src)], EVENING, phase="evening")

    evening_points = [
        _share("510300", DATA_DAY, "101"),
        _share("510310", DATA_DAY, "121"),  # +21% > 20% gate
        _share("510330", DATA_DAY, "102"),
        _share("159919", DATA_DAY, "103"),
    ]
    ingest(store, evening_points, EVENING, phase="evening")
    # Morning revises phase / may keep numbers; jump remains.
    ingest(store, evening_points, MORNING, phase="morning")

    jump = store.latest_join("510310", DATA_DAY, "shares", "sse_shares")
    assert jump["quality_status"] == "abnormal_jump"
    assert int(jump["authoritative"]) == 0
    ok = store.latest_join("510300", DATA_DAY, "shares", "sse_shares")
    assert ok["quality_status"] == "ok"
    assert int(ok["authoritative"]) == 1

    # Nav for three funds only — still no four-fund aggregate because 510310 blocks.
    for fund, source in (
        ("510300", "huatai_nav_table"),
        ("510310", "efunds_nav"),
        ("510330", "chinaamc_nav"),
        ("159919", "jsfund_nav"),
    ):
        ingest(store, [_nav(fund, DATA_DAY, "4.0000", source)], MORNING, phase="morning")

    text = "\n".join(day_lines(store, DATA_DAY, MORNING, 36))
    assert "四只合计：没有" in text
    assert "510310" in text
    assert "不会把缺的当成 0" in text


def test_missing_one_fund_is_not_zero_and_blocks_aggregate(store):
    for fund, value in (("510300", "10"), ("510330", "10"), ("159919", "10")):
        src = "szse_shares" if fund == "159919" else "sse_shares"
        ingest(store, [_share(fund, PRIOR_DAY, value, src)], EVENING, phase="evening")
        ingest(store, [_share(fund, DATA_DAY, "10.1", src)], MORNING, phase="morning")
        nav_src = {
            "510300": "huatai_nav_table",
            "510330": "chinaamc_nav",
            "159919": "jsfund_nav",
        }[fund]
        ingest(store, [_nav(fund, DATA_DAY, "4.0", nav_src)], MORNING, phase="morning")

    text = "\n".join(day_lines(store, DATA_DAY, MORNING, 36))
    assert "510310 没有份额，不记 0" in text
    assert "四只合计：没有" in text
    assert "缺 510310" in text
    assert "0 份" not in text


def test_friday_to_monday_is_backfill_not_morning_for_this_pair():
    friday = date(2026, 10, 16)
    monday = shanghai(2026, 10, 19, 8, 30)
    phase = classify_phase(
        friday,
        monday,
        morning_start=time(8, 0),
        session_close=time(15, 0),
        closures=set(),
    )
    assert phase == "backfill"
    target, auto = morning_session(date(2026, 10, 19), set())
    assert target == friday
    assert auto == "backfill"
    # Natural next morning (Saturday) for Friday evening still counts as morning.
    saturday = shanghai(2026, 10, 17, 8, 15)
    assert (
        classify_phase(
            friday,
            saturday,
            morning_start=time(8, 0),
            session_close=time(15, 0),
            closures=set(),
        )
        == "morning"
    )


def test_wed_evening_thu_morning_clock_phases_match_dot_pair():
    as_of = date(2026, 10, 21)
    assert (
        classify_phase(
            as_of,
            EVENING,
            morning_start=time(8, 0),
            session_close=time(15, 0),
            closures=set(),
        )
        == "evening"
    )
    assert (
        classify_phase(
            as_of,
            MORNING,
            morning_start=time(8, 0),
            session_close=time(15, 0),
            closures=set(),
        )
        == "morning"
    )
    # Before 15:00 same day is not evening.
    assert (
        classify_phase(
            as_of,
            shanghai(2026, 10, 21, 14, 59),
            morning_start=time(8, 0),
            session_close=time(15, 0),
            closures=set(),
        )
        == "before_close"
    )
