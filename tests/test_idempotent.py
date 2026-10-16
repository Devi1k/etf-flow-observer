import json
from datetime import date

from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.adapters.sse_shares import collect_sse
from etf_flow_observer.http_client import HttpClient
from tests.conftest import ingest, shanghai

DAY = "2026-10-15"
NOW = shanghai(2026, 10, 16, 9, 30)


def _share(value: str) -> RawPoint:
    return RawPoint(
        fund_code="510300",
        as_of_date=DAY,
        series="shares",
        original_value=value,
        original_unit="万份",
        source_name="sse_shares",
        source_url="https://query.sse.com.cn/commonQuery.do",
    )


def test_same_observation_is_not_stored_twice(store):
    first = ingest(store, [_share("10")], NOW, phase="morning")
    second = ingest(store, [_share("10")], shanghai(2026, 10, 16, 10, 0), phase="morning")
    assert first["actions"] == ["created"]
    assert second["actions"] == ["confirmed"]
    assert store.count_versions("510300", DAY, "shares", "sse_shares") == 1
    row = store.get_observation("510300", DAY, "shares", "sse_shares")
    assert row["first_seen_at"].startswith("2026-10-16T09:30")
    assert row["revised_at"] is None


def test_repeat_sse_fetch_does_not_add_a_version(store):
    payload = {
        "pageHelp": {"pageNo": 1, "pageCount": 1, "total": 1},
        "result": [
            {"STAT_DATE": DAY, "SEC_CODE": "510300", "SEC_NAME": "300ETF", "TOT_VOL": "10"},
            {"STAT_DATE": DAY, "SEC_CODE": "510050", "SEC_NAME": "50ETF", "TOT_VOL": "999"},
        ],
    }
    body = json.dumps(payload).encode()

    def transport(method, url, headers, request_body):
        return 200, {}, body

    client = HttpClient(
        store,
        user_agent="test",
        min_interval_seconds=0,
        timeout_seconds=5,
        max_retries=1,
        cache_ttl_seconds=0,
        max_http_requests=10,
        sleeper=lambda _seconds: None,
        clock=lambda: NOW,
        transport=transport,
    )
    for _ in range(2):
        batch = collect_sse(client, [date.fromisoformat(DAY)], page_size=1000, use_cache=False)
        ingest(store, batch.points, NOW, phase="morning")
    assert store.count_versions("510300", DAY, "shares", "sse_shares") == 1
    assert store.get_observation("510050", DAY, "shares", "sse_shares") is None
    assert store.raw_count() == 2
