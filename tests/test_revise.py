from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.timing import classify_phase
from tests.conftest import ingest, shanghai

DAY = "2026-10-15"


def _share(value: str) -> RawPoint:
    return RawPoint(
        fund_code="159919",
        as_of_date=DAY,
        series="shares",
        original_value=value,
        original_unit="万份",
        source_name="szse_shares",
        source_url="https://www.szse.cn/api/report/ShowReport/data",
    )


def test_evening_snapshot_is_revised_next_morning(store):
    evening = ingest(store, [_share("100")], shanghai(2026, 10, 15, 21, 0), phase="evening")
    morning = ingest(store, [_share("101")], shanghai(2026, 10, 16, 8, 30), phase="morning")
    assert evening["actions"] == ["created"]
    assert morning["actions"] == ["revised"]
    assert store.count_versions("159919", DAY, "shares", "szse_shares") == 2
    observation = store.get_observation("159919", DAY, "shares", "szse_shares")
    assert observation["first_seen_at"].startswith("2026-10-15T21:00")
    assert observation["revised_at"].startswith("2026-10-16T08:30")
    assert observation["authoritative"] == 1
    versions = store.conn.execute(
        """
        SELECT version_no, snapshot_phase, quality_status, standardized_value, first_seen_at
        FROM observation_versions
        ORDER BY version_no
        """
    ).fetchall()
    assert versions[0]["snapshot_phase"] == "evening"
    assert versions[0]["quality_status"] == "provisional_evening"
    assert versions[0]["first_seen_at"] == versions[1]["first_seen_at"]
    assert versions[1]["snapshot_phase"] == "morning"
    assert versions[1]["quality_status"] == "ok"
    assert versions[1]["standardized_value"] == "1010000"


def test_monday_fetch_of_friday_is_backfill_not_a_captured_morning():
    friday = __import__("datetime").date(2026, 10, 16)
    monday_morning = shanghai(2026, 10, 19, 8, 30)
    assert friday.weekday() == 4
    phase = classify_phase(
        friday,
        monday_morning,
        morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0),
        closures=set(),
    )
    assert phase == "backfill"
    saturday = shanghai(2026, 10, 17, 9, 0)
    assert (
        classify_phase(
            friday,
            saturday,
            morning_start=__import__("datetime").time(8, 0),
            session_close=__import__("datetime").time(15, 0),
            closures=set(),
        )
        == "morning"
    )


def test_same_morning_number_after_evening_keeps_first_seen(store):
    ingest(store, [_share("100")], shanghai(2026, 10, 15, 21, 0), phase="evening")
    result = ingest(store, [_share("100")], shanghai(2026, 10, 16, 8, 30), phase="morning")
    assert result["actions"] == ["phase_revised"]
    observation = store.get_observation("159919", DAY, "shares", "szse_shares")
    assert observation["first_seen_at"].startswith("2026-10-15T21:00")
    assert observation["revised_at"].startswith("2026-10-16T08:30")
    assert store.count_versions("159919", DAY, "shares", "szse_shares") == 2
