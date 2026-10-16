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
