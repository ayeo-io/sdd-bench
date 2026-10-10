# Feedback between rounds

A multi-round run sends a session one follow-up after each round that
leaves the tree short of its target. The follow-up is a scripted report,
written as a tester, a reviewer or a user would raise it: it describes a
symptom, never which hidden test failed and never how to fix it.

Rules:

- After a round, `tools/score.py` finds what is not met. The runner sends
  the first report in the scenario's `feedback.yml` whose part or
  criterion is not met. One report per round.
- Every framework gets the same reports in the same order.
- A run stops when the tree is at target, or after 5 rounds.
- The quality reports (`quality:` in each file) are shared wording: they
  name the check that failed, as a CI job would, and the score's own list
  of findings (lines, uncovered lines, surviving bugs) is attached, as a CI
  log would be.
- A checkpoint where the framework stops to ask a person is answered with
  `continue_reply` and does not count as a round.
