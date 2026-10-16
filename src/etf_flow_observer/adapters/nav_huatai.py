"""华泰柏瑞 510300 净值，只使用 www.huatai-pb.com。

历史表：/common-web/chart/fundnettable/getFundNetTableJson
pages 参数的形式是“页码-每页条数”，例如 1-10。字段 netvalue 是单位净值，
totalnetvalue 是累计净值。

首页静态表可以核对最新单位净值和日期。产品子页以前出现过 502；
若历史接口失败，不改用其他公司的净值。
"""

from __future__ import annotations

import json
import re
import urllib.parse
from datetime import date

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, attach_fetch, filter_window
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.standardize import as_original_text

SOURCE = "huatai_nav_table"
HOMEPAGE_SOURCE = "huatai_homepage"
API = "https://www.huatai-pb.com/common-web/chart/fundnettable/getFundNetTableJson"
HOME = "https://www.huatai-pb.com/"
PRODUCT = "https://www.huatai-pb.com/products/zhishu/510300/index.html"
FUND = "510300"
HOME_ROW = re.compile(
    r'title="510300"[\s\S]{0,900}?class="fundvalue">\s*([0-9]+(?:\.[0-9]+)?)\s*</div>'
    r'\s*<div class="fundcode">\s*(\d{4}-\d{2}-\d{2})',
    re.IGNORECASE,
)


def build_url(start: date, end: date, page: int, page_size: int, site_id: str) -> str:
    query = urllib.parse.urlencode(
        {
            "fundcode": FUND,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "pages": f"{page}-{page_size}",
            "siteId": site_id,
        }
    )
    return f"{API}?{query}"


def parse_huatai_table(payload: object, source_url: str) -> tuple[list[RawPoint], int, int]:
    if not isinstance(payload, dict) or "dataList" not in payload:
        raise ObserverError("华泰柏瑞净值表返回的不是预期 JSON")
    current = int(payload.get("currentPage") or 0)
    total = int(payload.get("totalPage") or 0)
    points: list[RawPoint] = []
    for row in payload.get("dataList") or []:
        nav_date = str(row.get("date") or "").strip()
        if not nav_date:
            continue
        net_value = row.get("netvalue")
        total_net = row.get("totalnetvalue")
        if net_value in (None, "", "--"):
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
                    note="缺少 netvalue，拒绝改用 totalnetvalue",
                )
            )
        else:
            points.append(
                RawPoint(
                    fund_code=FUND,
                    as_of_date=nav_date,
                    series="unit_nav",
                    original_value=as_original_text(net_value),
                    original_unit="元",
                    source_name=SOURCE,
                    source_url=source_url,
                    note="字段 netvalue，单位净值",
                )
            )
        if total_net not in (None, "", "--"):
            points.append(
                RawPoint(
                    fund_code=FUND,
                    as_of_date=nav_date,
                    series="cumulative_nav",
                    original_value=as_original_text(total_net),
                    original_unit="元",
                    source_name=SOURCE,
                    source_url=source_url,
                    note="字段 totalnetvalue，累计净值，不能当作单位净值",
                )
            )
    return points, current, total


def parse_huatai_homepage(html: str) -> RawPoint | None:
    match = HOME_ROW.search(html)
    if match is None:
        return None
    value, nav_date = match.group(1), match.group(2)
    return RawPoint(
        fund_code=FUND,
        as_of_date=nav_date,
        series="unit_nav",
        original_value=value,
        original_unit="元",
        source_name=HOMEPAGE_SOURCE,
        source_url=HOME,
        note="首页静态表的单位净值，只用于和历史表核对",
    )


def collect_huatai(
    client,
    start: date,
    end: date,
    *,
    page_size: int,
    site_id: str,
    use_cache: bool,
    homepage_cross_check: bool,
) -> FetchBatch:
    points: list[RawPoint] = []
    errors: list[str] = []
    notes: list[str] = []
    urls: list[str] = []
    page = 1
    total = 1
    while page <= total:
        url = build_url(start, end, page, page_size, site_id)
        urls.append(url)
        result = client.send(
            "GET",
            url,
            source_name=SOURCE,
            headers={
                "Referer": PRODUCT,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            },
            use_cache=use_cache,
        )
        if result.error or result.status != 200:
            errors.append(f"华泰柏瑞净值表第 {page} 页失败: {result.error or result.status}")
            notes.append("历史净值仍只找华泰柏瑞官网。失败时不改用第三方供应商。")
            break
        try:
            parsed, current, total = parse_huatai_table(result.json(), result.url)
        except (json.JSONDecodeError, ObserverError, ValueError) as exc:
            errors.append(f"华泰柏瑞第 {page} 页无法解析: {exc}")
            break
        if current != page:
            errors.append(f"华泰柏瑞页码错位：请求 {page}，返回 {current}")
            break
        points.extend(
            filter_window(attach_fetch(parsed, result), start, end, errors, f"华泰柏瑞第 {page} 页")
        )
        page += 1
        if page > 40:
            errors.append("华泰柏瑞分页超过 40 页，停止")
            break

    if homepage_cross_check:
        urls.append(HOME)
        home = client.send(
            "GET",
            HOME,
            source_name=HOMEPAGE_SOURCE,
            headers={"Referer": HOME},
            use_cache=use_cache,
        )
        if home.error or home.status != 200:
            errors.append(f"华泰柏瑞首页核对失败: {home.error or home.status}")
        else:
            row = parse_huatai_homepage(home.text)
            if row is None:
                notes.append("首页打开了，但没有解析到 510300 的单位净值和日期")
            else:
                attach_fetch([row], home)
                points.append(row)
                notes.append(f"首页静态表 {row.as_of_date} 单位净值 {row.original_value}")
    return FetchBatch(SOURCE, points, errors, notes, urls)
