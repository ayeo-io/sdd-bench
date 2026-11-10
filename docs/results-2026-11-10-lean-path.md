# Lean-path experiment: results, 10 November 2026

The plan and stop rule are in `docs/experiment-2026-11-10-lean-path.md`. Compass was measured at `b5881102`, the tip of the experimental branch `exp-lean`. The bare baseline is the 3 bare runs per scenario in `docs/results-2026-11-10-9-0-0.md`.

## Result

**The lean path passes the stop rule.** On `shop-tracing` its median is 2.20M tokens, which is 2.0 times bare (1.08M) and below the 3.24M limit. It does not yet meet the 1.5x release rule of ayeo-io/compass-delivery#361.

| Scenario | Bare median | Compass 9.0.0 median | Lean runs | Lean median | Lean vs bare |
|---|---|---|---|---|---|
| shop-idempotency | 0.46M | 1.67M (3.6x) | 0.67M, 1.40M | 1.04M | 2.2x |
| shop-tracing | 1.08M | 12.22M (11.3x) | 2.25M, 2.15M | 2.20M | 2.0x |

Tokens include the ship phase. Before the ship phase, the lean medians are 0.79M against bare 0.23M on `shop-idempotency` (3.4x; the two runs are 0.36M and 1.22M) and 1.78M against bare 0.78M on `shop-tracing` (2.3x).

## Runs

4 runs, all at target and merged. Total spend $25.79, approver included.

| Run | Tokens | Rounds | `compass` commands | All tool calls | Record |
|---|---|---|---|---|---|
| shop-idempotency r1 | 0.67M | 1 | 7 | 20 | passes all six checks |
| shop-idempotency r2 | 1.40M | 2 | 8 | 35 | passes all six checks |
| shop-tracing r1 | 2.25M | 3 | 11 | 63 | fails: 2 of 2 test digests do not match on the first of two issues |
| shop-tracing r2 | 2.15M | 3 | 11 | 61 | passes all six checks |

The 9.0.0 runs made 16 to 22 `compass` commands on `shop-idempotency` and 87 to 119 on `shop-tracing`, and no `shop-tracing` record passed.

## What is left

- **A shipped issue cannot take feedback.** In `shop-tracing` r1 the session committed the issue in round 1. When the next report came, it started a second issue for the same request, and its later test edits left the first issue's digests out of date. `finish` must reopen the issue.
- **`shop-idempotency` r2 used a second round** because the first round left a `mypy --strict` error. Bare did not make this error in its 3 runs. Two runs cannot say whether this is chance.
- **The count of `compass` commands is 7 to 11, not the 3 to 4 of the design.** The extra ones are a second `finish` and `status` calls.
- Two runs per scenario separate 2.0x from 1.5x poorly. The tracing result is clear against the 3x stop rule; the small-fix result is not clear against 1.5x.
