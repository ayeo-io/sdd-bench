# sdd-bench

A benchmark for spec-driven development frameworks. It gives an AI coding session a realistic change to make, runs the same change with and without each framework, and measures cost, wall time and whether the result passes tests the session never saw.

It lives apart from any framework it measures, so the scenarios cannot be tuned to suit one of them.

## What is here

```
seeds/shop/        a small codebase shared by several scenarios
scenarios/<id>/    one task each: scenario.yml, a copy of the seed, hidden tests
reference/<id>/    a known-good solution, used only to check the scenario
tools/             checks that keep the scenarios honest
```

### The shop seed

Three services - users, orders and subscriptions - that share nothing but an in-memory event bus. Delivery is at least once and on demand (`bus.run_pending()`), so every run is deterministic: no network, threads or timers. `docs/CONVENTIONS.md` in the seed sets the house rules a careful session should find and follow.

### Scenarios

| Scenario | The task | Route a process-adaptive framework should pick |
|---|---|---|
| shop-idempotency | A retried `create_order` must not make a second order | quick fix: small, one service |
| shop-tracing | A trace id follows a request through every service and event | regular: cross-cutting |
| shop-forget-user | Delete a user and everything about them, across separate stores, without the user service knowing who holds data | full: personal data |

Each scenario's `expected_route` is a check on the scenario, not a score: a scenario stays in the suite only while most runs take that route (see `docs/route-checks.md`).

Hidden tests are copied in only after the session ends. They cover what a careful engineer would catch, such as a retry after a failed first attempt, two requests handled together, a duplicate message or a late write after a deletion.

## Checking the scenarios

```
python3 tools/check_scenarios.py --sync
```

This copies the shared seed into each scenario, then checks that the seed's own tests pass, that the hidden tests fail on the untouched seed, and that they pass with the reference solution. Run it after any change to a seed, a hidden test or a reference.

## Running a scenario

For now the runner is the eval harness in the Compass repository, which accepts a scenario directory by path:

```
python3 evals/harness.py --scenario /path/to/sdd-bench/scenarios/shop-tracing \
  --condition compass --runs 4 --out /path/to/results
```

Results name the framework, its commit and the model. The plan is to move the runner here, so every framework is run by code none of them owns.

## Rules

- Every framework, including Compass, is pinned to a commit for each run.
- A result is published with its scenario commit, framework commits, model, runs per cell and raw records.
- A scenario changes only with a reason in its history. Results from before and after a change are not compared.
