#!/usr/bin/env bash
# Same-DB evening → next-morning pair for Dot evidence A.
# Does NOT install crontab. Does NOT start continuous gray. Does NOT open allow_trial.
#
# Usage:
#   ./scripts/same_db_pair.sh init              # create evidence dir + config (once)
#   ./scripts/same_db_pair.sh evening           # after 15:00 Asia/Shanghai on a trading day
#   ./scripts/same_db_pair.sh morning           # after 08:00 next natural day (not Monday-for-Friday)
#   ./scripts/same_db_pair.sh verify            # inspect the SAME live.sqlite (field mode)
#   ./scripts/same_db_pair.sh sim-check         # must print EXIT:2
#   ./scripts/same_db_pair.sh status
#
# Exit codes (morning / verify):
#   0  pass (verify field acceptance)
#   1  verify hard fail (even if collect exited 0)
#   2  usage / missing DB / config db_path ≠ EVIDENCE_ROOT/live.sqlite
#   3  pending-evidence (pair incomplete / uncovered; NOT acceptance)
#   other  collect process exit
#
# Override:
#   EVIDENCE_ROOT=/path DATA_DAY=2026-10-21 ./scripts/same_db_pair.sh evening

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

EVIDENCE_ROOT="${EVIDENCE_ROOT:-/workspace/etf-flow-evidence/same-db-20261021}"
CONFIG="${CONFIG:-$EVIDENCE_ROOT/config.toml}"
PY="${PY:-$ROOT/.venv/bin/python}"
OBS="${OBS:-$ROOT/.venv/bin/etf-flow-observer}"
EXPECTED_DB="$EVIDENCE_ROOT/live.sqlite"

need_venv() {
  if [[ ! -x "$PY" ]]; then
    echo "missing $PY — run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 2
  fi
}

shanghai_now() {
  TZ=Asia/Shanghai date '+%Y-%m-%dT%H:%M:%S%z'
}

# Resolve config storage.db_path and refuse collect/verify if it is not EVIDENCE_ROOT/live.sqlite.
assert_db_identity() {
  need_venv
  if [[ ! -f "$CONFIG" ]]; then
    echo "missing config: $CONFIG (run init first)" >&2
    exit 2
  fi
  local resolved expected
  resolved="$("$PY" - <<PY
from pathlib import Path
from etf_flow_observer.config import load_config
cfg = load_config(Path("$CONFIG"))
print(cfg.db_path.expanduser().resolve())
PY
)"
  expected="$(mkdir -p "$EVIDENCE_ROOT" && "$PY" -c "from pathlib import Path; print(Path('$EXPECTED_DB').expanduser().resolve())")"
  if [[ "$resolved" != "$expected" ]]; then
    echo "REFUSE: config db_path ($resolved) != EVIDENCE_ROOT/live.sqlite ($expected)" >&2
    echo "fix config storage.db_path or EVIDENCE_ROOT/CONFIG so collect and verify share one DB." >&2
    exit 2
  fi
  echo "db_identity_ok resolved=$resolved"
}

record_continuity() {
  local leg="$1" log="$2"
  need_venv
  local meta="$log/continuity-${leg}.txt"
  {
    echo "leg=$leg"
    echo "wall_clock=$(shanghai_now)"
    echo "evidence_root=$EVIDENCE_ROOT"
    echo "config=$CONFIG"
    echo "expected_db=$EXPECTED_DB"
    "$PY" - <<PY
from pathlib import Path
from etf_flow_observer.config import load_config
cfg = load_config(Path("$CONFIG"))
db = cfg.db_path.expanduser().resolve()
print(f"resolved_db={db}")
print(f"db_exists={db.is_file()}")
if db.is_file():
    st = db.stat()
    print(f"db_size={st.st_size}")
    print(f"db_mtime_ns={st.st_mtime_ns}")
    print(f"db_inode={st.st_ino}")
PY
    echo "git_sha=$(git -C "$ROOT" rev-parse HEAD)"
  } | tee "$meta"
}

# Compare evening-end identity to morning-start; keep refuse reason (not wiped by terminal stamp).
compare_pair_continuity() {
  local evening_end="$1" morning_start="$2" out="$3"
  need_venv
  {
    echo "compare=evening-end_vs_morning-start"
    echo "evening_end_file=$evening_end"
    echo "morning_start_file=$morning_start"
    if [[ ! -f "$evening_end" ]]; then
      echo "refuse_reason=missing_evening_end_continuity"
      echo "path_match=false"
      return 1
    fi
    if [[ ! -f "$morning_start" ]]; then
      echo "refuse_reason=missing_morning_start_continuity"
      echo "path_match=false"
      return 1
    fi
    local e_db m_db e_ino m_ino
    e_db=$(grep -E '^resolved_db=' "$evening_end" | head -1 | cut -d= -f2-)
    m_db=$(grep -E '^resolved_db=' "$morning_start" | head -1 | cut -d= -f2-)
    e_ino=$(grep -E '^db_inode=' "$evening_end" | head -1 | cut -d= -f2-)
    m_ino=$(grep -E '^db_inode=' "$morning_start" | head -1 | cut -d= -f2-)
    echo "evening_end_db=$e_db"
    echo "morning_start_db=$m_db"
    echo "evening_end_inode=$e_ino"
    echo "morning_start_inode=$m_ino"
    if [[ -z "$e_db" || -z "$m_db" || "$e_db" != "$m_db" ]]; then
      echo "refuse_reason=resolved_db_mismatch"
      echo "path_match=false"
      return 1
    fi
    if [[ -n "$e_ino" && -n "$m_ino" && "$e_ino" != "$m_ino" ]]; then
      echo "refuse_reason=db_inode_mismatch"
      echo "path_match=false"
      return 1
    fi
    echo "refuse_reason="
    echo "path_match=true"
    return 0
  } | tee "$out"
}

cmd_init() {
  mkdir -p "$EVIDENCE_ROOT/raw" "$EVIDENCE_ROOT/logs" "$EVIDENCE_ROOT/exports"
  if [[ ! -f "$CONFIG" ]]; then
    # Copy calendar/universe from example; pin db_path to THIS evidence dir.
    sed \
      -e "s|db_path = \"data/observer.sqlite\"|db_path = \"$EVIDENCE_ROOT/live.sqlite\"|" \
      -e "s|raw_dir = \"data/raw\"|raw_dir = \"$EVIDENCE_ROOT/raw\"|" \
      "$ROOT/config/example.toml" > "$CONFIG"
    echo "wrote $CONFIG"
  else
    echo "keep existing $CONFIG"
  fi
  cat > "$EVIDENCE_ROOT/README.md" << MD
# same-DB evening→morning pair

- DB: \`$EVIDENCE_ROOT/live.sqlite\` (ONE file for both legs)
- Not continuous gray; no crontab installed by these scripts
- Universe locked: 510300 / 510310 / 510330 / 159919
- Cross-DB prior evidence does not count
- Morning collect uses \`--no-cache\` so the 12h HTTP cache cannot reuse the evening body
- \`verify\` field mode exit 0=pass, 1=fail, 3=pending-evidence (not acceptance)

## Sequence (Asia/Shanghai)

1. Trading day after 15:00: \`./scripts/same_db_pair.sh evening\`
2. Next natural day after 08:00: \`./scripts/same_db_pair.sh morning\`
   - Wed evening → Thu morning counts (\`phase=morning\`)
   - Fri evening → Sat morning counts
   - Fri evening → Mon morning is \`backfill\` and does **not** count
3. \`./scripts/same_db_pair.sh verify\`
4. Paste \`sim-check\` EXIT:2 into the evidence note

MD
  echo "evidence root: $EVIDENCE_ROOT"
}

cmd_evening() {
  need_venv
  cmd_init
  assert_db_identity
  local stamp log
  stamp="$(TZ=Asia/Shanghai date '+%Y%m%dT%H%M%S%z')"
  log="$EVIDENCE_ROOT/logs/evening-$stamp"
  mkdir -p "$log"
  {
    echo "wall_clock_start=$(shanghai_now)"
    echo "config=$CONFIG"
    echo "db=$EXPECTED_DB"
    echo "git_sha=$(git -C "$ROOT" rev-parse HEAD)"
    echo "cmd=$OBS --config $CONFIG collect all --session evening --homepage-cross-check"
  } | tee "$log/run-meta.txt"
  record_continuity evening-start "$log"
  set +e
  "$OBS" --config "$CONFIG" collect all --session evening --homepage-cross-check \
    >"$log/stdout.txt" 2>"$log/stderr.txt"
  ec=$?
  set -e
  echo "wall_clock_end=$(shanghai_now)" | tee -a "$log/run-meta.txt"
  echo "exit_code=$ec" | tee -a "$log/run-meta.txt"
  "$OBS" --config "$CONFIG" status >"$log/status.txt" || true
  "$PY" "$ROOT/scripts/export_pair_snapshot.py" --db "$EXPECTED_DB" --out "$log"
  record_continuity evening-end "$log"
  cp "$log/continuity-evening-end.txt" "$EVIDENCE_ROOT/continuity-evening-end.txt"
  echo "evening leg done exit=$ec log=$log"
  exit "$ec"
}

cmd_morning() {
  need_venv
  if [[ ! -f "$EXPECTED_DB" ]]; then
    echo "missing live.sqlite — run evening first on this same path" >&2
    exit 2
  fi
  assert_db_identity
  local stamp log
  stamp="$(TZ=Asia/Shanghai date '+%Y%m%dT%H%M%S%z')"
  log="$EVIDENCE_ROOT/logs/morning-$stamp"
  mkdir -p "$log"
  {
    echo "wall_clock_start=$(shanghai_now)"
    echo "config=$CONFIG"
    echo "db=$EXPECTED_DB"
    echo "git_sha=$(git -C "$ROOT" rev-parse HEAD)"
    echo "cmd=$OBS --config $CONFIG collect all --session morning --homepage-cross-check --no-cache"
    echo "note=MUST be natural next morning; Monday-for-Friday is backfill and does not count"
    echo "note=--no-cache required so 12h TTL cannot reuse evening response as morning source"
  } | tee "$log/run-meta.txt"
  record_continuity morning-start "$log"
  set +e
  compare_pair_continuity \
    "$EVIDENCE_ROOT/continuity-evening-end.txt" \
    "$log/continuity-morning-start.txt" \
    "$log/continuity-compare.txt"
  compare_ec=$?
  set -e
  if [[ "$compare_ec" -ne 0 ]]; then
    echo "REFUSE: evening-end vs morning-start continuity mismatch (see $log/continuity-compare.txt)" >&2
    echo "compare_exit_code=$compare_ec" | tee -a "$log/run-meta.txt"
    {
      echo "terminal_state=refused_path_mismatch"
      echo "compare_exit_code=$compare_ec"
      echo "wall_clock=$(shanghai_now)"
    } | tee "$log/continuity-terminal.txt"
    record_continuity morning-end-refused "$log"
    exit 2
  fi
  set +e
  # Morning must not reuse evening HTTP body via the default 12h cache.
  "$OBS" --config "$CONFIG" collect all --session morning --homepage-cross-check --no-cache \
    >"$log/stdout.txt" 2>"$log/stderr.txt"
  collect_ec=$?
  set -e
  echo "wall_clock_end=$(shanghai_now)" | tee -a "$log/run-meta.txt"
  echo "collect_exit_code=$collect_ec" | tee -a "$log/run-meta.txt"
  "$OBS" --config "$CONFIG" status >"$log/status.txt" || true
  if [[ -f "$EXPECTED_DB" ]]; then
    "$PY" "$ROOT/scripts/export_pair_snapshot.py" --db "$EXPECTED_DB" --out "$log"
  fi
  local data_day
  data_day="${DATA_DAY:-$(TZ=Asia/Shanghai date -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || python3 -c 'from datetime import date,timedelta; print((date.today()-timedelta(days=1)).isoformat())')}"
  set +e
  "$PY" "$ROOT/scripts/verify_same_db_pair.py" --mode field --db "$EXPECTED_DB" --data-day "$data_day" \
    | tee "$log/verify.txt"
  verify_ec=${PIPESTATUS[0]}
  set -e
  echo "verify_exit_code=$verify_ec" | tee -a "$log/run-meta.txt"
  echo "data_day=$data_day" | tee -a "$log/run-meta.txt"
  # Terminal stamp is a NEW file; does not overwrite start/compare refuse evidence.
  {
    echo "terminal_collect_exit=$collect_ec"
    echo "terminal_verify_exit=$verify_ec"
    echo "compare_path_match=true"
    echo "wall_clock=$(shanghai_now)"
  } | tee "$log/continuity-terminal.txt"
  record_continuity morning-end "$log"
  echo "morning leg done collect_exit=$collect_ec verify_exit=$verify_ec log=$log data_day=$data_day"
  # Distinguish collect failure / verify fail / pending / pass. Never exit 0 when verify failed.
  if [[ "$collect_ec" -ne 0 ]]; then
    exit "$collect_ec"
  fi
  case "$verify_ec" in
    0) exit 0 ;;
    1) exit 1 ;;
    3) exit 3 ;;
    2) exit 2 ;;
    *) exit "$verify_ec" ;;
  esac
}

cmd_verify() {
  need_venv
  local data_day="${DATA_DAY:-}"
  if [[ -z "$data_day" ]]; then
    echo "set DATA_DAY=YYYY-MM-DD" >&2
    exit 2
  fi
  assert_db_identity
  "$PY" "$ROOT/scripts/verify_same_db_pair.py" --mode field --db "$EXPECTED_DB" --data-day "$data_day"
}

cmd_sim_check() {
  need_venv
  set +e
  "$OBS" sim-check --sim-config "$ROOT/config/simulation.example.toml"
  ec=$?
  set -e
  echo "EXIT:$ec"
  exit "$ec"
}

cmd_status() {
  need_venv
  assert_db_identity
  "$OBS" --config "$CONFIG" status
}

usage() {
  sed -n '2,28p' "$0"
}

case "${1:-}" in
  init) cmd_init ;;
  evening) cmd_evening ;;
  morning) cmd_morning ;;
  verify) cmd_verify ;;
  sim-check) cmd_sim_check ;;
  status) cmd_status ;;
  *) usage; exit 2 ;;
esac
