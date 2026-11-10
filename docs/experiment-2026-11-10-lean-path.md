# Experiment: a lean Compass path, 10 November 2026

The 9.0.0 measurement (`docs/results-2026-11-10-9-0-0.md`) failed the token rule on every scenario. This experiment tests one cause and one fix. It is not a release measurement.

## What it tests

In the measured runs, a Compass session made 18 to 108 `compass` commands, most of them record keeping done by hand. The experimental branch of Compass (`exp-lean`, from `71efbb89`) does that record keeping itself:

- one command starts the issue;
- one command at the end proves that the tests fail without the change and pass with it, records the changed files from git, and asks for the ship approval;
- the approval of the scenarios before code, for labeled work, stays;
- the ship approval by a person stays.

## Runs

- Scenarios: `shop-idempotency` and `shop-tracing`.
- Arm: Compass at the tip of `exp-lean`, 2 runs per scenario. The bare arm is not run again: the 3 bare runs per scenario of 10 November are the baseline, on the same harness, model and Claude Code version.
- Spending limit per run: $6 on `shop-idempotency`, $25 on `shop-tracing`.
- The harness and `tools/check_record.py` are unchanged.

## Stop rule, fixed before the runs

- If the median Compass tokens on `shop-tracing` are above 3 times the bare median (1.08M, so above 3.24M), the lean path has failed. Work on it stops, and the owner chooses between abandoning Compass and cutting it to the approval gate.
- If it is at or below 3 times, and the records pass the checker, the next step is a run on all four scenarios.

The results are written up either way, with every run.
