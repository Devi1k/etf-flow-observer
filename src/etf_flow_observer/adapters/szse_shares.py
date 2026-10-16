"""深交所 159919 份额。current_size 的单位是万份，数字里可能有千分位。

接口页脚写明：T 日晚间更新的 T 日规模仅供参考，以 T+1 日早间更新的为准。
分页参数是 PAGENO，每页条数由返回的 metadata.pagesize 决定。
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, in_window
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


def parse_szse(payload: object, source_url: str) -> tuple[list[RawPoint], int, int]:
    if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
        raise ObserverError("深交所返回的不是预期的报表列表")
    block = payload[0]
    if block.get("error"):
        raise ObserverError(f"深交所报表错误: {block.get('error')}")
    meta = block.get("metadata") or {}
    page_no = int(meta.get("pageno") or 1)
    page_count = int(meta.get("pagecount") or 1)
    points: list[RawPoint] = []
    for row in block.get("data") or []:
        code = str(row.get("fund_code") or "").strip()
        if code != FUND:
            continue
        size = row.get("current_size")
        if size in (None, ""):
            continue
        points.append(
            RawPoint(
                fund_code=code,
                as_of_date=str(row.get("size_date") or "").strip(),
                series="shares",
                original_value=as_original_text(size),
                original_unit="万份",
                source_name=SOURCE,
                source_url=source_url,
                note=f"security_short_name={row.get('security_short_name') or ''}",
            )
        )
    return points, page_no, page_count


def collect_szse(client, start: date, end: date, *, use_cache: bool) -> FetchBatch:
    points: list[RawPoint] = []
    errors: list[str] = []
    urls: list[str] = []
    page = 1
    page_count = 1
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
        try:
            payload = result.json()
            parsed, page_no, page_count = parse_szse(payload, result.url)
        except (json.JSONDecodeError, ObserverError, ValueError) as exc:
            errors.append(f"SZSE 第 {page} 页无法解析: {exc}")
            break
        if page_no != page:
            errors.append(f"SZSE 页码错位：请求 {page}，返回 {page_no}")
            break
        points.extend(item for item in parsed if in_window(item.as_of_date, start, end))
        page += 1
        if page > 20:
            errors.append("SZSE 分页超过 20 页，停止")
            break
    return FetchBatch(SOURCE, points, errors, [], urls)
