#!/usr/bin/env python3
"""Inspect one SQLite DB for Dot evidence-A same-DB evening→morning criteria.

Exit codes
  0  pass — field (or fixture) required checks all PASS
  1  fail — one or more hard FAIL checks
  2  usage / DB missing
  3  pending-evidence — pair incomplete or jump uncovered/undecidable;
     NOT an acceptance pass (do not treat as done)

Modes
  field   (default) — live evidence: four-fund coverage, same-key pairing,
          wall clocks, raw_fetch linkage, checkpoints, first_seen freeze.
          Empty raw/checkpoint cannot PASS.
  fixture — structural pairing checks for unit tests; prints mode=fixture and
          never claims field evidence. Still fails hard negatives.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SH = ZoneInfo("Asia/Shanghai")
FUNDS = ("510300", "510310", "510330", "159919")

# Check outcome kinds
PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"
INFO = "INFO"


def _connect(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_flags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    return list(value) if isinstance(value, list) else [str(value)]


def _parse_stamp(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=SH)
    return when.astimezone(SH)


def _share_source(fund: str) -> str:
    return "szse_shares" if fund.startswith("159") else "sse_shares"


def check_pair(
    conn: sqlite3.Connection,
    data_day: str,
    *,
    mode: str,
) -> list[tuple[str, str, str]]:
    """Return list of (name, outcome, detail). outcome in PASS/FAIL/PENDING/INFO."""
    results: list[tuple[str, str, str]] = []
    day = date.fromisoformat(data_day)
    evening_floor = datetime.combine(day, datetime.min.time(), tzinfo=SH).replace(hour=15)
    next_morning_floor = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=SH).replace(
        hour=8
    )

    results.append(("mode", INFO, mode))

    evening_rows = conn.execute(
        """
        SELECT v.fund_code, v.series, v.source_name, v.snapshot_phase, v.first_seen_at,
               v.version_no, v.quality_status, v.quality_flags, v.fetched_at,
               v.network_fetched_at, v.cache_accessed_at, v.raw_fetch_id, v.observation_id
        FROM observation_versions v
        WHERE v.as_of_date = ? AND v.snapshot_phase = 'evening'
        ORDER BY v.fund_code, v.series, v.version_no
        """,
        (data_day,),
    ).fetchall()
    morning_rows = conn.execute(
        """
        SELECT v.fund_code, v.series, v.source_name, v.snapshot_phase, v.first_seen_at,
               v.version_no, v.quality_status, v.quality_flags, v.fetched_at,
               v.network_fetched_at, v.cache_accessed_at, v.raw_fetch_id, v.observation_id
        FROM observation_versions v
        WHERE v.as_of_date = ? AND v.snapshot_phase = 'morning'
        ORDER BY v.fund_code, v.series, v.version_no
        """,
        (data_day,),
    ).fetchall()

    results.append(
        (
            "evening_versions_present",
            PASS if evening_rows else (PENDING if mode == "field" else FAIL),
            f"evening observation_versions rows={len(evening_rows)}",
        )
    )
    results.append(
        (
            "morning_versions_present",
            PASS if morning_rows else (PENDING if mode == "field" else FAIL),
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
            PASS if int(backfill) == 0 else FAIL,
            f"backfill rows for data-day={backfill} (Friday→Monday backfill does not count)",
        )
    )

    # ---- Same-key pairing: fund + series + source + data-day, evening then morning ----
    evening_keys = {
        (r["fund_code"], r["series"], r["source_name"]): r for r in evening_rows
    }
    morning_keys = {
        (r["fund_code"], r["series"], r["source_name"]): r for r in morning_rows
    }
    paired = sorted(set(evening_keys) & set(morning_keys))
    evening_only = sorted(set(evening_keys) - set(morning_keys))
    morning_only = sorted(set(morning_keys) - set(evening_keys))

    # Reject "different funds across phases" false-pass: require overlap on same keys.
    if evening_rows and morning_rows and not paired:
        results.append(
            (
                "same_key_phase_pairing",
                FAIL,
                f"no shared (fund,series,source) across phases; evening_only={evening_only} morning_only={morning_only}",
            )
        )
    elif not evening_rows or not morning_rows:
        results.append(
            (
                "same_key_phase_pairing",
                PENDING if mode == "field" else FAIL,
                f"paired={len(paired)} evening_only={len(evening_only)} morning_only={len(morning_only)}",
            )
        )
    else:
        results.append(
            (
                "same_key_phase_pairing",
                PASS,
                f"paired={len(paired)} evening_only={len(evening_only)} morning_only={len(morning_only)}",
            )
        )

    # first_seen freeze: EVERY version for the key (not only phase tip) must match observations.first_seen_at.
    # Comparing only the last evening/morning tip misses mid-phase rewrite (v1=20:30, v2=20:35 drift).
    first_seen_ok = True
    first_seen_notes: list[str] = []
    all_versions = conn.execute(
        """
        SELECT fund_code, series, source_name, snapshot_phase, version_no,
               first_seen_at, observation_id
        FROM observation_versions
        WHERE as_of_date = ?
        ORDER BY fund_code, series, source_name, version_no
        """,
        (data_day,),
    ).fetchall()
    freeze_by_obs: dict[int, str] = {}
    for row in all_versions:
        oid = int(row["observation_id"])
        if oid not in freeze_by_obs:
            obs = conn.execute(
                "SELECT first_seen_at FROM observations WHERE id = ?", (oid,)
            ).fetchone()
            freeze_by_obs[oid] = obs["first_seen_at"] if obs else ""
        freeze = freeze_by_obs[oid]
        if row["first_seen_at"] != freeze:
            first_seen_ok = False
            first_seen_notes.append(
                f"{row['fund_code']}:{row['series']}:{row['source_name']}:"
                f"v{row['version_no']}/{row['snapshot_phase']} "
                f"version_first_seen={row['first_seen_at']} obs_freeze={freeze}"
            )
    # Paired tips must also agree with each other (same freeze).
    for key in paired:
        e, m = evening_keys[key], morning_keys[key]
        if e["first_seen_at"] != m["first_seen_at"]:
            first_seen_ok = False
            first_seen_notes.append(
                f"{key}: tip evening={e['first_seen_at']} morning={m['first_seen_at']}"
            )
    if paired or all_versions:
        results.append(
            (
                "first_seen_at_preserved_on_append",
                PASS if first_seen_ok else FAIL,
                "; ".join(first_seen_notes)
                if first_seen_notes
                else f"versions={len(all_versions)} paired={len(paired)} first_seen freeze intact",
            )
        )
    else:
        results.append(
            (
                "first_seen_at_preserved_on_append",
                PENDING if mode == "field" else FAIL,
                "no versions to check first_seen freeze",
            )
        )

    # ---- Four-fund shares coverage (field) ----
    evening_share_funds = {
        r["fund_code"] for r in evening_rows if r["series"] == "shares" and r["fund_code"] in FUNDS
    }
    morning_share_funds = {
        r["fund_code"] for r in morning_rows if r["series"] == "shares" and r["fund_code"] in FUNDS
    }
    paired_share_funds = {
        k[0] for k in paired if k[1] == "shares" and k[0] in FUNDS
    }
    missing_evening = [f for f in FUNDS if f not in evening_share_funds]
    missing_morning = [f for f in FUNDS if f not in morning_share_funds]
    missing_paired = [f for f in FUNDS if f not in paired_share_funds]
    if mode == "field":
        if missing_paired:
            outcome = PENDING if (missing_evening or missing_morning) else FAIL
            results.append(
                (
                    "four_fund_shares_paired",
                    outcome,
                    f"paired_share_funds={sorted(paired_share_funds)}; missing={missing_paired}",
                )
            )
        else:
            results.append(
                (
                    "four_fund_shares_paired",
                    PASS,
                    f"all four funds have evening→morning shares pairing: {list(FUNDS)}",
                )
            )
    else:
        results.append(
            (
                "four_fund_shares_paired",
                INFO,
                f"fixture mode skips hard four-fund gate; paired={sorted(paired_share_funds)}",
            )
        )

    # ---- Wall clocks: evening ≥15:00 data-day; morning ≥08:00 next natural day ----
    def _clock_check(rows, floor, label, expect_date):
        ok = True
        notes: list[str] = []
        for row in rows:
            # Prefer network_fetched_at; never promote cache_accessed_at to source time.
            stamp = row["network_fetched_at"] or row["fetched_at"] or ""
            when = _parse_stamp(stamp)
            if when is None:
                ok = False
                notes.append(f"{row['fund_code']}:{row['series']} bad/missing stamp={stamp!r}")
                continue
            if row["cache_accessed_at"]:
                cache_when = _parse_stamp(row["cache_accessed_at"])
                # Source time must remain network/fetched, not cache access.
                if cache_when and when == cache_when and row["network_fetched_at"] is None:
                    ok = False
                    notes.append(f"{row['fund_code']}: cache_accessed promoted to source time")
            if when.date() != expect_date or when < floor:
                ok = False
                notes.append(f"{row['fund_code']}:{row['series']}@{stamp}")
        return ok, notes

    e_ok, e_notes = _clock_check(evening_rows, evening_floor, "evening", day)
    if evening_rows:
        results.append(
            (
                "evening_after_1500_data_day",
                PASS if e_ok else FAIL,
                "; ".join(e_notes) if e_notes else "all evening network/fetched_at on data-day ≥15:00",
            )
        )
    else:
        results.append(("evening_after_1500_data_day", PENDING if mode == "field" else FAIL, "no evening rows"))

    m_ok, m_notes = _clock_check(morning_rows, next_morning_floor, "morning", day + timedelta(days=1))
    if morning_rows:
        results.append(
            (
                "morning_after_0800_next_natural_day",
                PASS if m_ok else FAIL,
                "; ".join(m_notes) if m_notes else "all morning network/fetched_at on next natural day ≥08:00",
            )
        )
    else:
        results.append(
            ("morning_after_0800_next_natural_day", PENDING if mode == "field" else FAIL, "no morning rows")
        )

    # ---- Raw response linkage + checkpoints (existence ≠ match) ----
    raw_n = int(conn.execute("SELECT COUNT(*) AS n FROM raw_fetches").fetchone()["n"])
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
    cp_by_key = {(r["source_name"], r["checkpoint_key"]): r for r in cps}

    linked = []
    mismatched = []
    unlinked = []
    for row in list(evening_rows) + list(morning_rows):
        rid = row["raw_fetch_id"]
        label = f"{row['fund_code']}:{row['snapshot_phase']}:{row['series']}"
        if rid is None:
            unlinked.append(label)
            continue
        raw = conn.execute("SELECT * FROM raw_fetches WHERE id = ?", (rid,)).fetchone()
        if raw is None:
            unlinked.append(f"{label}: missing raw id {rid}")
            continue
        # Match: source, success status, and network time aligned with phase wall-clock rules.
        if raw["source_name"] != row["source_name"]:
            mismatched.append(f"{label}: raw source={raw['source_name']} != version source={row['source_name']}")
            continue
        if raw["http_status"] != 200 or raw["error"] is not None:
            mismatched.append(
                f"{label}: raw http={raw['http_status']} error={raw['error']!r} (not a success body)"
            )
            continue
        raw_net = _parse_stamp(raw["network_fetched_at"] or raw["fetched_at"])
        ver_net = _parse_stamp(row["network_fetched_at"] or row["fetched_at"])
        if row["snapshot_phase"] == "evening":
            if raw_net is None or raw_net.date() != day or raw_net < evening_floor:
                mismatched.append(f"{label}: raw network time {raw['network_fetched_at']!r} not evening≥15:00")
                continue
        elif row["snapshot_phase"] == "morning":
            if raw_net is None or raw_net.date() != day + timedelta(days=1) or raw_net < next_morning_floor:
                mismatched.append(
                    f"{label}: raw network time {raw['network_fetched_at']!r} not next-morning≥08:00"
                )
                continue
        if ver_net and raw_net and ver_net != raw_net and not row["cache_accessed_at"]:
            # Version source time should track the linked raw network time when not a cache access.
            mismatched.append(
                f"{label}: version network={row['network_fetched_at']!r} != raw network={raw['network_fetched_at']!r}"
            )
            continue
        linked.append(rid)

    # Phase-matched checkpoints: need evening AND morning keys for share sources when phases present.
    share_sources = sorted(
        {
            r["source_name"]
            for r in list(evening_rows) + list(morning_rows)
            if r["series"] == "shares"
        }
    )
    cp_mismatch = []
    for source in share_sources:
        for phase, present in (("evening", bool(evening_rows)), ("morning", bool(morning_rows))):
            if not present:
                continue
            # checkpoint_key form: start:end:phase — accept any key containing data_day and ending with :phase
            matches = [
                r
                for r in cps
                if r["source_name"] == source
                and r["checkpoint_key"].endswith(f":{phase}")
                and data_day in r["checkpoint_key"]
            ]
            if not matches:
                cp_mismatch.append(f"missing {source} checkpoint for phase={phase}")

    if mode == "field":
        if raw_n == 0 or not cps:
            results.append(
                (
                    "raw_and_checkpoints_present",
                    FAIL,
                    f"field mode requires raw_fetches and checkpoints; raw={raw_n} checkpoints={len(cps)} "
                    "(fixture/unit path must use --mode fixture, not field)",
                )
            )
        elif cp_mismatch:
            results.append(
                (
                    "raw_and_checkpoints_present",
                    FAIL,
                    f"checkpoints exist but phase-match failed: {cp_mismatch}; "
                    f"raw={raw_n} checkpoints={len(cps)}",
                )
            )
        else:
            results.append(
                (
                    "raw_and_checkpoints_present",
                    PASS,
                    f"raw_fetches={raw_n} checkpoints={len(cps)} statuses={sorted(statuses)} "
                    f"phase-matched sources={share_sources}",
                )
            )
        if (evening_rows or morning_rows) and (unlinked or mismatched):
            results.append(
                (
                    "raw_fetch_linkage",
                    FAIL,
                    f"unlinked={unlinked[:6]} mismatched={mismatched[:6]}",
                )
            )
        elif evening_rows or morning_rows:
            results.append(
                (
                    "raw_fetch_linkage",
                    PASS,
                    f"linked raw ids={sorted(set(linked))} (source/time/success matched)",
                )
            )
        else:
            results.append(("raw_fetch_linkage", PENDING, "no versions to link"))
    else:
        results.append(
            (
                "raw_and_checkpoints_present",
                INFO,
                f"fixture mode: raw={raw_n} checkpoints={len(cps)} (not field evidence)",
            )
        )
        results.append(
            (
                "raw_fetch_linkage",
                INFO,
                f"fixture mode: linked={len(linked)} unlinked={len(unlinked)} mismatched={len(mismatched)}",
            )
        )

    if statuses & {"waiting_update", "complete", "incomplete"}:
        results.append(
            (
                "checkpoint_status_vocabulary",
                PASS,
                f"seen {sorted(statuses & {'waiting_update', 'incomplete', 'complete'})}",
            )
        )

    # ---- Missing ≠ 0 ----
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
            PASS if int(zeroish) == 0 else FAIL,
            f"zero-like share versions={zeroish}",
        )
    )

    # ---- 510310 jump isolation: evening snapshot vs morning status, NOT current authoritative ----
    # Joining observations.authoritative conflates later morning recovery with evening jump.
    BLOCKING = {"abnormal_jump", "suspect_split_or_merge"}
    jump_evening = conn.execute(
        """
        SELECT v.quality_status, v.quality_flags, v.version_no, v.observation_id
        FROM observation_versions v
        WHERE v.as_of_date = ? AND v.fund_code = '510310' AND v.series = 'shares'
          AND v.snapshot_phase = 'evening'
        ORDER BY v.version_no DESC
        LIMIT 1
        """,
        (data_day,),
    ).fetchone()
    jump_morning = conn.execute(
        """
        SELECT v.quality_status, v.quality_flags, v.version_no, v.observation_id
        FROM observation_versions v
        WHERE v.as_of_date = ? AND v.fund_code = '510310' AND v.series = 'shares'
          AND v.snapshot_phase = 'morning'
        ORDER BY v.version_no DESC
        LIMIT 1
        """,
        (data_day,),
    ).fetchone()
    current_auth = None
    if jump_evening is not None:
        auth_row = conn.execute(
            "SELECT authoritative FROM observations WHERE id = ?",
            (jump_evening["observation_id"],),
        ).fetchone()
        current_auth = int(auth_row["authoritative"]) if auth_row else None
    prior = conn.execute(
        """
        SELECT quality_status FROM observation_versions
        WHERE fund_code = '510310' AND series = 'shares' AND as_of_date < ?
        ORDER BY as_of_date DESC, version_no DESC
        LIMIT 1
        """,
        (data_day,),
    ).fetchone()

    if jump_evening is None:
        results.append(
            (
                "510310_jump_isolation",
                PENDING,
                "uncovered/undecidable: no evening 510310 shares row for this data-day",
            )
        )
    else:
        e_flags = _parse_flags(jump_evening["quality_flags"])
        e_status = jump_evening["quality_status"]
        m_status = jump_morning["quality_status"] if jump_morning else None
        m_flags = _parse_flags(jump_morning["quality_flags"]) if jump_morning else []
        # Evening blocking statuses are valid isolation; do NOT require current auth==0
        # (morning revision may restore auth=1 while evening version stays abnormal_jump).
        if e_status in BLOCKING:
            results.append(
                (
                    "510310_jump_isolation",
                    PASS,
                    f"evening primary={e_status} flags={e_flags}; "
                    f"morning={m_status}; current_auth={current_auth} "
                    f"(evening snapshot independent of later authoritative)",
                )
            )
        elif "no_adjacent_share" in e_flags or prior is None:
            results.append(
                (
                    "510310_jump_isolation",
                    PENDING,
                    "uncovered/undecidable: missing prior-day base for jump check; "
                    f"evening={e_status} flags={e_flags}",
                )
            )
        elif e_status == "provisional_evening":
            results.append(
                (
                    "510310_jump_isolation",
                    PASS,
                    f"evening no blocking jump (status={e_status}); morning={m_status}",
                )
            )
        else:
            results.append(
                (
                    "510310_jump_isolation",
                    PASS,
                    f"evening={e_status} flags={e_flags}; morning={m_status}",
                )
            )

        # Reverse leak: morning blocking status must not sit under authoritative=1.
        if jump_morning is not None and m_status in BLOCKING and current_auth == 1:
            results.append(
                (
                    "510310_morning_blocking_vs_authoritative",
                    FAIL,
                    f"morning primary={m_status} flags={m_flags} but observations.authoritative=1",
                )
            )
        elif jump_morning is not None and m_status in BLOCKING:
            results.append(
                (
                    "510310_morning_blocking_vs_authoritative",
                    PASS,
                    f"morning primary={m_status} with authoritative={current_auth}",
                )
            )

    # Evening shares that are NOT blocking (abnormal_jump OR suspect_split_or_merge)
    # should be provisional_evening primary. Unify with BLOCKING used above — do not
    # only exempt abnormal_jump (that false-fails legitimate split/merge isolation).
    non_blocking_evening_shares = [
        r
        for r in evening_rows
        if r["series"] == "shares" and r["quality_status"] not in BLOCKING
    ]
    if non_blocking_evening_shares:
        provisional_ok = all(
            r["quality_status"] == "provisional_evening" for r in non_blocking_evening_shares
        )
        results.append(
            (
                "evening_shares_provisional_when_not_blocking",
                PASS if provisional_ok else FAIL,
                f"non-blocking evening share versions={len(non_blocking_evening_shares)}; "
                f"all provisional_evening → {provisional_ok}; "
                f"BLOCKING={sorted(BLOCKING)}",
            )
        )

    # Cache must not redefine source time on versions.
    cache_promotions = conn.execute(
        """
        SELECT fund_code, series, snapshot_phase, network_fetched_at, cache_accessed_at, fetched_at
        FROM observation_versions
        WHERE as_of_date = ?
          AND cache_accessed_at IS NOT NULL
          AND network_fetched_at IS NOT NULL
          AND cache_accessed_at = fetched_at
          AND cache_accessed_at != network_fetched_at
        """,
        (data_day,),
    ).fetchall()
    results.append(
        (
            "cache_access_not_promoted_to_source_time",
            PASS if not cache_promotions else FAIL,
            f"suspect rows={len(cache_promotions)}",
        )
    )

    return results


def summarize(results: list[tuple[str, str, str]]) -> tuple[int, int, int]:
    failed = sum(1 for _, o, _ in results if o == FAIL)
    pending = sum(1 for _, o, _ in results if o == PENDING)
    passed = sum(1 for _, o, _ in results if o == PASS)
    return passed, failed, pending


def exit_code_for(mode: str, failed: int, pending: int) -> int:
    if failed:
        return 1
    if pending:
        return 3
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--data-day", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--mode",
        choices=("field", "fixture"),
        default="field",
        help="field=live evidence gate; fixture=unit structural checks (not field evidence)",
    )
    args = parser.parse_args(argv)
    if not args.db.is_file():
        print(f"DB missing: {args.db}", file=sys.stderr)
        return 2
    conn = _connect(args.db)
    try:
        results = check_pair(conn, args.data_day, mode=args.mode)
    finally:
        conn.close()
    for name, outcome, detail in results:
        print(f"{outcome}\t{name}\t{detail}")
    passed, failed, pending = summarize(results)
    print(f"summary\tpassed={passed}\tfailed={failed}\tpending={pending}\tmode={args.mode}")
    code = exit_code_for(args.mode, failed, pending)
    if code == 0 and args.mode == "fixture":
        print("note\tfixture_mode_pass_is_not_field_evidence")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
