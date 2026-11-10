# Lean path on all four scenarios: results, 10 November 2026

The plan is `docs/plan-2026-11-10-lean-four-scenarios.md`. Compass was measured at `e60a2a13`, the tip of the experimental branch `exp-lean`. The bare baseline is the 3 bare runs per scenario in `docs/results-2026-11-10-9-0-0.md`.

## Result

**The lean path meets all three rules of ayeo-io/compass-delivery#361 on all four scenarios.**

| Rule, on every scenario | Result |
|---|---|
| Compass median tokens at most 1.5x bare | pass on 4 of 4: 0.77x to 1.29x |
| Compass reaches the target in at least bare's runs, less one | pass on 4 of 4: 12 of 12 runs at target and merged |
| Every Compass record passes `tools/check_record.py` | pass: 12 of 12 |

`exp-lean` is an experiment branch, not a release candidate. See "Limits".

## Bare, Compass 8.0.4, Compass 9.0.0 and the lean path

Median tokens, in millions, ship phase included, with the ratio to the bare median.

| Scenario | Bare | Compass 9.0.0 | Lean path | Lean runs |
|---|---|---|---|---|
| shop-idempotency | 0.46M | 1.67M (3.6x) | 0.59M (1.28x) | 0.63M, 0.39M, 0.59M |
| shop-tracing | 1.08M | 12.22M (11.3x) | 1.28M (1.18x) | 1.18M, 1.28M, 1.33M |
| shop-forget-user | 0.64M | 9.05M (14.2x) | 0.82M (1.29x) | 0.82M, 0.70M, 3.13M |
| shop-change-email | 1.10M | 13.31M (12.1x) | 0.85M (0.77x) | 1.02M, 0.85M, 0.63M |

Compass 8.0.4 was measured only before the ship phase (the pilot, 1 or 2 runs per cell). On that basis:

| Scenario | Bare, before ship | 8.0.4 | 9.0.0 | Lean path |
|---|---|---|---|---|
| shop-idempotency | 0.23M | 0.27M (1.4x its bare) | 1.27M (5.5x) | 0.51M (2.2x) |
| shop-tracing | 0.78M | not run | 12.22M (15.6x) | 1.17M (1.5x) |
| shop-forget-user | 0.30M | 5.65M (13.1x its bare) | 6.31M (21.1x) | 0.73M (2.4x) |
| shop-change-email | 0.75M | 6.69M (5.3x its bare) | 9.48M (12.7x) | 0.77M (1.0x) |

The lean path's ratios are higher before the ship phase than with it because it commits before the ship phase starts. Bare commits in the ship phase. The total, ship included, compares the same work.

## Runs

12 runs. Total spend $56.61, approver included.

| Scenario | `compass` commands per run | All tool calls per run | Rounds | Cost per run |
|---|---|---|---|---|
| shop-idempotency | 3 to 4 | 13 to 21 | 1 | $1.46 to $2.40 |
| shop-tracing | 5 | 40 to 46 | 3 | $4.68 to $5.00 |
| shop-forget-user | 4 to 7 | 23 to 67 | 1 to 3 | $3.33 to $19.60 |
| shop-change-email | 4 to 7 | 18 to 35 | 1 to 2 | $2.67 to $3.70 |

Both `personal-data` scenarios have all 3 required approvals on every record: the scenarios approved before the code, the `G5` sign-off, and the ship approval.

## Limits

- **One run is far from the others.** `shop-forget-user` run 3 used 3.13M tokens, 4.9 times bare, over 3 rounds. The median of 3 runs passes; with 3 runs the range crosses 1.5.
- **The bare baseline was run earlier the same day**, not interleaved with these runs.
- **`exp-lean` removes more than record keeping by hand.** On this branch no change owes the agent-written reviews, the Definition of Done or the four-layer acceptance evidence, at any risk. A feedback round keeps the first ship approval. The red shows that the tests fail without the change, not that they were written first.
- **The branch is not release quality.** Its full test suite has not been run, and at least 135 existing tests fail because they assert the 9.0.0 behavior.
