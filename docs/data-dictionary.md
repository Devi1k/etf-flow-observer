# 数据字典

观察按来源拆开保存。份额和单位净值来自不同网站，修订节奏也不一样，所以不把它们压成一行后再算哈希。需要一起看时，由读取逻辑按基金和数据日拼起来。

## 逻辑观察

唯一键：`fund_code + as_of_date + series + source_name`

`series` 只有三种：

| series | 含义 | 标准化单位 |
| --- | --- | --- |
| shares | 基金份额 | 份 |
| unit_nav | 单位净值或份额净值 | 元 |
| cumulative_nav | 累计净值 | 元 |

同一键的数字没变、阶段也没变、质量状态也没变时，再次抓取只记一次“内容相同”，不追加版本。数字变了，或者晚间参考变成早间确认，就追加版本。`first_seen_at` 始终是第一次看见的时间。`revised_at` 在第一次写入时为空，之后每次新版本更新。

## 每条版本上的字段

| 字段 | 含义 |
| --- | --- |
| fund_code | 510300、510310、510330、159919 之一 |
| as_of_date | 数据日，不是抓取日 |
| original_value | 页面上的原文，保留逗号等痕迹 |
| original_unit | 份额为“万份”，净值为“元” |
| standardized_value | 份额已乘 10000；净值仍是元。冲突或无法解析时为空，不是 0 |
| source_url | 实际请求的地址。嘉实若改走 www.jsfund.cn，这里会是实际地址 |
| fetched_at | 这一版所依据的网络响应时间。缓存复用不会把它改成后来的读取时间 |
| network_fetched_at | 正文第一次从网络到达的时间 |
| cache_accessed_at | 若这次是缓存复用，则为读取缓存的时间，否则为空。它不延长缓存有效期 |
| observation_available_at | 这条观察所用正文的到达时间。采集任务开始时的同一个 now 不能拿来填它 |
| first_seen_at | 本系统第一次看见该键的时间。不是交易所发布时间 |
| revised_at | 这一版若是修订则为修订时间，否则为空 |
| content_hash | 基金、日期、序列、单位和标准化数字的 SHA-256 |
| quality_status | 见下表 |
| snapshot_phase | evening、overnight、before_close、morning、backfill |
| authoritative | 只有份额在 morning 且状态为 ok 时，才视为深交所所说的早间权威数 |
| lookahead_free | 晚间、过夜、早间这些当时窗口为 1。backfill 为 0，不能拿去说无前视回测 |

拼起来阅读时，份额的 `original_unit` 仍是万份，`standardized_shares` 是份，`unit_nav` 来自单位净值序列。两个来源的 URL 都保留。

## 质量状态

| 状态 | 含义 | 能否计算可执行申赎 |
| --- | --- | --- |
| ok | 交易日、单位清楚、没有跳变，且阶段允许 | 还要有相邻上一交易日的可用份额 |
| provisional_evening | 当日晚间份额，只供参考 | 否 |
| overnight_provisional | 次日 08:00 之前看到的份额 | 否 |
| premature | 收盘前就去要当天收盘数据 | 否 |
| exploratory_backfill | 事后补录 | 否 |
| holiday_or_non_trading | 周末或配置的休市日 | 否 |
| abnormal_jump | 份额相对上一笔变化超过 20% 且不到 50% | 否 |
| suspect_split_or_merge | 变化达到或超过 50%，或上一笔为 0 | 否 |
| duplicate_conflict | 同一页或相邻页给出不同数字 | 否，不挑选其中一个 |
| stale | 读取时发现 ok 记录已超过配置的小时数 | 否 |
| cross_check_conflict | 华泰柏瑞历史表和首页不一致 | 否 |
| no_adjacent_share | 作为标志放在 flags 里。没有相邻上一交易日的份额。不能改用更早的非空值 | 否 |
| prior_not_valid | 相邻上一交易日的份额状态不能做差，例如异常跳变 | 否 |

`no_exchange_row` 和 `fetch_failed` 记在 `data_gaps`，不产生份额为 0 的观察。

分页里同一天、同一来源、同一数字出现多次，只留一条，并在 flags 里记下 `pagination_duplicate_same_value`。

## 来源名

| source_name | 内容 |
| --- | --- |
| sse_shares | 上交所三只的份额 |
| szse_shares | 159919 的份额 |
| efunds_nav | 510310 |
| chinaamc_nav | 510330 |
| jsfund_nav | 159919 |
| huatai_nav_table | 510300 历史净值表 |
| huatai_homepage | 510300 首页最新一行，只做核对 |

## 其他表

- `raw_fetches`：每一次真实往返和每一次重试各一行，缓存复用另记一行。正文按内容哈希放在 `data/raw/by-hash/`，已存在的文件不覆盖。观察版本的 `raw_fetch_id` 指向产生该正文的那一次网络抓取，不指向缓存读取。不进 git。
- `data_gaps`：明确的缺失。
- `quality_events`：创建、确认、修订、依赖日重算，以及首页核对冲突。重算只追加版本。
- `disclosure_records`：只允许 `etf_share_change`。`official_increase_holding` 会被拒绝。备注里出现“国家队”也会被拒绝。
- `checkpoints`：`complete` 才会让下一轮跳过。有缺口但没有 HTTP 错误是 `waiting_update`，下一轮仍会再跑。有错误，或窗口盖住 2026-10-01 至 10-07 而休市表没写明其中的工作日，是 `incomplete`。
- `sim_ledger`：表结构在，写入函数拒绝插入。影子试验没有启动。

## 原始响应里用到的字段

上交所：`STAT_DATE`、`SEC_CODE`、`SEC_NAME`、`TOT_VOL`。忽略宇宙以外的基金。

深交所：`size_date`、`fund_code`、`security_short_name`、`current_size`。页码看 `metadata.pageno` 和 `pagecount`。

易方达：`navDate`、`netValue`、`totalNetValue`。翻页看 `pageIndex` 和 `total`。

华夏：表格日期、第二列、第三列，以及脚本里的 `currentPage`、`totalPage`。

华泰柏瑞：`date`、`netvalue`、`totalnetvalue`，以及 `currentPage`、`totalPage`。`pages` 的形式是 `页码-每页条数`。

嘉实：HTML 行“日期、份额净值、累计净值”。指定的 `www.jsfund.com.cn` 若连不上，同一路径的 `www.jsfund.cn` 会作为同一官网页面尝试，并在备注里写明。这不是第三方供应商。
