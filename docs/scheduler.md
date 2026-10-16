# 调度说明

调度器没有安装，也没有在这台机器上启动。下面的时间只说明以后可以怎么跑。不要把这份说明当成已经部署。

时区用 Asia/Shanghai。

## 每个交易日晚间

收盘之后抓当天份额，阶段明确写成 evening。晚间结果只供参考，不能用来模拟当天收盘入场。

```bash
etf-flow-observer collect shares --session evening
```

`--session evening` 会选今天，并在今天确实是交易日时把阶段设为 evening。周末会直接拒绝。

## 次日早间

08:00 之后修订上一个自然日。只有数据日正好是昨天，阶段才会是 morning。周一早上跑，对应的是周五，阶段会是 backfill，因为程序没有在周六早间看见它。

```bash
etf-flow-observer collect shares --session morning
etf-flow-observer collect nav --session morning --homepage-cross-check
```

净值没有深交所那条“晚间仅供参考”的规则，但入场时点仍然要等份额变成权威，并且要晚于两边都已经抓到的时间。

## 建议的 cron 文本

不要直接装进 crontab。路径和交易日历都还要人工确认。

```cron
CRON_TZ=Asia/Shanghai
30 20 * * 1-5 cd /path/to/etf-flow-observer && .venv/bin/etf-flow-observer collect shares --session evening
20 8 * * 1-5 cd /path/to/etf-flow-observer && .venv/bin/etf-flow-observer collect shares --session morning
25 8 * * 1-5 cd /path/to/etf-flow-observer && .venv/bin/etf-flow-observer collect nav --session morning --homepage-cross-check
```

## 还不能开始影子试验

```bash
etf-flow-observer sim-check
```

退出码 2 是预期结果：参数没冻结，`allow_trial` 为 false，调度也没安装。把空参数填上并不会自动开始记账，写入函数在这一版里会拒绝。
