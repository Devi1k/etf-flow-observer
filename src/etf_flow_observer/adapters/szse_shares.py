"""深交所 159919 份额。current_size 的单位是万份，数字里可能有千分位。

接口页脚写明：T 日晚间更新的 T 日规模仅供参考，以 T+1 日早间更新的为准。
分页参数是 PAGENO，每页条数由返回的 metadata.pagesize 决定。
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, attach_fetch, filter_window
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.standardize import as_original_text

SOURCE = "szse_shares"
PAGE = "https://www.szse.cn/market/fund/disc/index.html"
API = "https://www.szse.cn/api/report/ShowReport/data"
FUND = "159919"


def build_url(start: date, end: date, page: int) -> str:
    query = urllib.parse.urlencode(
        {
            "SHOWTYPE": "JSON",
            "CATALOGID": "scsj_fund_jjgm",
            "jjlb": "ETF",
            "txtDm": FUND,
            "txtStart": start.isoformat(),
            "txtEnd": end.isoformat(),
            "PAGENO": str(page),
        }
    )
    return f"{API}?{query}"


def parse_szse(payload: object, source_url: str) -> tuple[list[RawPoint], int, int, list[str]]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ObserverError("深交所返回的不是预期的报表列表")
    block = payload[0]
    if block.get("error"):
        raise ObserverError(f"深交所报表错误: {block.get('error')}")
    meta = block.get("metadata")
    if meta is None:
        meta = {}
    if not isinstance(meta, dict):
        raise ObserverError("深交所 metadata 不是对象")
    try:
        page_no = int(meta.get("pageno") if meta.get("pageno") is not None else 1)
        page_count = int(meta.get("pagecount") if meta.get("pagecount") is not None else 1)
    except (TypeError, ValueError) as exc:
        raise ObserverError(f"深交所页码无效: {exc}") from exc
    rows = block.get("data")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ObserverError("深交所 data 不是列表")
    points: list[RawPoint] = []
    row_errors: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            row_errors.append(f"深交所第 {page_no} 页第 {index} 行不是对象: {type(row).__name__}")
            continue
        code = str(row.get("fund_code") or "").strip()
        if code != FUND:
            continue
        size = row.get("current_size")
        if size in (None, ""):
            continue
        as_of = str(row.get("size_date") or "").strip()
        if not as_of:
            row_errors.append(f"深交所第 {page_no} 页 {code} 缺少 size_date")
            continue
        points.append(
            RawPoint(
                fund_code=code,
                as_of_date=as_of,
                series="shares",
                original_value=as_original_text(size),
                original_unit="万份",
                source_name=SOURCE,
                source_url=source_url,
                note=f"security_short_name={row.get('security_short_name') or ''}",
            )
        )
    return points, page_no, page_count, row_errors


def collect_szse(client, start: date, end: date, *, use_cache: bool) -> FetchBatch:
    points: list[RawPoint] = []
    errors: list[str] = []
    notes: list[str] = []
    urls: list[str] = []
    page = 1
    page_count = 1
    day_ok = False
    while page <= page_count:
        url = build_url(start, end, page)
        urls.append(url)
        result = client.send(
            "GET",
            url,
            source_name=SOURCE,
            headers={"Referer": PAGE, "Accept": "application/json, text/plain, */*"},
            use_cache=use_cache,
        )
        if result.error or result.status != 200:
            errors.append(f"SZSE 第 {page} 页失败: {result.error or result.status}")
            break
        day_ok = True
        try:
            payload = result.json()
            parsed, page_no, page_count, row_errors = parse_szse(payload, result.url)
        except (json.JSONDecodeError, ObserverError, ValueError, TypeError) as exc:
            errors.append(f"SZSE 第 {page} 页无法解析: {exc}")
            break
        errors.extend(row_errors)
        if page_no != page:
            errors.append(f"SZSE 页码错位：请求 {page}，返回 {page_no}")
            break
        points.extend(filter_window(attach_fetch(parsed, result), start, end, errors, f"SZSE 第 {page} 页"))
        page += 1
        if page > 20:
            errors.append("SZSE 分页超过 20 页，停止")
            break
    # Empty-of-fund 200 (pre-publish) must not poison 12h cache for evening retry.
    if day_ok and not points and not errors:
        for url in urls:
            n = client.forget_cached("GET", url)
            if n:
                notes.append(f"SZSE 空结果已取消缓存资格 urls={len(urls)}")
                break
    return FetchBatch(SOURCE, points, errors, notes, urls)
