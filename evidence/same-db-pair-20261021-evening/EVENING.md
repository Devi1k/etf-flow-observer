# same-DB evidence A — evening leg (2026-10-21)

Desensitized local note only. No secrets, cookies, or raw HTML dumps.

| Item | Value |
| --- | --- |
| Wall clock start | 2026-10-21T15:16:22+0800 (Asia/Shanghai) |
| Wall clock end | 2026-10-21T15:16:43+0800 |
| Branch | `evidence/same-db-evening-morning` |
| git_sha | `a17d07559577a35e96f3097238e010f150c3b32b` |
| EVIDENCE_ROOT | `/workspace/etf-flow-evidence/same-db-20261021` |
| live.sqlite | `/workspace/etf-flow-evidence/same-db-20261021/live.sqlite` |
| db_inode | 103510 (unchanged start→end) |
| db_size start→end | 65536 → 73728 |
| evening log | `…/logs/evening-20261021T151622+0800` |
| evening_exit_code | **1** |
| sim-check | `EXIT:2` (expected; not an evening failure) |

## Continuity (evening-end)

```
resolved_db=/workspace/etf-flow-evidence/same-db-20261021/live.sqlite
db_inode=103510
db_size=73728
```

config `storage.db_path` matches the same path (`assert_db_identity` ok).

## Phase / authority (checked via export TSV + SQLite)

- Checkpoints use session key `…:evening…` for data day 2026-10-21 (sse/szse/huatai/efunds/chinaamc/jsfund).
- No exchange share rows stored for 2026-10-21 (`no_exchange_row` gaps for 510300/510310/510330/159919).
- One observation written: `510300` `2026-10-20` `unit_nav` `huatai_homepage`
  - export: `snapshot_phase=morning`, `authoritative=1`
  - SQLite `observations.authoritative=1`, `observation_versions.snapshot_phase='morning'`
  - stdout note: requested session evening vs clock phase morning for that as_of (T+1); cannot raise authority via `--session` alone.
- Exchange evening provisional shares (would be auth=0) were **not** present to assert.

## Collect outcome (why exit 1)

status.txt: 12 gaps for 2026-10-21 — mix of `no_exchange_row` (SSE/SZSE empty) and `fetch_failed` (chinaamc HTTP 404; jsfund SSL EOF). huatai homepage cross-check stored prior-day unit_nav only.

## Explicitly not done

- No crontab
- No continuous gray / allow_trial / universe expand
- No merge to main
- Morning routine etf-a-2 untouched
