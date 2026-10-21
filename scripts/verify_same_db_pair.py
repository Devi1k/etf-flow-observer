#!/usr/bin/env python3
"""Inspect one SQLite DB for Dot evidence-A same-DB evening→morning criteria.

Usage (from repo root, after both legs ran on the SAME db_path):

  .venv/bin/python scripts/verify_same_db_pair.py \\
      --db /workspace/etf-flow-evidence/same-db-20261021/live.sqlite \\
      --data-day 2026-10-21

Does not collect, does not install crontab, does not open allow_trial.
Exit 0 = checks printed with PASS/FAIL lines; always inspect FAIL lines.
Exit 2 = usage / DB missing.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SH = ZoneInfo("Asia/Shanghai")
FUNDS = ("510300", "510310", "510330", "159919")


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def check_pair(conn: sqlite3.Connection, data_day: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    day = date.fromisoformat(data_day)
    next_morning_floor = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=SH).replace(
        hour=8
    )

    evening_rows = conn.execute(
        """
        SELECT v.fund_code, v.series, v.snapshot_phase, v.first_seen_at, v.version_no,
               v.quality_status, o.authoritative
        FROM observation_versions v
        JOIN observations o ON o.id = v.observation_id
        WHERE v.as_of_date = ? AND v.snapshot_phase = 'evening'
        ORDER BY v.fund_code, v.series, v.version_no
        """,
        (data_day,),
    ).fetchall()
    results.append(
        (
            "evening_versions_present",
            len(evening_rows) > 0,
            f"evening observation_versions rows={len(evening_rows)}",
        )
    )

    # Authoritative flag on the observation row after evening-only (latest still evening).
    evening_latest_shares = conn.execute(
        """
        SELECT o.fund_code, o.authoritative, v.snapshot_phase, v.quality_status
        FROM observations o
        JOIN observation_versions v
          ON v.observation_id = o.id AND v.version_no = o.latest_version_no
        WHERE o.as_of_date = ? AND o.series = 'shares' AND v.snapshot_phase = 'evening'
        """,
        (data_day,),
    ).fetchall()
    # If morning already ran, evening versions still exist but latest may be morning;
    # check evening version quality_status instead for provisional.
    evening_share_versions = [r for r in evening_rows if r["series"] == "shares"]
    provisional = (
        all(r["quality_status"] == "provisional_evening" for r in evening_share_versions)
        if evening_share_versions
        else False
    )
    results.append(
        (
            "evening_shares_provisional",
            provisional and bool(evening_share_versions),
            f"evening share versions={len(evening_share_versions)}; all provisional_evening → {provisional}",
        )
    )
    if evening_latest_shares:
        auth0 = all(int(r["authoritative"]) == 0 for r in evening_latest_shares)
        results.append(
            (
                "evening_latest_shares_authoritative_0",
                auth0,
                f"latest-still-evening share rows={len(evening_latest_shares)}; all auth=0 → {auth0}",
            )
        )

    morning_rows = conn.execute(
        """
        SELECT v.fund_code, v.series, v.snapshot_phase, v.first_seen_at, v.version_no,
               v.fetched_at, v.quality_status, o.authoritative
        FROM observation_versions v
        JOIN observations o ON o.id = v.observation_id
        WHERE v.as_of_date = ? AND v.snapshot_phase = 'morning'
        ORDER BY v.fund_code, v.series, v.version_no
        """,
        (data_day,),
    ).fetchall()
    results.append(
        (
            "morning_versions_present",
            len(morning_rows) > 0,
            f"morning observation_versions rows={len(morning_rows)}",
        )
    )

    backfill = conn.execute(
        """
        SELECT COUNT(*) AS n FROM observation_versions
        WHERE as_of_date = ? AND snapshot_phase = 'backfill'
        """,
        (data_day,),
    ).fetchone()["n"]
    results.append(
        (
            "no_backfill_for_this_pair",
            int(backfill) == 0,
            f"backfill rows for data-day={backfill} (Friday→Monday backfill does not count)",
        )
    )

    # first_seen_at must match across versions of the same observation key.
    keys = conn.execute(
        """
        SELECT fund_code, series, source_name, COUNT(DISTINCT first_seen_at) AS n_seen,
               COUNT(*) AS n_ver, MIN(first_seen_at) AS first_seen
        FROM observation_versions
        WHERE as_of_date = ?
        GROUP BY fund_code, series, source_name
        """,
        (data_day,),
    ).fetchall()
    multi = [k for k in keys if int(k["n_ver"]) >= 2]
    preserved = all(int(k["n_seen"]) == 1 for k in multi) if multi else False
    results.append(
        (
            "first_seen_at_preserved_on_append",
            preserved and bool(multi),
            f"multi-version keys={len(multi)}; distinct first_seen all 1 → {preserved}",
        )
    )

    # Morning fetch wall-clock should be next natural day after 08:00 (when present).
    morning_ok_clock = True
    clock_notes = []
    for row in morning_rows:
        stamp = row["fetched_at"] or ""
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            morning_ok_clock = False
            clock_notes.append(f"bad stamp {stamp}")
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=SH)
        when = when.astimezone(SH)
        if when.date() != day + timedelta(days=1) or when < next_morning_floor:
            morning_ok_clock = False
            clock_notes.append(f"{row['fund_code']}:{row['series']}@{stamp}")
    results.append(
        (
            "morning_after_0800_next_natural_day",
            bool(morning_rows) and morning_ok_clock,
            "; ".join(clock_notes) if clock_notes else "all morning fetched_at on next natural day ≥08:00",
        )
    )

    # Checkpoint evolution (live collect writes these; fixture-only DBs may have none).
    cps = conn.execute(
        """
        SELECT source_name, checkpoint_key, status, detail
        FROM checkpoints
        WHERE checkpoint_key LIKE ?
        ORDER BY source_name, checkpoint_key
        """,
        (f"%{data_day}%",),
    ).fetchall()
    statuses = {row["status"] for row in cps}
    raw_n = int(conn.execute("SELECT COUNT(*) AS n FROM raw_fetches").fetchone()["n"])
    if raw_n == 0 and not cps:
        results.append(
            (
                "checkpoints_recorded",
                True,
                "no raw_fetches and no checkpoints (fixture/unit path); live collect must write checkpoints",
            )
        )
    else:
        results.append(
            (
                "checkpoints_recorded",
                len(cps) > 0,
                f"rows={len(cps)} statuses={sorted(statuses)} raw_fetches={raw_n}",
            )
        )
    if "waiting_update" in statuses or "complete" in statuses or "incomplete" in statuses:
        results.append(
            (
                "checkpoint_status_vocabulary",
                True,
                f"seen {sorted(statuses & {'waiting_update', 'incomplete', 'complete'})}",
            )
        )

    # Missing ≠ 0: data_gaps reasons should not invent zero observations.
    zeroish = conn.execute(
        """
        SELECT COUNT(*) AS n FROM observation_versions
        WHERE as_of_date = ? AND series = 'shares'
          AND (standardized_value = '0' OR original_value IN ('0', '0.0', '0.00'))
        """,
        (data_day,),
    ).fetchone()["n"]
    results.append(
        (
            "no_fabricated_zero_shares",
            int(zeroish) == 0,
            f"zero-like share versions={zeroish}",
        )
    )

    jump = conn.execute(
        """
        SELECT v.fund_code AS fund_code, v.quality_status AS quality_status, o.authoritative AS authoritative
        FROM observation_versions v
        JOIN observations o ON o.id = v.observation_id AND o.latest_version_no = v.version_no
        WHERE v.as_of_date = ? AND v.fund_code = '510310' AND v.series = 'shares'
        """,
        (data_day,),
    ).fetchone()
    if jump is not None and jump["quality_status"] == "abnormal_jump":
        results.append(
            (
                "510310_jump_isolated_auth0",
                int(jump["authoritative"]) == 0,
                f"status={jump['quality_status']} auth={jump['authoritative']}",
            )
        )
    else:
        results.append(
            (
                "510310_jump_isolated_auth0",
                True,
                "no abnormal_jump on latest 510310 shares (ok if live day had no >20% move)",
            )
        )

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--data-day", required=True, help="YYYY-MM-DD")
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(f"DB missing: {args.db}", file=sys.stderr)
        return 2
    conn = _connect(args.db)
    try:
        results = check_pair(conn, args.data_day)
    finally:
        conn.close()
    failed = 0
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"{mark}\t{name}\t{detail}")
    print(f"summary\tfailed={failed}\ttotal={len(results)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
