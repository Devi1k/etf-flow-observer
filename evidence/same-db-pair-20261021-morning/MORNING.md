# same-DB evidence A — morning leg (DATA_DAY=2026-10-21)

Desensitized local note only. No secrets, cookies, or raw HTML dumps.

| Item | Value |
| --- | --- |
| Wall clock start | 2026-10-22T08:13:59+0800 (Asia/Shanghai) |
| Wall clock end | 2026-10-22T08:14:28+0800 |
| Branch | `evidence/same-db-evening-morning` |
| HEAD at run | `0997d9a2688384c6941b5afd51058be75675c7a7` |
| Evening runtime SHA | `a17d07559577a35e96f3097238e010f150c3b32b` (ancestor; 0997d9a is evening evidence-note only) |
| EVIDENCE_ROOT | `/workspace/etf-flow-evidence/same-db-20261021` |
| live.sqlite | `/workspace/etf-flow-evidence/same-db-20261021/live.sqlite` |
| db_inode | 103510 (unchanged evening-end → morning-start → morning-end) |
| db_size morning-start→end | 73728 → 86016 |
| morning log | `…/logs/morning-20261022T081359+0800` |
| morning collect_exit | **0** |
| verify_exit (embedded + independent) | **3** (pending-evidence; not acceptance) |
| sim-check | `EXIT:2` (expected) |
| DATA_DAY | 2026-10-21 |
| session / phase | `--session morning`; all new `observation_versions.snapshot_phase=morning` (not backfill) |

## Continuity (evening-end vs morning-start)

```
path_match=true
evening_end_db=/workspace/etf-flow-evidence/same-db-20261021/live.sqlite
morning_start_db=/workspace/etf-flow-evidence/same-db-20261021/live.sqlite
evening_end_inode=103510
morning_start_inode=103510
refuse_reason=
```

Same `live.sqlite` only; no new DB. `assert_db_identity` ok.

## first_seen_at preservation

Pre-existing row id=1 (`510300` / `2026-10-20` / `unit_nav` / `huatai_homepage`):

- before: `2026-10-21T15:16:33+08:00`
- after:  `2026-10-21T15:16:33+08:00`
- unchanged: **yes** (append-only; verify also `PASS first_seen_at_preserved_on_append`)

## Phase / authority

- Morning checkpoints: `…:morning` for sse/szse/huatai/efunds/chinaamc/jsfund — all `complete` for data day 2026-10-21.
- New observation_versions for as_of 2026-10-21: **13** rows, all `snapshot_phase=morning` (plus prior evening-stored homepage row for 2026-10-20 also labeled morning by clock-phase rule).
- `backfill` rows for data-day: **0**.
- Evening observation_versions for this pair data-day: **0** (evening leg previously exit 1 / no exchange shares).

## Per-fund (as_of 2026-10-21, morning)

| Fund | shares | unit_nav | cumulative_nav | morning gaps created? |
| --- | --- | --- | --- | --- |
| 510300 华泰柏瑞沪深300ETF | yes 30199087700 份 (sse_shares) | yes 4.1856 (huatai_nav_table + homepage agree) | yes 1.8791 | no (stored=3/gaps=0 on morning checkpoint) |
| 510310 易方达沪深300ETF | yes 17062844000 份 (sse_shares) | yes 4.0664 (efunds_nav) | yes 2.1629 | no |
| 510330 华夏沪深300ETF | yes 9702249800 份 (sse_shares) | yes 4.3645 (chinaamc_nav) | yes 2.1305 | no |
| 159919 嘉实沪深300ETF | yes 7565616600 份 (szse_shares) | yes 4.369 (jsfund_nav; apex fallback after primary SSL EOF) | yes 2.0272 | no |

Share quality_flags include `no_adjacent_share` (no 2026-10-20 share row in this DB to compute change); values were **not** filled with 0. Status “四只合计：没有” refers to unavailable adjacent-day change aggregate, not missing morning share rows.

Historical evening gaps (fetched_at 2026-10-21T15:16:22, `no_exchange_row` / `fetch_failed`) remain in `data_gaps` as evening-leg records; morning did not fabricate clears or rewrite them into success.

## Verify checklist (field mode, DATA_DAY=2026-10-21)

| Item | Result | Reason |
| --- | --- | --- |
| evening_versions_present | 未通过/PENDING | evening observation_versions rows=0 |
| morning_versions_present | 已通过 | morning rows=13 |
| no_backfill_for_this_pair | 已通过 | backfill rows=0 |
| same_key_phase_pairing | 未通过/PENDING | paired=0; morning_only=13 |
| first_seen_at_preserved_on_append | 已通过 | freeze intact |
| four_fund_shares_paired | 未通过/PENDING | missing all four (no evening share leg) |
| evening_after_1500_data_day | 未通过/PENDING | no evening rows |
| morning_after_0800_next_natural_day | 已通过 | next natural day ≥08:00 |
| raw_and_checkpoints_present | 已通过 | raw=21 checkpoints=12 |
| raw_fetch_linkage | 已通过 | linked morning raw ids |
| checkpoint_status_vocabulary | 已通过 | complete/incomplete/waiting_update |
| no_fabricated_zero_shares | 已通过 | zero-like share versions=0 |
| 510310_jump_isolation | 未通过/PENDING | no evening 510310 shares |
| cache_access_not_promoted_to_source_time | 已通过 | suspect=0 |
| sim-check EXIT:2 | 已通过 | printed EXIT:2 |
| continuity same inode/path | 已通过 | inode 103510 path_match=true |
| phase=morning (not backfill) | 已通过 | all new versions morning |
| 严格同库配对验收 | **未通过** | evening leg invalid (collect exit 1; 0 evening versions); dots: successful morning cannot auto-count as strict same-DB pair |

summary: passed=9 failed=0 pending=5 → verify exit **3**.

## Honest overall

**严格同库配对不可验收。** Morning collect succeeded (exit 0) with four-fund shares+NAV and phase=morning on the same inode DB, but the prior evening leg was not a valid evening leg. Per dots prior review: even a successful morning cannot be back-filled into a strict same-DB pair acceptance.

## Explicitly not done

- No crontab / no continuous gray / allow_trial / universe expand
- No new DB; no first_seen rewrite; no fabricated 0 shares
- No phase relabel to fake evening success
- No Slack / user message from this run
- No merge to main
