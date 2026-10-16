# 晚间腿证据（evening → next-morning 对照 1/2）

- **角色**：真实跨晚间→次晨对照的**晚间腿**。
- **自然次晨**：晚间腿墙钟为 2026-10-16（周五）晚；自然次晨是 **2026-10-17（周六）**，不是下一个交易日周一。次晨腿已改排 **2026-10-17 08:15（Asia/Shanghai）**，按墙钟采同一数据日 `2026-10-16`，保留失败与版本，不要求数字必变。
- **若只在 2026-10-19（周一）再采**：只能称为**周末延后补采**，工具阶段应保留 `backfill`（或如实记录当时相位），**不计**次晨验收，**不得**强升为 `morning`。当前代码周一读周五会归 backfill，不能称为已完成「次晨修订」。
- **份额对照上限**：本晚间腿四只份额均为 `no_exchange_row`（未取得）。后续若份额出现，本轮对照只能证明 **未取得→取得**，**不能**称为「修订」（无晚间份额基线可比）。
- **不是**连续灰度，**不是**交易模拟；**未**为合计或异常放宽质量规则。
- **产品代码未改**；main 仍为 `789ac36`。本文仅文档纠偏（dot 收束晚间证据后要求），不加功能、不加验收项。

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
| 510310 | 易方达沪深300ETF | **无**（上交所 `no_exchange_row`） | 4.1221 元（`efunds_nav`） | evening | 累计净值 2.1908；**本腿无份额，故无新跳变判定**（见下节新旧库隔离区分） |
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

上交所对 `STAT_DATE=2026-10-16` 返回空列表：晚间闭市后约 21:00 仍未见当日份额行——这是晚间腿相对后续采集的预期对照点之一（份额是否从无到有），不是日历误报（10-16 不在 closures）。因晚间未取得份额，后续出现份额时只证「未取得→取得」，不证修订。

## 请求统计

- raw_fetches：**11**
- observation_versions：**7**（均为 evening / ok）
- 失败：嘉实导致进程退出码 1

详见同目录 `fetches.tsv`、`observations-latest.tsv`、`gaps.tsv`、`stdout.txt`、`stderr.txt`（空）、`status.txt`、`run-meta.txt`。

## 510310 隔离：新旧库必须分开说

两件事互不继承，勿混写：

1. **先前证据库**（`evidence/23909fb` 对应的独立 live.sqlite / smoke 库）：数据日 2026-10-15 相对 10-14，510310 易方达沪深300ETF 份额 **+37.5859%**，质量状态 `abnormal_jump`、权威=0、四只合计门禁因缺 510310 而 **blocked**。该隔离结论仍在该库与相关证据文件中（见 `evidence/23909fb/510310-jump-recompute.md`），**未放宽、未撤销**。
2. **本晚间库**（`/workspace/etf-flow-evidence/evening-20261016/live.sqlite`）：**新建空库**，**未**从先前库复制观察版本、质量状态或隔离标记。本腿 **没有** 写入任何 510310 份额行，因此本库内 **没有** `abnormal_jump` 事件、**没有**可继承的隔离状态。本腿合计 blocked 仅因四只份额 `no_exchange_row`，与旧库 +37.59% 不是同一条证据链。

本轮未改质量阈值、未为出合计放宽。旧异常「继续保留」仅指**审查口径上仍隔离、不因日历或晚间快照放行**；**不是**说本晚间库已载入该隔离记录。

## 下一步

- **次晨腿（2/2）**：自然次晨 **2026-10-17 08:15（Asia/Shanghai）**，对同一数据日 `2026-10-16` 再采一次；按墙钟与日历如实记录 phase（勿伪造 morning）；保留失败与版本；不要求数字必变。份额侧若出现，只记「未取得→取得」。
- **若改到或仅在 2026-10-19 再采**：文档与验收须改称周末延后补采，保留 `backfill`，**不计**次晨验收，勿强升 morning。
- 仍不启动连续灰度、不做交易模拟；本轮不加其他验收项。

## 文档纠偏说明（相对 9465320）

相对提交 `9465320` 原文：已删除「次晨腿 = 下个交易日 2026-10-19 周一」及「周一次晨」表述；明确自然次晨为 10-17、10-19 仅为周末延后补采且不计次晨验收；写清无晚间份额时后续只能证未取得→取得；将 510310 旧库异常与本晚间空库未继承隔离拆成两条事实。

