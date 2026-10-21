# 同库晚间→次晨对照：准备证据（尚非 live 成对）

- **角色**：为 Dot 证据 A 准备同库 harness、回归测试与操作步骤。
- **不是**连续灰度；**未**安装 crontab；**未**打开 `allow_trial`；宇宙未扩。
- **先前跨库证据不计**：`evidence/evening-20261016` + `evidence/morning-20261017`（`51c0f9e` / `9cdec31`）明确为独立空库，不能替代本项。
- **未恢复**例程 `etf-a` / `etf-a-2`；本轮**未**跑真实晚间/次晨采集。

## 墙钟与窗口（本修正提交时）

| 项 | 值 |
| --- | --- |
| 修正墙钟 | 2026-10-21 约 10:45+ Asia/Shanghai（仍早于晚间窗 15:00） |
| 被审基线 | `77144c6`（Dot 正式审查：**暂不通过现场链路**） |
| 计划晚间腿 | 数据日 **2026-10-21**，当日 **15:00 之后**（修完并经 Dot 再审后才可跑） |
| 计划次晨腿 | **2026-10-22** **08:00 之后**，同一 `live.sqlite` |
| 分支 | `evidence/same-db-evening-morning` |

因墙钟仍早于 15:00，且 Dot 要求先修 6 项再跑现场，**本目录不声称已完成 live 同库成对**。

## Dot 对 `77144c6` 的 6 项结论与本轮处置

| # | Dot 结论 | 本轮处置 | 状态 |
| --- | --- | --- | --- |
| 1 | 导出 SQL 从 `observation_versions` 读不存在的 `authoritative`；勿把当前权威位映射成历史事实 | `export_pair_snapshot.py`：versions TSV **无** authoritative；latest TSV 保留 **当前** observations.authoritative | **已修**（代码+`test_export_script_against_real_store_schema`） |
| 2 | 验证器会误通过：未要求同键跨阶段；夹具可冒充现场 | `verify_same_db_pair.py`：`--mode field\|fixture`；field 强制四只同键配对、墙钟、raw/checkpoint、first_seen 冻结；fixture 明示非现场 | **已修**（正例+分属两阶段反例+缺 raw 反例） |
| 3 | 验证器会误拒绝：跳变主状态应为 `abnormal_jump`；缺 510310/前日基数→未覆盖/不可判断 | 跳变隔离看 evening 主状态；`provisional_evening` 可留 flags；缺数 → `PENDING` 退出码 3，不假 PASS | **已修**（跳变正例+缺 510310 pending 例） |
| 4 | 默认 12h 缓存可能晚间→次晨复用；不可把缓存访问时间升级为来源时间 | `same_db_pair.sh morning` 使用 `--no-cache`；校验器检查 cache 未提升为 source time；单测证明 TTL 内命中 vs `--no-cache` 取新；`waiting_update` 可重试 | **已修**（缓存单测+unpublished 重试） |
| 5 | morning `\|\| true` 吞掉 verify 失败仍可能 exit 0 | 分别记录 `collect_exit_code` / `verify_exit_code`；verify 1→壳 exit 1，3→pending，0→0；collect≠0 优先 | **已修**（`test_same_db_pair_sh_morning_verify_fail_does_not_exit_0`） |
| 6 | 可能采 A 库验 B 库 | 采集/验证前 `assert_db_identity`：config `db_path` 必须 resolve 到 `EVIDENCE_ROOT/live.sqlite`，否则 REFUSE exit 2；写 `continuity.txt` | **已修**（路径不一致反例） |

### Dot 审查本身

| 项 | 状态 |
| --- | --- |
| 静态审查 `77144c6` | Dot 已做；**不通过**现场链路 |
| Dot 独立跑测 | **未运行**（Dot 自述） |
| 本方原报 67 passed | 仅证明 Store 回归；**不**证明 export/verify 脚本（Dot 正确指出） |

## 本轮已交付（修后）

1. 脚本修复：`scripts/export_pair_snapshot.py`、`verify_same_db_pair.py`、`same_db_pair.sh`
2. 新增脚本路径测试：`tests/test_same_db_pair_scripts.py`（**实际 subprocess 调用** export/verify/shell）
3. 保留原 Store 回归：`tests/test_same_db_evening_morning.py`
4. `sim-check` 仍为 **EXIT:2**（见 `sim-check.txt`）
5. pytest：见 `pytest.txt` / `pytest-same-db.txt`

### 退出码约定（verify / morning）

| 码 | 含义 |
| --- | --- |
| 0 | 通过（field 验收意义下的 PASS） |
| 1 | 硬失败 |
| 2 | 用法错误 / DB 缺失 / 双路径不一致 |
| 3 | 待证据（pending / uncovered）；**不等于**验收完成 |

## 仍未运行 / 明确未做

| 项 | 状态 |
| --- | --- |
| 真实同库 evening collect | **未运行**（等 Dot 再审本修正 + 15:00 窗） |
| 真实同库 morning collect | **未运行** |
| 连续灰度 / crontab / 扩池 / allow_trial | **未做** |
| 例程 etf-a / etf-a-2 | **未恢复** |
| 首对计入正式连续观察 / 接日报 | **否** |

## Dot 如何复核本修正

```bash
cd /workspace/etf-flow-observer
git checkout evidence/same-db-evening-morning
.venv/bin/pytest tests/test_same_db_pair_scripts.py tests/test_same_db_evening_morning.py -q
.venv/bin/pytest -q
./scripts/same_db_pair.sh sim-check   # 期望 EXIT:2
```

现场一对仍须窗口内另跑，且首对不计正式连续观察。
