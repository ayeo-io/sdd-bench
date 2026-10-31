# Pilot on Compass 8.0.4: results, 31 October 2026

This pilot measured two things before the 9.0.0 run (ayeo-io/compass-delivery#349):

- how much the bare arm varies between runs;
- whether the file-only record checker, `tools/check_record.py`, works on real Compass records.

It is not the pre-registered measurement. It has 1 or 2 runs per cell, and no Compass run on `shop-tracing`. The plan and its reasons are in `docs/pilot-8x.md`.

## Runs

12 runs, all at target. Total spend $61.71: bare $14.83, Compass $46.88, approver included.

| Scenario | Bare tokens (r1, r2) | Compass tokens | Compass route | Compass / bare median |
|---|---|---|---|---|
| shop-idempotency | 0.23M, 0.15M | 0.25M, 0.28M | quick fix | 1.4x |
| shop-forget-user | 0.55M, 0.31M | 5.65M | full | 13.1x |
| shop-change-email | 0.63M, 1.88M | 6.69M | full | 5.3x |
| shop-tracing | 0.97M, 0.90M | not run | | |

The source is `~/dev/sdd-bench-runs/pilot-8x/SUMMARY.md` and the run records beside it.

## Bare spread

Between its two runs, bare moved by:

- 3.0x on `shop-change-email`;
- 1.8x on `shop-forget-user`;
- 1.5x on `shop-idempotency`;
- 1.1x on `shop-tracing`.

A spread of 3x between two runs of the same arm means one run per cell cannot separate a 1.5x result from noise. The full run keeps 6 runs per arm per scenario, with medians.

## What the checker found

| Check | Quick fix (2 runs) | Full route (2 runs) |
|---|---|---|
| red-before-green | pass | fail: one red for the whole suite, none per scenario |
| test-digests | not checkable | not checkable |
| request-link | fail | fail |
| approvals | pass | fail: 3 of 5 missing (the `personal-data` sign-off, refine and plan checkpoints) |
| land-commit | fail | fail |

What each result means:

- **red-before-green.** On the full route, each session recorded one red and one green for the whole suite, not one per scenario. Compass 8.x accepted that. This is the gap in ayeo-io/compass-delivery#347.
- **test-digests.** 8.x records hold a git tree id and a digest over re-serialized JSON, so no digest can be checked against a file. This is expected and is ayeo-io/compass-delivery#348.
- **request-link.** The bench prompts carry no issue link. The 9.0.0 run must supply one.
- **approvals.** Neither full-route session reached ship. Each stopped after the change was green and asked whether to commit. So the `personal-data` sign-off was never requested, and the refine and plan checkpoints were left open.
- **land-commit.** No run in either arm commits, because the harness ends the session before a commit. The 9.0.0 run must let the session commit and record its PR, or the checker must read `land_commit` from the result branch the harness makes.

## What this changes for the 9.0.0 run

- Keep 6 runs per cell.
- The harness must give each Compass session a request link, and let it reach ship.
- The checker's red-before-green message must say when a red exists but names no scenario, rather than "no red on record".
