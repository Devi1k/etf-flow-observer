from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.pipeline import day_lines
from etf_flow_observer.quality import blocks_flow
from tests.conftest import ingest, shanghai

NOW = shanghai(2026, 10, 16, 9, 0)


def _point(day: str, value: str) -> RawPoint:
    return RawPoint(
        fund_code="510330",
        as_of_date=day,
        series="shares",
        original_value=value,
        original_unit="万份",
        source_name="sse_shares",
        source_url="https://query.sse.com.cn/commonQuery.do",
    )


def test_large_but_not_split_sized_jump_blocks_flow(store):
    ingest(store, [_point("2026-10-14", "10")], NOW, phase="backfill")
    ingest(store, [_point("2026-10-15", "13")], NOW, phase="morning")
    row = store.latest_join("510330", "2026-10-15", "shares", "sse_shares")
    assert row["quality_status"] == "abnormal_jump"
    assert row["standardized_value"] == "130000"
    flags = __import__("json").loads(row["quality_flags"])
    assert blocks_flow(row["quality_status"], flags)
    text = "\n".join(day_lines(store, "2026-10-15", NOW, 36))
    assert "不计算可执行申赎" in text
    assert "四只合计：没有" in text


def test_research_estimate_is_not_described_as_an_executable_signal(store):
    ingest(store, [_point("2026-10-14", "10")], NOW, phase="backfill")
    ingest(store, [_point("2026-10-15", "10.1")], NOW, phase="morning")
    ingest(
        store,
        [
            RawPoint(
                fund_code="510330",
                as_of_date="2026-10-15",
                series="unit_nav",
                original_value="4.0000",
                original_unit="元",
                source_name="chinaamc_nav",
                source_url="https://www.chinaamc.com/product/fundLishijingzhi.do",
            )
        ],
        NOW,
        phase="morning",
    )
    text = "\n".join(day_lines(store, "2026-10-15", NOW, 36))
    assert "不是可执行信号" in text
    assert "上一笔份额状态为 exploratory_backfill" in text
    assert "四只合计：没有" in text


def test_doubling_is_treated_as_a_possible_split_or_merge(store):
    ingest(store, [_point("2026-10-14", "10")], NOW, phase="backfill")
    ingest(store, [_point("2026-10-15", "20")], NOW, phase="morning")
    row = store.latest_join("510330", "2026-10-15", "shares", "sse_shares")
    assert row["quality_status"] == "suspect_split_or_merge"
    assert blocks_flow(row["quality_status"], [])
