from datetime import timedelta
from decimal import Decimal

import pytest

from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.pipeline import day_lines, record_expected_gaps
from etf_flow_observer.quality import effective_status
from etf_flow_observer.signals import require_four
from etf_flow_observer.universe import FUND_CODES, SSE_SHARE_CODES
from tests.conftest import ingest, shanghai

DAY = "2026-10-15"
NOW = shanghai(2026, 10, 16, 9, 0)


def test_missing_fund_is_not_zero_and_blocks_the_four_fund_total(store):
    ingest(
        store,
        [
            RawPoint(
                fund_code="510300",
                as_of_date=DAY,
                series="shares",
                original_value="10",
                original_unit="万份",
                source_name="sse_shares",
                source_url="https://query.sse.com.cn/commonQuery.do",
            )
        ],
        NOW,
        phase="morning",
    )
    record_expected_gaps(
        store,
        funds=list(SSE_SHARE_CODES),
        series=["shares"],
        source_name="sse_shares",
        days=[__import__("datetime").date.fromisoformat(DAY)],
        now=NOW,
    )
    assert store.get_observation("510310", DAY, "shares", "sse_shares") is None
    assert store.get_observation("510330", DAY, "shares", "sse_shares") is None
    zeros = store.conn.execute(
        "SELECT COUNT(*) AS n FROM observation_versions WHERE standardized_value = '0'"
    ).fetchone()
    assert zeros["n"] == 0
    gap_codes = {
        row["fund_code"]
        for row in store.conn.execute("SELECT fund_code FROM data_gaps")
    }
    assert gap_codes == {"510310", "510330"}
    text = "\n".join(day_lines(store, DAY, NOW, 36))
    assert "四只合计：没有" in text
    assert "510310" in text


def test_stale_ok_row_cannot_be_treated_as_fresh():
    now = shanghai(2026, 10, 16, 12, 0)
    assert effective_status("ok", now - timedelta(hours=40), now, timedelta(hours=36)) == "stale"
    assert effective_status("ok", now - timedelta(hours=2), now, timedelta(hours=36)) == "ok"


def test_partial_universe_cannot_be_summed_as_zero():
    values = {code: Decimal("1") for code in FUND_CODES}
    values["159919"] = None
    with pytest.raises(ObserverError, match="159919"):
        require_four(values, "四只合计")
