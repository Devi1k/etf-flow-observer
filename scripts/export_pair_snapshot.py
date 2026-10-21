#!/usr/bin/env python3
"""Export compact TSV snapshots from a live.sqlite into an evidence log dir."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path


def dump(conn: sqlite3.Connection, sql: str, path: Path) -> None:
    rows = conn.execute(sql).fetchall()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not rows:
            fh.write("")
            return
        writer = csv.writer(fh, delimiter="\t")
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow([row[k] for k in row.keys()])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        dump(
            conn,
            """
            SELECT fund_code, as_of_date, series, source_name, version_no, snapshot_phase,
                   original_value, standardized_value, quality_status, quality_flags,
                   authoritative, first_seen_at, revised_at, fetched_at
            FROM observation_versions
            ORDER BY as_of_date, fund_code, series, version_no
            """,
            args.out / "observations-versions.tsv",
        )
        dump(
            conn,
            """
            SELECT o.fund_code, o.as_of_date, o.series, o.source_name, o.first_seen_at,
                   o.revised_at, o.authoritative, o.latest_version_no,
                   v.snapshot_phase, v.quality_status, v.standardized_value
            FROM observations o
            JOIN observation_versions v
              ON v.observation_id = o.id AND v.version_no = o.latest_version_no
            ORDER BY o.as_of_date DESC, o.fund_code, o.series
            """,
            args.out / "observations-latest.tsv",
        )
        dump(
            conn,
            "SELECT fund_code, as_of_date, series, source_name, reason, fetched_at FROM data_gaps ORDER BY as_of_date, fund_code",
            args.out / "gaps.tsv",
        )
        dump(
            conn,
            "SELECT source_name, checkpoint_key, status, updated_at, detail FROM checkpoints ORDER BY source_name, checkpoint_key",
            args.out / "checkpoints.tsv",
        )
        dump(
            conn,
            """
            SELECT id, source_name, http_status, fetched_at, network_fetched_at, from_cache, error, url
            FROM raw_fetches ORDER BY id
            """,
            args.out / "fetches.tsv",
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
