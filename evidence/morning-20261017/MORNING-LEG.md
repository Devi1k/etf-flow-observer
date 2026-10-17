# 次晨腿证据（evening → next-morning 对照 2/2）

- **角色**：真实跨晚间→次晨对照的**次晨腿**；对应晚间腿证据提交 `9465320` / 目录 `evidence/evening-20261016/`（后经 `d79e98a` 纠偏自然次晨日期）。
- **自然次晨**：晚间腿墙钟为 2026-10-16（周五）约 21:00；本腿在 **2026-10-17（周六）08:25–08:26 Asia/Shanghai** 采集，数据日仍为 `2026-10-16`。
- **不是**连续灰度，**不是**交易模拟，**未**放宽 510310 易方达沪深300ETF 隔离。
- **产品代码未改**；实现 SHA 仍为 `789ac36`（main）。

## 固定版本与环境

| 项 | 值 |
| --- | --- |
| 实现 SHA | `789ac366de8a8ffe8a64a1c73dfa6572fe3ffc25` |
| 命令 | `python -m etf_flow_observer --config …/morning-20261017/config.toml collect all --session morning --homepage-cross-check` |
| 独立库 | `/workspace/etf-flow-evidence/morning-20261017/live.sqlite`（新建空库，未复用晚间库或旧 live.sqlite） |
| 配置休市日 | 与 `789ac36` 对齐的 **19** 个工作日休市（见 config `[calendar].closures`） |
| schema_version | **2** |
| 墙钟开始 | 2026-10-17T08:25:59+08:00（Asia/Shanghai，已过 `morning_start=08:00`） |
| 墙钟结束 | 2026-10-17T08:26:24+08:00 |
| 退出码 | **0**（嘉实经 `www.jsfund.cn` 回落成功；主域仍有 SSLEOFError 提示） |

未使用 `smoke`。本腿用 `--session morning`。`morning_session(2026-10-17)` → 数据日 `2026-10-16`、自动阶段名 `morning`（上一自然日 = 昨天，**不是**周一读周五的 `backfill`）。

## 阶段（phase）与分类

| 项 | 值 |
| --- | --- |
| 意图 | `--session morning` |
| `morning_session` 目标日 | `2026-10-16` |
| `morning_session` 自动阶段 | **`morning`**（因 `target == today - 1 day`） |
| 工具实际写入 `snapshot_phase` | **全部为 `morning`（13/13）** |
| 是否 backfill | **否**。若等到 2026-10-19（周一）再采同一周五，当前代码会标 `backfill`，不能计作次晨验收。 |

## 晚间 vs 次晨对照（数据日均为 2026-10-16）

| 代码 | 名称 | 晚间份额 (9465320) | 次晨份额 (本腿) | 晚间单位净值 | 次晨单位净值 | 阶段晚间→次晨 |
| --- | --- | --- | --- | --- | --- | --- |
| 510300 | 华泰柏瑞沪深300ETF | 无（`no_exchange_row`） | **2855298.77 万份**（28552987700 份，`sse_shares` ok） | 4.2426（表+首页一致） | 4.2426（表+首页一致） | evening → **morning** |
| 510310 | 易方达沪深300ETF | 无（`no_exchange_row`） | **1687924.4 万份**（16879244000 份，`sse_shares` ok） | 4.1221 | 4.1221 | evening → **morning** |
| 510330 | 华夏沪深300ETF | 无（`no_exchange_row`） | **868884.98 万份**（8688849800 份，`sse_shares` ok） | 4.4239 | 4.4239 | evening → **morning** |
| 159919 | 嘉实沪深300ETF | 无（`no_exchange_row`）；净值 `jsfund_nav` `fetch_failed` | **692931.66 万份**（6929316600 份，`szse_shares` ok）；净值 **4.4289** / 累计 **2.0526**（回落域名成功） | 无 | 4.4289 | — → **morning** |

累计净值（有晚间对照的三只）次晨与晚间一致：510300=1.9002，510310=2.1908，510330=2.1548。

## 缺口与门禁

| 腿 | data_gaps | 退出码 | 说明 |
| --- | --- | --- | --- |
| 晚间 | 6（四只份额 `no_exchange_row` + 159919 净值双缺 `fetch_failed`） | 1 | 合计门禁 **blocked**（四只份额均缺，不记 0） |
| 次晨 | **0** | **0** | 四只份额与净值均写入；`quality_flags` 含 `no_adjacent_share`（独立空库无 2026-10-15 相邻份额，**不能**算日变化/合计变化） |

次晨 `status` 仍打印「四只合计：没有」是因为**独立库缺相邻交易日份额**，不是缺当日份额；与晚间「当日份额未取得→blocked」不是同一门禁语义。本腿可证 **未取得→取得**；**不能**在本独立库上证日环比或合计变化。

## 请求统计

- raw_fetches：**10**
- observation_versions：**13**（均为 morning / ok）
- data_gaps：**0**
- 失败：无进程级失败；嘉实主域 SSL 提示后回落成功

详见同目录 `fetches.tsv`、`observations-latest.tsv`、`gaps.tsv`、`stdout.txt`、`stderr.txt`（空）、`status.txt`、`run-meta.txt`。

## 510310 隔离

- 本独立次晨库**首次**写入 510310 份额（无库内前一日），故 **没有** 新的 `abnormal_jump` 事件；仅有 `no_adjacent_share`。
- 先前旧库中 10/15 相对 10/14 的 +37.5859% 隔离结论**不在本库继承**；未改质量阈值、未放宽门禁。报告须区分「旧库异常」与「本空库未继承」。

## 本腿能证明 / 不能证明

**能：**

- 自然次晨（周六）对数据日 10-16 跑 `--session morning` 时，阶段为真实 **`morning`**，不是 `backfill`。
- 相对晚间腿：四只份额由「交易所无行」变为「有行且 ok」；159919 净值由 `fetch_failed` 变为 ok。
- 三只沪市 ETF 单位/累计净值相对晚间**未修订**（同值）。

**不能：**

- 不是连续灰度、不是交易模拟、不构成下单依据。
- 本空库无法验证份额日环比或四只合计变化（缺 10-15）。
- 不解除 510310 旧异常隔离；本库也未复现该跳变。
- 不证明 08:00 配置分界等于交易所权威发布时间。

## 对照晚间腿路径

- 晚间证据目录：`/workspace/etf-flow-evidence/evening-20261016/` 与仓库 `evidence/evening-20261016/`
- 晚间提交：`9465320`（纠偏：`d79e98a`）
