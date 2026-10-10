# Multi-round run to the target, 10 Oct 2026

Both conditions run until the tree is at target (`target.md` plus
`docs/target-quality.md`), or 8 rounds, or the run's budget. Checkpoints are
approved by the runner, standing in for a product owner who knows only the
request. One run per cell, so this shows what happens, not how much it varies.

Compass at 150501ef (6.0.0 plus 3 commits), model claude-opus-5-5, harness
from that commit with `tools/compass-harness-multi-round.patch` applied,
read-only bind mount of the plugin copy, scenarios at 3833ffd (idempotency
I6 corrected afterwards, see below). Every session was contained.

| Scenario | Condition | Reached target | Rounds | Approvals | Cost | Tokens | Wall time |
|---|---|---|---|---|---|---|---|
| shop-idempotency | bare | yes | 1 | 0 | $0.34 | 0.22M | 90 s |
| shop-idempotency | compass | yes | 1 | 0 | $0.43 | 0.34M | 113 s |
| shop-tracing | bare | yes | 2 | 0 | $0.93 | 0.53M | 168 s |
| shop-tracing | compass | yes | 4 | 4 | $36.20 | 9.89M | 1,260 s |
| shop-forget-user | bare | yes | 1 | 0 | $0.59 | 0.42M | 147 s |
| shop-forget-user | compass | yes | 1 | 1 | $12.98 | 12.48M | 976 s |

Approver cost is not in these figures: $0.02-0.14 a run.

## What it shows

- Both conditions reach production-grade code on all three scenarios.
- On the quick-fix route, Compass costs about the same as bare (1.3x).
- On the regular route (tracing), Compass took 4 rounds and 39x bare's cost.
  A first Compass tracing run stopped at its $15 cap after one round, 5 of 7
  criteria, $18.75; it is not in the table.
- On the full route (forget a user), Compass reached target in one round, as
  bare did, at 22x bare's cost and 6.6x its wall time.
- The approver granted process waivers Compass asked for (building as one
  unit instead of the multiagent split). A person in the loop would have
  been asked the same thing.

## Corrections made during the run

- I6 first required a request id reused by another user to be refused.
  Treating ids as each user's own is an equally sound design, and the bare
  run did that; the target and its bug report now accept either. Under the
  old test that run went 8 rounds without progress. It was re-run under the
  corrected target and is the row above.
- Unknown ids: the conventions now say an operation on an unknown id raises
  `UnknownUser`. Without that, the target's choice was not discoverable.
- The runner now stops a run as stuck after the same report three times.
