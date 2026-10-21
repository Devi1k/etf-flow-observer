# 同库晚间→次晨对照：准备证据（尚非 live 成对）

- **角色**：为 Dot 证据 A 准备同库 harness、回归测试与操作步骤。
- **不是**连续灰度；**未**安装 crontab；**未**打开 `allow_trial`；宇宙未扩。
- **先前跨库证据不计**：`evidence/evening-20261016` + `evidence/morning-20261017`（`51c0f9e` / `9cdec31`）明确为独立空库，不能替代本项。
- **未恢复**例程 `etf-a` / `etf-a-2`；本轮**未**跑真实晚间/次晨采集。

## 墙钟与提交链（本修正）

| 项 | 值 |
| --- | --- |
| 修正墙钟 | 2026-10-21 约 11:10+ Asia/Shanghai（仍早于晚间窗 15:00） |
| 被拒 tip（Dot 复审） | `00dfac8`（有实质进展，准备包仍未通过；禁止按此版启现场） |
| 基线（相对） | `00dfac8` |
| 本修正 tip | `5250afd14377a49b778ea4ddb6ba6ef4c630692a` |
| 计划晚间腿 | 数据日 **2026-10-21**，当日 **15:00 之后**（修完并经 Dot 再审后才可跑） |
| 计划次晨腿 | **2026-10-22** **08:00 之后**，同一 `live.sqlite` |
| 分支 | `evidence/same-db-evening-morning` |

## Dot 对 `00dfac8` 复审六反例与本轮处置

| # | Dot 反例 | 本轮处置 | 状态 |
| --- | --- | --- | --- |
| 1 | 完整晚间→空次晨→缺口检查看到旧晚间值，可能将 morning 记 complete，发布后重试在 HTTP 前跳过 | `record_expected_gaps(..., required_phase=)` + `Store.phase_value`；`finish_batch` 传入 `phase_override` | **已修反例**（`test_ce1_...` 实测 finish_batch/should_skip） |
| 2 | 晚间 15:00 空 200 占 12h 缓存，挡住 20:00 已发布重试 | `cacheable` 列 + `invalidate_cache` / `HttpClient.forget_cached`；空 body 与 SSE/SZSE 无基金空结果取消缓存资格；`collect_sse` 路径空→有数据重试 | **已修反例**（`test_ce2_...` 真实调用 collect_sse） |
| 3 | first_seen 只比每阶段 tip，晚间 v1 漂移、tip/次晨仍对齐可漏检 | 校验器核**全版本** `first_seen_at` 对 `observations.first_seen_at` 冻结 | **已修反例**（`test_ce3_...` 调 verify 脚本） |
| 4 | 异常状态与当前 authoritative 混用；晚间 jump + 次晨恢复误失败；反向 morning jump+auth1 漏检 | 晚间快照独立判定；新增 `510310_morning_blocking_vs_authoritative`；覆盖 `suspect_split_or_merge` | **已修反例**（`test_ce4_...` 正例+反例） |
| 5 | raw/checkpoint 仅查存在；错 source、HTTP500、仅晚间 checkpoint 仍可能 PASS | 逐腿匹配 source/成功状态/相位墙钟；双阶段 checkpoint 相位匹配 | **已修反例**（`test_ce5_...`） |
| 6 | continuity.txt 起止 tee 同文件覆盖，丢失 refuse 证据 | `continuity-${leg}.txt` 分文件；`compare_pair_continuity`；`continuity-terminal.txt` 不覆盖 start/compare | **已修反例**（`test_ce6_...` 调 same_db_pair.sh） |

### 分类汇总（按 Dot 用语）

| 分类 | 项 |
| --- | --- |
| **静态已核**（上一轮 00dfac8 已核未回退） | 导出不分历史 authoritative；morning 传递 verify 失败/pending 退出码；配置库路径不一致拒绝；分属两阶段误通过已堵 |
| **已修反例**（本轮） | 上表 1–6，均有代码 + 实测脚本/采集链测试 |
| **未独立运行** | Dot 方独立跑测（待其复审本 tip） |
| **live 未跑** | 真实同库 evening/morning collect；连续灰度；crontab；扩池；allow_trial；例程 etf-a / etf-a-2；正式连续观察；日报接入 |

## 本轮已交付

1. 代码：`pipeline.py`、`storage.py`、`http_client.py`、`adapters/sse_shares.py`、`adapters/szse_shares.py`、`scripts/verify_same_db_pair.py`、`scripts/same_db_pair.sh`
2. 测试：`tests/test_same_db_pair_scripts.py` 新增 CE1–CE6（实际调用 export/verify/shell/collect_sse/finish_batch）
3. `sim-check` 仍为 **EXIT:2**（见 `sim-check.txt`）
4. pytest：**89 passed**（见 `pytest.txt`）

### 退出码约定（verify / morning）

| 码 | 含义 |
| --- | --- |
| 0 | 通过（field 验收意义下的 PASS） |
| 1 | 硬失败 |
| 2 | 用法错误 / DB 缺失 / 双路径不一致 / continuity 路径拒绝 |
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

现场一对仍须窗口内另跑，且首对不计正式连续观察。不以 passed 数量替代反例闭环。
