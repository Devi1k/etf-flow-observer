# 同库晚间→次晨对照：准备证据（尚非 live 成对）

- **角色**：为 Dot 证据 A 准备同库 harness、回归测试与操作步骤。
- **不是**连续灰度；**未**安装 crontab；**未**打开 `allow_trial`；宇宙未扩。
- **先前跨库证据不计**：`evidence/evening-20261016` + `evidence/morning-20261017`（`51c0f9e` / `9cdec31`）明确为独立空库，不能替代本项。
- **未恢复**例程 `etf-a` / `etf-a-2`；本轮**未**跑真实晚间/次晨采集。

## 墙钟与提交链（本修正）

| 项 | 值 |
| --- | --- |
| 修正墙钟 | 2026-10-21 约 11:01+ Asia/Shanghai（仍早于晚间窗 15:00） |
| 被拒 tip（Dot 复审） | `81be172`（六反例大多静态已关；仍有 3 个阻断，禁止按此版启现场） |
| 基线（相对） | `81be1724611cdbd3984a0eb7c2c1c8de9b30aadb` |
| 本修正 tip | （见本提交 / 推送 tip） |
| 计划晚间腿 | 数据日 **2026-10-21**，当日 **15:00 之后**（本三阻断清完并经 Dot 再审后才可跑） |
| 计划次晨腿 | **2026-10-22** **08:00 之后**，同一 `live.sqlite` |
| 分支 | `evidence/same-db-evening-morning` |

## Dot 对 `81be172` 剩余三阻断与本轮处置

| # | Dot 阻断 | 本轮处置 | 状态 |
| --- | --- | --- | --- |
| CE4 | `suspect_split_or_merge` 合法隔离正例误失败：先验 99、晚间/次晨均为 160 且 auth=0，因 verify L602–615 只豁免 `abnormal_jump` 仍要求 `provisional_evening` | 与 `BLOCKING` 统一：豁免 `abnormal_jump` **与** `suspect_split_or_merge`；检查改名 `evening_shares_provisional_when_not_blocking`；新增正例 `test_ce4_suspect_split_or_merge_isolation_positive`；**撤回**先前「CE4 已覆盖 suspect_split_or_merge」过宽声称 | **已修**（正例实测 PASS） |
| CE5 | 错 source / HTTP 500 / 错相位钟未独立成反例；错 source+500 被 source 先挡致 500 路径未证；错时注释仍误用 MORNING | 拆成三独立负例：`test_ce5_raw_wrong_source_alone_is_mismatch`、`test_ce5_raw_http_500_alone_is_mismatch`、`test_ce5_raw_wrong_phase_clock_alone_is_mismatch`（后者用 **EVENING** 时间挂在 morning 版本上） | **已修**（三路径各自断言） |
| 分页空缓存 | 空响应跨多页时 `forget_cached` 首成功即 `break`，后续页留陈旧缓存；单页 CE2 结论可保留，不可声称覆盖全部分页路径 | **已修** SSE/SZSE：对 `day_urls`/`urls` **全部** `forget_cached`；新增 `test_ce2_multi_page_empty_response_clears_all_page_caches`（pageCount=2）；单页 CE2 仍保留 | **已修**（多页实测 calls==4） |

### 分类汇总（按 Dot 用语）

| 分类 | 项 |
| --- | --- |
| **静态已核**（上一轮 81be172 已关未回退） | CE1 缺口重试相位；CE2 单页空缓存；CE3 全版本 first_seen；CE4 abnormal_jump 隔离 + morning auth1 反例；CE6 continuity 分文件；导出 authoritative 位；morning 退出码；库路径一致 |
| **本轮新关** | CE4 suspect_split_or_merge 正例；CE5 三独立负例；多页空缓存失效 |
| **收窄 / 更正** | 撤回 EVIDENCE 中「CE4 已覆盖 suspect_split_or_merge」；CE5 不再用合并用例冒充三路径；多页空缓存此前**未**覆盖，现已补测（不再仅声称单页） |
| **未独立运行** | Dot 方独立跑测（待其复审本 tip）；**89/本轮 93 passed 与 sim-check EXIT:2 仍为本地实测，Dot 未复跑** |
| **live 未跑** | 真实同库 evening/morning collect；连续灰度；crontab；扩池；allow_trial；例程 etf-a / etf-a-2；正式连续观察；日报接入 |

## 本轮已交付

1. 代码：`scripts/verify_same_db_pair.py`、`adapters/sse_shares.py`、`adapters/szse_shares.py`
2. 测试：`tests/test_same_db_pair_scripts.py`（CE4 正例、CE5×3、CE2 多页）
3. `sim-check` 仍为 **EXIT:2**（见 `sim-check.txt`）
4. pytest：**93 passed**（见 `pytest.txt` / `pytest-count.txt`；相对 `81be172` 的 89 = +4）

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
| 按本 tip 启动现场例程 | **否**（三阻断清完前禁止） |

## Dot 如何复核本修正

```bash
cd /workspace/etf-flow-observer
git checkout evidence/same-db-evening-morning
.venv/bin/pytest tests/test_same_db_pair_scripts.py::test_ce4_suspect_split_or_merge_isolation_positive \
  tests/test_same_db_pair_scripts.py::test_ce5_raw_wrong_source_alone_is_mismatch \
  tests/test_same_db_pair_scripts.py::test_ce5_raw_http_500_alone_is_mismatch \
  tests/test_same_db_pair_scripts.py::test_ce5_raw_wrong_phase_clock_alone_is_mismatch \
  tests/test_same_db_pair_scripts.py::test_ce2_multi_page_empty_response_clears_all_page_caches -q
.venv/bin/pytest -q
./scripts/same_db_pair.sh sim-check   # 期望 EXIT:2
```

现场一对仍须窗口内另跑，且首对不计正式连续观察。不以 passed 数量替代反例闭环。
