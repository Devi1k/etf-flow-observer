# 全部 44 条 data_gaps 分类（现有库导出）

导出自 `live.sqlite` 表 `data_gaps`，共 **44** 条。`status.txt` 只打印了 **40** 行「缺口 …」（缺末尾 10-07 的 510310×2、510330×2），不能以 UI 行数代替库计数。

## 汇总

- **calendar_false_positive（日历误报）: 44**
  - 其中 **中秋休市 2026-09-25**: 3（不能归因国庆）
  - 其中 **国庆休市工作日 10-01/02/05/06/07**: 41
- **real_missing_return（真实未返回）: 0**
- 配置当时 `calendar.closures = []`；smoke 日志多次提示休市表未覆盖国庆工作日。
- 官方依据：上交所《2026年部分节假日休市安排》（上证公告〔2025〕45号）及 2026-09-17 中秋/国庆休市公告：中秋 09-25～09-27；国庆 10-01～10-07。
- 逐条明细见 `gaps-44-classified.csv`。

## 按日计数

| as_of_date | 休市归因 | 条数 | 分类 |
|---|---|---:|---|
| 2026-09-25 | 中秋休市 | 3 | calendar_false_positive |
| 2026-10-01 | 国庆休市 | 7 | calendar_false_positive |
| 2026-10-02 | 国庆休市 | 7 | calendar_false_positive |
| 2026-10-05 | 国庆休市 | 9 | calendar_false_positive |
| 2026-10-06 | 国庆休市 | 9 | calendar_false_positive |
| 2026-10-07 | 国庆休市 | 9 | calendar_false_positive |

## status.txt 未展示的 4 条（库内有）

- 2026-10-07 510310 易方达沪深300ETF cumulative_nav efunds_nav no_exchange_row
- 2026-10-07 510310 易方达沪深300ETF unit_nav efunds_nav no_exchange_row
- 2026-10-07 510330 华夏沪深300ETF cumulative_nav chinaamc_nav no_exchange_row
- 2026-10-07 510330 华夏沪深300ETF unit_nav chinaamc_nav no_exchange_row
