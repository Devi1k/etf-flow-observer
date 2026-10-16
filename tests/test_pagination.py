import json
from datetime import date
from email.message import Message

from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.adapters.nav_chinaamc import build_form, collect_chinaamc
from etf_flow_observer.adapters.nav_efunds import collect_efunds
from etf_flow_observer.adapters.szse_shares import parse_szse
from etf_flow_observer.http_client import HttpClient
from etf_flow_observer.pipeline import dedupe_points
from tests.conftest import ingest, shanghai


def test_later_chinaamc_page_omits_is_query():
    first = build_form(date(2026, 8, 1), date(2026, 10, 16), 1, first_page=True)
    second = build_form(date(2026, 8, 1), date(2026, 10, 16), 2, first_page=False)
    assert b"isQuery=true" in first
    assert b"pageIndex=1" in first
    assert b"isQuery" not in second
    assert b"pageIndex=2" in second


def test_chinaamc_client_requests_page_two_without_resetting(store):
    bodies = []

    def transport(method, url, headers, body):
        bodies.append(body)
        page = 2 if b"pageIndex=2" in body else 1
        current = page
        html = (
            f"<script>let totalPage = '2'; let currentPage = '{current}';</script>"
            f"<tr><td>2026-10-1{page}</td><td><span>4.10</span></td><td><span>2.10</span></td></tr>"
        )
        return 200, Message(), html.encode()

    client = _client(store, transport)
    batch = collect_chinaamc(
        client, date(2026, 10, 1), date(2026, 10, 16), use_cache=False
    )
    assert batch.errors == []
    assert b"isQuery=true" in bodies[0]
    assert b"isQuery" not in bodies[1]
    assert len(bodies) == 2


def test_same_page_duplicate_collapses_and_conflict_keeps_no_number(store):
    same = [
        _nav("4.10"),
        _nav("4.10"),
    ]
    kept, _notes = dedupe_points(same)
    assert len(kept) == 1
    assert "pagination_duplicate_same_value" in kept[0].flags

    conflict = [_nav("4.10"), _nav("4.20")]
    kept, notes = dedupe_points(conflict)
    assert kept[0].conflict is True
    assert notes
    result = ingest(store, conflict, shanghai(2026, 10, 16, 9, 0), phase="morning")
    assert result["actions"] == ["created"]
    row = store.latest_join("510330", "2026-10-15", "unit_nav", "chinaamc_nav")
    assert row["standardized_value"] is None
    assert row["quality_status"] == "duplicate_conflict"
    assert row["original_value"] == ""


def test_efunds_walks_zero_based_pages(store):
    seen = []

    def transport(method, url, headers, body):
        payload = json.loads(body)
        seen.append(payload["pageIndex"])
        rows = [
            {"navDate": "2026-10-15", "netValue": "4.1164", "totalNetValue": "2.1879"}
        ]
        if payload["pageIndex"] == 1:
            rows = [
                {"navDate": "2026-10-08", "netValue": "4.2578", "totalNetValue": "2.2586"}
            ]
        data = {
            "status": 1,
            "message": "success",
            "data": {"pageSize": 5, "pageIndex": payload["pageIndex"], "total": 6, "data": rows},
        }
        return 200, Message(), json.dumps(data).encode()

    client = _client(store, transport)
    batch = collect_efunds(
        client,
        date(2026, 10, 1),
        date(2026, 10, 16),
        page_size=5,
        use_cache=False,
    )
    assert batch.errors == []
    assert seen == [0, 1]
    dates = sorted({item.as_of_date for item in batch.points if item.series == "unit_nav"})
    assert dates == ["2026-10-08", "2026-10-15"]


def test_szse_duplicate_rows_do_not_pick_one(store):
    payload = [
        {
            "metadata": {"pageno": 1, "pagecount": 1},
            "data": [
                {
                    "size_date": "2026-10-15",
                    "fund_code": "159919",
                    "security_short_name": "沪深300ETF嘉实",
                    "current_size": "100",
                },
                {
                    "size_date": "2026-10-15",
                    "fund_code": "159919",
                    "security_short_name": "沪深300ETF嘉实",
                    "current_size": "110",
                },
            ],
            "error": None,
        }
    ]
    points, page_no, page_count = parse_szse(payload, "https://www.szse.cn/api")
    assert (page_no, page_count) == (1, 1)
    ingest(store, points, shanghai(2026, 10, 16, 9, 0), phase="morning")
    row = store.latest_join("159919", "2026-10-15", "shares", "szse_shares")
    assert row["quality_status"] == "duplicate_conflict"
    assert row["standardized_value"] is None


def _nav(value: str) -> RawPoint:
    return RawPoint(
        fund_code="510330",
        as_of_date="2026-10-15",
        series="unit_nav",
        original_value=value,
        original_unit="元",
        source_name="chinaamc_nav",
        source_url="https://www.chinaamc.com/product/fundLishijingzhi.do",
    )


def _client(store, transport) -> HttpClient:
    return HttpClient(
        store,
        user_agent="test",
        min_interval_seconds=0,
        timeout_seconds=5,
        max_retries=1,
        cache_ttl_seconds=0,
        max_http_requests=10,
        sleeper=lambda _seconds: None,
        clock=lambda: shanghai(2026, 10, 16, 9, 0),
        transport=transport,
    )
