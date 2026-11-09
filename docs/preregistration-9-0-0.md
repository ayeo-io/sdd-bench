# Pre-registration: Compass 9.0.0 on sdd-bench (draft)

**Status: draft.** The owner reviews this file before it is pushed. It becomes the pre-registration when it is committed and pushed before the first paid run, and it does not change after that. Every value marked **TO CONFIRM** must be settled before then.

This measurement is ayeo-io/compass-delivery#361 [Run the pre-registered sdd-bench measurement on the 9.0.0 release candidate]. It follows the 8.x pilot (`docs/pilot-8x.md`, results in `docs/results-2026-10-31-pilot-8x.md`), which set the run count and found that the harness had to supply a request link and let a session reach ship.

## Questions

1. What does a Compass 9.0.0 session cost, in tokens and dollars, to reach the target of each scenario, compared with a session with no framework (bare)?
2. Does it reach the target as often, and in as many rounds?
3. Does a Compass session that reaches the target leave a record that `tools/check_record.py` passes, reading only the files the run left behind?

## What runs

| | |
|---|---|
| Arms | `bare`, and `compass` at the 9.0.0 release candidate, commit **TO CONFIRM** (local branch `v9`, tip `af632567` on 9 Nov 2026; tag name **TO CONFIRM**, `tools/run-9-0-0.sh` defaults to `v9.0.0`) |
| Scenarios | `shop-idempotency`, `shop-tracing`, `shop-forget-user`, `shop-change-email`, at the bench commit that adds this file |
| Runs | 6 per arm per scenario, 48 in all |
| Order | Interleaved: run 1 of every cell, then run 2, and so on. Within a run number, scenario by scenario, bare then Compass. A stop at the budget leaves every cell with the same number of runs, give or take one. |
| Runner | `tools/harness.py` at the bench commit. The harness no longer lives in Compass (#354), so the runner is not part of the framework under test. |
| Model | `claude-opus-5-5`, pinned in the harness. Claude Code version **TO CONFIRM** (recorded in `RUN.yml`). |
| Command | `bash tools/run-9-0-0.sh` |

The pilot showed bare varying by up to 3x between two runs of one cell, so one run per cell cannot separate a 1.5x result from noise. Six runs per cell, reported as medians with their range, is the plan the pilot kept.

## How a run goes

Each run is one Claude Code session in a fresh git repository made from the scenario's seed.

1. **The request.** The prompt is the scenario's `prompt:` text. Its last line links the request, for example `Request: https://github.com/acme-shop/shop/issues/41 (from Sam Taylor)`. Both arms see the same text. 9.0.0 asks for the request link at assess (#356), so the Compass session records it itself.
2. **Rounds to the target.** After each round, `tools/score.py` scores the working tree. Short of the target, the session gets one scripted report from the scenario's `feedback.yml`, at most 8 rounds. A model approver (Sonnet, no tools) answers when the session stops to ask a question, and the runner approves pending Compass approval requests at a pseudo-terminal, as a person would.
3. **The ship phase.** It runs only for a run at target with budget left:
   1. The harness sends both arms the commit message below, up to 3 times, until the session has committed and is not waiting on the person. No commit gives `ship.stop: "no commit"`.
   2. The harness squash-merges the session's branch into `main` with git plumbing (`commit-tree`, `update-ref`), and does not touch the working tree. A commit made straight on `main` is recorded as a fast-forward.
   3. The harness writes the merged pull request and one approving review into the fake GitHub.
   4. The harness sends both arms the merged message below. Compass's post-merge step (`compass issue link set --pr <n>`) then reads the pull request and its review through the fake GitHub, and records the ship approval. Its tokens count: they are the cost of the record.

### The fixed messages

From `scenarios/ship-messages.yml`, the same for both arms:

- Commit: "That is what I asked for. Commit it on a new branch; I will open the pull request and review it."
- Merged: "I reviewed and approved pull request #{number} ({url}) and merged it into main as {sha8}. Anything left on your side?"

### The request and the pull request

| Scenario | Request | Requester | Pull request |
|---|---|---|---|
| shop-idempotency | acme-shop/shop#41 | Sam Taylor | #42 |
| shop-tracing | acme-shop/shop#47 | Priya Shah | #48 |
| shop-forget-user | acme-shop/shop#53 | Alex Morgan | #54 |
| shop-change-email | acme-shop/shop#58 | Jordan Lee | #59 |

`acme-shop/shop` is a made-up name. **TO CONFIRM:** that no repository of that name exists on GitHub. The fake GitHub answers for it either way, so a run never reads a real repository.

### The fake GitHub

GitHub is a stand-in, `tools/fake_gh.py`, for both arms:

- A `gh` wrapper comes first on the session's `PATH`, with `GH_CONFIG_DIR` naming an empty folder and no `GH_TOKEN` or `GITHUB_TOKEN`, so no command in the session can use the real `gh` or the owner's login.
- It answers `gh pr view`, `gh issue view`, `gh api user` and `gh api repos/<r>/pulls/<n>` and `.../reviews`, from a state file the harness writes. It answers no write and nothing else, logs every call, and never runs the real `gh`.
- The repository's `origin` is `https://github.com/acme-shop/shop.git`. Its push URL is a local bare repository, so a push cannot reach GitHub.

### Who approves

**No person reads or answers anything in this measurement.** Every approval in a record is the bench's, and names a bench identity so that no reader takes it for a person's:

- The pull request is opened by `sdd-bench-author`, the login the fake GitHub reads as.
- It is reviewed and approved by `sdd-bench-approver`, a minute before the merge.
- The runner's terminal approvals also name `sdd-bench-approver`, with role `owner`. The Compass arm's seed holds `compass.yml` with `owner: sdd-bench-approver`, so these name a project approver. The pilot's full-route sessions spent 5 or 6 rounds on approvals the runner could not give without it.

## Outcomes

Primary, per run:

- tokens, and dollars (session plus approver), in total and for the ship phase alone;
- whether the working tree reached the target (the pilot's rule), and in how many rounds.

Secondary, per run:

- `ship.stop`, and whether the merged tree on `main` is also at target (`merged_tree_at_target`). A difference from the working-tree result is reported, not hidden;
- for each Compass run, the six verdicts of `tools/check_record.py --branch main --base <seed> --expect-request <the scenario's request> --require-ship-approval`: red-before-green, test-digests, request-link, approvals, land-commit and ship-approval;
- any change the session made to `compass.yml`, which the run records and the summary shows.

## Analysis

- Each cell is reported as the median and the range of its runs, with the number of runs.
- The cost result is the ratio of the Compass median to the bare median, per scenario.
- Reach is reported as runs at target out of runs started. A run that does not reach target has no ship phase and counts as a miss. The record criterion applies to Compass runs that reached target.
- The thresholds that would count as a pass or a fail for 9.0.0 are **TO CONFIRM** with #361. This draft states none, because none is sourced.
- Runs are not dropped. A run that fails for a reason outside the session (a harness error, an API outage) is reported with its reason and run again once, at the end.

## Budget

The approved budget is about **$150 to $400** (#361). `STOP_USD=400` stops the script from starting a new run once the runs so far have spent that much, session plus approver.

Caps per run, for the session, ship phase included (`SDD_RUN_BUDGET`), **TO CONFIRM**:

| Scenario | Bare | Compass |
|---|---|---|
| shop-idempotency | 5 | 6 |
| shop-tracing | 10 | 60 |
| shop-forget-user | 8 | 35 |
| shop-change-email | 15 | 35 |

The harness checks a cap between turns, so a run can go a few dollars over it.

What the pilot (Compass 8.0.4) spent per run, session plus approver:

| Scenario | Bare | Compass 8.0.4 |
|---|---|---|
| shop-idempotency | $0.33, $0.75 | $0.40, $0.68 |
| shop-tracing | $2.09, $2.19 | not run; $36 to $51 before 6.1.0 |
| shop-forget-user | $0.52, $1.30 | $18.61 |
| shop-change-email | $1.16, $6.49 | $27.19 |

If 9.0.0 costs what 8.0.4 cost, with Compass `shop-tracing` at the middle of its earlier range, one run of every cell costs about $97, and 6 runs about **$580**, above the budget; the stop would end the run near run 4. 9.0.0 runs one path of four stages (ADR-092), so it may cost less; it has not been measured. **TO CONFIRM:** whether to keep 6 runs and accept a stop, or to cut the Compass `shop-tracing` cell as the pilot did. The ship phase adds a cost that has not been measured (**TO CONFIRM** after the smoke test).

Duration: the pilot's runs took 78 to 332 seconds bare and 98 to 795 seconds with Compass. With a Compass `shop-tracing` run at about 15 minutes (**TO CONFIRM**), one run of every cell takes about an hour, and 48 runs about 6 hours, one after another, plus the ship phase.

## Before the paid run

1. **$0, done.** A stand-in `claude` (`tools/standin_claude.py`) ran the ship phase against the 9.0.0 release candidate, in three runs:
   - `shop-idempotency`, Compass: it linked the request, landed the change on a branch with `compass quick-fix finish`, and ran `compass issue link set --pr 42` after the merged message. The fake GitHub logged the three expected calls. The land commit, read from git because the record landed with the code, was the squash commit at the tip of `main`. The checker passed all six checks, and failed a copy that was wrong on purpose on four of them.
   - `shop-change-email`, Compass: it asked for the scenario and `G5` sign-offs, which the runner approved at the terminal, and committed with git. The checker passed the approvals and the ship approval, and failed land-commit, because the stand-in does not do the full route's reviews and the issue did not land.
   - `shop-idempotency`, bare: it committed on a branch; the harness merged it, and the fake GitHub logged no call.
2. **Smoke test, about $1 to $3:** `shop-idempotency`, one bare run and one Compass run, on the release candidate.
3. **Smoke test, about $3 to $35:** `shop-change-email`, one bare run and one Compass run. It is the only scenario with a sign-off.

The record shape the checker reads must match what the release candidate writes before this file is pushed.

## Limits

- The fake GitHub is not GitHub. A framework that reads more of GitHub than Compass's post-merge step does gets an exit 1, which the run log shows.
- The squash merge takes the branch's tree as it is. GitHub would merge it with any later commit on `main`; the record shows `main_moved` when that differs.
- The bench approves on a person's behalf. The measurement says nothing about how a person would answer.
- The ship messages ask for a commit on a branch. A framework that does not commit, or commits only on `main`, is recorded as such.
