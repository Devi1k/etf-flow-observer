# etf-flow-observer

采集并校验四只沪深 300 ETF 的公开份额和单位净值，用来研究“净申购赎回的代理变量是否比价格多带一点信息”。

这不是交易程序。它不连接券商，不读取真实账户，也不把份额上升叫成国家队资金。

固定观察这四只，不按表现更换：

1. 510300 华泰柏瑞沪深300ETF
2. 510310 易方达沪深300ETF
3. 510330 华夏沪深300ETF
4. 159919 嘉实沪深300ETF

## 环境

Python 3.11 或更新。除测试用的 pytest 外，运行时只用标准库。

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

在仓库根目录运行。配置里的 `data/` 会在本地生成，已经被 git 忽略。不要把原始响应提交进仓库。

## 常用命令

```bash
.venv/bin/etf-flow-observer collect shares --session morning
.venv/bin/etf-flow-observer collect nav --session morning --homepage-cross-check
.venv/bin/etf-flow-observer status
.venv/bin/etf-flow-observer smoke --write-report docs/live-smoke.md
.venv/bin/etf-flow-observer sim-check
```

`collect shares` 默认最多请求 5 个上交所交易日。120 日全量回补还没验收，超过上限会停止。`--allow-long-backfill` 只是取消这道保护，不表示回补已经被接受。

`sim-check` 退出码 2 是当前的正确结果：影子试验的交易参数还没冻结，调度器也没有安装。

## 数据从哪里来

份额：

- 上交所 510300、510310、510330，一次请求按日期返回，字段 `TOT_VOL`，单位万份。
- 深交所 159919，按日期区间和 `PAGENO` 翻页，字段 `current_size`，单位万份。T 日晚间数字只供参考，T+1 早间才权威。

单位净值：

- 510310 易方达 JSON：用 `netValue`，不用 `totalNetValue`。
- 510330 华夏历史净值表。第一页可以带 `isQuery=true`，后面的页不能带，否则会回到第 1 页。
- 510300 华泰柏瑞官网历史净值表 `getFundNetTableJson`，`pages` 形如 `1-10`。首页静态表只核对最新一行。
- 159919 嘉实 `NavHistory.jsp`。份额净值和累计净值分开保存。

任一基金缺失就记缺口，不记 0，也不再输出四只合计。估计申赎金额是份额变化乘以当日单位净值，不等于现金流入。

## 目录

```text
config/example.toml              采集配置
config/simulation.example.toml   尚未冻结的试验参数
docs/experiment-protocol.md      研究规则
docs/data-dictionary.md          字段和状态
docs/scheduler.md                以后如何启动，当前未安装
src/etf_flow_observer/           采集、换算、版本库和命令行
tests/                           用夹具覆盖的校验，不访问网络
data/                            本地库和原始响应，不提交
```

## 当前边界

代码里已经有适配器、限速、缓存、断点、版本化 SQLite 和校验。单元测试不访问网络。2026-10-16 的现场核对记在 `docs/live-smoke.md`：四个净值源和两家交易所份额都有可解析结果，但嘉实主域名当天没有 DNS，510310 的份额跳变挡住了四只合计。那份记录只描述这一次运行。

历史下载的 `first_seen_at` 只是本系统看见的时间。它不能用来宣称无前视回测已经就绪。
