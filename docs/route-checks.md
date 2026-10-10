# Route checks

A scenario names the route a process-adaptive framework should pick for it. Before a scenario is used for comparisons, it runs 4 times under such a framework and stays in the suite only if at least 3 runs take that route. This keeps each scenario measuring the route it was written for.

## 10 Oct 2026

Compass at 150501ef (6.0.0 plus 3 commits), model claude-opus-5-5, the eval harness from that commit, read-only bind mount of the plugin copy, one reply allowed per session. Bare is one run per scenario, to show a session with no framework can finish. Scenarios at b05c307.

| Scenario | Expected | Compass routes (4 runs) | Kept | Compass mean | Bare (1 run) | Hidden tests, Compass / bare |
|---|---|---|---|---|---|---|
| shop-idempotency | quick fix | quick fix x4 | yes | 225k tokens, 69 s, $0.29 | 170k, 51 s, $0.29 | 20/20, 5/5 |
| shop-tracing | regular | regular x4 | yes | 2,675k tokens, 341 s, $2.31 | 298k, 72 s, $0.38 | 24/24, 6/6 |
| shop-forget-user | full | full x3, unfinished assessment x1 | yes | 783k tokens, 151 s, $1.17 | 176k, 91 s, $0.32 | 0/32, 8/8 |

Every session was contained. Total $16.08.

## What the checks found

- **All three scenarios route as intended.** They can be used to compare routes.
- **shop-forget-user cannot be finished under the full route with one reply.** The full route stops at checkpoints for a person (after the acceptance criteria, for example), and the harness sends one reply. Every Compass session ended before writing code, so 0 of 32 hidden tests passed. One session also stopped earlier, waiting for approval of a command. This is a limit of the runner, not of the scenario: bare finished it and passed 8 of 8. Until the runner can answer more than one checkpoint, results on this scenario measure where a framework stops, not what it builds.
- **The regular route cost about 9 times bare on shop-tracing,** for the same hidden-test result. This is a first reading at 4 runs and 1 bare run, not a comparison result.
