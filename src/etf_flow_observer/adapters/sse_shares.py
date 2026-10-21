"""上交所 ETF 份额。TOT_VOL 的单位是万份。一次请求里有全部上交所 ETF，只留下宇宙内的三只。"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date

from etf_flow_observer.adapters.common import FetchBatch, RawPoint, attach_fetch, filter_window
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.standardize import as_original_text
from etf_flow_observer.universe import SSE_SHARE_CODES

SOURCE = "sse_shares"
PAGE = "https://www.sse.com.cn/market/funddata/volumn/etfvolumn/"
API = "https://query.sse.com.cn/commonQuery.do"
SQL_ID = "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"


def build_url(day: date, page: int, page_size: int) -> str:
    query = urllib.parse.urlencode(
        {
            "isPagination": "true",
            "pageHelp.pageSize": str(page_size),
            "pageHelp.pageNo": str(page),
            "sqlId": SQL_ID,
            "STAT_DATE": day.isoformat(),
        }
    )
    return f"{API}?{query}"


def parse_sse(payload: object, source_url: str) -> tuple[list[RawPoint], int, int, list[str]]:
    if not isinstance(payload, dict):
        raise ObserverError("上交所返回的不是对象")
    page_help = payload.get("pageHelp")
    if page_help is None:
        page_help = {}
    if not isinstance(page_help, dict):
        raise ObserverError("上交所 pageHelp 不是对象")
    try:
        page_no = int(page_help.get("pageNo") if page_help.get("pageNo") is not None else 1)
        page_count = int(page_help.get("pageCount") if page_help.get("pageCount") is not None else 1)
    except (TypeError, ValueError) as exc:
        raise ObserverError(f"上交所页码无效: {exc}") from exc
    rows = payload.get("result")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        raise ObserverError("上交所 result 不是列表")
    points: list[RawPoint] = []
    row_errors: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            row_errors.append(f"上交所第 {page_no} 页第 {index} 行不是对象: {type(row).__name__}")
            continue
        code = str(row.get("SEC_CODE") or "").strip()
        if code not in SSE_SHARE_CODES:
            continue
        if "TOT_VOL" not in row or row.get("TOT_VOL") in (None, ""):
            continue
        as_of = str(row.get("STAT_DATE") or "").strip()
        if not as_of:
            row_errors.append(f"上交所第 {page_no} 页 {code} 缺少 STAT_DATE")
            continue
        points.append(
            RawPoint(
                fund_code=code,
                as_of_date=as_of,
                series="shares",
                original_value=as_original_text(row.get("TOT_VOL")),
                original_unit="万份",
                source_name=SOURCE,
                source_url=source_url,
                note=f"SEC_NAME={row.get('SEC_NAME') or ''}",
            )
        )
    return points, page_no, page_count, row_errors


def collect_sse(client, days: list[date], *, page_size: int, use_cache: bool) -> FetchBatch:
    points: list[RawPoint] = []
    errors: list[str] = []
    notes: list[str] = []
    urls: list[str] = []
    for day in days:
        page = 1
        page_count = 1
        day_urls: list[str] = []
        day_ok = False
        while page <= page_count:
            url = build_url(day, page, page_size)
            urls.append(url)
            day_urls.append(url)
            result = client.send(
                "GET",
                url,
                source_name=SOURCE,
                headers={"Referer": PAGE, "Accept": "application/json"},
                use_cache=use_cache,
            )
            if result.error or result.status != 200:
                errors.append(f"SSE {day.isoformat()} 第 {page} 页失败: {result.error or result.status}")
                break
            day_ok = True
            try:
                payload = result.json()
            except json.JSONDecodeError as exc:
                errors.append(f"SSE {day.isoformat()} 不是 JSON: {exc}")
                break
            try:
                parsed, page_no, page_count, row_errors = parse_sse(payload, result.url)
            except (ObserverError, ValueError, TypeError) as exc:
                errors.append(f"SSE {day.isoformat()} 第 {page} 页页码无效: {exc}")
                break
            errors.extend(row_errors)
            if page_no != page:
                errors.append(f"SSE 页码错位：请求 {page}，返回 {page_no}")
                break
            points.extend(
                filter_window(attach_fetch(parsed, result), day, day, errors, f"SSE {day.isoformat()}")
            )
            page += 1
            if page > 10:
                errors.append("SSE 分页超过 10 页，停止")
                break
        found = {item.fund_code for item in points if item.as_of_date == day.isoformat()}
        missing = [code for code in SSE_SHARE_CODES if code not in found]
        if missing:
            notes.append(f"{day.isoformat()} 上交所结果里没有 {','.join(missing)}，不会记成 0")
            # Pre-publish empty 200 must not occupy 12h cache and block evening retry.
            # Clear EVERY page URL — breaking on first success leaves later pages stale.
            if day_ok and not found:
                cleared = 0
                for url in day_urls:
                    cleared += client.forget_cached("GET", url)
                if cleared:
                    notes.append(
                        f"{day.isoformat()} 空结果已取消缓存资格 "
                        f"cleared={cleared} fingerprint-urls={len(day_urls)}"
                    )
    return FetchBatch(SOURCE, points, errors, notes, urls)
