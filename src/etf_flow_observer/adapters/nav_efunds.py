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


def parse_efunds(payload: object, source_url: str) -> tuple[list[RawPoint], int, int, int, int, list[str]]:
    """Parse one page. Returns points, page_index, total, page_size, physical_row_count, row_errors."""
    row_errors: list[str] = []
    if not isinstance(payload, dict):
        raise ObserverError("易方达返回的不是对象")
    if payload.get("status") not in (1, "1"):
        raise ObserverError(f"易方达状态异常: {payload.get('message')}")
    block = payload.get("data")
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ObserverError("易方达 data 不是对象")
    rows = block.get("data")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ObserverError("易方达 data.data 不是列表")
    try:
        page_index = int(block.get("pageIndex") if block.get("pageIndex") is not None else 0)
        total = int(block.get("total") if block.get("total") is not None else 0)
        page_size = int(block.get("pageSize") if block.get("pageSize") is not None else 0)
    except (TypeError, ValueError) as exc:
        raise ObserverError(f"易方达分页字段无效: {exc}") from exc
    points: list[RawPoint] = []
    physical = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            row_errors.append(f"易方达第 {page_index} 页第 {index} 行不是对象: {type(row).__name__}")
            continue
        physical += 1
        nav_date = str(row.get("navDate") or "").strip()
        if not nav_date:
            row_errors.append(f"易方达第 {page_index} 页第 {index} 行缺少 navDate")
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
    return points, page_index, total, page_size, physical, row_errors


def collect_efunds(client, start: date, end: date, *, page_size: int, use_cache: bool) -> FetchBatch:
    """翻页按唯一日期数与响应 metadata 判定完整性。

    物理行数不能替代唯一日期。重复页、total 中途缩小等异常一律记不完整，
    绝不当成完成。
    """
    points: list[RawPoint] = []
    errors: list[str] = []
    urls: list[str] = []
    page_index = 0
    total: int | None = None
    seen_dates: set[str] = set()
    physical_rows = 0
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
            parsed, got_index, page_total, got_size, row_count, row_errors = parse_efunds(
                result.json(), result.url
            )
        except (json.JSONDecodeError, ObserverError, ValueError, TypeError) as exc:
            errors.append(f"易方达第 {page_index} 页无法解析: {exc}")
            break
        errors.extend(row_errors)
        if got_index != page_index:
            errors.append(f"易方达页码错位：请求 {page_index}，返回 {got_index}")
            break
        if total is None:
            total = page_total
        elif page_total != total:
            errors.append(
                f"易方达分页 metadata 不一致：先前 total={total}，第 {page_index} 页 total={page_total}"
            )
            points.extend(
                filter_window(attach_fetch(parsed, result), start, end, errors, f"易方达第 {page_index} 页")
            )
            break
        if row_count == 0 and (total is None or len(seen_dates) < total):
            errors.append(
                f"易方达第 {page_index} 页没有日期行，累计唯一日期 {len(seen_dates)}，"
                f"响应 total 为 {total}，分页不完整"
            )
            break
        page_dates = {
            item.as_of_date
            for item in parsed
            if item.series == "unit_nav" and item.as_of_date
        }
        overlap = page_dates & seen_dates
        if overlap:
            sample = sorted(overlap)[:3]
            errors.append(
                f"易方达第 {page_index} 页与先前页日期重复（例 {', '.join(sample)}），"
                f"拒绝按物理行数当成完成"
            )
            points.extend(
                filter_window(attach_fetch(parsed, result), start, end, errors, f"易方达第 {page_index} 页")
            )
            break
        if got_size and row_count < got_size and total is not None and len(seen_dates) + len(page_dates) < total:
            errors.append(
                f"易方达第 {page_index} 页只有 {row_count} 行，响应 pageSize 为 {got_size}，"
                f"累计唯一日期仍少于 total {total}，分页不完整"
            )
            points.extend(
                filter_window(attach_fetch(parsed, result), start, end, errors, f"易方达第 {page_index} 页")
            )
            break
        kept = filter_window(attach_fetch(parsed, result), start, end, errors, f"易方达第 {page_index} 页")
        points.extend(kept)
        seen_dates.update(page_dates)
        physical_rows += row_count
        if total is not None and len(seen_dates) >= total:
            break
        if row_count == 0:
            break
        page_index += 1
        if page_index > 30:
            errors.append("易方达分页超过 30 页，停止")
            break
    if total is not None and len(seen_dates) < total and not any("分页不完整" in item for item in errors):
        errors.append(
            f"易方达唯一日期 {len(seen_dates)}（物理行 {physical_rows}）少于响应 total {total}，分页不完整"
        )
    return FetchBatch(SOURCE, points, errors, [], urls)
