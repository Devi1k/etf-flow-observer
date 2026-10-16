from decimal import Decimal

from etf_flow_observer.adapters.nav_chinaamc import parse_chinaamc
from etf_flow_observer.adapters.nav_efunds import parse_efunds
from etf_flow_observer.adapters.nav_huatai import parse_huatai_table
from etf_flow_observer.adapters.nav_jsfund import parse_jsfund
from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.pipeline import compare_huatai_homepage
from etf_flow_observer.signals import daily_flow
from tests.conftest import ingest, shanghai


EFUNDS = {
    "status": 1,
    "message": "success",
    "data": {
        "pageSize": 5,
        "pageIndex": 0,
        "total": 1,
        "data": [
            {
                "navDate": "2026-10-15",
                "netValue": "4.1164",
                "totalNetValue": "2.1879",
            }
        ],
    },
}

HUATAI = {
    "currentPage": 1,
    "totalPage": 1,
    "dataList": [
        {"date": "2026-10-15", "netvalue": "4.2366", "totalnetvalue": "1.8980"}
    ],
}

CHINAAMC = """
<script>let totalPage = '1'; let currentPage = '1';</script>
<tr><td>2026-10-15</td><td><span>4.4176</span></td><td><span>2.1522</span></td></tr>
"""

JSFUND = """
<title>嘉实基金</title>
<tr><td class="mm_r_table3_t">日期</td><td>份额净值</td><td>累计净值</td></tr>
<tr><td>2026-10-15</td><td>4.4226</td><td>2.0499</td></tr>
"""


def _pair(points):
    unit = next(item for item in points if item.series == "unit_nav")
    cumulative = next(item for item in points if item.series == "cumulative_nav")
    return unit, cumulative


def test_unit_nav_is_not_cumulative_nav():
    samples = [
        _pair(parse_efunds(EFUNDS, "https://api.efunds.com.cn/xcowch/front/fund/nav")[0]),
        _pair(parse_huatai_table(HUATAI, "https://www.huatai-pb.com/nav")[0]),
        _pair(parse_chinaamc(CHINAAMC, "https://www.chinaamc.com/product/fundLishijingzhi.do")[0]),
        _pair(parse_jsfund(JSFUND, "https://www.jsfund.cn/nav", used_fallback=False)),
    ]
    for unit, cumulative in samples:
        assert unit.original_value != cumulative.original_value
        assert "累计" in cumulative.note
        delta = Decimal("100000")
        assert daily_flow(delta, Decimal(unit.original_value)) != daily_flow(
            delta, Decimal(cumulative.original_value)
        )


def test_homepage_cross_check_uses_qualified_columns(store):
    now = shanghai(2026, 10, 16, 16, 30)
    common = dict(
        fund_code="510300",
        as_of_date="2026-10-15",
        series="unit_nav",
        original_unit="元",
        source_url="https://www.huatai-pb.com/",
    )
    ingest(
        store,
        [
            RawPoint(original_value="4.2366", source_name="huatai_nav_table", **common),
            RawPoint(original_value="4.2366", source_name="huatai_homepage", **common),
        ],
        now,
        phase="morning",
    )
    notes = compare_huatai_homepage(store, now)
    assert notes == ["510300 2026-10-15 首页和历史表单位净值一致"]


def test_missing_unit_nav_does_not_fall_back_to_cumulative():
    payload = {
        "status": 1,
        "message": "success",
        "data": {
            "pageSize": 1,
            "pageIndex": 0,
            "total": 1,
            "data": [{"navDate": "2026-10-15", "netValue": None, "totalNetValue": "2.1879"}],
        },
    }
    points, *_ = parse_efunds(payload, "https://api.efunds.com.cn/nav")
    unit = next(item for item in points if item.series == "unit_nav")
    cumulative = next(item for item in points if item.series == "cumulative_nav")
    assert unit.conflict is True
    assert unit.original_value == ""
    assert cumulative.original_value == "2.1879"
