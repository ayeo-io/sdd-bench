#!/bin/bash
# Run the pre-registered sdd-bench measurement of Compass 9.0.0
# (docs/preregistration-9-0-0.md): 6 runs per arm per scenario, 48 runs, in
# this order:
#   run 1 of every cell, then run 2, and so on to run 6;
#   within a run number, scenario by scenario, bare then Compass.
# So a stop at the budget leaves every cell with the same number of runs, give
# or take one.
#
# The runner is tools/harness.py at this repository's commit. The plugin under
# test is the Compass release named by COMPASS_REF, copied as a git worktree.
# Each run reaches target over rounds, then the ship phase asks for a commit,
# squash-merges it into main and records an approving review in the fake
# GitHub (tools/fake_gh.py). After each Compass run, tools/check_record.py
# checks the record the run left behind, on main, after the seed, against the
# scenario's request.
#
# Every run calls a model and costs money. Read the budget in
# docs/preregistration-9-0-0.md before you start it.
#
# Usage:
#   bash tools/run-9-0-0.sh --dry-run    print what would run; calls no model
#   bash tools/run-9-0-0.sh              set up (once) and run
#
# Settings, from the environment:
#   COMPASS_REPO  the Compass checkout to take the release from (default ~/dev/compass)
#   COMPASS_REF   the Compass release measured (default v9.0.0)
#   RUN_OUT       where the plugin copy and the results go
#                 (default ~/dev/sdd-bench-runs/9-0-0)
#   PY            the python3 that has pytest, mypy, ruff, coverage and pyyaml
#                 (default: python3 on PATH)
#   RUNS          runs per arm per scenario (default 6)
#   ONLY          a space-separated subset of scenarios, for the smoke test
#   STOP_USD      start no new run once the runs so far have spent this much,
#                 session plus approver (default 400, the top of the budget)
#
# A run that already has a DONE file is skipped, so the script can be started
# again after a stop.
set -u

BENCH=$(cd "$(dirname "$0")/.." && pwd)
COMPASS_REPO=${COMPASS_REPO:-$HOME/dev/compass}
COMPASS_REF=${COMPASS_REF:-v9.0.0}
RUN_OUT=${RUN_OUT:-$HOME/dev/sdd-bench-runs/9-0-0}
PY=${PY:-python3}
RUNS=${RUNS:-6}
STOP_USD=${STOP_USD:-400}
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

# ONLY names a subset, for the smoke test, as a space-separated list.
if [ -n "${ONLY:-}" ]; then
  read -r -a SCENARIOS <<< "$ONLY"
else
  SCENARIOS=(shop-idempotency shop-tracing shop-forget-user shop-change-email)
fi
ARMS=(bare compass)

# Caps in dollars per run, for the session, ship phase included. Bare: about
# 2 to 3 times its largest pilot spend. Compass: about 1.3 times its largest
# pilot spend, and for shop-tracing, which the pilot did not run, its largest
# earlier spend. The harness checks a cap between turns, so a run can go a few
# dollars over it. TO CONFIRM in the pre-registration.
cap() {
  case "$1:$2" in
    bare:shop-idempotency) echo 5 ;;
    bare:shop-tracing) echo 10 ;;
    bare:shop-forget-user) echo 8 ;;
    bare:shop-change-email) echo 15 ;;
    compass:shop-idempotency) echo 6 ;;
    compass:shop-tracing) echo 60 ;;
    compass:shop-forget-user) echo 35 ;;
    compass:shop-change-email) echo 35 ;;
    *) echo "no cap for $1 $2" >&2; exit 2 ;;
  esac
}

# The request a scenario links, as owner/repo#number.
request_of() {
  "$PY" - "$BENCH/scenarios/$1/scenario.yml" <<'EOF'
import sys, yaml
r = yaml.safe_load(open(sys.argv[1]))["request"]
print(f"{r['repo']}#{r['number']}")
EOF
}

# Dollars spent by the runs recorded so far: session (ship phase included) plus
# the approver in the rounds and in the ship phase.
spent() {
  "$PY" - "$RUN_OUT/runs" <<'EOF'
import glob, json, sys
total = 0.0
for path in glob.glob(f"{sys.argv[1]}/*/*.json"):
    if path.endswith("check.json"):
        continue
    r = json.load(open(path))
    mr = r.get("multi_round") or {}
    total += float(r.get("cost_usd") or 0)
    total += float(mr.get("approver_cost_usd") or 0)
    total += float((mr.get("ship") or {}).get("approver_cost_usd") or 0)
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
COMPASS_COMMIT=$(git -C "$COMPASS_REPO" rev-parse "$COMPASS_REF^{commit}") || exit 2

PLUGIN=$RUN_OUT/plugin      # the plugin source: the release, unchanged
if [ ! -d "$PLUGIN" ]; then
  do_or_say mkdir -p "$RUN_OUT"
  do_or_say git -C "$COMPASS_REPO" worktree add --detach "$PLUGIN" "$COMPASS_REF"
fi

if [ $DRY = 0 ]; then
  mkdir -p "$RUN_OUT/runs"
  {
    echo "bench_commit: $BENCH_COMMIT"
    echo "runner: tools/harness.py at the bench commit"
    echo "compass_ref: $COMPASS_REF"
    echo "compass_commit: $COMPASS_COMMIT"
    echo "runs_per_cell: $RUNS"
    echo "stop_usd: $STOP_USD"
    echo "claude_version: $(claude --version 2>/dev/null)"
    echo "python: $($PY --version 2>&1)"
    echo "started: $(date -u '+%FT%TZ')"
  } > "$RUN_OUT/RUN.yml"
fi

for r in $(seq 1 "$RUNS"); do
  for s in "${SCENARIOS[@]}"; do
    for arm in "${ARMS[@]}"; do
      dir=$RUN_OUT/runs/$s-$arm-r$r
      [ -e "$dir/DONE" ] && { echo "skip $s $arm r$r (done)"; continue; }
      c=$(cap "$arm" "$s") || exit 2
      req=$(request_of "$s") || exit 2
      ws=$dir/workspace/$s-$arm-1
      if [ $DRY = 1 ]; then
        say "cd $BENCH && SDD_BENCH_ROOT=$BENCH SDD_RUN_BUDGET=$c" \
            "SDD_KEEP_WORKSPACE=$dir/workspace $PY tools/harness.py" \
            "--scenario $s --condition $arm --runs 1 --out $dir --plugin-source $PLUGIN"
        [ "$arm" = compass ] && say "$PY tools/check_record.py --workspace $ws" \
            "--branch main --base <root commit of main> --expect-request $req" \
            "--require-ship-approval --json $dir/check.json"
        continue
      fi
      so_far=$(spent)
      if "$PY" -c "import sys; sys.exit(float('$so_far') < float('$STOP_USD'))"; then
        echo "stop: \$$so_far spent, at or over STOP_USD \$$STOP_USD"
        break 3
      fi
      rm -rf "$dir" && mkdir -p "$dir"
      echo "start $s $arm r$r cap \$$c, \$$so_far spent so far $(date '+%T')"
      (cd "$BENCH" && SDD_BENCH_ROOT=$BENCH SDD_RUN_BUDGET=$c \
         SDD_KEEP_WORKSPACE=$dir/workspace "$PY" tools/harness.py \
         --scenario "$s" --condition "$arm" --runs 1 \
         --out "$dir" --plugin-source "$PLUGIN") > "$dir/run.log" 2>&1
      code=$?
      if [ "$arm" = compass ] && [ -d "$ws" ]; then
        base=$(git -C "$ws" rev-list --max-parents=0 main 2>/dev/null | tail -1)
        "$PY" "$BENCH/tools/check_record.py" --workspace "$ws" --branch main \
          --base "${base:-main}" --expect-request "$req" --require-ship-approval \
          --json "$dir/check.json" > "$dir/check.txt" 2>&1
      fi
      echo "exit $code $(date -u '+%FT%TZ')" > "$dir/DONE"
    done
  done
done

[ $DRY = 1 ] && exit 0

# One line per run: tokens, dollars, reach, ship and the checker.
"$PY" - "$RUN_OUT/runs" <<'EOF' | tee "$RUN_OUT/SUMMARY.md"
import glob, json, os, sys
root = sys.argv[1]
print("| Run | Tokens | Session $ | Approver $ | Rounds | Reached | Ship | Ship $ "
      "| Merged tree at target | Uncommitted | compass.yml changed | gh calls | Checker |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for d in sorted(glob.glob(os.path.join(root, "*"))):
    recs = [p for p in glob.glob(os.path.join(d, "*.json")) if not p.endswith("check.json")]
    if not recs:
        print(f"| {os.path.basename(d)} | no record |" + " |" * 11); continue
    r = json.load(open(recs[0])); mr = r.get("multi_round") or {}
    ship = mr.get("ship") or {}
    rounds = mr.get("rounds") or []
    reached = bool(rounds and rounds[-1].get("at_target"))
    approver = float(mr.get("approver_cost_usd") or 0) + float(ship.get("approver_cost_usd") or 0)
    check = os.path.join(d, "check.json")
    verdict = ""
    if os.path.exists(check):
        rep = json.load(open(check))
        verdict = "; ".join(f"{k} {v['status']}" for i in rep["issues"]
                            for k, v in i["checks"].items()) or "no record"
    merged = ship.get("merged_tree_at_target")
    print(f"| {os.path.basename(d)} | {(r.get('tokens') or 0)/1e6:.2f}M | "
          f"{float(r.get('cost_usd') or 0):.2f} | {approver:.2f} | {len(rounds)} | "
          f"{'yes' if reached else 'no'} ({mr.get('stop')}) | {ship.get('stop', '')}"
          f"{' (fast-forward)' if ship.get('fast_forward') else ''} | "
          f"{float(ship.get('cost_usd') or 0):.2f} | "
          f"{'' if merged is None else ('yes' if merged else 'no')} | "
          f"{len(ship.get('uncommitted') or [])} | "
          f"{'yes' if ship.get('compass_yml_changed') else 'no'} | "
          f"{len(ship.get('gh_calls') or [])} | {verdict} |")
EOF
