# 晚间腿证据（evening → next-morning 对照 1/2）

- **角色**：真实跨晚间→次晨对照的**晚间腿**；次晨腿计划下个交易日（2026-10-19 周一）早间再跑。
- **不是**连续灰度，**不是**交易模拟，**未**放宽 510310 易方达沪深300ETF 隔离。
- **产品代码未改**；main 仍为 `789ac36`。

## 固定版本与环境

| 项 | 值 |
| --- | --- |
| 实现 SHA | `789ac366de8a8ffe8a64a1c73dfa6572fe3ffc25` |
| 命令 | `python -m etf_flow_observer --config …/evening-20261016/config.toml collect all --session evening --homepage-cross-check` |
| 独立库 | `/workspace/etf-flow-evidence/evening-20261016/live.sqlite`（新建空库，未复用先前 live.sqlite） |
| 配置休市日 | 与 `789ac36` 对齐的 **19** 个工作日休市（此前口头误写 17；日期不变，见 config `[calendar].closures`） |
| schema_version | **2**（跑完后查询） |
| 墙钟开始 | 2026-10-16T20:58:59+08:00（Asia/Shanghai，已过 `session_close=15:00`） |
| 墙钟结束 | 2026-10-16T20:59:27+08:00 |
| 退出码 | **1**（嘉实净值源有错误；见下） |

未使用 `smoke`：`smoke` 固定走 `morning_session`，今晚会把阶段标成 morning。本腿用 `--session evening`，由钟点/日历给出实际阶段，**未伪造 phase**。

## 阶段（phase）

- 意图：`--session evening`
- 工具实际写入观察版本的 `snapshot_phase`：**全部为 `evening`**（7/7）
- 数据日：`2026-10-16`（当日晚间快照）
- `request_started_at` 最早 20:58:59；`network_fetched_at` 自 20:59:03 起

## 四只快照（代码 + 中文名）

数据日均为 **2026-10-16**。

| 代码 | 名称 | 份额 | 单位净值 | 阶段 | 说明 |
| --- | --- | --- | --- | --- | --- |
| 510300 | 华泰柏瑞沪深300ETF | **无**（上交所 `no_exchange_row`，HTTP 200 但 `pageHelp.data=[]`） | 4.2426 元（`huatai_nav_table` + 首页一致） | evening | 累计净值 1.9002 |
| 510310 | 易方达沪深300ETF | **无**（上交所 `no_exchange_row`） | 4.1221 元（`efunds_nav`） | evening | 累计净值 2.1908；**本腿无份额，故无新跳变判定**；此前 10/15 +37.59% 隔离**继续保留、未放宽** |
| 510330 | 华夏沪深300ETF | **无**（上交所 `no_exchange_row`） | 4.4239 元（`chinaamc_nav`） | evening | 累计净值 2.1548 |
| 159919 | 嘉实沪深300ETF | **无**（深交所 `no_exchange_row`） | **无**（`jsfund_nav` `fetch_failed`） | — | 主域三次 `SSLEOFError`；回落 `www.jsfund.cn` 先 `IncompleteRead`，后 HTTP 200 但窗口内无净值行 |

## 合计门禁

```
数据日 2026-10-16
  510300 没有份额，不记 0
  510310 没有份额，不记 0
  510330 没有份额，不记 0
  159919 没有份额，不记 0
  四只合计：没有。缺 510300、510310、510330、159919。不会把缺的当成 0。
```

**门禁结果：blocked**（四只份额均缺）。未把缺额当 0，未为合计放宽。

## 缺口（6）

| as_of | fund | series | source | reason |
| --- | --- | --- | --- | --- |
| 2026-10-16 | 510300 | shares | sse_shares | no_exchange_row |
| 2026-10-16 | 510310 | shares | sse_shares | no_exchange_row |
| 2026-10-16 | 510330 | shares | sse_shares | no_exchange_row |
| 2026-10-16 | 159919 | shares | szse_shares | no_exchange_row |
| 2026-10-16 | 159919 | unit_nav | jsfund_nav | fetch_failed |
| 2026-10-16 | 159919 | cumulative_nav | jsfund_nav | fetch_failed |

上交所对 `STAT_DATE=2026-10-16` 返回空列表：晚间闭市后约 21:00 仍未见当日份额行——这是晚间腿相对次晨腿的预期对照点之一，不是日历误报（10-16 不在 closures）。

## 请求统计

- raw_fetches：**11**
- observation_versions：**7**（均为 evening / ok）
- 失败：嘉实导致进程退出码 1

详见同目录 `fetches.tsv`、`observations-latest.tsv`、`gaps.tsv`、`stdout.txt`、`stderr.txt`（空）、`status.txt`、`run-meta.txt`。

## 510310 隔离

本晚间腿 **没有** 写入 510310 份额，因此 **没有** 新的 `abnormal_jump` 事件。先前证据库中 10/15 相对 10/14 的 +37.5859% 隔离结论不变；本轮未改质量阈值、未放宽门禁。

## 下一步

- **次晨腿（2/2）**：下个交易日 2026-10-19（周一）早间，对同一数据日 `2026-10-16` 再采一次，对照份额是否出现、净值是否修订、phase 是否为 morning/backfill（周一隔周末，工具可能标 `backfill`——届时如实记录）。
- 仍不启动连续灰度、不做交易模拟。

