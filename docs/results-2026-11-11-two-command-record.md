# The two-command record on sdd-bench: results, 11 November 2026

This is the measurement that `docs/plan-2026-11-11-two-command-record.md` planned, for ayeo-io/compass-delivery#361 [Run the pre-registered sdd-bench measurement on the 9.0.0 release candidate]. Compass was measured at commit `ac859818`, the release build of the two-command record. Bare and Compass ran side by side in the same run.

## Result

**This build passes the #361 rule on all 4 scenarios.**

| Rule (#361), on every scenario | Result |
|---|---|
| Compass median tokens at most 1.5x bare | pass on 4 of 4: 0.61x to 1.48x |
| Compass reaches the target in at least bare's runs, less one | pass on 4 of 4: Compass 12 of 12, bare 11 of 12 |
| Every Compass record passes `tools/check_record.py` | pass: 12 of 12 records, all six checks |

`shop-idempotency` passes by a small margin: 1.48x against the limit of 1.5x. See "How firm the result is".

## Bare, Compass 8.0.4, the failed 9.0.0 candidate and this build

Tokens are medians of 3 runs, in millions, ship phase included. Each ratio is against the bare median of the same measurement.

| Scenario | Bare (this run) | 9.0.0 candidate `71efbb89`, 10 Nov | Experiment `e60a2a13`, 10 Nov | This build `ac859818` |
|---|---|---|---|---|
| shop-idempotency | 0.42M | 1.67M (3.6x) | 0.59M (1.28x) | 0.61M (1.48x) |
| shop-tracing | 1.10M | 12.22M (11.3x) | 1.28M (1.18x) | 1.45M (1.32x) |
| shop-forget-user | 1.23M | 9.05M (14.2x) | 0.82M (1.29x) | 0.75M (0.61x) |
| shop-change-email | 1.12M | 13.31M (12.1x) | 0.85M (0.77x) | 0.86M (0.76x) |

The 9.0.0 candidate and the experiment used the bare runs of 10 November (medians 0.46M, 1.08M, 0.64M and 1.10M) for their ratios. The experiment's Compass runs did not run beside bare runs.

Compass 8.0.4 was measured in the pilot without a ship phase, so the like-for-like comparison uses the tokens before the ship phase. This table is for context and decides nothing.

| Scenario | Bare, before ship (this run) | 8.0.4, before ship (pilot) | 9.0.0 candidate, before ship | This build, before ship |
|---|---|---|---|---|
| shop-idempotency | 0.23M | 0.27M (1.4x its own bare) | 1.27M (5.5x) | 0.54M (2.4x) |
| shop-tracing | 0.78M | not run | 12.22M (15.6x) | 1.28M (1.6x) |
| shop-forget-user | 0.97M | 5.65M (13.1x its own bare) | 6.31M (21.1x) | 0.61M (0.6x) |
| shop-change-email | 0.78M | 6.69M (5.3x its own bare) | 9.48M (12.7x) | 0.77M (1.0x) |

Before the ship phase, Compass costs more than bare on the two smaller scenarios, because the record is written there. Compass then spends less than bare in the ship phase, because `finish` has already committed.

## Runs

24 runs, 3 per arm per scenario. Total spend about $110, approver included, against a stop of $150.

| Scenario | Bare tokens (3 runs) | Compass tokens (3 runs) | Bare at target | Compass at target | Compass records that pass |
|---|---|---|---|---|---|
| shop-idempotency | 0.42M, 0.42M, 0.42M | 0.42M, 0.61M, 0.61M | 3 of 3 | 3 of 3 | 3 of 3 |
| shop-tracing | 2.16M, 1.10M, 0.67M | 2.74M, 1.39M, 1.45M | 3 of 3 | 3 of 3 | 3 of 3 |
| shop-forget-user | 1.23M, 0.81M, 1.42M | 1.53M, 0.75M, 0.72M | 3 of 3 | 3 of 3 | 3 of 3 |
| shop-change-email | 0.55M, 1.98M, 1.12M | 0.86M, 0.59M, 1.67M | 2 of 3 | 3 of 3 | 3 of 3 |

All 12 Compass runs merged, and each merged tree is at target. Three bare runs did not finish the ship phase:

- `shop-tracing` run 1 reached the target at its spending limit and did not ship, so its 2.16M has no ship phase;
- `shop-forget-user` run 3 stopped at its spending limit in the ship phase;
- `shop-change-email` run 2 did not reach the target in 4 rounds.

The Compass sessions made 16 to 58 tool calls, of which 3 to 14 were `compass` commands. Bare made 13 to 54 tool calls. On the 9.0.0 candidate the Compass sessions made 43 to 263 tool calls, of which 16 to 133 were `compass` commands.

## How firm the result is

- **`shop-idempotency` is close to the limit.** Two of the three Compass runs are at 1.48x. The bare runs barely vary (0.42M each), so this ratio is steady, and a small added cost would fail the rule. The fixed cost of the record is about 0.2M tokens, and this is the smallest scenario.
- **`shop-tracing`:** the Compass runs range from 1.27x to 2.50x of the bare median, so the range crosses 1.5. Bare ranges from 0.61x to 1.97x of its own median.
- **`shop-forget-user` and `shop-change-email`:** the 0.61x and 0.76x say that Compass is no more expensive than bare. They do not show that it is cheaper: bare varies by 2x to 3x between runs of one scenario, and the bare `shop-forget-user` median was 0.64M on 10 November and 1.23M here.
- A median of 3 runs separates a 1.5x result from noise less well than the 6 runs that #361 first asked for.

Each run's record and checker output is in the run folder `two-command/runs/`, with `SUMMARY.md` beside it.
