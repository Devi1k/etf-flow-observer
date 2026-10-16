"""命令行。采集可以重复执行；模拟账本在本阶段不会写入。"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from etf_flow_observer import __version__
from etf_flow_observer.adapters.nav_chinaamc import SOURCE as CHINAAMC
from etf_flow_observer.adapters.nav_chinaamc import collect_chinaamc
from etf_flow_observer.adapters.nav_efunds import SOURCE as EFUNDS
from etf_flow_observer.adapters.nav_efunds import collect_efunds
from etf_flow_observer.adapters.nav_huatai import SOURCE as HUATAI
from etf_flow_observer.adapters.nav_huatai import collect_huatai
from etf_flow_observer.adapters.nav_jsfund import SOURCE as JSFUND
from etf_flow_observer.adapters.nav_jsfund import collect_jsfund
from etf_flow_observer.adapters.sse_shares import SOURCE as SSE
from etf_flow_observer.adapters.sse_shares import collect_sse
from etf_flow_observer.adapters.szse_shares import SOURCE as SZSE
from etf_flow_observer.adapters.szse_shares import collect_szse
from etf_flow_observer.config import AppConfig, load_config, load_sim_config
from etf_flow_observer.errors import ObserverError
from etf_flow_observer.http_client import HttpClient
from etf_flow_observer.pipeline import (
    checkpoint_key,
    day_lines,
    finish_batch,
    mark_checkpoint,
    should_skip,
)
from etf_flow_observer.sim import blockers
from etf_flow_observer.storage import Store
from etf_flow_observer.timing import (
    evening_session,
    expected_trading_days,
    morning_session,
    now_shanghai,
    previous_weekday,
)
from etf_flow_observer.universe import FUND_BY_CODE, SSE_SHARE_CODES

NAV_SOURCES = {
    "510300": HUATAI,
    "510310": EFUNDS,
    "510330": CHINAAMC,
    "159919": JSFUND,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="etf-flow-observer",
        description="采集四只沪深300 ETF 的官方份额和单位净值。这不是交易程序。",
    )
    parser.add_argument("--config", default="config/example.toml")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="抓取份额、净值，或两者")
    collect.add_argument("target", choices=("shares", "nav", "all"))
    _add_window_args(collect)

    status = sub.add_parser("status", help="查看已入库的版本和缺口")
    del status

    sim_check = sub.add_parser("sim-check", help="检查影子试验为什么还不能启动")
    sim_check.add_argument("--sim-config", default="config/simulation.example.toml")

    smoke = sub.add_parser("smoke", help="对公开接口做一小轮现场核对，不是 120 日回补")
    smoke.add_argument("--write-report", default="")

    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ObserverError as exc:
        print(exc)
        return 1

    if args.command == "sim-check":
        return cmd_sim_check(args.sim_config)
    store = Store(cfg.db_path, cfg.raw_dir)
    try:
        if args.command == "status":
            return cmd_status(store, cfg)
        if args.command == "smoke":
            return cmd_smoke(store, cfg, args.write_report)
        return cmd_collect(store, cfg, args)
    except ObserverError as exc:
        print(exc)
        return 1
    finally:
        store.close()


def _add_window_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", help="单个数据日 YYYY-MM-DD")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--session", choices=("morning", "evening"))
    parser.add_argument("--phase", choices=("morning", "evening", "overnight", "backfill"))
    parser.add_argument("--fund", choices=tuple(FUND_BY_CODE))
    parser.add_argument("--page-size", type=int)
    parser.add_argument("--homepage-cross-check", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--allow-long-backfill",
        action="store_true",
        help="越过上交所单次日期上限。加上也不表示 120 日回补已验收。",
    )


def cmd_sim_check(path: str) -> int:
    sim = load_sim_config(path)
    print("影子试验没有启动。下面这些门还关着：")
    for item in blockers(sim):
        print(f"- {item}")
    print("账本写入会被拒绝。调度示例见 docs/scheduler.md，本机没有安装。")
    return 2


def cmd_status(store: Store, cfg: AppConfig) -> int:
    now = now_shanghai()
    for line in store.summary_lines():
        print(line)
    rows = store.conn.execute(
        "SELECT DISTINCT as_of_date FROM observations ORDER BY as_of_date DESC LIMIT 8"
    ).fetchall()
    for row in rows:
        for line in day_lines(store, row["as_of_date"], now, cfg.stale_after_hours, cfg.closures):
            print(line)
    if not rows:
        print("还没有观察记录。")
    return 0


def cmd_collect(store: Store, cfg: AppConfig, args) -> int:
    now = now_shanghai()
    start, end, phase = resolve_window(args, cfg, now)
    client = _client(cfg, store)
    summaries = _dispatch(store, client, cfg, args, start, end, phase, now)
    _print_summaries(summaries)
    return 1 if any(item["errors"] for item in summaries) else 0


def cmd_smoke(store: Store, cfg: AppConfig, write_report: str) -> int:
    now = now_shanghai()
    target, phase = morning_session(now.date(), cfg.closures)
    sse_days = expected_trading_days(previous_weekday(target, cfg.closures), target, cfg.closures)
    client = _client(cfg, store)
    print(
        f"现场核对数据日 {target.isoformat()}，若今天紧挨着它则阶段为 {phase}。"
        "上交所多取前一个交易日，用来判断份额跳变。这不是 120 日回补。"
    )
    summaries: list[dict] = []

    print("上交所份额，最近两个交易日")
    summaries.append(
        _run_sse(store, client, cfg, sse_days, None, now, force=True, use_cache=True)
    )
    print("深交所 159919，约一个半月，用来核对翻页")
    summaries.append(
        _run_szse(
            store,
            client,
            cfg,
            target - timedelta(days=45),
            target,
            None,
            now,
            force=True,
            use_cache=True,
        )
    )
    nav_start = target - timedelta(days=15)
    print("易方达净值，pageSize=5，用来核对第 2 页")
    summaries.append(
        _run_nav(
            store,
            client,
            cfg,
            "510310",
            nav_start,
            target,
            None,
            now,
            force=True,
            use_cache=True,
            page_size=5,
            homepage=False,
        )
    )
    print("华泰柏瑞净值表和首页核对")
    summaries.append(
        _run_nav(
            store,
            client,
            cfg,
            "510300",
            nav_start,
            target,
            None,
            now,
            force=True,
            use_cache=True,
            page_size=5,
            homepage=True,
        )
    )
    print("华夏净值，窗口拉长到会翻页")
    summaries.append(
        _run_nav(
            store,
            client,
            cfg,
            "510330",
            target - timedelta(days=80),
            target,
            None,
            now,
            force=True,
            use_cache=True,
            page_size=None,
            homepage=False,
        )
    )
    print("嘉实净值")
    summaries.append(
        _run_nav(
            store,
            client,
            cfg,
            "159919",
            target - timedelta(days=10),
            target,
            None,
            now,
            force=True,
            use_cache=True,
            page_size=None,
            homepage=False,
        )
    )

    before = _version_count(store, "510300", target.isoformat(), "shares", SSE)
    print("再次抓取上交所这两天，且不用缓存")
    second = _run_sse(store, client, cfg, sse_days, None, now, force=True, use_cache=False)
    after = _version_count(store, "510300", target.isoformat(), "shares", SSE)
    second["notes"] = list(second["notes"]) + [
        f"重复抓取前版本数 {before}，之后 {after}。"
        + ("没有新增版本。" if before == after else "版本数变了，需要查看是修订还是重复写入。")
    ]
    summaries.append(second)
    _print_summaries(summaries)
    for line in day_lines(store, target.isoformat(), now, cfg.stale_after_hours, cfg.closures):
        print(line)
    if write_report:
        _write_report(Path(write_report), now, target, phase, summaries, store, cfg)
        print(f"核对摘要已写入 {write_report}")
    return 1 if any(item["errors"] for item in summaries) else 0


def _dispatch(store, client, cfg, args, start, end, phase, now) -> list[dict]:
    use_cache = not args.no_cache
    summaries: list[dict] = []
    if args.target in {"shares", "all"}:
        summaries.extend(_collect_shares(store, client, cfg, args, start, end, phase, now, use_cache))
    if args.target in {"nav", "all"}:
        funds = [args.fund] if args.fund else list(NAV_SOURCES)
        for fund in funds:
            summaries.append(
                _run_nav(
                    store,
                    client,
                    cfg,
                    fund,
                    start,
                    end,
                    phase,
                    now,
                    force=args.force,
                    use_cache=use_cache,
                    page_size=args.page_size,
                    homepage=args.homepage_cross_check or fund == "510300",
                )
            )
    return summaries


def _collect_shares(store, client, cfg, args, start, end, phase, now, use_cache) -> list[dict]:
    days = expected_trading_days(start, end, cfg.closures)
    if len(days) > cfg.max_sse_dates_per_run and not args.allow_long_backfill:
        raise ObserverError(
            f"上交所要按日请求 {len(days)} 天，超过上限 {cfg.max_sse_dates_per_run}。"
            "120 日全量回补还没验收，默认停止。这不是接口已经失败。"
        )
    return [
        _run_sse(store, client, cfg, days, phase, now, args.force, use_cache),
        _run_szse(store, client, cfg, start, end, phase, now, args.force, use_cache),
    ]


def _run_sse(store, client, cfg, days: list[date], phase, now, force: bool, use_cache: bool) -> dict:
    if not days:
        return _empty(SSE, "窗口里没有交易日")
    start, end = days[0], days[-1]
    key = checkpoint_key(start, end, phase)
    if should_skip(store, SSE, key, force):
        return _skipped(SSE)
    batch = collect_sse(client, days, page_size=cfg.sse_page_size, use_cache=use_cache)
    summary = finish_batch(
        store,
        batch,
        now=now,
        phase_override=phase,
        closures=cfg.closures,
        abnormal_ratio=cfg.abnormal_share_jump_ratio,
        split_ratio=cfg.split_or_merge_ratio,
        morning_start=cfg.morning_start,
        session_close=cfg.session_close,
        expected_days=days,
        expected_funds=list(SSE_SHARE_CODES),
        expected_series=["shares"],
    )
    mark_checkpoint(store, SSE, key, summary, now, start=start, end=end, closures=cfg.closures)
    return summary


def _run_szse(store, client, cfg, start, end, phase, now, force: bool, use_cache: bool) -> dict:
    key = checkpoint_key(start, end, phase)
    if should_skip(store, SZSE, key, force):
        return _skipped(SZSE)
    days = expected_trading_days(start, end, cfg.closures)
    batch = collect_szse(client, start, end, use_cache=use_cache)
    summary = finish_batch(
        store,
        batch,
        now=now,
        phase_override=phase,
        closures=cfg.closures,
        abnormal_ratio=cfg.abnormal_share_jump_ratio,
        split_ratio=cfg.split_or_merge_ratio,
        morning_start=cfg.morning_start,
        session_close=cfg.session_close,
        expected_days=days,
        expected_funds=["159919"],
        expected_series=["shares"],
    )
    mark_checkpoint(store, SZSE, key, summary, now, start=start, end=end, closures=cfg.closures)
    return summary


def _run_nav(
    store,
    client,
    cfg,
    fund: str,
    start,
    end,
    phase,
    now,
    *,
    force: bool,
    use_cache: bool,
    page_size: int | None,
    homepage: bool,
) -> dict:
    source = NAV_SOURCES[fund]
    key = checkpoint_key(start, end, phase) + f":{page_size or 'default'}:{int(homepage)}"
    if should_skip(store, source, key, force):
        return _skipped(source)
    if fund == "510310":
        batch = collect_efunds(
            client,
            start,
            end,
            page_size=page_size or cfg.efunds_page_size,
            use_cache=use_cache,
        )
    elif fund == "510330":
        batch = collect_chinaamc(client, start, end, use_cache=use_cache)
    elif fund == "159919":
        batch = collect_jsfund(
            client,
            start,
            end,
            primary_url=cfg.jsfund_primary_url,
            fallback_url=cfg.jsfund_fallback_url,
            use_cache=use_cache,
        )
    elif fund == "510300":
        batch = collect_huatai(
            client,
            start,
            end,
            page_size=page_size or cfg.huatai_page_size,
            site_id=cfg.huatai_site_id,
            use_cache=use_cache,
            homepage_cross_check=homepage,
        )
    else:
        raise ObserverError(fund)
    days = expected_trading_days(start, end, cfg.closures)
    summary = finish_batch(
        store,
        batch,
        now=now,
        phase_override=phase,
        closures=cfg.closures,
        abnormal_ratio=cfg.abnormal_share_jump_ratio,
        split_ratio=cfg.split_or_merge_ratio,
        morning_start=cfg.morning_start,
        session_close=cfg.session_close,
        expected_days=days,
        expected_funds=[fund],
        expected_series=["unit_nav", "cumulative_nav"],
    )
    mark_checkpoint(store, source, key, summary, now, start=start, end=end, closures=cfg.closures)
    return summary


def _client(cfg: AppConfig, store: Store) -> HttpClient:
    return HttpClient(
        store,
        user_agent=cfg.user_agent,
        min_interval_seconds=cfg.min_interval_seconds,
        timeout_seconds=cfg.timeout_seconds,
        max_retries=cfg.max_retries,
        cache_ttl_seconds=cfg.cache_ttl_seconds,
        max_http_requests=cfg.max_http_requests,
    )


def resolve_window(args, cfg: AppConfig, now):
    today = now_shanghai(now).date()
    phase = args.phase
    if args.session == "morning":
        day, auto_phase = morning_session(today, cfg.closures)
        return day, day, phase or auto_phase
    if args.session == "evening":
        day, auto_phase = evening_session(today, cfg.closures)
        return day, day, phase or auto_phase
    if args.date:
        day = date.fromisoformat(args.date)
        return day, day, phase
    if args.start and args.end:
        return date.fromisoformat(args.start), date.fromisoformat(args.end), phase
    raise ObserverError("需要 --date，或同时给出 --start 和 --end，或 --session morning|evening")


def _empty(source: str, note: str) -> dict:
    return {
        "source": source,
        "errors": [],
        "notes": [note],
        "stored": 0,
        "actions": [],
        "gaps": 0,
        "urls": [],
        "skipped": False,
    }


def _skipped(source: str) -> dict:
    return {
        "source": source,
        "errors": [],
        "notes": ["检查点已完成，跳过。加 --force 会再跑一遍。"],
        "stored": 0,
        "actions": [],
        "gaps": 0,
        "urls": [],
        "skipped": True,
    }


def _print_summaries(summaries: list[dict]) -> None:
    for item in summaries:
        print(f"[{item['source']}] 写入 {item['stored']} 条，缺口记录 {item['gaps']} 条")
        for note in item["notes"]:
            print(f"  {note}")
        for error in item["errors"]:
            print(f"  失败: {error}")


def _version_count(store: Store, fund: str, as_of: str, series: str, source: str) -> int:
    return store.count_versions(fund, as_of, series, source)


def _write_report(path: Path, now, target: date, phase: str, summaries: list[dict], store: Store, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# 现场核对 {now.date().isoformat()}",
        "",
        f"运行时刻（上海）: {now.isoformat(timespec='seconds')}",
        f"早间任务对应的数据日: {target.isoformat()}，自动阶段: {phase}",
        "",
        "这里只记录来源是否返回了可解析的数据，不收录原始响应正文。",
        "120 日份额回补没有执行，也不能从这次核对推出可以回测。",
        "",
        "## 来源",
        "",
    ]
    for item in summaries:
        state = "失败" if item["errors"] else "有返回并已入库"
        if item.get("skipped"):
            state = "跳过"
        lines.append(f"### {item['source']}: {state}")
        lines.append(f"- 写入条数: {item['stored']}")
        lines.append(f"- 缺口记录: {item['gaps']}")
        lines.append(f"- 请求数: {len(item['urls'])}")
        for note in item["notes"]:
            lines.append(f"- {note}")
        for error in item["errors"]:
            lines.append(f"- 失败: {error}")
        lines.append("")
    lines.append("## 样本")
    lines.append("")
    lines.extend(_sample_lines(store, target))
    lines.append("")
    lines.append("## 这一天的合计判断")
    lines.append("")
    lines.extend(day_lines(store, target.isoformat(), now, cfg.stale_after_hours, cfg.closures))
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sample_lines(store: Store, target: date) -> list[str]:
    lines = []
    specs = [
        ("510300", "shares", SSE),
        ("510310", "shares", SSE),
        ("510330", "shares", SSE),
        ("159919", "shares", SZSE),
        ("510300", "unit_nav", HUATAI),
        ("510310", "unit_nav", EFUNDS),
        ("510330", "unit_nav", CHINAAMC),
        ("159919", "unit_nav", JSFUND),
    ]
    for fund, series, source in specs:
        row = store.latest_join(fund, target.isoformat(), series, source)
        if row is None:
            lines.append(f"- {fund} {series} {source}: 没有记录")
            continue
        lines.append(
            f"- {fund} {series}: 原始 {row['original_value']} {row['original_unit']}，"
            f"标准化 {row['standardized_value']} {row['standardized_unit'] or ''}，"
            f"状态 {row['quality_status']}，阶段 {row['snapshot_phase']}，"
            f"权威 {row['authoritative']}"
        )
    return lines
