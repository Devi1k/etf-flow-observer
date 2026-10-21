#!/usr/bin/env bash
# Same-DB evening → next-morning pair for Dot evidence A.
# Does NOT install crontab. Does NOT start continuous gray. Does NOT open allow_trial.
#
# Usage:
#   ./scripts/same_db_pair.sh init              # create evidence dir + config (once)
#   ./scripts/same_db_pair.sh evening           # after 15:00 Asia/Shanghai on a trading day
#   ./scripts/same_db_pair.sh morning           # after 08:00 next natural day (not Monday-for-Friday)
#   ./scripts/same_db_pair.sh verify            # inspect the SAME live.sqlite
#   ./scripts/same_db_pair.sh sim-check         # must print EXIT:2
#   ./scripts/same_db_pair.sh status
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

need_venv() {
  if [[ ! -x "$PY" ]]; then
    echo "missing $PY — run: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
    exit 2
  fi
}

shanghai_now() {
  TZ=Asia/Shanghai date '+%Y-%m-%dT%H:%M:%S%z'
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
  local stamp log
  stamp="$(TZ=Asia/Shanghai date '+%Y%m%dT%H%M%S%z')"
  log="$EVIDENCE_ROOT/logs/evening-$stamp"
  mkdir -p "$log"
  {
    echo "wall_clock_start=$(shanghai_now)"
    echo "config=$CONFIG"
    echo "db=$EVIDENCE_ROOT/live.sqlite"
    echo "git_sha=$(git -C "$ROOT" rev-parse HEAD)"
    echo "cmd=$OBS --config $CONFIG collect all --session evening --homepage-cross-check"
  } | tee "$log/run-meta.txt"
  set +e
  "$OBS" --config "$CONFIG" collect all --session evening --homepage-cross-check \
    >"$log/stdout.txt" 2>"$log/stderr.txt"
  ec=$?
  set -e
  echo "wall_clock_end=$(shanghai_now)" | tee -a "$log/run-meta.txt"
  echo "exit_code=$ec" | tee -a "$log/run-meta.txt"
  "$OBS" --config "$CONFIG" status >"$log/status.txt" || true
  "$PY" "$ROOT/scripts/export_pair_snapshot.py" --db "$EVIDENCE_ROOT/live.sqlite" --out "$log"
  echo "evening leg done exit=$ec log=$log"
  exit "$ec"
}

cmd_morning() {
  need_venv
  if [[ ! -f "$EVIDENCE_ROOT/live.sqlite" ]]; then
    echo "missing live.sqlite — run evening first on this same path" >&2
    exit 2
  fi
  local stamp log
  stamp="$(TZ=Asia/Shanghai date '+%Y%m%dT%H%M%S%z')"
  log="$EVIDENCE_ROOT/logs/morning-$stamp"
  mkdir -p "$log"
  {
    echo "wall_clock_start=$(shanghai_now)"
    echo "config=$CONFIG"
    echo "db=$EVIDENCE_ROOT/live.sqlite"
    echo "git_sha=$(git -C "$ROOT" rev-parse HEAD)"
    echo "cmd=$OBS --config $CONFIG collect all --session morning --homepage-cross-check"
    echo "note=MUST be natural next morning; Monday-for-Friday is backfill and does not count"
  } | tee "$log/run-meta.txt"
  set +e
  "$OBS" --config "$CONFIG" collect all --session morning --homepage-cross-check \
    >"$log/stdout.txt" 2>"$log/stderr.txt"
  ec=$?
  set -e
  echo "wall_clock_end=$(shanghai_now)" | tee -a "$log/run-meta.txt"
  echo "exit_code=$ec" | tee -a "$log/run-meta.txt"
  "$OBS" --config "$CONFIG" status >"$log/status.txt" || true
  "$PY" "$ROOT/scripts/export_pair_snapshot.py" --db "$EVIDENCE_ROOT/live.sqlite" --out "$log"
  local data_day
  data_day="${DATA_DAY:-$(TZ=Asia/Shanghai date -d 'yesterday' '+%Y-%m-%d' 2>/dev/null || python3 -c 'from datetime import date,timedelta; print((date.today()-timedelta(days=1)).isoformat())')}"
  "$PY" "$ROOT/scripts/verify_same_db_pair.py" --db "$EVIDENCE_ROOT/live.sqlite" --data-day "$data_day" \
    | tee "$log/verify.txt" || true
  echo "morning leg done exit=$ec log=$log data_day=$data_day"
  exit "$ec"
}

cmd_verify() {
  need_venv
  local data_day="${DATA_DAY:-}"
  if [[ -z "$data_day" ]]; then
    echo "set DATA_DAY=YYYY-MM-DD" >&2
    exit 2
  fi
  "$PY" "$ROOT/scripts/verify_same_db_pair.py" --db "$EVIDENCE_ROOT/live.sqlite" --data-day "$data_day"
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
  "$OBS" --config "$CONFIG" status
}

usage() {
  sed -n '2,20p' "$0"
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
