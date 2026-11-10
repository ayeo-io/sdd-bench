# Lean path on all four scenarios: plan, 10 November 2026

The lean-path experiment (`docs/results-2026-11-10-lean-path.md`) passed its stop rule. This run measures the lean path on all four scenarios against the pass rule of ayeo-io/compass-delivery#361. This plan is written before the first run.

## What runs

- Compass at `e60a2a13`, the tip of the experimental branch `exp-lean`. Since the first experiment it has two changes: a request that already has an issue reuses it, and `finish` commits by itself once the approvals are on record.
- Scenarios: `shop-idempotency`, `shop-tracing`, `shop-forget-user`, `shop-change-email`.
- 3 Compass runs per scenario, 12 in all. The bare arm is not run again: the 3 bare runs per scenario of 10 November (`docs/results-2026-11-10-9-0-0.md`) are the baseline, on the same harness, model and Claude Code version.
- Spending limit per run: $6, $25, $35 and $35. No new run starts once $100 is spent.
- The harness and `tools/check_record.py` are unchanged.

## Pass rule, unchanged from #361

On every scenario:

1. the median Compass tokens over the median bare tokens is at most 1.5;
2. Compass reaches the target in at least as many runs as bare, less one;
3. every Compass record passes `tools/check_record.py`.

The owner confirmed on 10 November that 1.5 stays. Tokens are the unit. The result is written up either way, with every run, beside the bare, 8.0.4 and 9.0.0 figures.

## Limits

- The bare baseline was run earlier the same day, not interleaved with these runs.
- `exp-lean` is an experiment branch. Its full test suite has not been run, and 135 or more of its existing tests fail because they assert the 9.0.0 behavior.
