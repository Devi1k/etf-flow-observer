from datetime import date

from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.quality import blocks_flow
from etf_flow_observer.timing import expected_trading_days
from tests.conftest import ingest, shanghai

NOW = shanghai(2026, 10, 16, 9, 0)


def test_weekend_and_configured_closure_are_not_trading_days():
    days = expected_trading_days(date(2026, 10, 15), date(2026, 10, 19), {date(2026, 10, 16)})
    assert days == [date(2026, 10, 15), date(2026, 10, 19)]


def test_share_row_on_a_holiday_is_kept_but_not_turned_into_flow(store):
    point = RawPoint(
        fund_code="510300",
        as_of_date="2026-10-17",
        series="shares",
        original_value="10",
        original_unit="万份",
        source_name="sse_shares",
        source_url="https://query.sse.com.cn/commonQuery.do",
    )
    ingest(store, [point], NOW, phase="backfill")
    row = store.latest_join("510300", "2026-10-17", "shares", "sse_shares")
    assert row["standardized_value"] == "100000"
    assert row["quality_status"] == "holiday_or_non_trading"
    assert blocks_flow(row["quality_status"], [])
    assert row["standardized_value"] != "0"


def test_configured_closure_blocks_a_weekday(store):
    point = RawPoint(
        fund_code="510310",
        as_of_date="2026-10-14",
        series="shares",
        original_value="8",
        original_unit="万份",
        source_name="sse_shares",
        source_url="https://query.sse.com.cn/commonQuery.do",
    )
    ingest(store, [point], NOW, phase="morning", closures={date(2026, 10, 14)})
    row = store.latest_join("510310", "2026-10-14", "shares", "sse_shares")
    assert row["quality_status"] == "holiday_or_non_trading"


def test_example_config_carries_official_2026_closures():
    from pathlib import Path
    import tomllib

    cfg = tomllib.loads((Path(__file__).resolve().parents[1] / "config" / "example.toml").read_text(encoding="utf-8"))
    closures = {date.fromisoformat(d) for d in cfg["calendar"]["closures"]}
    for d in [date(2026, 9, 25), date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7)]:
        assert d in closures
    days = expected_trading_days(date(2026, 9, 24), date(2026, 10, 9), closures)
    assert days == [date(2026, 9, 24), date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 8), date(2026, 10, 9)]
