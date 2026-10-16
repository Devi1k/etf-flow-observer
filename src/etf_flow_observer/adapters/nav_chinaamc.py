"""华夏 510330 历史净值。

表格列顺序是：净值日期、单位净值、累计净值、资产净值。
第一页查询带 isQuery=true。后面的页不能再带 isQuery，否则站点会回到第 1 页。
"""

from __future__ import annotations

import re
import urllib.parse
from datetime import date

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, attach_fetch, filter_window

SOURCE = "chinaamc_nav"
API = "https://www.chinaamc.com/product/fundLishijingzhi.do?fundcode=510330"
FUND = "510330"
ROW = re.compile(
    r"<tr>\s*<td>\s*(\d{4}-\d{2}-\d{2})\s*</td>\s*"
    r"<td>\s*(?:<span>)?\s*([0-9]+(?:\.[0-9]+)?|--)\s*(?:</span>)?\s*</td>\s*"
    r"<td>\s*(?:<span>)?\s*([0-9]+(?:\.[0-9]+)?|--)?\s*(?:</span>)?\s*</td>",
    re.IGNORECASE,
)
TOTAL_PAGE = re.compile(r"totalPage\s*=\s*'(\d+)'")
CURRENT_PAGE = re.compile(r"currentPage\s*=\s*'(\d+)'")


def build_form(start: date, end: date, page_index: int, *, first_page: bool) -> bytes:
    fields = {
        "fundcode": FUND,
        "beginDate": start.isoformat(),
        "endDate": end.isoformat(),
        "pageIndex": str(page_index),
    }
    if first_page:
        fields["isQuery"] = "true"
    return urllib.parse.urlencode(fields).encode("utf-8")


def parse_chinaamc(html: str, source_url: str) -> tuple[list[RawPoint], int | None, int | None]:
    totals = TOTAL_PAGE.findall(html)
    currents = CURRENT_PAGE.findall(html)
    total_page = int(totals[0]) if totals else None
    current_page = int(currents[0]) if currents else None
    points: list[RawPoint] = []
    for nav_date, unit_nav, cumulative in ROW.findall(html):
        if unit_nav in {"", "--"}:
            points.append(
                RawPoint(
                    fund_code=FUND,
                    as_of_date=nav_date,
                    series="unit_nav",
                    original_value="",
                    original_unit="元",
                    source_name=SOURCE,
                    source_url=source_url,
                    conflict=True,
                    note="缺少单位净值，拒绝改用累计净值",
                )
            )
        else:
            points.append(
                RawPoint(
                    fund_code=FUND,
                    as_of_date=nav_date,
                    series="unit_nav",
                    original_value=unit_nav,
                    original_unit="元",
                    source_name=SOURCE,
                    source_url=source_url,
                    note="历史净值表第 2 列，单位净值",
                )
            )
        if cumulative and cumulative != "--":
            points.append(
                RawPoint(
                    fund_code=FUND,
                    as_of_date=nav_date,
                    series="cumulative_nav",
                    original_value=cumulative,
                    original_unit="元",
                    source_name=SOURCE,
                    source_url=source_url,
                    note="历史净值表第 3 列，累计净值，不能当作单位净值",
                )
            )
    return points, current_page, total_page


def collect_chinaamc(client, start: date, end: date, *, use_cache: bool) -> FetchBatch:
    points: list[RawPoint] = []
    errors: list[str] = []
    urls: list[str] = []
    page = 1
    total_page = 1
    while page <= total_page:
        body = build_form(start, end, page, first_page=(page == 1))
        urls.append(f"{API}#pageIndex={page}")
        result = client.send(
            "POST",
            API,
            source_name=SOURCE,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.chinaamc.com/",
            },
            body=body,
            use_cache=use_cache,
        )
        if result.error or result.status != 200:
            errors.append(f"华夏第 {page} 页失败: {result.error or result.status}")
            break
        parsed, current, total_page_value = parse_chinaamc(result.text, result.url)
        if current is None or total_page_value is None:
            errors.append(f"华夏第 {page} 页没有页码")
            break
        if current != page:
            errors.append(
                f"华夏页码被重置：请求 {page}，页面显示 {current}。"
                "后续页不能提交 isQuery。"
            )
            break
        total_page = total_page_value
        points.extend(filter_window(attach_fetch(parsed, result), start, end, errors, f"华夏第 {page} 页"))
        page += 1
        if page > 40:
            errors.append("华夏净值分页超过 40 页，停止")
            break
    return FetchBatch(SOURCE, points, errors, [], urls)
