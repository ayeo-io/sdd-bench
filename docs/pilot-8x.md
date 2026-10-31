# Pilot on Compass 8.x: plan

This pilot runs before the 9.0.0 measurement. It has two purposes:

- measure how much the bare arm varies between runs, to set the run count for
  the full measurement (6 per cell is the plan);
- try `tools/check_record.py` on real Compass records.

The budget is $80.

## What runs

12 runs, in this order:

1. bare: 2 runs on each of the 4 scenarios (run 1 of each scenario, then
   run 2), 8 runs;
2. Compass at `v8.0.4`: 2 runs on `shop-idempotency`, 1 on
   `shop-change-email`, 1 on `shop-forget-user`.

The cheap runs come first, so a stop at the budget cuts the expensive ones.

There is no Compass run on `shop-tracing`. Its Compass cost is already
measured at $36-51 a run (see the cost estimate below), and a run there serves
neither purpose of the pilot. It says nothing about bare's spread, and the
other Compass runs already give the checker records from the quick-fix route
and from the full route with a sign-off. Two tracing runs would take most of
the budget.

The runner is the Compass eval harness at `v8.0.4`, with
`tools/compass-harness-multi-round.patch` and then
`tools/compass-harness-pilot.patch` applied.

## The command

`tools/run-pilot-8x.sh` sets up the runner and the plugin copy as two git
worktrees of the tag, does the 12 runs, runs the checker after each Compass
run, and writes `SUMMARY.md`. First look at what it will do; this calls no
model and creates nothing:

```
PY=~/.pyenv/shims/python3 bash tools/run-pilot-8x.sh --dry-run
```

Then run it from a terminal:

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
| shop-tracing | 11 | no run |
| shop-forget-user | 9 | 30 |
| shop-change-email | 5 | 30 |

Bare caps are about 3 times bare's largest past spend. Compass caps are about
its largest past spend, so one run cannot take most of the budget. The harness
checks a cap between turns, so a run can go a few dollars over it.

`PILOT_STOP_USD=80` stops the script from starting a new run once the runs so
far have spent $80, session plus approver.

## How the approver is simulated

**The bench approves on a person's behalf.** No person reads or answers any
request in this pilot. Every approval in a Compass record from this pilot is
the bench's, and it names the approver `sdd-bench-approver` so that no reader
takes it for a person's.

The multi-round runner sends a model approver the session's last message, and
the approver answers in text, as a product owner would. That is not enough on
8.x, which records an approval in only two ways:

- A person types `/compass:approve`. The hook refuses it in a `claude -p`
  session, because Claude Code reports `CLAUDE_CODE_ENTRYPOINT` as `sdk-cli`
  there (Compass `cli/compass_pkg/prompt_approval.py`, ADR-068 decision 2).
- A person runs `compass evidence approve` in a terminal. The verb refuses
  unless standard input is a terminal (`cli/compass_pkg/approve_cmd.py`).

Without a change, a Compass session on `shop-change-email` asks for the
sign-off, gets a text reply, and cannot ship: `compass check` fails
`human-approval-present` for a `personal-data` change. The same holds for the
checkpoint hand-offs that the full route waits at.

`tools/compass-harness-pilot.patch` makes the runner act as the person at a
terminal. Before it asks the model approver, it looks for the issue's pending
approval request files. For each one it has not answered yet, it runs the
command that `compass evidence request` prints for a host with no prompt path,
under a pseudo-terminal:

```
compass evidence approve --issue <slug> --<form> <value> \
  --approver sdd-bench-approver --role owner --scope "<scope>"
```

It then tells the session it approved. The record holds `via: terminal` and
`approver: sdd-bench-approver`. The run record lists these approvals under
`multi_round.terminal_approvals`. The terminal verb does not close the request
file, so the runner keeps its own list of answered requests and answers each
one once.

The patch also adds `SDD_KEEP_WORKSPACE`. The harness deletes each run's
repository when the run ends, and the record keeps only the manifest text,
not the evidence files or `.git`. With the setting, the runner copies the
repository to `<dir>/<scenario>-<condition>-<run>/` when the session ends,
before the hidden tests are copied in, so the checker can read it.

### Checked with a stand-in for `claude`

Both additions were run on `v8.0.4` with the harness's `--claude` option
pointing at a stand-in that calls no model. The stand-in asks for the G5
sign-off with `compass evidence request` on a `personal-data` issue, writes
the reference change and stops. In that run:

- the runner answered request 1 once, with exit 0, then asked the model
  approver (also the stand-in), which said the session was not waiting;
- the manifest holds `EV-APPROVAL-G5-1`: `human-approval`, `guardrail: G5`,
  `approver: sdd-bench-approver`, `role: owner`, `decision: approved`,
  `via: terminal`;
- the kept copy holds `.git` with the session's commit, and no hidden tests;
- the checker read the kept copy and passed `approvals`.

No run with a real model has used either addition yet.

## Cost estimate

No run of 8.x on this bench exists, so the estimate uses two earlier
measurements. Totals are session plus approver.

| Scenario | Bare, per run | Compass, per run | Source |
|---|---|---|---|
| shop-idempotency | $0.34 - $1.45 | $0.43 - $0.44 | `docs/results-2026-10-10-multi-round.md:15-16`; spike baseline `SUMMARY.md:48-49` |
| shop-tracing | $0.93 - $3.63 | $36.20 - $50.90 (not run) | `docs/results-2026-10-10-multi-round.md:17-18`; spike baseline `SUMMARY.md:44-45` |
| shop-forget-user | $0.59 - $2.69 | $12.98 - $30.20 | `docs/results-2026-10-10-multi-round.md:19-20`; spike baseline `SUMMARY.md:46-47` |
| shop-change-email | $0.34 - $1.45 | $10 - $30 | no run; guessed from idempotency (bare) and forget-user (Compass, the same full route) |

The 10 Oct figures are for Compass 6.0.0 plus 3 commits and leave out the
approver ($0.02-0.14 a run, `docs/results-2026-10-10-multi-round.md:22`). The
spike baseline is Compass at `1776a1dc`, before 6.1.0, and is kept outside
this repository (`spikes/results/base/SUMMARY.md`, cell means and ranges).

For the 12 runs:

- bare, 8 runs: $4 - $18;
- Compass, 4 runs: $24 - $61, and up to about $66 at the caps;
- in all: about $28 - $79, inside the $80 budget. `PILOT_STOP_USD` holds the
  total if 8.x costs more than the earlier measurements.

Compass 8.x has changed since both measurements. The one-unit breakdown landed
(measured -19.8% in the cost spikes), and other changes have not been
measured. The range can move either way.

## What the checker should report on 8.x

- `test-digests`: `not-checkable` on every run. 8.x records store `tree_id`,
  `changes_id` and a digest over re-serialized JSON, not a digest of each
  test file.
- `request-link`: `fail` on every run. A bench prompt has no GitHub issue to
  link, and 8.x does not require one. This is accepted for the pilot. **The
  9.0.0 run must supply a request link**, for example by giving each scenario
  an issue that the runner sets with `compass issue link set`. Otherwise the
  check fails on every run there too.
- `land-commit`: `fail` on a run that does not reach ship. On a run that
  ships, it can pass in the bench, because the harness repository has no
  squash merge.
- `red-before-green` and `approvals`: either way. These are the two checks
  the pilot is for.
