"""研究口径下的估计申赎和入场时点。

估计金额 = 份额变化 × 当日单位净值。这不是现金流入。
这里不产生成交，也不把历史下载说成可以回测。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal

from etf_flow_observer.errors import ObserverError
from etf_flow_observer.quality import blocks_executable
from etf_flow_observer.timing import next_entry_timestamp
from etf_flow_observer.universe import FUND_CODES, is_full_universe


@dataclass(frozen=True)
class WindowReadiness:
    ready: bool
    complete_prior_indicators: int
    raw_observation_rows: int
    reason: str


@dataclass(frozen=True)
class SchedulePiece:
    fund_code: str
    shares_status: str
    nav_status: str
    shares_fetched_at: datetime | None
    nav_fetched_at: datetime | None
    authoritative_shares: bool


@dataclass(frozen=True)
class ScheduleResult:
    schedulable: bool
    available_at: datetime | None
    executable_at: datetime | None
    reasons: list[str]


def daily_flow(delta_shares: Decimal, unit_nav: Decimal) -> Decimal:
    """份额变化乘当日单位净值。调用方必须已经排除累计净值。"""
    return delta_shares * unit_nav


def require_four(values: dict[str, Decimal | None], what: str) -> None:
    if set(values) != set(FUND_CODES):
        missing = [code for code in FUND_CODES if code not in values]
        extra = sorted(set(values) - set(FUND_CODES))
        raise ObserverError(f"{what}必须正好是四只基金。缺 {missing}，多 {extra}。不能把缺的当成 0。")
    empty = [code for code, value in values.items() if value is None]
    if empty:
        raise ObserverError(f"{what}里 {empty} 没有数，不能把缺失当成 0 再做四只合计。")


def aum_at_window_start(shares: dict[str, Decimal | None], unit_navs: dict[str, Decimal | None]) -> Decimal:
    require_four(shares, "窗口起点份额")
    require_four(unit_navs, "窗口起点单位净值")
    total = Decimal(0)
    for code in FUND_CODES:
        total += shares[code] * unit_navs[code]  # type: ignore[operator]
    return total


def five_day_indicator(flows: list[Decimal], aum_start: Decimal) -> Decimal:
    if len(flows) != 5:
        raise ObserverError("5 日指标必须正好有 5 个完整的单日估计，不能用更短的窗口凑数")
    if aum_start <= 0:
        raise ObserverError("窗口起点规模无效")
    return sum(flows, Decimal(0)) / aum_start


def linear_percentile(values: list[Decimal], q: Decimal) -> Decimal:
    """Hyndman-Fan type 7：位置 = (n-1)*q，再线性插值。

    这是指标定义里写明的分位数算法，不是事后挑选的交易参数。
    """
    if not values:
        raise ObserverError("分位数样本是空的")
    if q < 0 or q > 1:
        raise ObserverError("分位数必须在 0 和 1 之间")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (Decimal(len(ordered) - 1)) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - Decimal(lower)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def percentile_80(prior: list[Decimal]) -> Decimal:
    if len(prior) < 120:
        raise ObserverError(
            "同一口径、且不含当前值的完整 5 日指标不足 120 个，不能计算 80 分位"
        )
    return linear_percentile(prior, Decimal("0.8"))


def trigger_long(current: Decimal, prior: list[Decimal]) -> bool:
    """当前指标大于 0，且严格高于此前 120 个同口径指标的 80 分位。"""
    if len(prior) < 120:
        raise ObserverError("分位窗口还没准备好，不能给出触发结论")
    if current <= 0:
        return False
    return current > percentile_80(prior)


def assess_window(*, raw_observation_rows: int, complete_prior_indicators: int) -> WindowReadiness:
    ready = complete_prior_indicators >= 120
    if ready:
        reason = "剔除当前值后已有 120 个同口径指标。这仍不是可回测结论。"
    elif raw_observation_rows >= 121:
        reason = (
            "原始观察已经不少于 121 行，但完整的 5 日指标在剔除当前值后还不足 120 个。"
            "不能因为看见 121 行就宣布窗口准备好了。"
        )
    else:
        reason = "剔除当前值后的同口径完整指标不足 120 个。"
    return WindowReadiness(
        ready=ready,
        complete_prior_indicators=complete_prior_indicators,
        raw_observation_rows=raw_observation_rows,
        reason=reason,
    )


def schedule_entry(
    pieces: list[SchedulePiece],
    *,
    as_of: date,
    entry_clock: time | None,
    is_closed_day,
) -> ScheduleResult:
    reasons: list[str] = []
    times: list[datetime] = []
    codes = {piece.fund_code for piece in pieces}
    if not is_full_universe(codes) or len(pieces) != len(set(codes)):
        reasons.append("可执行时点要求四只基金各有一份份额和一份单位净值，不能用子集合计")
    for piece in pieces:
        if piece.shares_fetched_at is None or piece.nav_fetched_at is None:
            reasons.append(f"{piece.fund_code} 份额或单位净值还没有实际抓到")
            continue
        if blocks_executable(piece.shares_status) or not piece.authoritative_shares:
            reasons.append(
                f"{piece.fund_code} 份额状态为 {piece.shares_status}，"
                "晚间参考数和事后补录都不能用来排入场"
            )
        if blocks_executable(piece.nav_status):
            reasons.append(f"{piece.fund_code} 单位净值状态为 {piece.nav_status}")
        times.append(piece.shares_fetched_at)
        times.append(piece.nav_fetched_at)
    if reasons:
        return ScheduleResult(False, None, None, reasons)
    available = max(times)
    if entry_clock is None:
        return ScheduleResult(False, available, None, ["入场时点还没冻结，不能排程"])
    executable = next_entry_timestamp(available, entry_clock, as_of, is_closed_day)
    return ScheduleResult(True, available, executable, [])
