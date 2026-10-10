# The quality part of every target

Each scenario's `target.md` lists the behaviours it needs. Every scenario
also needs the following, because production code needs them. `tools/score.py`
checks all of it; a tree is at target only when every part passes.

| Part | What good looks like | How it is checked |
|---|---|---|
| Regression | Nothing that worked before is broken | The seed's own tests, as shipped, pass |
| Own tests | The project's suite passes | `pytest` on the tree's tests |
| Static | The new code is fully typed, lint-clean and documented | `mypy --strict shop` and `ruff check` (the seed's `ruff.toml`) report nothing on added lines |
| Coverage | Every new line runs under the project's own tests, error paths included | At least 90% of added executable lines in `shop/` run under the tree's own tests |
| Tests that bite | The tests fail when the new behaviour breaks | At least 80% of small bugs planted in the added lines (flipped comparisons, deleted statements, negated conditions, changed constants, `return None`) make the tree's own tests fail |
| Conventions | The seed's `docs/CONVENTIONS.md` holds | Services do not import each other; no handler swallows every error; no name or email reaches the log, the audit trail or an event |

The bars are set from the reference solutions, which reach them (coverage
100%, planted bugs caught 83-96%). Some planted bugs change nothing a test
could see, so 100% is not the aim.

The score holds the change to the bar, not the seed: static findings,
coverage and planted bugs count only on lines the change added.

What the target leaves open: names of events, helpers and modules, class
layout, and how the work is split across files. Two different designs that
both meet every criterion are both at target.
