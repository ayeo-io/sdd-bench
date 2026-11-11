# Compass with the two-command record: measurement plan, 11 November 2026

This run measures the version of Compass that is proposed as 9.0.0 after the release candidate failed (`docs/results-2026-11-10-9-0-0.md`). It applies the pass rule of ayeo-io/compass-delivery#361 [Run the pre-registered sdd-bench measurement on the 9.0.0 release candidate]. This plan is committed and pushed before the first run.

## What changed since the last runs

The experiment branch that passed on 10 November (`docs/results-2026-11-10-lean-four-scenarios.md`) was rebuilt as release code. Compared with the experiment:

- an approval covers the change the person saw: after a later change the check fails until a person approves again;
- `critical` risk owes the approval of the scenarios before code again;
- a project setting can add evidence back;
- facts that the shortened instructions had lost are restored. The text every session loads went from 275 to 342 words;
- `finish` refuses or reports files that were committed by hand or left untracked without a record.

Each of these can change the token cost, so the experiment's result does not carry over.

## What runs

- Arms: bare, and Compass at commit `ac859818` (branch `exp-lean` of the Compass repository; it becomes the v9 branch if this run passes).
- Model `claude-opus-5-5`, Claude Code `2.1.321`, as in the earlier runs.
- Scenarios: `shop-idempotency`, `shop-tracing`, `shop-forget-user`, `shop-change-email`.
- 3 runs per arm per scenario, 24 in all, both arms side by side: within a run number, scenario by scenario, bare then Compass.
- Spending limit per run: bare $5, $10, $8, $15; Compass $6, $25, $35, $35. No new run starts once $150 is spent.
- The harness and `tools/check_record.py` are as in `docs/preregistration-9-0-0.md`.

## Pass rule, unchanged

On every scenario:

1. the median Compass tokens over the median bare tokens is at most 1.5;
2. Compass reaches the target in at least as many runs as bare, less one;
3. every Compass record passes `tools/check_record.py`.

Tokens are the unit; dollars decide nothing. Runs are not dropped. A run that fails for a reason outside the session is reported and run again once. The result is published either way, with every run, beside the bare, 8.0.4, 9.0.0 release candidate and experiment figures. With 3 runs per cell, the report names any scenario whose range of runs crosses 1.5.
