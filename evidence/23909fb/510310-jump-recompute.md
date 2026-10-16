# 510310 易方达沪深300ETF 份额跳变复算（证据库只读）

数据来源：`/workspace/etf-flow-evidence/live.sqlite`（现场 smoke 独立库，未改代码、未重跑采集）。

## 观察版本链路

| 项 | 2026-10-14（基数） | 2026-10-15（跳变日） |
|---|---|---|
| observation_id | 2 | 5 |
| version_no | 1 | 1 |
| observation_versions.id | 2 | 5 |
| fund | 510310 易方达沪深300ETF | 同左 |
| series / source | shares / sse_shares | shares / sse_shares |
| original_value | 1215694.4 万份 | 1672624.4 万份 |
| standardized_value | 12156944000 份 | 16726244000 份 |
| quality_status | exploratory_backfill | abnormal_jump |
| quality_flags | ["no_adjacent_share", "exploratory_backfill"] | ["abs_change_ratio=0.375859", "abnormal_jump"] |
| content_hash（观察行） | `6dab8e71ff380f9959d56f47a9f2439650577f23c18ebb5657c70a0ce94f8199` | `6a9aedf5bf78423314ccaed7ab0878acb3fd33c83a8c9bc006e190270f818220` |
| raw_fetch_id | 1 | 2 |
| snapshot_phase | backfill | morning |
| authoritative（observations） | 0 | 0 |
| note | SEC_NAME=HS300ETF | SEC_NAME=HS300ETF |

## raw_fetches（请求与正文哈希）

### raw_fetch_id=1 → 10-14 基数

- method: `GET`
- url: `https://query.sse.com.cn/commonQuery.do?isPagination=true&pageHelp.pageSize=1000&pageHelp.pageNo=1&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE=2026-10-14`
- request_body: `None`（GET，无 POST body）
- http_status: 200
- content_sha256（正文）: `7451e804798455c046c9cbb93e4e198286dffade2ce4f79977145c79a3029ebf`
- body_path: `/workspace/etf-flow-evidence/raw/by-hash/7451e804798455c046c9cbb93e4e198286dffade2ce4f79977145c79a3029ebf`
- request_started_at: 2026-10-16T20:44:11+08:00
- network_fetched_at: 2026-10-16T20:44:19+08:00
- from_cache: 0
- error: None

原始 JSON 行（正文内）：`SEC_CODE=510310`, `SEC_NAME=HS300ETF`, `STAT_DATE=2026-10-14`, `TOT_VOL=1215694.4`

### raw_fetch_id=2 → 10-15 跳变

- method: `GET`
- url: `https://query.sse.com.cn/commonQuery.do?isPagination=true&pageHelp.pageSize=1000&pageHelp.pageNo=1&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L&STAT_DATE=2026-10-15`
- request_body: `None`（GET，无 POST body）
- http_status: 200
- content_sha256（正文）: `95414b0a1faf3751227837f2a76f2d7bc6a254dc7f649a0828aa28671943e429`
- body_path: `/workspace/etf-flow-evidence/raw/by-hash/95414b0a1faf3751227837f2a76f2d7bc6a254dc7f649a0828aa28671943e429`
- request_started_at: 2026-10-16T20:44:19+08:00
- network_fetched_at: 2026-10-16T20:44:29+08:00
- from_cache: 0
- error: None

原始 JSON 行（正文内）：`SEC_CODE=510310`, `SEC_NAME=HS300ETF`, `STAT_DATE=2026-10-15`, `TOT_VOL=1672624.4`

## 算术（与 quality_flags 对齐）

相对上一笔已保存份额（10-14）计算绝对变化比：

```
prev  = 1215694.4 万份   # 10-14 original_value / SSE TOT_VOL
curr  = 1672624.4 万份   # 10-15 original_value / SSE TOT_VOL
ratio = abs(curr - prev) / abs(prev)
      = (1672624.4 - 1215694.4) / 1215694.4
      = 456930.0 / 1215694.4
      = 0.3758592619987391568144099372
      ≈ 0.375859   # 与 quality_flags abs_change_ratio=0.375859 一致
      ≈ 37.5859%
```

门禁：`abnormal_share_jump_ratio = 0.20`；`0.375859 > 0.20` → `abnormal_jump`；权威位 0；四只合计 blocked（不当 0、不放宽）。

标准化：`万份 × 10000 = 份` → 10-14 `12156944000` 份，10-15 `16726244000` 份（比值相同）。

## 关联说明

- `observation_versions.raw_fetch_id` → `raw_fetches.id`
- `observation_versions.content_hash` 为观察行内容哈希；`raw_fetches.content_sha256` 为整份 HTTP 正文哈希（二者不同属正常）
- 同一次 smoke 里 raw_fetch 17/18 为强制不缓存的二次 SSE 抓取，正文 sha 与 id 1/2 相同，未新增 observation 版本
