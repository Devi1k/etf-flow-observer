# 同库晚间 → 次晨对照（Dot 证据 A）

跨库晚间/次晨快照（`evidence/evening-20261016` 与 `evidence/morning-20261017`，提交 `51c0f9e` / `9cdec31`）**不算**本对照。本对照要求：**同一个持久 SQLite** 上先写晚间腿，再在自然次晨追加。

本阶段**不**启动连续灰度，**不**安装 crontab，**不**打开 `allow_trial`，宇宙仍锁定四只 CSI300：`510300` / `510310` / `510330` / `159919`。

## 通过条件（摘自 Dot 10/20）

| 项 | 要求 |
| --- | --- |
| 晚间 | 同一数据日，墙钟在 Asia/Shanghai **15:00 之后**，`snapshot_phase=evening`，份额权威位 **0** |
| 次晨 | **下一个自然日** 08:00 之后；`snapshot_phase` 必须是 **`morning`**。周五晚→周一早是 `backfill`，**不计** |
| 版本 | 数字变或仅阶段变都追加版本；**不改写** `first_seen_at` |
| 缺口 | 同库内检查点可走 `waiting_update` / `incomplete` / `complete` |
| 510310 | 约 20% 跳变保持隔离，不抬门槛；缺一只则无四只合计；缺 ≠ 0 |
| sim-check | 退出码 **2**（粘贴原文） |
| 调度 | 本对照**不**装 crontab |

## 怎么跑（本机）

仓库根目录，已建 `.venv`：

```bash
# 一次性：固定证据目录与同一 live.sqlite
./scripts/same_db_pair.sh init
# 默认 EVIDENCE_ROOT=/workspace/etf-flow-evidence/same-db-20261021

# 交易日 15:00 之后（Asia/Shanghai）
./scripts/same_db_pair.sh evening

# 次日自然日 08:00 之后（周三晚→周四早；或周五晚→周六早）
DATA_DAY=2026-10-21 ./scripts/same_db_pair.sh morning

# 核对
DATA_DAY=2026-10-21 ./scripts/same_db_pair.sh verify

# 必须仍为 2
./scripts/same_db_pair.sh sim-check
```

配置模板：`config/same-db-pair.example.toml`（`db_path` 指向上述唯一库）。`scripts/same_db_pair.sh init` 会把 `config/example.toml` 的日历与宇宙拷过去并改写路径。

## 验证退出码与缓存

- `verify` / `morning` 后验证：`0` 通过，`1` 硬失败，`2` 用法或 **config db_path ≠ EVIDENCE_ROOT/live.sqlite**，`3` 待证据（未齐/不可判断；**不是**验收完成）。
- 次晨采集固定加 `--no-cache`，避免默认 12h HTTP 缓存复用晚间响应；缓存访问时间不得升级为来源时间。
- 导出：`observations-versions.tsv` 不含 `authoritative`（该列只在 `observations` 当前状态）；`observations-latest.tsv` 才带当前权威位。


## 回归测试（无网络）

```bash
.venv/bin/pytest tests/test_same_db_evening_morning.py -q
```

覆盖：同库 `first_seen_at` 保留、阶段 evening→morning、仅阶段变化也追加版本、进程重启后继承、缺口 `waiting_update`→`complete`、510310 跳变隔离、缺一只不记 0、周五→周一为 `backfill`。

## 与连续灰度的边界

跑通同库对照 **不等于** 连续灰度开始。灰度、扩池、模拟入场仍单独验收。`sim-check` 保持退出码 2。
