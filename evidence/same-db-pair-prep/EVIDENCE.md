# 同库晚间→次晨对照：准备证据（尚非 live 成对）

- **角色**：为 Dot 证据 A 准备同库 harness、回归测试与操作步骤。
- **不是**连续灰度；**未**安装 crontab；**未**打开 `allow_trial`；宇宙未扩。
- **先前跨库证据不计**：`evidence/evening-20261016` + `evidence/morning-20261017`（`51c0f9e` / `9cdec31`）明确为独立空库，不能替代本项。

## 墙钟与窗口（准备时）

| 项 | 值 |
| --- | --- |
| 准备墙钟 | 2026-10-21 约 10:35 Asia/Shanghai（开盘后、**晚间窗 15:00 未开**） |
| 计划晚间腿 | 数据日 **2026-10-21**，当日 **15:00 之后**，`--session evening` |
| 计划次晨腿 | **2026-10-22**（周四）**08:00 之后**，同一 `live.sqlite`，`--session morning` |
| 实现基线 | `origin/main` @ `789ac36`；本准备落在分支 `evidence/same-db-evening-morning` |

因准备时刻早于 15:00，**本目录不声称已完成 live 同库成对**。live 成对需按 `docs/same-db-evening-morning.md` 在窗口内执行后另附日志。

## 本轮已交付

1. **回归测试** `tests/test_same_db_evening_morning.py`：同库 evening→morning、`first_seen_at` 不改写、阶段区分、缺口检查点演进、Store 关闭再开继承、510310 跳变隔离、缺一只≠0、周五→周一=`backfill`。
2. **操作脚本**
   - `scripts/same_db_pair.sh`：`init` / `evening` / `morning` / `verify` / `sim-check` / `status`
   - `scripts/verify_same_db_pair.py`：对单一 DB 打印 PASS/FAIL
   - `scripts/export_pair_snapshot.py`：导出 versions / gaps / checkpoints TSV
3. **配置模板** `config/same-db-pair.example.toml`（固定唯一 `db_path`）
4. **说明** `docs/same-db-evening-morning.md`
5. **`sim-check` 退出码 2** 原文：见同目录 `sim-check.txt`
6. **pytest**：见 `pytest.txt`（含新增同库用例）

## 代码能力（main 已有，本轮未改门禁）

产品侧同库追加逻辑已在 `Store.upsert_version` / `classify_phase` / `mark_checkpoint`：

- 晚间份额 → `provisional_evening`、权威 0
- 次晨同键追加版本，保留原 `first_seen_at`
- 缺口无 HTTP 错 → `waiting_update`；齐了 → `complete`
- 缺基金不记 0；异常跳变隔离，不抬 20% 门槛

本轮**没有**放宽质量规则，**没有**扩宇宙。

## 仍需 live 窗口才能闭合的项

| 项 | 状态 |
| --- | --- |
| 15:00 后真实 `--session evening` 写入同库 | 待 2026-10-21 15:00+ |
| 次日 08:00+ `--session morning` 追加同库 | 待 2026-10-22 |
| 交易所是否当晚给出份额行 | 未知（可能仍 `no_exchange_row`；仍可证未取得→取得或同值 phase_revised） |
| 将 live 日志 / verify 输出贴回本目录或新 evidence 子目录 | 待跑完 |

## Dot 如何验收准备部分（现在）

```bash
cd /workspace/etf-flow-observer
git checkout evidence/same-db-evening-morning
.venv/bin/pytest tests/test_same_db_evening_morning.py -q
./scripts/same_db_pair.sh sim-check   # 期望 EXIT:2
```

## Dot 如何验收 live 成对（窗口后）

```bash
EVIDENCE_ROOT=/workspace/etf-flow-evidence/same-db-20261021 ./scripts/same_db_pair.sh evening
# …次日…
DATA_DAY=2026-10-21 EVIDENCE_ROOT=/workspace/etf-flow-evidence/same-db-20261021 ./scripts/same_db_pair.sh morning
DATA_DAY=2026-10-21 ./scripts/same_db_pair.sh verify
```

核对日志目录下 `run-meta.txt`（墙钟、exit、SHA）、`observations-versions.tsv`（evening→morning、同一 `first_seen_at`）、`checkpoints.tsv`、以及 `sim-check.txt` 的 `EXIT:2`。

## 明确未做

- 未声称连续灰度已开始
- 未安装 crontab
- 未改 `allow_trial`
- 未扩观察池
- 未把跨库 10/16–10/17 证据改称同库成对
