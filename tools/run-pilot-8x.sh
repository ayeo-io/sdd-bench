#!/bin/bash
# Run the sdd-bench pilot on Compass 8.x: 2 runs per arm (bare, Compass) for
# each of the 4 scenarios, 16 runs, interleaved arm by arm, each with a
# spending cap. After each Compass run, tools/check_record.py checks the
# record the run left behind.
#
# Every run calls a model and costs money. Read the cost estimate in
# docs/pilot-8x.md before you start it.
#
# Usage:
#   bash tools/run-pilot-8x.sh --dry-run    print what would run; calls no model
#   bash tools/run-pilot-8x.sh              set up (once) and run
#
# Settings, from the environment:
#   COMPASS_REPO  the Compass checkout to take the tag from (default ~/dev/compass)
#   COMPASS_TAG   the Compass release measured (default v8.0.4)
#   PILOT_OUT     where the runner, the plugin copy and the results go
#                 (default ~/dev/sdd-bench-runs/pilot-8x)
#   PY            the python3 that has pytest, mypy, ruff, coverage and pyyaml
#                 (default: python3 on PATH)
#   PILOT_STOP_USD  start no new run once the runs so far have spent this
#                 much, session plus approver (default 80, the approved top)
#
# A run that already has a DONE file is skipped, so the script can be started
# again after a stop.
set -u

BENCH=$(cd "$(dirname "$0")/.." && pwd)
COMPASS_REPO=${COMPASS_REPO:-$HOME/dev/compass}
COMPASS_TAG=${COMPASS_TAG:-v8.0.4}
PILOT_OUT=${PILOT_OUT:-$HOME/dev/sdd-bench-runs/pilot-8x}
PY=${PY:-python3}
PILOT_STOP_USD=${PILOT_STOP_USD:-80}
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

SCENARIOS=(shop-idempotency shop-tracing shop-forget-user shop-change-email)
ARMS=(bare compass)
RUNS=(1 2)

# Caps in dollars per run, for the session. Bare: about 3 times its largest
# past spend. Compass: what the approved budget allows; on shop-tracing the
# cap can decide reach, as it did in the cost-spike baseline.
cap() {
  case "$1:$2" in
    bare:shop-idempotency) echo 5 ;;
    bare:shop-tracing) echo 11 ;;
    bare:shop-forget-user) echo 9 ;;
    bare:shop-change-email) echo 5 ;;
    compass:shop-idempotency) echo 6 ;;
    compass:shop-tracing) echo 50 ;;
    compass:shop-forget-user) echo 30 ;;
    compass:shop-change-email) echo 30 ;;
  esac
}

# Dollars spent by the runs recorded so far, session plus approver.
spent() {
  "$PY" - "$PILOT_OUT/runs" <<'EOF'
import glob, json, sys
total = 0.0
for path in glob.glob(f"{sys.argv[1]}/*/*.json"):
    if path.endswith("check.json"):
        continue
    r = json.load(open(path))
    total += float(r.get("cost_usd") or 0)
    total += float((r.get("multi_round") or {}).get("approver_cost_usd") or 0)
print(f"{total:.2f}")
EOF
}

say() { echo "+ $*"; }
do_or_say() { if [ $DRY = 1 ]; then say "$@"; else "$@"; fi; }

# The results must name the scenario commit, so the bench must be clean.
if [ -n "$(git -C "$BENCH" status --porcelain --untracked-files=no)" ]; then
  echo "sdd-bench has uncommitted changes; commit them first" >&2
  [ $DRY = 1 ] || exit 2
fi
BENCH_COMMIT=$(git -C "$BENCH" rev-parse HEAD)
COMPASS_COMMIT=$(git -C "$COMPASS_REPO" rev-parse "$COMPASS_TAG^{commit}") || exit 2

RUNNER=$PILOT_OUT/runner      # the harness: the tag plus the two lab patches
PLUGIN=$PILOT_OUT/plugin      # the plugin source: the tag, unchanged
if [ ! -d "$RUNNER" ]; then
  do_or_say mkdir -p "$PILOT_OUT"
  do_or_say git -C "$COMPASS_REPO" worktree add --detach "$RUNNER" "$COMPASS_TAG"
  do_or_say patch -d "$RUNNER" -p1 -i "$BENCH/tools/compass-harness-multi-round.patch"
  do_or_say patch -d "$RUNNER" -p1 -i "$BENCH/tools/compass-harness-pilot.patch"
fi
if [ ! -d "$PLUGIN" ]; then
  do_or_say git -C "$COMPASS_REPO" worktree add --detach "$PLUGIN" "$COMPASS_TAG"
fi

if [ $DRY = 0 ]; then
  mkdir -p "$PILOT_OUT/runs"
  {
    echo "bench_commit: $BENCH_COMMIT"
    echo "compass_tag: $COMPASS_TAG"
    echo "compass_commit: $COMPASS_COMMIT"
    echo "claude_version: $(claude --version 2>/dev/null)"
    echo "python: $($PY --version 2>&1)"
    echo "started: $(date -u '+%FT%TZ')"
  } > "$PILOT_OUT/PILOT.yml"
fi

for r in "${RUNS[@]}"; do
  for s in "${SCENARIOS[@]}"; do
    for arm in "${ARMS[@]}"; do
      dir=$PILOT_OUT/runs/$s-$arm-r$r
      [ -e "$dir/DONE" ] && { echo "skip $s $arm r$r (done)"; continue; }
      c=$(cap "$arm" "$s")
      if [ $DRY = 1 ]; then
        say "cd $RUNNER && SDD_BENCH_ROOT=$BENCH SDD_RUN_BUDGET=$c" \
            "SDD_KEEP_WORKSPACE=$dir/workspace $PY evals/harness.py" \
            "--scenario $BENCH/scenarios/$s --condition $arm --runs 1" \
            "--out $dir --plugin-source $PLUGIN"
        [ "$arm" = compass ] && say "$PY $BENCH/tools/check_record.py" \
            "--workspace $dir/workspace/$s-compass-1 --json $dir/check.json"
        continue
      fi
      so_far=$(spent)
      if "$PY" -c "import sys; sys.exit(float('$so_far') < float('$PILOT_STOP_USD'))"; then
        echo "stop: \$$so_far spent, at or over PILOT_STOP_USD \$$PILOT_STOP_USD"
        break 3
      fi
      rm -rf "$dir" && mkdir -p "$dir"
      echo "start $s $arm r$r cap \$$c, \$$so_far spent so far $(date '+%T')"
      (cd "$RUNNER" && SDD_BENCH_ROOT=$BENCH SDD_RUN_BUDGET=$c \
         SDD_KEEP_WORKSPACE=$dir/workspace "$PY" evals/harness.py \
         --scenario "$BENCH/scenarios/$s" --condition "$arm" --runs 1 \
         --out "$dir" --plugin-source "$PLUGIN") > "$dir/run.log" 2>&1
      code=$?
      if [ "$arm" = compass ] && [ -d "$dir/workspace/$s-compass-1" ]; then
        "$PY" "$BENCH/tools/check_record.py" --workspace "$dir/workspace/$s-compass-1" \
          --json "$dir/check.json" > "$dir/check.txt" 2>&1
      fi
      echo "exit $code $(date -u '+%FT%TZ')" > "$dir/DONE"
    done
  done
done

[ $DRY = 1 ] && exit 0

# One line per run: tokens, dollars (session and approver), reach, checker.
"$PY" - "$PILOT_OUT/runs" <<'EOF' | tee "$PILOT_OUT/SUMMARY.md"
import glob, json, os, sys
root = sys.argv[1]
print("| Run | Tokens | Session $ | Approver $ | Rounds | Reached | Terminal approvals | Checker |")
print("|---|---|---|---|---|---|---|---|")
for d in sorted(glob.glob(os.path.join(root, "*"))):
    recs = glob.glob(os.path.join(d, "*.json"))
    recs = [p for p in recs if not p.endswith("check.json")]
    if not recs:
        print(f"| {os.path.basename(d)} | no record | | | | | | |"); continue
    r = json.load(open(recs[0])); mr = r.get("multi_round") or {}
    rounds = mr.get("rounds") or []
    reached = bool(rounds and rounds[-1].get("at_target"))
    check = os.path.join(d, "check.json")
    verdict = ""
    if os.path.exists(check):
        rep = json.load(open(check))
        verdict = "; ".join(f"{k} {v['status']}" for i in rep["issues"]
                            for k, v in i["checks"].items()) or "no record"
    print(f"| {os.path.basename(d)} | {(r.get('tokens') or 0)/1e6:.2f}M | "
          f"{float(r.get('cost_usd') or 0):.2f} | {float(mr.get('approver_cost_usd') or 0):.2f} | "
          f"{len(rounds)} | {'yes' if reached else 'no'} ({mr.get('stop')}) | "
          f"{len(mr.get('terminal_approvals') or [])} | {verdict} |")
EOF
