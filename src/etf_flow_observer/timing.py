"""上海时区的交易日、晚间快照和下一档可执行时点。

first_seen_at 只表示本系统第一次看见，不是交易所或基金公司的发布时间。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from etf_flow_observer.errors import ObserverError

SHANGHAI = ZoneInfo("Asia/Shanghai")


def now_shanghai(clock: datetime | None = None) -> datetime:
    if clock is None:
        return datetime.now(SHANGHAI)
    if clock.tzinfo is None:
        raise ObserverError("时间必须带时区")
    return clock.astimezone(SHANGHAI)


def parse_hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))


def is_weekend(day: date) -> bool:
    return day.weekday() >= 5


def is_closed(day: date, closures: set[date]) -> bool:
    return is_weekend(day) or day in closures


def expected_trading_days(start: date, end: date, closures: set[date]) -> list[date]:
    if end < start:
        raise ObserverError("结束日期早于开始日期")
    days: list[date] = []
    cursor = start
    while cursor <= end:
        if not is_closed(cursor, closures):
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def classify_phase(
    as_of: date,
    now: datetime,
    *,
    morning_start: time,
    session_close: time,
    closures: set[date],
) -> str:
    """按抓取时刻给单个数据日贴阶段。

    morning 只给“正好是上一个自然日，且已经过了早间起点”的抓取。
    周一去拉周五会落到 backfill：中间隔了周末，不能说成当时已经看见的早间修订。
    """
    local = now_shanghai(now)
    today = local.date()
    if as_of > today:
        return "future_invalid"
    if is_closed(as_of, closures):
        return "backfill"
    if as_of == today:
        if local.time() < session_close:
            return "before_close"
        return "evening"
    if as_of == today - timedelta(days=1):
        if local.time() < morning_start:
            return "overnight"
        return "morning"
    return "backfill"


def previous_weekday(today: date, closures: set[date]) -> date:
    cursor = today - timedelta(days=1)
    while is_closed(cursor, closures):
        cursor -= timedelta(days=1)
    return cursor


def morning_session(today: date, closures: set[date]) -> tuple[date, str]:
    """早间任务要修订的数据日，以及应使用的阶段名。"""
    target = previous_weekday(today, closures)
    if target == today - timedelta(days=1):
        return target, "morning"
    return target, "backfill"


def evening_session(today: date, closures: set[date]) -> tuple[date, str]:
    if is_closed(today, closures):
        raise ObserverError("今天不是交易日，没有当日晚间份额快照可采")
    return today, "evening"


# 2026-10-01 到 10-07 里的工作日。空的休市表不能把覆盖这段的历史说成完整。
# 这是完整性门禁，不是对官方放假通知的重新验收。
NATIONAL_DAY_2026_WEEKDAYS = (
    date(2026, 10, 1),
    date(2026, 10, 2),
    date(2026, 10, 5),
    date(2026, 10, 6),
    date(2026, 10, 7),
)


def national_day_history_block(start: date, end: date, closures: set[date]) -> str | None:
    """窗口盖住 2026 年 10 月 1 日至 7 日时，休市表必须写明其中的工作日，否则拒绝验收。"""
    if end < date(2026, 10, 1) or start > date(2026, 10, 7):
        return None
    missing = [day for day in NATIONAL_DAY_2026_WEEKDAYS if start <= day <= end and day not in closures]
    if not missing:
        return None
    listed = "、".join(day.isoformat() for day in missing)
    return (
        f"休市表没有覆盖 {listed}。"
        "空的休市表不能通过国庆这段历史的完整性验收。"
        "08:00 和这些日期都不是交易所保证。"
    )


def applied_phase(
    as_of: date,
    now: datetime,
    requested: str | None,
    *,
    morning_start: time,
    session_close: time,
    closures: set[date],
) -> tuple[str, str | None]:
    """`--session` / `--phase` 只表示操作意图，不能把钟点阶段提升成更权威的阶段。

    08:00 是配置里的分界。到了这个钟点并不表示交易所已经发布权威份额。
    """
    clock_phase = classify_phase(
        as_of,
        now,
        morning_start=morning_start,
        session_close=session_close,
        closures=closures,
    )
    if requested is None or requested == clock_phase:
        return clock_phase, None
    return clock_phase, (
        f"请求的阶段 {requested} 只是意图，实际按日历和钟点是 {clock_phase}。"
        "不能因此提高权威。08:00 是配置分界，不是交易所保证。"
    )


def assert_entry_after_data(executable: datetime, available_at: datetime, as_of: date) -> None:
    if executable.tzinfo is None or available_at.tzinfo is None:
        raise ObserverError("入场时点和数据可得时间都必须带时区")
    if executable <= available_at:
        raise ObserverError("信号时点早于或等于数据实际可得时间，不能排程")
    if executable.astimezone(SHANGHAI).date() == as_of:
        raise ObserverError("不能把数据日当天的收盘当作入场时点")


def next_entry_timestamp(
    available_at: datetime,
    entry_clock: time,
    as_of: date,
    is_closed_day,
) -> datetime:
    """下一个严格晚于数据可得时间、且不是数据日本身的入场时点。"""
    local = now_shanghai(available_at)
    day = local.date()
    for _ in range(21):
        candidate = datetime.combine(day, entry_clock, tzinfo=SHANGHAI)
        if (
            candidate > available_at
            and day != as_of
            and not is_closed_day(day)
        ):
            assert_entry_after_data(candidate, available_at, as_of)
            return candidate
        day += timedelta(days=1)
    raise ObserverError("21 天内没有找到晚于数据可得时间的入场时点")
