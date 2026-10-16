"""影子试验的门禁。

账本表可以存在，但本版本的写入函数始终拒绝。
参数没冻结、试验没显式打开、调度器也没有安装。
"""

from __future__ import annotations

from etf_flow_observer.errors import SimNotReady

UNDECIDED = (
    ("instrument", "交易标的"),
    ("entry_timestamp", "入场时点"),
    ("order_size", "下单规模"),
    ("slippage", "滑点"),
    ("commission", "佣金"),
    ("cash_idle_return", "空仓资金收益"),
    ("exit_day_counting", "持有满 5 个交易日怎么数到退出"),
    ("price_source", "价格来源"),
    ("random_seed", "随机对照的随机数规则"),
)


def blockers(sim: dict) -> list[str]:
    reasons: list[str] = []
    if not str(sim.get("version_id") or "").strip():
        reasons.append("version_id 还没冻结")
    for key, label in UNDECIDED:
        if not str(sim.get(key) or "").strip():
            reasons.append(f"{label}（{key}）还没决定，不能替研究者选一个好看的数")
    if sim.get("stacking") is not False:
        reasons.append("stacking 必须显式写成 false，不能叠仓")
    if sim.get("extension") is not False:
        reasons.append("extension 必须显式写成 false，到期不延长")
    if sim.get("hold_trading_days") != 5:
        reasons.append("hold_trading_days 必须是 5")
    if sim.get("allow_trial") is not False:
        reasons.append("allow_trial 必须显式为 false。本阶段不打开试验。")
    reasons.append("调度器没有安装，也没有在本机启动过影子试验")
    return reasons


def book_entry(store, sim: dict, **_ignored) -> None:
    """始终拒绝。不插入模拟成交，也不跨版本拼接损益。"""
    del store
    raise SimNotReady("；".join(blockers(sim)))
