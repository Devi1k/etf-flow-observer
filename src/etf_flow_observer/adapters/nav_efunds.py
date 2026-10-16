"""易方达 510310 单位净值。

使用 netValue。totalNetValue 是累计净值，单独入库，绝不能填进单位净值。
已核对的请求体是 pageIndex 从 0 开始，siteID 为 1。
"""

from __future__ import annotations

import json
from datetime import date

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, attach_fetch, filter_window
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.standardize import as_original_text

SOURCE = "efunds_nav"
API = "https://api.efunds.com.cn/xcowch/front/fund/nav"
FUND = "510310"


def build_body(start: date, end: date, page_index: int, page_size: int) -> bytes:
    payload = {
        "fundCode": FUND,
        "pageIndex": page_index,
        "pageSize": page_size,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "siteID": 1,
    }
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def parse_efunds(payload: object, source_url: str) -> tuple[list[RawPoint], int, int, int, int]:
    if not isinstance(payload, dict):
        raise ObserverError("易方达返回的不是对象")
    if payload.get("status") not in (1, "1"):
        raise ObserverError(f"易方达状态异常: {payload.get('message')}")
    block = payload.get("data") or {}
    rows = block.get("data") or []
    page_index = int(block.get("pageIndex") or 0)
    total = int(block.get("total") or 0)
    page_size = int(block.get("pageSize") or 0)
    points: list[RawPoint] = []
    for row in rows:
        nav_date = str(row.get("navDate") or "").strip()
        if not nav_date:
            continue
        net_value = row.get("netValue")
        total_net = row.get("totalNetValue")
        if net_value not in (None, "", "--"):
            points.append(
                RawPoint(
                    fund_code=FUND,
                    as_of_date=nav_date,
                    series="unit_nav",
                    original_value=as_original_text(net_value),
                    original_unit="元",
                    source_name=SOURCE,
                    source_url=source_url,
                    note="字段 netValue，单位净值",
                )
            )
        else:
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
                    note="缺少 netValue，拒绝改用 totalNetValue",
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
                    note="字段 totalNetValue，累计净值，不能当作单位净值",
                )
            )
    return points, page_index, total, page_size, len(rows)


def collect_efunds(client, start: date, end: date, *, page_size: int, use_cache: bool) -> FetchBatch:
    """翻页只看响应里的 pageIndex、pageSize、total 和本页日期行数。

    请求里的 page_size 不参与停止条件。日期行数不是单位净值加累计净值的点数。
    """
    points: list[RawPoint] = []
    errors: list[str] = []
    urls: list[str] = []
    page_index = 0
    total: int | None = None
    date_rows = 0
    while True:
        body = build_body(start, end, page_index, page_size)
        urls.append(f"{API}#pageIndex={page_index}")
        result = client.send(
            "POST",
            API,
            source_name=SOURCE,
            headers={
                "Content-Type": "application/json",
                "Referer": "https://www.efunds.com.cn/",
                "Origin": "https://www.efunds.com.cn",
                "Accept": "application/json",
            },
            body=body,
            use_cache=use_cache,
        )
        if result.error or result.status != 200:
            errors.append(f"易方达第 {page_index} 页失败: {result.error or result.status}")
            break
        try:
            parsed, got_index, total, got_size, row_count = parse_efunds(result.json(), result.url)
        except (json.JSONDecodeError, ObserverError, ValueError, TypeError) as exc:
            errors.append(f"易方达第 {page_index} 页无法解析: {exc}")
            break
        if got_index != page_index:
            errors.append(f"易方达页码错位：请求 {page_index}，返回 {got_index}")
            break
        if row_count == 0 and (total is None or date_rows < total):
            errors.append(
                f"易方达第 {page_index} 页没有日期行，累计 {date_rows} 行，响应 total 为 {total}，分页不完整"
            )
            break
        if got_size and row_count < got_size and total is not None and date_rows + row_count < total:
            errors.append(
                f"易方达第 {page_index} 页只有 {row_count} 行，响应 pageSize 为 {got_size}，"
                f"累计仍少于 total {total}，分页不完整"
            )
            points.extend(
                filter_window(attach_fetch(parsed, result), start, end, errors, f"易方达第 {page_index} 页")
            )
            break
        kept = filter_window(attach_fetch(parsed, result), start, end, errors, f"易方达第 {page_index} 页")
        points.extend(kept)
        date_rows += row_count
        if total is not None and date_rows >= total:
            break
        if row_count == 0:
            break
        page_index += 1
        if page_index > 30:
            errors.append("易方达分页超过 30 页，停止")
            break
    if total is not None and date_rows < total and not any("分页不完整" in item for item in errors):
        errors.append(f"易方达日期行 {date_rows} 少于响应 total {total}，分页不完整")
    return FetchBatch(SOURCE, points, errors, [], urls)
