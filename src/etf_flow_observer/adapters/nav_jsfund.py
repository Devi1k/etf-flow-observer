"""嘉实 159919 净值。

指定页面是 www.jsfund.com.cn 上的 NavHistory.jsp。
份额净值在前，累计净值在后。页面一次返回很长的历史，调用方按日期窗口截取。
若主域名 DNS 或 TLS 失败，才显式改用同一 JSP 路径的 www.jsfund.cn，并在记录里写明。
这不是第三方净值供应商。
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, in_window

SOURCE = "jsfund_nav"
FUND = "159919"
ROW = re.compile(
    r"<tr>\s*<td>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*"
    r"<td>\s*([0-9]+(?:\.[0-9]+)?)\s*</td>\s*"
    r"<td>\s*([0-9]+(?:\.[0-9]+)?)\s*</td>\s*</tr>",
    re.IGNORECASE,
)


def build_url(base: str) -> str:
    parts = urlsplit(base)
    query = "FundCode=159919&SiteID=1"
    if parts.query:
        query = parts.query
    return urlunsplit((parts.scheme or "https", parts.netloc, parts.path, query, ""))


def parse_jsfund(html: str, source_url: str, *, used_fallback: bool) -> list[RawPoint]:
    note_flag = "主域名不可达，改用 www.jsfund.cn 上的同一嘉实 JSP" if used_fallback else "份额净值"
    points: list[RawPoint] = []
    for nav_date, unit_nav, cumulative in ROW.findall(html):
        flags = ["primary_host_unreachable_used_official_apex"] if used_fallback else []
        points.append(
            RawPoint(
                fund_code=FUND,
                as_of_date=nav_date,
                series="unit_nav",
                original_value=unit_nav,
                original_unit="元",
                source_name=SOURCE,
                source_url=source_url,
                note=f"份额净值。{note_flag}",
                flags=list(flags),
            )
        )
        points.append(
            RawPoint(
                fund_code=FUND,
                as_of_date=nav_date,
                series="cumulative_nav",
                original_value=cumulative,
                original_unit="元",
                source_name=SOURCE,
                source_url=source_url,
                note="累计净值，不能当作份额净值",
                flags=list(flags),
            )
        )
    return points


def collect_jsfund(
    client,
    start: date,
    end: date,
    *,
    primary_url: str,
    fallback_url: str,
    use_cache: bool,
) -> FetchBatch:
    notes: list[str] = []
    errors: list[str] = []
    urls = [build_url(primary_url)]
    used_fallback = False
    result = client.send(
        "GET",
        urls[0],
        source_name=SOURCE,
        headers={"Referer": "https://www.jsfund.com.cn/"},
        use_cache=use_cache,
    )
    if result.error or result.status != 200 or "份额净值" not in result.text:
        notes.append(
            f"嘉实主域名未拿到净值表: {result.error or result.status or '页面里没有份额净值'}。"
            "改试 www.jsfund.cn 上的同一路径。"
        )
        fallback = build_url(fallback_url)
        urls.append(fallback)
        result = client.send(
            "GET",
            fallback,
            source_name=SOURCE,
            headers={"Referer": "https://www.jsfund.cn/"},
            use_cache=use_cache,
        )
        used_fallback = True
    if result.error or result.status != 200:
        errors.append(f"嘉实净值失败: {result.error or result.status}")
        return FetchBatch(SOURCE, [], errors, notes, urls)
    if "嘉实" not in result.text or "份额净值" not in result.text:
        errors.append("返回页面不像嘉实基金的历史净值表，拒绝入库")
        return FetchBatch(SOURCE, [], errors, notes, urls)
    parsed = parse_jsfund(result.text, result.url, used_fallback=used_fallback)
    points = [item for item in parsed if in_window(item.as_of_date, start, end)]
    if not points:
        errors.append("嘉实页面里没有窗口内的净值行")
    return FetchBatch(SOURCE, points, errors, notes, urls)
