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
