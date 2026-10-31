# Pilot on Compass 8.x: plan

This pilot runs before the 9.0.0 measurement. It measures how much each arm
varies between runs, and it tries `tools/check_record.py` on real Compass
records. Its results set the run count for the full measurement (6 per cell
is the plan).

## What runs

- Arms: bare (`--condition bare`) and Compass at `v8.0.4`.
- Scenarios: `shop-idempotency`, `shop-tracing`, `shop-forget-user` and
  `shop-change-email`.
- Runs: 2 per arm per scenario, 16 in all, interleaved: run 1 of every
  scenario, bare then Compass, then run 2 the same way.
- Runner: the Compass eval harness at `v8.0.4`, with
  `tools/compass-harness-multi-round.patch` and then
  `tools/compass-harness-pilot.patch` applied.

## The command

`tools/run-pilot-8x.sh` sets up the runner and the plugin copy as two git
worktrees of the tag, runs the 16 runs, runs the checker after each Compass
run, and writes `SUMMARY.md`. First look at what it will do; this calls no
model:

```
PY=~/.pyenv/shims/python3 bash tools/run-pilot-8x.sh --dry-run
```

Then run it:

```
PY=~/.pyenv/shims/python3 PILOT_STOP_USD=80 nohup bash tools/run-pilot-8x.sh \
  > ~/dev/sdd-bench-runs/pilot-8x.log 2>&1 &
```

`PY` must have pytest, mypy, ruff, coverage and pyyaml
(`tools/requirements.txt`), and must be the `python3` a session finds on
`PATH`. The script refuses to start while sdd-bench has uncommitted changes,
because the results must name the scenario commit.

### Caps

Per run, for the session, in dollars (`SDD_RUN_BUDGET`):

| Scenario | Bare | Compass |
|---|---|---|
| shop-idempotency | 5 | 6 |
| shop-tracing | 11 | 50 |
| shop-forget-user | 9 | 30 |
| shop-change-email | 5 | 30 |

Bare caps are about 3 times bare's largest past spend. The Compass caps are
not: 3 times the largest Compass spend would be about $150 on tracing. On
tracing the cap can decide reach, as it did in the cost-spike baseline, where
3 of 4 runs stopped at a $40 cap. The harness checks the cap between turns, so
a run can go a few dollars over it.

`PILOT_STOP_USD` stops the script from starting a new run once the runs so far
have spent that much.

## How the approver is simulated

The multi-round runner sends a model approver the session's last message. The
approver answers in text, as a product owner would ("approved, carry on").

That is not enough on 8.x. Compass 8.x records an approval in only two ways,
and the harness can use neither as it stands:

- A person types `/compass:approve`. The hook refuses it in a `claude -p`
  session, because Claude Code reports `CLAUDE_CODE_ENTRYPOINT` as `sdk-cli`
  there (Compass `cli/compass_pkg/prompt_approval.py`, ADR-068 decision 2).
- A person runs `compass evidence approve` in a terminal. The verb refuses
  unless standard input is a terminal (`cli/compass_pkg/approve_cmd.py`).

So without a change, a Compass session on `shop-change-email` asks for the
sign-off, gets a text reply, and cannot ship: `compass check` fails
`human-approval-present` for a `personal-data` change. The same holds for the
checkpoint hand-offs that the full route waits at.

`tools/compass-harness-pilot.patch` makes the runner act as the person at a
terminal. Before it asks the model approver, it looks for request files in
`.compass/work/*/approval-requests/pending/`. For each one it has not answered
yet, it runs the command that `compass evidence request` prints for a host
with no prompt path, under a pseudo-terminal:

```
compass evidence approve --issue <slug> --<form> <value> \
  --approver sdd-bench-approver --role owner --scope "<scope>"
```

It then tells the session it approved. The record holds `via: terminal` and
the approver `sdd-bench-approver`, so a reader can tell a simulated approval
from a person's. The run record lists these approvals under
`multi_round.terminal_approvals`. The terminal verb does not close the request
file, so the runner keeps its own list of answered requests.

The patch also adds `SDD_KEEP_WORKSPACE`. The harness deletes each run's
repository when the run ends, and the record keeps only the manifest text,
not the evidence files or `.git`. With the setting, the runner copies the
repository to `<dir>/<scenario>-<condition>-<run>/` when the session ends,
before the hidden tests are copied in, so the checker can read it.

I have not run either addition against a model. The patch applies to
`v8.0.4` on top of the multi-round patch, and the result parses.

## Cost estimate

No run of 8.x on this bench exists, so the estimate uses the two earlier
measurements. Totals are session plus approver.

| Scenario | Bare, per run | Compass, per run | Source |
|---|---|---|---|
| shop-idempotency | $0.34 - $1.45 | $0.43 - $0.44 | `docs/results-2026-10-10-multi-round.md:15-16`; spike baseline `SUMMARY.md:48-49` |
| shop-tracing | $0.93 - $3.63 | $36.20 - $50.90 | `docs/results-2026-10-10-multi-round.md:17-18`; spike baseline `SUMMARY.md:44-45` |
| shop-forget-user | $0.59 - $2.69 | $12.98 - $30.20 | `docs/results-2026-10-10-multi-round.md:19-20`; spike baseline `SUMMARY.md:46-47` |
| shop-change-email | $0.34 - $1.45 | $10 - $30 | no run; guessed from idempotency (bare) and forget-user (Compass, the same full route) |

The 10 Oct figures are for Compass 6.0.0 plus 3 commits and leave out the
approver ($0.02-0.14 a run, `docs/results-2026-10-10-multi-round.md:22`). The
spike baseline is Compass at `1776a1dc`, before 6.1.0, and is kept outside
this repository (`spikes/results/base/SUMMARY.md`, cell means and ranges).

For 16 runs:

- bare: $4 - $18;
- Compass: $119 - $223, and up to about $232 at the caps;
- in all: about $125 - $240.

This is above the approved $40-80. Tracing alone is $72-102 of it on the
Compass arm. Compass 8.x has changed since both measurements: the one-unit
breakdown landed (measured -19.8% in the cost spikes), and other changes
have not been measured. The range can move either way.

## What blocks the pilot

1. **Budget.** The estimate is about 2 to 3 times the approved $40-80. With
   `PILOT_STOP_USD=80` the script stops early, after roughly run 1 of each
   cell. The owner must choose: raise the budget, or cut the Compass arm on
   `shop-tracing`, or accept a partial pilot.
2. **Approvals.** Without `tools/compass-harness-pilot.patch`, no Compass run
   on a `personal-data` or full-route scenario can record an approval. The
   patch is written but not tried on a real run.
3. **Records.** Without `SDD_KEEP_WORKSPACE`, the checker has nothing to
   read. The same patch adds it.

## What the checker should report on 8.x

- `test-digests`: `not-checkable` on every run. 8.x records store `tree_id`,
  `changes_id` and a digest over re-serialized JSON, not a digest of each
  test file.
- `request-link`: `fail` on every run. A bench session has no GitHub issue to
  link, and 8.x does not require one.
- `land-commit`: `fail` on a run that does not reach ship. On a run that
  ships, it can pass in the bench, because the harness repository has no
  squash merge.
- `red-before-green` and `approvals`: either way. These are the two checks
  the pilot is for.
