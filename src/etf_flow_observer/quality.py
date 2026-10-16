"""份额跳变、休市、过期和净值交叉核对。

任何一只基金缺失，都不能记成 0，也不能继续报四只合计。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from etf_flow_observer.timing import is_closed


def phase_quality(phase: str, series: str) -> tuple[str, bool, bool]:
    """返回 (若没有别的问题时应使用的状态, 是否权威, 是否算作当时看见)。

    深交所说明的是份额：T 日晚间数字只供参考，T+1 早间才算权威。
    单位净值没有这条晚间修订规则，晚间公布的净值可以是当日净值本身。
    """
    if series == "shares":
        if phase == "evening":
            return "provisional_evening", False, True
        if phase == "overnight":
            return "overnight_provisional", False, True
        if phase == "before_close":
            return "premature", False, True
        if phase == "morning":
            return "ok", True, True
        if phase == "backfill":
            return "exploratory_backfill", False, False
        if phase == "future_invalid":
            return "gap", False, False
        raise ValueError(f"未知阶段 {phase}")

    if phase == "before_close":
        return "premature", False, True
    if phase == "backfill":
        return "exploratory_backfill", False, False
    if phase == "future_invalid":
        return "gap", False, False
    if phase in {"evening", "overnight", "morning"}:
        return "ok", True, True
    raise ValueError(f"未知阶段 {phase}")


def calendar_status(day: date, closures: set[date]) -> str:
    if is_closed(day, closures):
        return "holiday_or_non_trading"
    return "ok"


def assess_share_jump(
    previous: Decimal | None,
    current: Decimal,
    *,
    abnormal_ratio: Decimal,
    split_ratio: Decimal,
) -> tuple[str, list[str]]:
    """相对上一笔已保存的份额看跳变。没有上一笔时不计算申赎。"""
    flags: list[str] = []
    if previous is None:
        return "ok", ["no_prior_share"]
    if previous == 0:
        return "suspect_split_or_merge", ["prev_share_zero"]
    change = abs(current - previous) / abs(previous)
    flags.append(f"abs_change_ratio={canonical_ratio(change)}")
    if change >= split_ratio:
        return "suspect_split_or_merge", flags
    if change > abnormal_ratio:
        return "abnormal_jump", flags
    return "ok", flags


def canonical_ratio(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")


def merge_status(
    *,
    phase: str,
    series: str,
    jump_status: str,
    day: date,
    closures: set[date],
    extra_flags: list[str] | None = None,
) -> tuple[str, list[str], bool, bool]:
    phase_status, phase_auth, lookahead = phase_quality(phase, series)
    closed = calendar_status(day, closures)
    flags = list(extra_flags or [])
    if jump_status != "ok":
        flags.append(jump_status)
    if closed != "ok":
        flags.append(closed)
    if phase_status != "ok":
        flags.append(phase_status)
    if jump_status != "ok":
        status = jump_status
    elif closed != "ok":
        status = closed
    else:
        status = phase_status
    authoritative = bool(phase_auth and status == "ok")
    return status, flags, authoritative, lookahead


def effective_status(status: str, fetched_at: datetime, now: datetime, stale_after: timedelta) -> str:
    if status == "ok" and now - fetched_at > stale_after:
        return "stale"
    return status


def blocks_executable(status: str) -> bool:
    return status != "ok"


def blocks_flow(status: str, flags: list[str]) -> bool:
    if status != "ok":
        return True
    return "no_prior_share" in flags


def nav_cross_check(primary: Decimal, other: Decimal, tolerance: Decimal = Decimal("0.00005")) -> str:
    if abs(primary - other) > tolerance:
        return "cross_check_conflict"
    return "ok"
