"""把解析结果换成标准单位、做质量判断，并写入版本库。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from etf_flow_observer.adapters.common import FetchBatch, RawPoint
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.quality import (
    assess_share_jump,
    blocks_flow,
    effective_status,
    merge_status,
    nav_cross_check,
    prior_blocks_delta,
)
from etf_flow_observer.standardize import (
    canonical_number,
    content_hash,
    parse_decimal,
    to_nav_yuan,
    to_shares,
)
from etf_flow_observer.storage import Store
from etf_flow_observer.timing import applied_phase, national_day_history_block, previous_weekday
from etf_flow_observer.universe import FUND_CODES, FUNDS, ensure_known


def dedupe_points(points: list[RawPoint]) -> tuple[list[RawPoint], list[str]]:
    grouped: dict[tuple, list[RawPoint]] = defaultdict(list)
    order: list[tuple] = []
    for point in points:
        key = (point.fund_code, point.as_of_date, point.series, point.source_name)
        if key not in grouped:
            order.append(key)
        grouped[key].append(point)
    kept: list[RawPoint] = []
    notes: list[str] = []
    for key in order:
        items = grouped[key]
        if any(item.conflict for item in items):
            kept.append(_conflict_point(items[0], "来源自己标记了冲突，不选用数字"))
            notes.append(f"冲突 {key}")
            continue
        canons: list[str] = []
        bad = False
        for item in items:
            try:
                canons.append(canonical_number(parse_decimal(item.original_value)))
            except ObserverError:
                bad = True
                break
        if bad or len(set(canons)) > 1:
            kept.append(_conflict_point(items[0], f"分页或重复行的值不一致: {canons}"))
            notes.append(f"分页冲突 {key} -> {canons}")
            continue
        chosen = items[0]
        if len(items) > 1:
            flag = "pagination_duplicate_same_value"
            if flag not in chosen.flags:
                chosen.flags.append(flag)
            chosen.note = (chosen.note + "; 分页重复且数值相同，只保留一条").strip("; ")
        kept.append(chosen)
    return kept, notes


def _conflict_point(point: RawPoint, note: str) -> RawPoint:
    return RawPoint(
        fund_code=point.fund_code,
        as_of_date=point.as_of_date,
        series=point.series,
        original_value="",
        original_unit=point.original_unit,
        source_name=point.source_name,
        source_url=point.source_url,
        note=note,
        conflict=True,
        flags=["duplicate_conflict"],
        raw_fetch_id=point.raw_fetch_id,
        network_fetched_at=point.network_fetched_at,
        cache_accessed_at=point.cache_accessed_at,
        observation_available_at=point.observation_available_at,
    )


def ingest_points(
    store: Store,
    points: list[RawPoint],
    *,
    now: datetime,
    phase_override: str | None,
    closures: set[date],
    abnormal_ratio: Decimal,
    split_ratio: Decimal,
    morning_start,
    session_close,
) -> dict:
    kept, notes = dedupe_points(points)
    kept.sort(key=lambda item: (item.as_of_date, item.fund_code, item.series, item.source_name))
    actions: list[str] = []
    errors: list[str] = []
    for point in kept:
        if point.fund_code not in {fund.code for fund in FUNDS}:
            notes.append(f"忽略宇宙外的 {point.fund_code}")
            continue
        try:
            result, note = _ingest_one(
                store,
                point,
                now=now,
                phase_override=phase_override,
                closures=closures,
                abnormal_ratio=abnormal_ratio,
                split_ratio=split_ratio,
                morning_start=morning_start,
                session_close=session_close,
            )
        except (ObserverError, ValueError) as exc:
            errors.append(
                f"{point.source_name} {point.fund_code} {point.as_of_date} {point.series}: {exc}"
            )
            continue
        if note:
            notes.append(note)
        actions.append(result.action)
        if point.series == "shares" and result.action != "confirmed":
            notes.extend(
                _recompute_later_shares(
                    store,
                    fund_code=point.fund_code,
                    source_name=point.source_name,
                    after_date=point.as_of_date,
                    now=now,
                    closures=closures,
                    abnormal_ratio=abnormal_ratio,
                    split_ratio=split_ratio,
                )
            )
    return {"actions": actions, "notes": notes, "stored": len(actions), "errors": errors}


def _ingest_one(store, point: RawPoint, **kwargs):
    now = kwargs["now"]
    day = date.fromisoformat(point.as_of_date)
    # 阶段按「正文可得时间」判，不用批次 now。跨 08:00 缓存命中仍可能带 07:50 的原文。
    available = point.observation_available_at or point.network_fetched_at or now
    phase, phase_note = applied_phase(
        day,
        available,
        kwargs["phase_override"],
        morning_start=kwargs["morning_start"],
        session_close=kwargs["session_close"],
        closures=kwargs["closures"],
    )
    status, flags, authoritative, lookahead, canonical, standardized, standardized_unit = _judge_point(
        store,
        point,
        phase=phase,
        day=day,
        closures=kwargs["closures"],
        abnormal_ratio=kwargs["abnormal_ratio"],
        split_ratio=kwargs["split_ratio"],
    )
    digest = content_hash(
        fund_code=point.fund_code,
        as_of_date=point.as_of_date,
        series=point.series,
        original_unit=point.original_unit,
        canonical_value=canonical,
    )
    result = store.upsert_version(
        fund_code=point.fund_code,
        as_of_date=point.as_of_date,
        series=point.series,
        source_name=point.source_name,
        original_value=point.original_value,
        original_unit=point.original_unit,
        standardized_value=standardized,
        standardized_unit=standardized_unit,
        source_url=point.source_url,
        fetched_at=point.network_fetched_at or available,
        snapshot_phase=phase,
        content_hash=digest,
        quality_status=status,
        quality_flags=flags,
        authoritative=authoritative,
        lookahead_free=lookahead,
        raw_fetch_id=point.raw_fetch_id,
        note=point.note,
        network_fetched_at=point.network_fetched_at,
        cache_accessed_at=point.cache_accessed_at,
        observation_available_at=available,
    )
    return result, phase_note


def _judge_point(store, point: RawPoint, *, phase, day, closures, abnormal_ratio, split_ratio):
    extra_flags = list(point.flags)
    if point.conflict:
        return (
            "duplicate_conflict",
            extra_flags,
            False,
            False,
            "CONFLICT",
            None,
            None,
        )
    number = parse_decimal(point.original_value)
    if point.series == "shares":
        standardized_number, standardized_unit = to_shares(number, point.original_unit)
        previous, prior_flags = _adjacent_share_value(
            store, point.fund_code, point.source_name, day, closures
        )
        jump_status, jump_flags = assess_share_jump(
            previous,
            standardized_number,
            abnormal_ratio=abnormal_ratio,
            split_ratio=split_ratio,
        )
        extra_flags.extend(prior_flags)
        extra_flags.extend(jump_flags)
    elif point.series == "unit_nav":
        standardized_number, standardized_unit = to_nav_yuan(number, point.original_unit)
        jump_status = "ok"
    elif point.series == "cumulative_nav":
        if not number.is_finite():
            raise ObserverError(f"累计净值不是有限数: {number}")
        standardized_number, standardized_unit = number, "元"
        if point.original_unit != "元":
            raise ObserverError(f"净值单位必须是元，收到 {point.original_unit!r}")
        jump_status = "ok"
    else:
        raise ObserverError(f"未知序列 {point.series}")
    canonical = canonical_number(standardized_number)
    status, flags, authoritative, lookahead = merge_status(
        phase=phase,
        series=point.series,
        jump_status=jump_status,
        day=day,
        closures=closures,
        extra_flags=extra_flags,
    )
    return status, flags, authoritative, lookahead, canonical, canonical, standardized_unit


def _adjacent_share_value(store, fund_code: str, source_name: str, day: date, closures: set[date]):
    prev_day = previous_weekday(day, closures)
    row = store.latest_join(fund_code, prev_day.isoformat(), "shares", source_name)
    if row is None or row["standardized_value"] is None:
        return None, []
    flags = []
    if prior_blocks_delta(row["quality_status"]):
        flags.append("prior_not_valid")
        flags.append(f"prior_status={row['quality_status']}")
    return Decimal(row["standardized_value"]), flags


_DERIVED_FLAGS = {
    "no_adjacent_share",
    "no_prior_share",
    "prior_not_valid",
    "abnormal_jump",
    "suspect_split_or_merge",
    "holiday_or_non_trading",
    "provisional_evening",
    "overnight_provisional",
    "premature",
    "exploratory_backfill",
    "duplicate_conflict",
}


def _recompute_later_shares(
    store: Store,
    *,
    fund_code: str,
    source_name: str,
    after_date: str,
    now: datetime,
    closures: set[date],
    abnormal_ratio: Decimal,
    split_ratio: Decimal,
) -> list[str]:
    """更早一天被修订后，只追加后来日期的新版本，不改旧版本。"""
    rows = store.conn.execute(
        """
        SELECT v.*
        FROM observation_versions v
        JOIN observations o ON o.id = v.observation_id AND o.latest_version_no = v.version_no
        WHERE v.fund_code = ? AND v.source_name = ? AND v.series = 'shares'
          AND v.as_of_date > ? AND v.standardized_value IS NOT NULL
        ORDER BY v.as_of_date
        """,
        (fund_code, source_name, after_date),
    ).fetchall()
    notes: list[str] = []
    for row in rows:
        day = date.fromisoformat(row["as_of_date"])
        old_flags = json.loads(row["quality_flags"])
        kept = [
            flag
            for flag in old_flags
            if flag not in _DERIVED_FLAGS and not str(flag).startswith("abs_change_ratio=")
            and not str(flag).startswith("prior_status=")
        ]
        previous, prior_flags = _adjacent_share_value(store, fund_code, source_name, day, closures)
        jump_status, jump_flags = assess_share_jump(
            previous,
            Decimal(row["standardized_value"]),
            abnormal_ratio=abnormal_ratio,
            split_ratio=split_ratio,
        )
        status, flags, authoritative, lookahead = merge_status(
            phase=row["snapshot_phase"],
            series="shares",
            jump_status=jump_status,
            day=day,
            closures=closures,
            extra_flags=kept + prior_flags + jump_flags,
        )
        if status == row["quality_status"] and flags == old_flags:
            continue
        available = row["observation_available_at"] or row["fetched_at"]
        store.upsert_version(
            fund_code=fund_code,
            as_of_date=row["as_of_date"],
            series="shares",
            source_name=source_name,
            original_value=row["original_value"],
            original_unit=row["original_unit"],
            standardized_value=row["standardized_value"],
            standardized_unit=row["standardized_unit"],
            source_url=row["source_url"],
            fetched_at=datetime.fromisoformat(row["fetched_at"]),
            snapshot_phase=row["snapshot_phase"],
            content_hash=row["content_hash"],
            quality_status=status,
            quality_flags=flags,
            authoritative=authoritative,
            lookahead_free=lookahead,
            raw_fetch_id=row["raw_fetch_id"],
            note=(row["note"] + "；因更早交易日修订而重算质量").strip("；"),
            network_fetched_at=(
                datetime.fromisoformat(row["network_fetched_at"]) if row["network_fetched_at"] else None
            ),
            cache_accessed_at=(
                datetime.fromisoformat(row["cache_accessed_at"]) if row["cache_accessed_at"] else None
            ),
            observation_available_at=datetime.fromisoformat(available),
            decided_at=now,
            cause="dependent",
        )
        detail = (
            f"{row['as_of_date']} 质量由 {row['quality_status']} 改为 {status}。"
            "旧版本保留，不改写。"
        )
        store.add_quality_event(
            fund_code=fund_code,
            as_of_date=row["as_of_date"],
            series="shares",
            source_name=source_name,
            status="dependent_recalc",
            detail=detail,
            created_at=now,
        )
        notes.append(detail)
    return notes


def record_expected_gaps(
    store: Store,
    *,
    funds: list[str],
    series: list[str],
    source_name: str,
    days: list[date],
    now: datetime,
    reason_if_absent: str = "no_exchange_row",
) -> int:
    """窗口里应有、但没有成功数值的日期记成缺口，不写成 0。"""
    added = 0
    for day in days:
        iso = day.isoformat()
        for fund in funds:
            ensure_known(fund)
            for item_series in series:
                row = store.latest_join(fund, iso, item_series, source_name)
                if row is not None and row["standardized_value"] is not None:
                    continue
                reason = reason_if_absent if row is None else row["quality_status"]
                store.add_gap(
                    fund_code=fund,
                    as_of_date=iso,
                    series=item_series,
                    source_name=source_name,
                    reason=reason,
                    fetched_at=now,
                )
                added += 1
    return added


def compare_huatai_homepage(store: Store, now: datetime) -> list[str]:
    rows = store.conn.execute(
        """
        SELECT v.as_of_date, v.standardized_value
        FROM observation_versions v
        JOIN observations o ON o.id = v.observation_id AND o.latest_version_no = v.version_no
        WHERE v.fund_code = '510300' AND v.series = 'unit_nav' AND v.source_name = 'huatai_homepage'
          AND v.standardized_value IS NOT NULL
        """
    ).fetchall()
    notes: list[str] = []
    for row in rows:
        primary = store.latest_join("510300", row["as_of_date"], "unit_nav", "huatai_nav_table")
        if primary is None or primary["standardized_value"] is None:
            notes.append(f"510300 {row['as_of_date']} 有首页净值，历史表还没有同一天")
            continue
        status = nav_cross_check(
            Decimal(primary["standardized_value"]),
            Decimal(row["standardized_value"]),
        )
        if status != "ok":
            store.add_quality_event(
                fund_code="510300",
                as_of_date=row["as_of_date"],
                series="unit_nav",
                source_name="huatai_nav_table",
                status="cross_check_conflict",
                detail=(
                    f"历史表 {primary['standardized_value']} 与首页 {row['standardized_value']} 不一致，"
                    "两边都保留，不挑选其中一个"
                ),
                created_at=now,
            )
            notes.append(f"510300 {row['as_of_date']} 首页和历史表不一致")
        else:
            notes.append(f"510300 {row['as_of_date']} 首页和历史表单位净值一致")
    return notes


def finish_batch(
    store: Store,
    batch: FetchBatch,
    *,
    now: datetime,
    phase_override: str | None,
    closures: set[date],
    abnormal_ratio: Decimal,
    split_ratio: Decimal,
    morning_start,
    session_close,
    expected_days: list[date],
    expected_funds: list[str],
    expected_series: list[str],
) -> dict:
    ingested = ingest_points(
        store,
        batch.points,
        now=now,
        phase_override=phase_override,
        closures=closures,
        abnormal_ratio=abnormal_ratio,
        split_ratio=split_ratio,
        morning_start=morning_start,
        session_close=session_close,
    )
    gaps = record_expected_gaps(
        store,
        funds=expected_funds,
        series=expected_series,
        source_name=batch.source_name,
        days=expected_days,
        now=now,
        reason_if_absent="fetch_failed" if batch.errors else "no_exchange_row",
    )
    cross = []
    if batch.source_name == "huatai_nav_table":
        cross = compare_huatai_homepage(store, now)
    return {
        "source": batch.source_name,
        "errors": list(batch.errors) + list(ingested["errors"]),
        "notes": batch.notes + ingested["notes"] + cross,
        "stored": ingested["stored"],
        "actions": ingested["actions"],
        "gaps": gaps,
        "urls": batch.request_urls,
    }


def checkpoint_key(start: date, end: date, phase: str | None) -> str:
    return f"{start.isoformat()}:{end.isoformat()}:{phase or 'auto'}"


def should_skip(store: Store, source_name: str, key: str, force: bool) -> bool:
    if force:
        return False
    row = store.checkpoint(source_name, key)
    return row is not None and row["status"] == "complete"


def mark_checkpoint(
    store: Store,
    source_name: str,
    key: str,
    summary: dict,
    now: datetime,
    *,
    start: date,
    end: date,
    closures: set[date],
) -> None:
    block = national_day_history_block(start, end, closures)
    if block:
        summary["notes"] = list(summary["notes"]) + [block]
    if summary["errors"] or block:
        status = "incomplete"
    elif summary["gaps"]:
        status = "waiting_update"
    else:
        status = "complete"
    summary["checkpoint"] = status
    detail = f"stored={summary['stored']};gaps={summary['gaps']}"
    if block:
        detail = f"{detail};{block}"
    store.set_checkpoint(source_name, key, status, now, detail=detail)


def day_lines(
    store: Store,
    as_of: str,
    now: datetime,
    stale_after_hours: int,
    closures: set[date] | None = None,
) -> list[str]:
    calendar = set(closures or ())
    lines = [f"数据日 {as_of}"]
    blocked: list[str] = []
    flows: dict[str, Decimal | None] = {}
    for fund in FUNDS:
        share = store.latest_join(fund.code, as_of, "shares", fund.share_source)
        nav = store.latest_join(fund.code, as_of, "unit_nav", fund.nav_source)
        if share is None or share["standardized_value"] is None:
            blocked.append(fund.code)
            flows[fund.code] = None
            lines.append(f"  {fund.code} 没有份额，不记 0")
            continue
        share_flags = json.loads(share["quality_flags"])
        share_status = effective_status(
            share["quality_status"],
            datetime.fromisoformat(share["fetched_at"]),
            now,
            timedelta(hours=stale_after_hours),
        )
        nav_status = "missing"
        if nav is not None and nav["standardized_value"] is not None:
            nav_status = effective_status(
                nav["quality_status"],
                datetime.fromisoformat(nav["fetched_at"]),
                now,
                timedelta(hours=stale_after_hours),
            )
            if _homepage_conflict(store, fund.code, as_of):
                nav_status = "cross_check_conflict"
        else:
            blocked.append(fund.code)
        flow_blocked = (
            blocks_flow(share_status, share_flags)
            or nav_status != "ok"
            or not share["authoritative"]
            or nav is None
        )
        prev_day = previous_weekday(date.fromisoformat(as_of), calendar)
        adjacent = store.latest_join(fund.code, prev_day.isoformat(), "shares", fund.share_source)
        adjacent_missing = adjacent is None or adjacent["standardized_value"] is None
        if "no_adjacent_share" in share_flags or adjacent_missing:
            flows[fund.code] = None
            blocked.append(fund.code)
            lines.append(
                f"  {fund.code} 没有相邻交易日 {prev_day.isoformat()} 的份额，"
                "不能用更早的非空值代替，也不计算变化"
            )
            continue
        if prior_blocks_delta(adjacent["quality_status"]) or "prior_not_valid" in share_flags:
            flows[fund.code] = None
            blocked.append(fund.code)
            lines.append(
                f"  {fund.code} 相邻交易日 {prev_day.isoformat()} 份额状态为 {adjacent['quality_status']}，"
                "不计算变化"
            )
            continue
        if flow_blocked:
            if fund.code not in blocked:
                blocked.append(fund.code)
            flows[fund.code] = None
            lines.append(
                f"  {fund.code} 份额 {share['standardized_value']} 份，状态 {share_status}，"
                f"净值状态 {nav_status}，不计算可执行申赎"
            )
            continue
        previous = Decimal(adjacent["standardized_value"])
        delta = Decimal(share["standardized_value"]) - previous
        amount = delta * Decimal(nav["standardized_value"])
        flows[fund.code] = amount
        prior_status = adjacent["quality_status"]
        lines.append(
            f"  {fund.code} 研究估计 {canonical_number(amount)} 元"
            "（份额变化乘当日单位净值，不是现金流入，也不是可执行信号）。"
            f"上一笔份额状态为 {prior_status}。"
        )
    if any(flows.get(code) is None for code in FUND_CODES):
        lines.append(
            "  四只合计：没有。缺 "
            + "、".join(code for code in FUND_CODES if flows.get(code) is None)
            + "。不会把缺的当成 0。"
        )
    else:
        total = sum((flows[code] for code in FUND_CODES), Decimal(0))
        lines.append(f"  四只合计估计申赎 {canonical_number(total)} 元。这不是可交易信号。")
    return lines


def _homepage_conflict(store: Store, fund_code: str, as_of: str) -> bool:
    if fund_code != "510300":
        return False
    row = store.conn.execute(
        """
        SELECT 1 FROM quality_events
        WHERE fund_code = ? AND as_of_date = ? AND status = 'cross_check_conflict'
        LIMIT 1
        """,
        (fund_code, as_of),
    ).fetchone()
    return row is not None
