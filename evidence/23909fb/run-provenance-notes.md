# detached / 空库 / 退出码 0 — 可追溯性说明

仅依据**已保存的证据文件与现有库**；本轮未改代码、未重跑采集。

## schema_version（本轮补查，现有库）

```sql
SELECT * FROM schema_version;
-- id=1, version=2
PRAGMA user_version;
-- 0
```

表集合与 `src/etf_flow_observer/storage.py` 中 schema 一致（含 raw_fetches 时间链列、observation_versions.raw_fetch_id 等）。

## detached SHA

- 已保存：`pytest-23909fb.txt` 首行 `SHA: 23909fbf3513bfcbe3bbe2acd8fb62913d795dda`
- 已保存：`EVIDENCE.md` 写明 detached、工作树干净
- **未保存**：当时 shell 的 `git status` / `git rev-parse HEAD` 原始终端全文（除上述摘录外）→ 更细的「detached 提示符原文」**无法从contemporaneous 日志追溯**，只能采信已写入证据文件的 SHA 字符串。

## 全新空库

- 已保存：`EVIDENCE.md` / `config.toml` 指向独立路径 `live.sqlite`；库现有 raw_fetches=18、observations=181、data_gaps=44，与单次 smoke 规模一致
- **未保存**：运行前 `ls`/`sqlite3`「库不存在或 0 字节」的 contemporaneous 命令输出 → **空库前置状态无法独立追溯**，只能从「独立路径 + 单次写入规模 + schema_version=2」间接支持。

## 退出码 0

- 已保存：`EVIDENCE.md` 写「退出码 0」；`smoke-stdout.txt` 完整跑完并写出 `live-smoke-23909fb.md`，无异常栈
- **未保存**：shell 字面量 `echo $?` / `exit_code=` 行 → **精确退出码的 contemporaneous 捕获无法追溯**；成功完成有强旁证，但若审查要求「终端 exit 行」，应标为不可追溯。
