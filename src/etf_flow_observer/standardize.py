"""单位换算。份额入库前把万份换成份；净值只接受元。"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from etf_flow_observer.errors import ObserverError

WAN_FEN = "万份"
FEN = "份"
YUAN = "元"
SHARES_PER_WAN = Decimal("10000")


def parse_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise ObserverError(f"无法把 {value!r} 当成数字")
    if isinstance(value, float):
        # 避免二进制浮点直接参与金额。调用方应使用 parse_float=Decimal。
        text = format(value, "f")
    else:
        text = str(value).strip().replace(",", "").replace("，", "").replace(" ", "")
    if text in {"", "--", "null", "None"}:
        raise ObserverError(f"空的或无效的数字: {value!r}")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ObserverError(f"无法解析数字 {value!r}") from exc


def canonical_number(value: Decimal) -> str:
    normalized = value.normalize()
    return format(normalized, "f")


def as_original_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return format(Decimal(str(value)), "f")
    raise ObserverError(f"无法保留原始数字 {value!r}")


def to_shares(value: Decimal, unit: str) -> tuple[Decimal, str]:
    """返回 (标准化份额, 标准化单位)。"""
    if unit == WAN_FEN:
        return value * SHARES_PER_WAN, FEN
    if unit == FEN:
        return value, FEN
    raise ObserverError(f"份额单位 {unit!r} 无法换算，拒绝把未知单位当成份")


def to_nav_yuan(value: Decimal, unit: str) -> tuple[Decimal, str]:
    if unit != YUAN:
        raise ObserverError(f"净值单位必须是元，收到 {unit!r}")
    return value, YUAN


def content_hash(
    *,
    fund_code: str,
    as_of_date: str,
    series: str,
    original_unit: str,
    canonical_value: str,
) -> str:
    payload = {
        "as_of_date": as_of_date,
        "canonical_value": canonical_value,
        "fund_code": fund_code,
        "original_unit": original_unit,
        "series": series,
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
