# 验收证据 23909fb（2026-10-16 上海）

仅供审查，不是灰度启动，不代表策略有效。未改代码、未加功能、未启动连续采集。

- SHA: 23909fbf3513bfcbe3bbe2acd8fb62913d795dda（detached，工作树干净）
- pytest: 59 passed / 0 failed / 0 skipped（完整输出 `pytest-23909fb.txt`，含 Python/pytest 版本与时间）
- 现场采集: `etf-flow-observer --config config.toml smoke`，全新独立库，2026-10-16 20:44:11–20:45:14 +08:00，退出码 0
- 数据日 2026-10-15，smoke 自动阶段标 morning（实际运行于 10-16 晚间，非次晨对照）

## 每只 ETF（数据日 2026-10-15）
| ETF | 份额（来源/状态） | 单位净值（来源/状态） |
|---|---|---|
| 510300 华泰柏瑞沪深300ETF | SSE 2548488.77万份 ok（变化3.22%） | 华泰历史表 4.2366 ok；首页 10-16 4.2426（历史表尚无 10-16） |
| 510310 易方达沪深300ETF | SSE 1672624.4万份 **abnormal_jump（37.59%），权威=0，隔离** | 易方达 4.1164 ok |
| 510330 华夏沪深300ETF | SSE 862404.98万份 ok（0.57%） | 华夏 4.4176 ok |
| 159919 嘉实沪深300ETF | SZSE 685,191.66万份 ok（0.18%） | 嘉实 4.4226 ok（主域失败后用 www.jsfund.cn） |

## 四只合计门禁
**blocked**：缺 510310（abnormal_jump），不当 0，不输出合计。门禁未放宽。

## 失败/缺口
- 嘉实主域 www.jsfund.com.cn 3 次 `SSLEOFError: UNEXPECTED_EOF_WHILE_READING`，回退 www.jsfund.cn 成功（上次为 DNS gaierror）。
- 缺口 44 条，均 no_exchange_row；休市表为空，未覆盖国庆 10-01~10-07，历史完整性不能验收。
- 响应时间（秒级精度）：SSE 7–10s，SZSE 1–2s，易方达 1–2s，华泰 2–5s，华夏 1–3s，嘉实回退 2s。明细 `fetches.tsv`。

## 文件
pytest-23909fb.txt, smoke-stdout.txt, live-smoke-23909fb.md, fetches.tsv, observations-latest.tsv, status.txt, config.toml（库与原始响应不提交）

## 本轮补证（2026-10-16 晚，仅现有库，无代码改动、无重跑采集）

对照 dot：① 全量 44 缺口分类；② 510310 请求/raw_fetch/哈希/观察版本与 10-14 基数复算；③ detached/空库/退出码可追溯性 + schema_version。

### ① 缺口 44 条

- 导出：`gaps-44-classified.csv`（全 44 行）+ `gaps-44-classified.md`
- **calendar_false_positive: 44**；**real_missing_return: 0**
  - 中秋休市 **2026-09-25**：**3**（159919 嘉实沪深300ETF 份额；510330 华夏沪深300ETF 单位/累计净值）——**不能归因国庆**
  - 国庆休市工作日 10-01/02/05/06/07：**41**
- 原因均为 `no_exchange_row`；当时 `calendar.closures=[]`
- `status.txt` 只列出 **40** 行缺口，库内另有 10-07 的 510310 易方达沪深300ETF×2、510330 华夏沪深300ETF×2 未打印

### ② 510310 易方达沪深300ETF +37.5859%

- 明细：`510310-jump-recompute.md`、`510310-jump-linkage.tsv`
- 10-14 基数：`1215694.4` 万份；raw_fetch_id=**1**；GET `…STAT_DATE=2026-10-14`；正文 sha256 `7451e804…029ebf`；观察版本 id=2 / obs_id=2
- 10-15：`1672624.4` 万份；raw_fetch_id=**2**；GET `…STAT_DATE=2026-10-15`；正文 sha256 `95414b0a…43e429`；观察版本 id=5 / obs_id=5；flags `abs_change_ratio=0.375859`
- 复算：`(1672624.4−1215694.4)/1215694.4 = 0.375859…`；request_body 均为 null（GET）

### ③ 运行可追溯性 + schema_version

- 见 `run-provenance-notes.md`
- 现查：`schema_version.version = 2`；`PRAGMA user_version = 0`
- **不可追溯（无 contemporaneous 命令原文）**：运行前空库证明；shell `echo $?` 退出码字面行；完整 `git status` detached 提示符原文（仅采信已写入的 SHA 字符串与成功跑完旁证）

仍仅为审查证据，**不是灰度**，未改代码、未加功能、未启动连续采集。main 未动。
