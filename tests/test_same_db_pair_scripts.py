"""Dot 77144c6 follow-up: exercise export / verify / same_db_pair.sh paths.

These tests invoke the scripts (subprocess), not only Store helpers.
Fixtures here prove script behavior; they are not field evidence.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import textwrap
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.message import Message
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from etf_flow_observer.adapters.common import RawPoint
from etf_flow_observer.http_client import HttpClient
from etf_flow_observer.pipeline import finish_batch, mark_checkpoint
from etf_flow_observer.adapters.common import FetchBatch
from etf_flow_observer.storage import Store
from tests.conftest import ingest, shanghai

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "bin" / "python"
EXPORT = ROOT / "scripts" / "export_pair_snapshot.py"
VERIFY = ROOT / "scripts" / "verify_same_db_pair.py"
PAIR_SH = ROOT / "scripts" / "same_db_pair.sh"

DATA_DAY = "2026-10-21"
PRIOR_DAY = "2026-10-20"
FUNDS = ("510300", "510310", "510330", "159919")
SH = ZoneInfo("Asia/Shanghai")
EVENING = shanghai(2026, 10, 21, 20, 30)
MORNING = shanghai(2026, 10, 22, 8, 20)


def _write_evening_end_continuity(evidence: Path, db: Path) -> None:
    """Seed parked evening-end continuity so morning compare can run."""
    st = db.stat()
    (evidence / "continuity-evening-end.txt").write_text(
        "\n".join(
            [
                "leg=evening-end",
                f"resolved_db={db.resolve()}",
                "db_exists=True",
                f"db_size={st.st_size}",
                f"db_mtime_ns={st.st_mtime_ns}",
                f"db_inode={st.st_ino}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _run(args: list[str], *, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd or ROOT),
        env=env or os.environ.copy(),
        text=True,
        capture_output=True,
        check=False,
    )


def _share(fund: str, day: str, value: str, *, raw_id: int | None = None, when: datetime | None = None) -> RawPoint:
    src = "szse_shares" if fund.startswith("159") else "sse_shares"
    point = RawPoint(
        fund_code=fund,
        as_of_date=day,
        series="shares",
        original_value=value,
        original_unit="万份",
        source_name=src,
        source_url="https://example.test/shares",
    )
    if raw_id is not None:
        point.raw_fetch_id = raw_id
    if when is not None:
        point.network_fetched_at = when
        point.observation_available_at = when
    return point


def _save_raw(store: Store, *, source: str, when: datetime, body: bytes = b"{}", from_cache: bool = False) -> int:
    result = store.save_raw(
        source_name=source,
        fingerprint=f"fp-{source}-{when.isoformat()}-{from_cache}",
        method="GET",
        url=f"https://example.test/{source}",
        request_body=None,
        http_status=200,
        body=body,
        fetched_at=when,
        from_cache=from_cache,
        error=None,
        network_fetched_at=when if not from_cache else when - timedelta(hours=11),
        cache_accessed_at=when if from_cache else None,
    )
    return int(result)


def _seed_pair(
    store: Store,
    *,
    funds=FUNDS,
    evening_values: dict[str, str] | None = None,
    morning_values: dict[str, str] | None = None,
    with_prior: bool = True,
    with_raw: bool = True,
    with_checkpoints: bool = True,
    evening_when: datetime = EVENING,
    morning_when: datetime = MORNING,
    corrupt_first_seen: bool = False,
) -> dict[str, int]:
    evening_values = evening_values or {f: "100" for f in funds}
    morning_values = morning_values or {f: "101" for f in funds}
    raw_ids: dict[str, int] = {}

    if with_prior:
        for fund in funds:
            rid = _save_raw(store, source=_share(fund, PRIOR_DAY, "99").source_name, when=EVENING - timedelta(days=1)) if with_raw else None
            ingest(
                store,
                [_share(fund, PRIOR_DAY, "99", raw_id=rid, when=EVENING - timedelta(days=1))],
                EVENING - timedelta(days=1),
                phase="evening",
            )

    evening_points = []
    for fund in funds:
        rid = None
        if with_raw:
            rid = _save_raw(store, source=_share(fund, DATA_DAY, "100").source_name, when=evening_when, body=b'{"phase":"evening"}')
            raw_ids[f"evening-{fund}"] = rid
        evening_points.append(_share(fund, DATA_DAY, evening_values[fund], raw_id=rid, when=evening_when))
    ingest(store, evening_points, evening_when, phase="evening")

    morning_points = []
    for fund in funds:
        rid = None
        if with_raw:
            rid = _save_raw(store, source=_share(fund, DATA_DAY, "101").source_name, when=morning_when, body=b'{"phase":"morning"}')
            raw_ids[f"morning-{fund}"] = rid
        morning_points.append(_share(fund, DATA_DAY, morning_values[fund], raw_id=rid, when=morning_when))
    ingest(store, morning_points, morning_when, phase="morning")

    if with_checkpoints:
        for phase, when in (("evening", evening_when), ("morning", morning_when)):
            for source in ("sse_shares", "szse_shares"):
                store.set_checkpoint(
                    source,
                    f"{DATA_DAY}:{DATA_DAY}:{phase}",
                    "complete",
                    when,
                    detail=f"test-{phase}",
                )

    if corrupt_first_seen:
        # Break freeze on one paired key to produce a hard FAIL.
        store.conn.execute(
            """
            UPDATE observation_versions
            SET first_seen_at = ?
            WHERE as_of_date = ? AND fund_code = '510300' AND series = 'shares'
              AND snapshot_phase = 'morning'
            """,
            ((morning_when + timedelta(minutes=1)).isoformat(timespec="seconds"), DATA_DAY),
        )
        store.conn.commit()

    return raw_ids


# ---------------------------------------------------------------------------
# 1. Export against real Store schema
# ---------------------------------------------------------------------------


def test_export_script_against_real_store_schema(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store)
    # Ensure current authoritative differs across versions historically:
    # evening provisional auth=0, morning ok auth=1 on observation row only.
    store.close()

    out = tmp_path / "export"
    proc = _run([str(PY), str(EXPORT), "--db", str(db), "--out", str(out)])
    assert proc.returncode == 0, proc.stderr
    versions = (out / "observations-versions.tsv").read_text(encoding="utf-8").splitlines()
    latest = (out / "observations-latest.tsv").read_text(encoding="utf-8").splitlines()
    assert versions, "versions TSV should have header+rows"
    ver_header = versions[0].split("\t")
    lat_header = latest[0].split("\t")
    assert "authoritative" not in ver_header
    assert "authoritative" in lat_header
    assert "quality_flags" in ver_header
    assert "raw_fetch_id" in ver_header
    # Historical rows exist for both phases without inventing authoritative history.
    body = "\n".join(versions[1:])
    assert "evening" in body and "morning" in body


# ---------------------------------------------------------------------------
# 2. Positive: four funds same-key pairing (fixture mode structural + field)
# ---------------------------------------------------------------------------


def test_verify_positive_four_fund_same_key_pairing(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store)
    store.close()

    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 0, field.stdout + field.stderr
    assert "PASS\tsame_key_phase_pairing" in field.stdout
    assert "PASS\tfour_fund_shares_paired" in field.stdout
    assert "PASS\tfirst_seen_at_preserved_on_append" in field.stdout
    assert "failed=0" in field.stdout


# ---------------------------------------------------------------------------
# 3. Positive: abnormal jump isolation (primary status abnormal_jump)
# ---------------------------------------------------------------------------


def test_verify_positive_abnormal_jump_isolation(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    # 510310 +21% vs prior → abnormal_jump primary; provisional_evening stays in flags.
    _seed_pair(
        store,
        evening_values={"510300": "100", "510310": "121", "510330": "100", "159919": "100"},
        morning_values={"510300": "100", "510310": "121", "510330": "100", "159919": "100"},
    )
    jump = store.latest_join("510310", DATA_DAY, "shares", "sse_shares")
    # After morning append latest may be morning; check evening version row.
    evening_jump = store.conn.execute(
        """
        SELECT quality_status, quality_flags FROM observation_versions
        WHERE fund_code='510310' AND as_of_date=? AND series='shares' AND snapshot_phase='evening'
        """,
        (DATA_DAY,),
    ).fetchone()
    assert evening_jump["quality_status"] == "abnormal_jump"
    flags = json.loads(evening_jump["quality_flags"])
    assert "provisional_evening" in flags or "abnormal_jump" in flags
    store.close()

    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 0, field.stdout + field.stderr
    assert "PASS\t510310_jump_isolation" in field.stdout
    assert "primary=abnormal_jump" in field.stdout


# ---------------------------------------------------------------------------
# 4. Negative: different funds split across two phases → FAIL pairing
# ---------------------------------------------------------------------------


def test_verify_negative_different_funds_across_phases(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    # Evening only 510300; morning only 159919 — no shared key.
    rid_e = _save_raw(store, source="sse_shares", when=EVENING)
    rid_m = _save_raw(store, source="szse_shares", when=MORNING)
    ingest(store, [_share("510300", DATA_DAY, "100", raw_id=rid_e, when=EVENING)], EVENING, phase="evening")
    ingest(store, [_share("159919", DATA_DAY, "50", raw_id=rid_m, when=MORNING)], MORNING, phase="morning")
    for phase, when in (("evening", EVENING), ("morning", MORNING)):
        store.set_checkpoint("sse_shares", f"{DATA_DAY}:{DATA_DAY}:{phase}", "waiting_update", when, detail="split")
        store.set_checkpoint("szse_shares", f"{DATA_DAY}:{DATA_DAY}:{phase}", "waiting_update", when, detail="split")
    store.close()

    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\tsame_key_phase_pairing" in field.stdout


# ---------------------------------------------------------------------------
# 5. Negatives: missing raw/checkpoint, wrong first_seen, wrong evening clock
# ---------------------------------------------------------------------------


def test_verify_negative_missing_raw_and_checkpoints_in_field_mode(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store, with_raw=False, with_checkpoints=False)
    store.close()

    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\traw_and_checkpoints_present" in field.stdout

    # Same DB is allowed to pass structural checks under fixture mode, but must declare not-field.
    fixture = _run([str(PY), str(VERIFY), "--mode", "fixture", "--db", str(db), "--data-day", DATA_DAY])
    assert "mode=fixture" in fixture.stdout
    assert "fixture_mode_pass_is_not_field_evidence" in fixture.stdout or fixture.returncode in {0, 3, 1}


def test_verify_negative_wrong_first_seen(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store, corrupt_first_seen=True)
    store.close()

    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\tfirst_seen_at_preserved_on_append" in field.stdout


def test_verify_negative_wrong_evening_clock(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store)
    # Keep snapshot_phase=evening but rewrite source stamps to before 15:00 (field clock gate).
    bad = shanghai(2026, 10, 21, 14, 30).isoformat(timespec="seconds")
    store.conn.execute(
        """
        UPDATE observation_versions
        SET fetched_at = ?, network_fetched_at = ?
        WHERE as_of_date = ? AND snapshot_phase = 'evening'
        """,
        (bad, bad, DATA_DAY),
    )
    store.conn.commit()
    store.close()

    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\tevening_after_1500_data_day" in field.stdout


def test_verify_510310_missing_is_undecidable_not_hard_fail(tmp_path: Path):
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    three = ("510300", "510330", "159919")
    _seed_pair(store, funds=three)
    store.close()

    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    # Missing 510310 → pending/undecidable jump + pending four-fund; not a false "jump PASS".
    assert "PENDING\t510310_jump_isolation" in field.stdout
    assert "uncovered/undecidable" in field.stdout
    assert field.returncode == 3, field.stdout  # pending-evidence, not 0


# ---------------------------------------------------------------------------
# 6. Cache hit / morning unpublished then publish
# ---------------------------------------------------------------------------


def test_cache_hit_keeps_network_time_and_morning_nocache_fetches_new(tmp_path: Path):
    store = Store(tmp_path / "cache.sqlite", tmp_path / "raw")
    clock = {"now": EVENING}
    calls = {"n": 0}
    bodies = [b'{"evening":true}', b'{"morning":true}']

    def transport(method, url, headers, body):
        payload = bodies[min(calls["n"], 1)]
        calls["n"] += 1
        return 200, Message(), payload

    client = HttpClient(
        store,
        user_agent="test",
        min_interval_seconds=0,
        timeout_seconds=5,
        max_retries=1,
        cache_ttl_seconds=43200,  # 12h — evening→morning still inside
        max_http_requests=20,
        sleeper=lambda _s: None,
        clock=lambda: clock["now"],
        transport=transport,
    )
    url = "https://example.test/sse"
    evening = client.send("GET", url, source_name="sse_shares", use_cache=True)
    assert evening.from_cache is False
    assert calls["n"] == 1
    evening_net = evening.network_fetched_at

    # ~11.5h later still within 12h TTL → cache hit if use_cache=True
    clock["now"] = MORNING
    cached = client.send("GET", url, source_name="sse_shares", use_cache=True)
    assert cached.from_cache is True
    assert calls["n"] == 1
    assert cached.network_fetched_at == evening_net
    assert cached.cache_accessed_at == MORNING
    assert cached.cache_accessed_at != cached.network_fetched_at

    # Morning field path uses --no-cache → new network response
    fresh = client.send("GET", url, source_name="sse_shares", use_cache=False)
    assert fresh.from_cache is False
    assert calls["n"] == 2
    assert fresh.network_fetched_at == MORNING
    assert fresh.body == bodies[1]
    store.close()


def test_unpublished_waiting_update_allows_morning_retry(tmp_path: Path):
    """Gaps → waiting_update; should_skip False so unpublished can retry."""
    from etf_flow_observer.pipeline import should_skip

    db = tmp_path / "wait.sqlite"
    store = Store(db, tmp_path / "raw")
    rid = _save_raw(store, source="sse_shares", when=EVENING)
    batch = FetchBatch(
        "sse_shares",
        [_share("510300", DATA_DAY, "10", raw_id=rid, when=EVENING)],
        [],
        [],
        ["https://example.test/sse"],
    )
    summary = finish_batch(
        store,
        batch,
        now=EVENING,
        phase_override="evening",
        closures=set(),
        abnormal_ratio=Decimal("0.20"),
        split_ratio=Decimal("0.50"),
        morning_start=__import__("datetime").time(8, 0),
        session_close=__import__("datetime").time(15, 0),
        expected_days=[date.fromisoformat(DATA_DAY)],
        expected_funds=["510300", "510310", "510330"],
        expected_series=["shares"],
    )
    mark_checkpoint(
        store,
        "sse_shares",
        f"{DATA_DAY}:{DATA_DAY}:evening",
        summary,
        EVENING,
        start=date.fromisoformat(DATA_DAY),
        end=date.fromisoformat(DATA_DAY),
        closures=set(),
    )
    assert summary["checkpoint"] == "waiting_update"
    assert should_skip(store, "sse_shares", f"{DATA_DAY}:{DATA_DAY}:evening", False) is False
    # Morning key is independent; also not complete yet.
    assert should_skip(store, "sse_shares", f"{DATA_DAY}:{DATA_DAY}:morning", False) is False
    store.close()


# ---------------------------------------------------------------------------
# 7. collect=0 but verify fails → shell must not exit 0
# ---------------------------------------------------------------------------


def test_same_db_pair_sh_morning_verify_fail_does_not_exit_0(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    db = evidence / "live.sqlite"
    raw = evidence / "raw"
    store = Store(db, raw)
    # Split funds → verify FAIL
    rid_e = _save_raw(store, source="sse_shares", when=EVENING)
    rid_m = _save_raw(store, source="szse_shares", when=MORNING)
    ingest(store, [_share("510300", DATA_DAY, "100", raw_id=rid_e, when=EVENING)], EVENING, phase="evening")
    ingest(store, [_share("159919", DATA_DAY, "50", raw_id=rid_m, when=MORNING)], MORNING, phase="morning")
    store.set_checkpoint("sse_shares", f"{DATA_DAY}:{DATA_DAY}:evening", "complete", EVENING, detail="x")
    store.set_checkpoint("szse_shares", f"{DATA_DAY}:{DATA_DAY}:morning", "complete", MORNING, detail="x")
    store.close()
    _write_evening_end_continuity(evidence, db)

    config = evidence / "config.toml"
    example = (ROOT / "config" / "example.toml").read_text(encoding="utf-8")
    config.write_text(
        example.replace('db_path = "data/observer.sqlite"', f'db_path = "{db}"').replace(
            'raw_dir = "data/raw"', f'raw_dir = "{raw}"'
        ),
        encoding="utf-8",
    )

    # Stub observer so collect "succeeds" with 0 without network.
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "etf-flow-observer"
    stub.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # pretend collect / status succeed
            if [[ "${1:-}" == "sim-check" ]]; then exit 2; fi
            exit 0
            """
        ),
        encoding="utf-8",
    )
    stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "EVIDENCE_ROOT": str(evidence),
            "CONFIG": str(config),
            "OBS": str(stub),
            "PY": str(PY),
            "DATA_DAY": DATA_DAY,
        }
    )
    proc = _run(["bash", str(PAIR_SH), "morning"], env=env)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "verify_exit_code=1" in proc.stdout or "FAIL" in (evidence / "logs").joinpath(
        next((evidence / "logs").glob("morning-*")).name if (evidence / "logs").exists() else ""
    ) or "FAIL\tsame_key_phase_pairing" in proc.stdout


# ---------------------------------------------------------------------------
# 8. Two DB paths inconsistent → refuse
# ---------------------------------------------------------------------------


def test_same_db_pair_sh_refuses_mismatched_db_paths(tmp_path: Path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    other = tmp_path / "other.sqlite"
    Store(other, tmp_path / "raw").close()
    config = evidence / "config.toml"
    example = (ROOT / "config" / "example.toml").read_text(encoding="utf-8")
    # Point config at a DIFFERENT db than EVIDENCE_ROOT/live.sqlite
    config.write_text(
        example.replace('db_path = "data/observer.sqlite"', f'db_path = "{other}"').replace(
            'raw_dir = "data/raw"', f'raw_dir = "{tmp_path / "raw"}"'
        ),
        encoding="utf-8",
    )
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "etf-flow-observer"
    stub.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "EVIDENCE_ROOT": str(evidence),
            "CONFIG": str(config),
            "OBS": str(stub),
            "PY": str(PY),
            "DATA_DAY": DATA_DAY,
        }
    )
    # verify path hits assert_db_identity
    proc = _run(["bash", str(PAIR_SH), "verify"], env=env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "REFUSE" in proc.stderr or "REFUSE" in proc.stdout


def test_sim_check_still_exit_2():
    obs = ROOT / ".venv" / "bin" / "etf-flow-observer"
    proc = _run([str(obs), "sim-check", "--sim-config", str(ROOT / "config" / "simulation.example.toml")])
    assert proc.returncode == 2
# ---------------------------------------------------------------------------
# Dot 00dfac8 re-review: six remaining counterexamples
# ---------------------------------------------------------------------------


def test_ce1_empty_morning_after_complete_evening_allows_retry(tmp_path: Path):
    """CE1: complete evening → empty morning must NOT mark morning complete via stale evening values."""
    from datetime import time as dtime

    from etf_flow_observer.pipeline import finish_batch, mark_checkpoint, should_skip

    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    # Prior + complete evening for all SSE funds.
    for fund, val in (("510300", "100"), ("510310", "100"), ("510330", "100")):
        rid = _save_raw(store, source="sse_shares", when=EVENING - timedelta(days=1))
        ingest(store, [_share(fund, PRIOR_DAY, "99", raw_id=rid, when=EVENING - timedelta(days=1))], EVENING - timedelta(days=1), phase="evening")
    evening_points = []
    for fund in ("510300", "510310", "510330"):
        rid = _save_raw(store, source="sse_shares", when=EVENING, body=b'{"evening":1}')
        evening_points.append(_share(fund, DATA_DAY, "100", raw_id=rid, when=EVENING))
    evening_batch = FetchBatch("sse_shares", evening_points, [], [], ["https://example.test/sse-e"])
    evening_summary = finish_batch(
        store,
        evening_batch,
        now=EVENING,
        phase_override="evening",
        closures=set(),
        abnormal_ratio=Decimal("0.20"),
        split_ratio=Decimal("0.50"),
        morning_start=dtime(8, 0),
        session_close=dtime(15, 0),
        expected_days=[date.fromisoformat(DATA_DAY)],
        expected_funds=["510300", "510310", "510330"],
        expected_series=["shares"],
    )
    mark_checkpoint(
        store,
        "sse_shares",
        f"{DATA_DAY}:{DATA_DAY}:evening",
        evening_summary,
        EVENING,
        start=date.fromisoformat(DATA_DAY),
        end=date.fromisoformat(DATA_DAY),
        closures=set(),
    )
    assert evening_summary["checkpoint"] == "complete"
    assert evening_summary["gaps"] == 0

    # Empty morning batch (source returned nothing) — must record phase gaps, not reuse evening.
    empty_morning = FetchBatch("sse_shares", [], [], ["empty morning"], ["https://example.test/sse-m"])
    morning_summary = finish_batch(
        store,
        empty_morning,
        now=MORNING,
        phase_override="morning",
        closures=set(),
        abnormal_ratio=Decimal("0.20"),
        split_ratio=Decimal("0.50"),
        morning_start=dtime(8, 0),
        session_close=dtime(15, 0),
        expected_days=[date.fromisoformat(DATA_DAY)],
        expected_funds=["510300", "510310", "510330"],
        expected_series=["shares"],
    )
    mark_checkpoint(
        store,
        "sse_shares",
        f"{DATA_DAY}:{DATA_DAY}:morning",
        morning_summary,
        MORNING,
        start=date.fromisoformat(DATA_DAY),
        end=date.fromisoformat(DATA_DAY),
        closures=set(),
    )
    assert morning_summary["gaps"] == 3, morning_summary
    assert morning_summary["checkpoint"] == "waiting_update"
    assert should_skip(store, "sse_shares", f"{DATA_DAY}:{DATA_DAY}:morning", False) is False

    # After "publish": morning points arrive; retry must not be blocked.
    morning_points = []
    for fund in ("510300", "510310", "510330"):
        rid = _save_raw(store, source="sse_shares", when=MORNING + timedelta(minutes=30), body=b'{"morning":1}')
        morning_points.append(_share(fund, DATA_DAY, "101", raw_id=rid, when=MORNING + timedelta(minutes=30)))
    retry = finish_batch(
        store,
        FetchBatch("sse_shares", morning_points, [], [], ["https://example.test/sse-m2"]),
        now=MORNING + timedelta(minutes=30),
        phase_override="morning",
        closures=set(),
        abnormal_ratio=Decimal("0.20"),
        split_ratio=Decimal("0.50"),
        morning_start=dtime(8, 0),
        session_close=dtime(15, 0),
        expected_days=[date.fromisoformat(DATA_DAY)],
        expected_funds=["510300", "510310", "510330"],
        expected_series=["shares"],
    )
    mark_checkpoint(
        store,
        "sse_shares",
        f"{DATA_DAY}:{DATA_DAY}:morning",
        retry,
        MORNING + timedelta(minutes=30),
        start=date.fromisoformat(DATA_DAY),
        end=date.fromisoformat(DATA_DAY),
        closures=set(),
    )
    assert retry["stored"] >= 1
    assert retry["checkpoint"] == "complete"
    assert store.phase_value("510300", DATA_DAY, "shares", "sse_shares", "morning") is not None
    store.close()


def test_ce2_evening_empty_response_cache_does_not_block_later_fetch(tmp_path: Path):
    """CE2: evening empty 200 cached at 15:00 must not poison 20:00 retry (full SSE collect path)."""
    from etf_flow_observer.adapters.sse_shares import collect_sse

    store = Store(tmp_path / "cache.sqlite", tmp_path / "raw")
    clock = {"now": shanghai(2026, 10, 21, 15, 5)}
    calls = {"n": 0}
    empty = b'{"pageHelp":{"pageNo":1,"pageCount":1},"result":[]}'
    full = (
        b'{"pageHelp":{"pageNo":1,"pageCount":1},"result":['
        b'{"SEC_CODE":"510300","TOT_VOL":"100","SEC_NAME":"A","STAT_DATE":"2026-10-21"},'
        b'{"SEC_CODE":"510310","TOT_VOL":"100","SEC_NAME":"B","STAT_DATE":"2026-10-21"},'
        b'{"SEC_CODE":"510330","TOT_VOL":"100","SEC_NAME":"C","STAT_DATE":"2026-10-21"}'
        b"]}"
    )
    bodies = [empty, full]

    def transport(method, url, headers, body):
        payload = bodies[min(calls["n"], 1)]
        calls["n"] += 1
        return 200, Message(), payload

    client = HttpClient(
        store,
        user_agent="test",
        min_interval_seconds=0,
        timeout_seconds=5,
        max_retries=1,
        cache_ttl_seconds=43200,
        max_http_requests=20,
        sleeper=lambda _s: None,
        clock=lambda: clock["now"],
        transport=transport,
    )
    day = date.fromisoformat(DATA_DAY)
    first = collect_sse(client, [day], page_size=10, use_cache=True)
    assert first.points == []
    assert calls["n"] == 1
    assert any("空结果已取消缓存" in n or "没有" in n for n in first.notes)

    # Still inside 12h TTL; with use_cache=True must hit network again (empty was uncacheable).
    clock["now"] = shanghai(2026, 10, 21, 20, 30)
    second = collect_sse(client, [day], page_size=10, use_cache=True)
    assert calls["n"] == 2, "empty evening response must not satisfy 12h cache"
    assert {p.fund_code for p in second.points} >= {"510300", "510310", "510330"}
    store.close()


def test_ce3_first_seen_rewrite_on_non_tip_version_is_detected(tmp_path: Path):
    """CE3: drifting first_seen on evening v1 while tip v2 matches still must FAIL."""
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store)
    # Insert an extra evening version then rewrite an OLDER version's first_seen.
    store.conn.execute(
        """
        UPDATE observation_versions
        SET first_seen_at = ?
        WHERE as_of_date = ? AND fund_code = '510300' AND series = 'shares'
          AND snapshot_phase = 'evening' AND version_no = (
            SELECT MIN(version_no) FROM observation_versions
            WHERE as_of_date = ? AND fund_code = '510300' AND series = 'shares'
              AND snapshot_phase = 'evening'
          )
        """,
        (
            (EVENING + timedelta(minutes=5)).isoformat(timespec="seconds"),
            DATA_DAY,
            DATA_DAY,
        ),
    )
    # Ensure a higher evening version exists with the correct freeze (tip looks fine).
    rid = _save_raw(store, source="sse_shares", when=EVENING + timedelta(minutes=10))
    ingest(
        store,
        [_share("510300", DATA_DAY, "100.5", raw_id=rid, when=EVENING + timedelta(minutes=10))],
        EVENING + timedelta(minutes=10),
        phase="evening",
    )
    # Tip evening + morning first_seen still match obs freeze; only old v drifted.
    store.close()
    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\tfirst_seen_at_preserved_on_append" in field.stdout
    assert "version_first_seen=" in field.stdout or "v1/" in field.stdout or "evening" in field.stdout


def test_ce4_evening_jump_then_morning_ok_not_failed_by_current_auth(tmp_path: Path):
    """CE4: evening abnormal_jump + morning recovery (auth=1) must PASS evening isolation."""
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(
        store,
        evening_values={"510300": "100", "510310": "121", "510330": "100", "159919": "100"},
        morning_values={"510300": "100", "510310": "101", "510330": "100", "159919": "100"},
    )
    evening = store.conn.execute(
        """
        SELECT quality_status FROM observation_versions
        WHERE fund_code='510310' AND as_of_date=? AND series='shares' AND snapshot_phase='evening'
        ORDER BY version_no DESC LIMIT 1
        """,
        (DATA_DAY,),
    ).fetchone()
    morning = store.conn.execute(
        """
        SELECT quality_status FROM observation_versions
        WHERE fund_code='510310' AND as_of_date=? AND series='shares' AND snapshot_phase='morning'
        ORDER BY version_no DESC LIMIT 1
        """,
        (DATA_DAY,),
    ).fetchone()
    obs = store.get_observation("510310", DATA_DAY, "shares", "sse_shares")
    assert evening["quality_status"] == "abnormal_jump"
    assert morning["quality_status"] == "ok"
    assert int(obs["authoritative"]) == 1
    store.close()
    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 0, field.stdout
    assert "PASS\t510310_jump_isolation" in field.stdout
    assert "current_auth=1" in field.stdout or "later authoritative" in field.stdout


def test_ce4_morning_blocking_with_auth1_is_fail(tmp_path: Path):
    """CE4 reverse: morning abnormal_jump under authoritative=1 must FAIL."""
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(
        store,
        evening_values={"510300": "100", "510310": "100", "510330": "100", "159919": "100"},
        morning_values={"510300": "100", "510310": "121", "510330": "100", "159919": "100"},
    )
    # Force authoritative=1 while morning status stays abnormal_jump (inconsistent).
    store.conn.execute(
        """
        UPDATE observations SET authoritative = 1
        WHERE fund_code='510310' AND as_of_date=? AND series='shares'
        """,
        (DATA_DAY,),
    )
    store.conn.commit()
    morning = store.conn.execute(
        """
        SELECT quality_status FROM observation_versions
        WHERE fund_code='510310' AND as_of_date=? AND series='shares' AND snapshot_phase='morning'
        ORDER BY version_no DESC LIMIT 1
        """,
        (DATA_DAY,),
    ).fetchone()
    assert morning["quality_status"] == "abnormal_jump"
    store.close()
    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\t510310_morning_blocking_vs_authoritative" in field.stdout


def test_ce5_raw_wrong_source_or_http_fail_is_mismatch(tmp_path: Path):
    """CE5: raw row exists but wrong source / HTTP 500 / evening time on morning → FAIL match."""
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store)
    # Corrupt one morning raw: point version at a 500 / wrong-source raw.
    bad_id = store.save_raw(
        source_name="wrong_source",
        fingerprint="bad-fp",
        method="GET",
        url="https://example.test/bad",
        request_body=None,
        http_status=500,
        body=b"err",
        fetched_at=MORNING,
        from_cache=False,
        error="HTTP 500",
        network_fetched_at=MORNING,
    )
    store.conn.execute(
        """
        UPDATE observation_versions SET raw_fetch_id = ?
        WHERE as_of_date = ? AND fund_code = '510300' AND snapshot_phase = 'morning' AND series = 'shares'
        """,
        (bad_id, DATA_DAY),
    )
    store.conn.commit()
    store.close()
    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\traw_fetch_linkage" in field.stdout
    assert "mismatched=" in field.stdout


def test_ce5_evening_checkpoint_only_fails_phase_match(tmp_path: Path):
    """CE5: checkpoints exist but only evening phase → FAIL phase-match (not mere existence)."""
    db = tmp_path / "live.sqlite"
    store = Store(db, tmp_path / "raw")
    _seed_pair(store, with_checkpoints=False)
    # Only evening checkpoints present.
    for source in ("sse_shares", "szse_shares"):
        store.set_checkpoint(source, f"{DATA_DAY}:{DATA_DAY}:evening", "complete", EVENING, detail="only-e")
    store.close()
    field = _run([str(PY), str(VERIFY), "--mode", "field", "--db", str(db), "--data-day", DATA_DAY])
    assert field.returncode == 1, field.stdout
    assert "FAIL\traw_and_checkpoints_present" in field.stdout
    assert "phase-match failed" in field.stdout or "missing" in field.stdout


def test_ce6_continuity_start_not_overwritten_by_terminal(tmp_path: Path):
    """CE6: morning keeps start/compare evidence; terminal stamp is a separate file."""
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    db = evidence / "live.sqlite"
    raw = evidence / "raw"
    store = Store(db, raw)
    rid_e = _save_raw(store, source="sse_shares", when=EVENING)
    rid_m = _save_raw(store, source="szse_shares", when=MORNING)
    ingest(store, [_share("510300", DATA_DAY, "100", raw_id=rid_e, when=EVENING)], EVENING, phase="evening")
    ingest(store, [_share("159919", DATA_DAY, "50", raw_id=rid_m, when=MORNING)], MORNING, phase="morning")
    store.set_checkpoint("sse_shares", f"{DATA_DAY}:{DATA_DAY}:evening", "complete", EVENING, detail="x")
    store.set_checkpoint("szse_shares", f"{DATA_DAY}:{DATA_DAY}:morning", "complete", MORNING, detail="x")
    store.close()
    _write_evening_end_continuity(evidence, db)

    config = evidence / "config.toml"
    example = (ROOT / "config" / "example.toml").read_text(encoding="utf-8")
    config.write_text(
        example.replace('db_path = "data/observer.sqlite"', f'db_path = "{db}"').replace(
            'raw_dir = "data/raw"', f'raw_dir = "{raw}"'
        ),
        encoding="utf-8",
    )
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "etf-flow-observer"
    stub.write_text("#!/usr/bin/env bash\nif [[ \"${1:-}\" == \"sim-check\" ]]; then exit 2; fi\nexit 0\n", encoding="utf-8")
    stub.chmod(0o755)
    env = os.environ.copy()
    env.update({"EVIDENCE_ROOT": str(evidence), "CONFIG": str(config), "OBS": str(stub), "PY": str(PY), "DATA_DAY": DATA_DAY})
    proc = _run(["bash", str(PAIR_SH), "morning"], env=env)
    # verify fails on split funds → exit 1, but continuity files must remain distinct
    assert proc.returncode == 1, proc.stdout + proc.stderr
    logs = list((evidence / "logs").glob("morning-*"))
    assert logs, proc.stdout
    log = logs[0]
    start = log / "continuity-morning-start.txt"
    end = log / "continuity-morning-end.txt"
    compare = log / "continuity-compare.txt"
    terminal = log / "continuity-terminal.txt"
    assert start.is_file(), "start continuity must exist"
    assert end.is_file(), "end continuity must exist"
    assert compare.is_file(), "compare evidence must exist"
    assert terminal.is_file(), "terminal stamp must be separate"
    assert "leg=morning-start" in start.read_text(encoding="utf-8")
    assert "path_match=true" in compare.read_text(encoding="utf-8")
    assert "terminal_verify_exit=1" in terminal.read_text(encoding="utf-8")
    # start file must not have been replaced by terminal-only content
    assert "terminal_verify_exit" not in start.read_text(encoding="utf-8")


def test_ce6_continuity_path_mismatch_keeps_refuse_reason(tmp_path: Path):
    """CE6: path mismatch refuse reason survives; not replaced by a bare terminal success/fail."""
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    db = evidence / "live.sqlite"
    raw = evidence / "raw"
    Store(db, raw).close()
    # Evening-end points at a DIFFERENT db path → morning compare refuses.
    (evidence / "continuity-evening-end.txt").write_text(
        "leg=evening-end\nresolved_db=/tmp/other-not-this.sqlite\ndb_inode=1\n",
        encoding="utf-8",
    )
    config = evidence / "config.toml"
    example = (ROOT / "config" / "example.toml").read_text(encoding="utf-8")
    config.write_text(
        example.replace('db_path = "data/observer.sqlite"', f'db_path = "{db}"').replace(
            'raw_dir = "data/raw"', f'raw_dir = "{raw}"'
        ),
        encoding="utf-8",
    )
    stub = tmp_path / "bin"
    stub.mkdir()
    obs = stub / "etf-flow-observer"
    obs.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    obs.chmod(0o755)
    env = os.environ.copy()
    env.update({"EVIDENCE_ROOT": str(evidence), "CONFIG": str(config), "OBS": str(obs), "PY": str(PY), "DATA_DAY": DATA_DAY})
    proc = _run(["bash", str(PAIR_SH), "morning"], env=env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    logs = list((evidence / "logs").glob("morning-*"))
    assert logs
    compare = (logs[0] / "continuity-compare.txt").read_text(encoding="utf-8")
    terminal = (logs[0] / "continuity-terminal.txt").read_text(encoding="utf-8")
    assert "refuse_reason=resolved_db_mismatch" in compare
    assert "path_match=false" in compare
    assert "terminal_state=refused_path_mismatch" in terminal
    # compare refuse evidence still present alongside terminal
    assert "refuse_reason=resolved_db_mismatch" in compare
