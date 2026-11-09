#!/usr/bin/env python3
"""A stand-in for `claude` that calls no model, for the $0 check of the ship
phase (step 0 of the harness change for the 9.0.0 measurement).

Point the harness at it with `--claude tools/standin_claude.py`, and put a
directory first on the harness's `PATH` in which `claude` runs this file, so
the harness's model approver reaches it too and never the real CLI.

It plays a session that does what a careful Compass 9.0.0 session would do, on
two scenarios, using the reference solution under `reference/`:

- shop-idempotency, Compass arm: start a quick fix with the request link and
  requester from the prompt's last line, record a red, write the fix, record
  a green; on the commit message, branch and land it with `compass quick-fix
  finish`, which commits the record with the code; on the merged message, run
  `compass issue link set --pr <n>`.
- shop-change-email, Compass arm: start the issue labeled `personal-data` and
  ask for the scenario sign-off and the `G5` sign-off, then stop; once the
  harness approves both at the terminal, record the red and the green; on the
  commit message, branch and commit the code with git (the full route owes
  reviews this stand-in does not do, so it does not land); on the merged
  message, run `compass issue link set --pr <n>`.
- Any scenario, bare arm: write the reference solution; on the commit
  message, branch and commit it.

As the approver (`--output-format json`), it always answers that the session
is not waiting. Every command it runs, and its output, goes to
`out/standin-claude/<session>.log`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "out" / "standin-claude"
REQUEST = re.compile(r"Request: https://github\.com/([^/\s]+/[^/\s]+)/issues/([0-9]+) "
                     r"\(from ([^)]+)\)")
MERGED = re.compile(r"pull request #([0-9]+)")
PYTEST = ["python3", "-m", "pytest", "-q"]


def emit(session: str, text: str) -> None:
    """The stream-json events the harness reads."""
    for event in ({"type": "system", "subtype": "init", "session_id": session,
                   "cwd": os.getcwd(), "model": "standin"},
                  {"type": "assistant", "message": {"content": [{"type": "text",
                                                                 "text": text}]}},
                  {"type": "result", "subtype": "success", "session_id": session,
                   "result": text, "total_cost_usd": 0, "usage": {}}):
        print(json.dumps(event))


def run(log: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    done = subprocess.run(list(argv), capture_output=True, text=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(argv)}\n[exit {done.returncode}]\n{done.stdout}{done.stderr}\n")
    return done


def copy_reference(scenario: str, part: str) -> None:
    """Lay `reference/<scenario>/<part>` over the working tree."""
    shutil.copytree(ROOT / "reference" / scenario / part, Path.cwd() / part,
                    dirs_exist_ok=True)


def which_scenario(prompt: str) -> str:
    if "request_id" in prompt:
        return "shop-idempotency"
    if "email" in prompt:
        return "shop-change-email"
    return "other"


def first_turn(state: dict, prompt: str, log: Path) -> str:
    scenario, compass = state["scenario"], state["compass"]
    found = REQUEST.search(prompt)
    request = f"{found.group(1)}#{found.group(2)}" if found else ""
    requester = found.group(3) if found else ""
    if not compass or scenario == "other":
        if scenario != "other":
            copy_reference(scenario, "tests")
            copy_reference(scenario, "shop")
        return "Done: the change is made and the tests pass."
    if scenario == "shop-idempotency":
        run(log, "compass", "quick-fix", "start", "idem",
            "--risk", "contained - one function in one service",
            "--familiarity", "brownfield-mapped - a small seed with conventions",
            "--size", "small - one function and its tests",
            "--intent", "A retried create_order makes one order",
            "--scenario", "Given an order made with a request id, when create_order is "
            "retried with it, then the same order id comes back",
            "--test", "tests/test_idempotency.py",
            "--request", request, "--requester", requester)
        copy_reference(scenario, "tests")
        run(log, "compass", "tdd-red", "--loop", "outer", "--scenario", "TRC-001", "--",
            *PYTEST, "tests/test_idempotency.py")
        copy_reference(scenario, "shop")
        run(log, "compass", "tdd-green", "--loop", "outer", "--scenario", "TRC-001",
            "--candidate", "local", "--client", "api", "--", *PYTEST, "tests")
        return "Done: create_order takes request_id, and the tests pass."
    run(log, "compass", "quick-fix", "start", "change-email",
        "--risk", "contained - one method in the user service",
        "--familiarity", "brownfield-mapped - a small seed with conventions",
        "--size", "small - one method and its tests", "--labels", "personal-data",
        "--intent", "Customers can change the email address on their account",
        "--scenario", "Given a user, when change_email is called with a new address, "
        "then get_user returns the new address",
        "--test", "tests/test_change_email.py::test_e1_the_new_address_is_stored",
        "--request", request, "--requester", requester)
    run(log, "compass", "evidence", "request", "--checkpoint", "specify",
        "--scope", "the scenarios in the acceptance criteria")
    run(log, "compass", "evidence", "request", "--guardrail", "G5",
        "--scope", "change_email stores the new address and announces the change by id")
    state["phase"] = "waiting for sign-off"
    return ("This change touches personal data. I need your sign-off on requests 1 and 2 "
            "before I write code.")


def after_sign_off(state: dict, log: Path) -> str:
    copy_reference("shop-change-email", "tests")
    run(log, "compass", "tdd-red", "--scenario", "TRC-001", "--", *PYTEST,
        "tests/test_change_email.py::test_e1_the_new_address_is_stored")
    copy_reference("shop-change-email", "shop")
    run(log, "compass", "tdd-green", "--scenario", "TRC-001", "--", *PYTEST, "tests")
    state["phase"] = "built"
    return "Done: change_email stores the new address and announces it by id."


def commit(state: dict, log: Path) -> str:
    branch = f"fix/{state['scenario']}"
    run(log, "git", "checkout", "-b", branch)
    run(log, "git", "add", "shop", "tests")
    if state["compass"] and state["scenario"] == "shop-idempotency":
        run(log, "compass", "quick-fix", "finish", "-m", "Make create_order idempotent on "
            "request_id", "--candidate", "local", "--client", "api", "--release-note",
            "A retried order with the same request id no longer makes a second order.",
            "--", *PYTEST, "tests")
    else:
        run(log, "git", "commit", "-q", "-m", "Make the requested change")
    return f"Committed on {branch}."


def merged(state: dict, message: str, log: Path) -> str:
    found = MERGED.search(message)
    if not state["compass"] or not found:
        return "Thanks. Nothing left on my side."
    done = run(log, "compass", "issue", "link", "set", "--pr", found.group(1))
    if "compass record commit" in done.stdout:
        run(log, "compass", "record", "commit", "--issue", state["slug"])
    return "I recorded the merged pull request and its approval. Nothing left."


def main(argv: list[str]) -> int:
    if argv == ["--version"]:
        print("standin-claude 0.0.0")
        return 0
    message = argv[argv.index("-p") + 1] if "-p" in argv else ""
    if "--output-format" in argv and argv[argv.index("--output-format") + 1] == "json":
        # The harness's model approver.
        print(json.dumps({"result": json.dumps({"waiting": False, "reply": ""}),
                          "total_cost_usd": 0}))
        return 0
    LOGS.mkdir(parents=True, exist_ok=True)
    session = argv[argv.index("--resume") + 1] if "--resume" in argv else str(uuid.uuid4())
    state_path = LOGS / f"{session}.json"
    log = LOGS / f"{session}.log"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"### message: {message[:200]!r}\n### cwd: {os.getcwd()}\n")
    if "--resume" not in argv:
        scenario = which_scenario(message)
        state = {"scenario": scenario, "compass": "--plugin-dir" in argv,
                 "slug": "idem" if scenario == "shop-idempotency" else "change-email",
                 "phase": "start"}
        text = first_turn(state, message, log)
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if message.startswith("I approved request") and state["phase"] == "waiting for sign-off":
            text = after_sign_off(state, log)
        elif message.startswith("That is what I asked for"):
            text = commit(state, log)
        elif message.startswith("I reviewed and approved pull request"):
            text = merged(state, message, log)
        else:
            text = "Noted."
    state_path.write_text(json.dumps(state), encoding="utf-8")
    emit(session, text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
