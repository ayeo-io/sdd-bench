"""A stand-in for the `gh` command, so a bench session never reaches GitHub.

The harness puts a `gh` wrapper first on the session's `PATH` for every arm.
The wrapper runs this file with `python3 -I` and sets `GH_FAKE_STATE` to the
run's state file. The variable starts with `GH_` because Compass passes `gh`
only an allow-list of the environment, and that list keeps every `GH_*`
variable.

It reads only the state file and the standard library. It answers these
calls, and only these:

- `gh pr view <n> [--repo R] [--json FIELDS]`;
- `gh issue view <n> [--repo R] [--json FIELDS]`;
- `gh api [--paginate] user [--jq .login]`;
- `gh api [--paginate] repos/R/pulls/N/reviews [--jq <Compass's filter>]`;
- `gh api repos/R/pulls/N` and `gh api repos/R/issues/N`.

Every call is appended to `calls.jsonl` beside the state file, with its
argument list and exit status. Any other call, any write (a method other
than GET, a field or `--input`) and any `--jq` filter it does not know exits
1. It never runs the real `gh`.

The state file is JSON:

    {"repo": "shopfront-example/shop",
     "login": "<the login gh reads as>",
     "issues": {"shopfront-example/shop#41": {<gh issue view JSON>}},
     "prs": {"shopfront-example/shop#42": {<gh pr view JSON>}},
     "reviews": {"shopfront-example/shop#42": [<REST review objects>]}}

The harness writes `issues` when the run starts and `prs` and `reviews` when
it merges the session's branch.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: The `--jq` filter Compass 9.0.0 sends with the reviews call
#: (`pull_request_link.REVIEWS_JQ`), with white space removed.
REVIEWS_JQ = (".[]|{id,state,submitted_at,commit_id,html_url,"
              "user:{login:.user.login,type:.user.type}}")
_PULL = re.compile(r"repos/([^/]+/[^/]+)/pulls/([0-9]+)")
_REVIEWS = re.compile(r"repos/([^/]+/[^/]+)/pulls/([0-9]+)/reviews")
_ISSUE = re.compile(r"repos/([^/]+/[^/]+)/issues/([0-9]+)")
_NUMBER = re.compile(r"(?:.*/(?:pull|issues)/)?#?([0-9]+)/?")
#: Flags of `gh api` that take a value.
_API_VALUE_FLAGS = ("--jq", "-q", "--method", "-X", "--header", "-H", "--hostname",
                    "--cache", "--template", "-t", "--preview", "-p")
#: Flags of `gh api` that send a body, and so make the call a write.
_API_BODY_FLAGS = ("-f", "--raw-field", "-F", "--field", "--input")


class Refused(Exception):
    """A call this stand-in does not answer."""


def _flag(argv: list[str], *names: str) -> str | None:
    """The value of the first of `names` in `argv`, in `--x v` or `--x=v` form."""
    for i, word in enumerate(argv):
        for name in names:
            if word == name and i + 1 < len(argv):
                return argv[i + 1]
            if word.startswith(name + "="):
                return word.split("=", 1)[1]
    return None


def _pick(document: dict[str, Any], fields: str | None) -> dict[str, Any]:
    """Only the `--json` fields asked for, as `gh` prints them."""
    if fields is None:
        return document
    asked = [f.strip() for f in fields.split(",") if f.strip()]
    return {k: document[k] for k in asked if k in document}


def _view(kind: str, argv: list[str], state: dict[str, Any]) -> str:
    """`gh pr view` or `gh issue view`."""
    if len(argv) < 3:
        raise Refused(f"{kind} view needs a number")
    found = _NUMBER.fullmatch(argv[2])
    if not found:
        raise Refused(f"{kind} view: {argv[2]!r} is not a number")
    repo = _flag(argv, "--repo", "-R") or state.get("repo", "")
    table = state.get("prs" if kind == "pr" else "issues") or {}
    document = table.get(f"{repo}#{found.group(1)}")
    if document is None:
        what = "PullRequest" if kind == "pr" else "Issue"
        raise Refused(f"GraphQL: Could not resolve to a {what} with the number of "
                      f"{found.group(1)}. (repository.{what[0].lower() + what[1:]})")
    fields = _flag(argv, "--json")
    if fields is None:
        return f"{document.get('title', '')}\n{document.get('state', '')}\n"
    return json.dumps(_pick(document, fields)) + "\n"


def _rest_pull(pr: dict[str, Any]) -> dict[str, Any]:
    """A `gh pr view` document in the shape of the REST pull request."""
    merge = pr.get("mergeCommit") or {}
    return {"number": pr.get("number"), "title": pr.get("title"),
            "state": "closed" if pr.get("state") in ("MERGED", "CLOSED") else "open",
            "merged": pr.get("state") == "MERGED", "merged_at": pr.get("mergedAt"),
            "merge_commit_sha": merge.get("oid"), "html_url": pr.get("url"),
            "user": {"login": (pr.get("author") or {}).get("login"), "type": "User"},
            "head": {"sha": pr.get("headRefOid"), "ref": pr.get("headRefName")},
            "base": {"ref": pr.get("baseRefName")}}


def _rest_issue(issue: dict[str, Any]) -> dict[str, Any]:
    """A `gh issue view` document in the shape of the REST issue."""
    return {"number": issue.get("number"), "title": issue.get("title"),
            "body": issue.get("body"), "state": str(issue.get("state", "")).lower(),
            "html_url": issue.get("url"),
            "user": {"login": (issue.get("author") or {}).get("login"), "type": "User"},
            "labels": issue.get("labels") or []}


def _jq(value: Any, jq: str | None) -> str:
    """`value` printed as `gh api --jq` prints it, for the filters Compass uses."""
    if jq is None:
        return json.dumps(value) + "\n"
    squeezed = re.sub(r"\s+", "", jq)
    if squeezed == ".login" and isinstance(value, dict):
        return f"{value.get('login', '')}\n"
    if squeezed == REVIEWS_JQ and isinstance(value, list):
        lines = []
        for review in value:
            user = review.get("user") or {}
            lines.append(json.dumps({
                "id": review.get("id"), "state": review.get("state"),
                "submitted_at": review.get("submitted_at"),
                "commit_id": review.get("commit_id"), "html_url": review.get("html_url"),
                "user": {"login": user.get("login"), "type": user.get("type")}}))
        return "".join(line + "\n" for line in lines)
    raise Refused(f"--jq {jq!r} is not a filter this stand-in knows")


def _api(argv: list[str], state: dict[str, Any]) -> str:
    """`gh api`, for reads only."""
    method = (_flag(argv, "--method", "-X") or "GET").upper()
    if method != "GET" or any(w == f or w.startswith(f + "=")
                              for w in argv for f in _API_BODY_FLAGS):
        raise Refused("gh api writes are not answered")
    words, skip = [], False
    for word in argv[1:]:
        if skip:
            skip = False
            continue
        if word in _API_VALUE_FLAGS:
            skip = True
            continue
        if word.startswith("-"):
            continue
        words.append(word)
    if len(words) != 1:
        raise Refused("gh api needs exactly one path")
    path = words[0].lstrip("/")
    jq = _flag(argv, "--jq", "-q")
    if path == "user":
        return _jq({"login": state.get("login", ""), "type": "User"}, jq)
    found = _REVIEWS.fullmatch(path)
    if found:
        key = f"{found.group(1)}#{found.group(2)}"
        if key not in (state.get("prs") or {}):
            raise Refused("gh: Not Found (HTTP 404)")
        return _jq((state.get("reviews") or {}).get(key, []), jq)
    found = _PULL.fullmatch(path)
    if found:
        pr = (state.get("prs") or {}).get(f"{found.group(1)}#{found.group(2)}")
        if pr is None:
            raise Refused("gh: Not Found (HTTP 404)")
        return _jq(_rest_pull(pr), jq)
    found = _ISSUE.fullmatch(path)
    if found:
        issue = (state.get("issues") or {}).get(f"{found.group(1)}#{found.group(2)}")
        if issue is None:
            raise Refused("gh: Not Found (HTTP 404)")
        return _jq(_rest_issue(issue), jq)
    raise Refused(f"gh api {path} is not answered")


def answer(argv: list[str], state: dict[str, Any]) -> str:
    """The standard output of one call, or Refused."""
    if argv[:2] == ["pr", "view"]:
        return _view("pr", argv, state)
    if argv[:2] == ["issue", "view"]:
        return _view("issue", argv, state)
    if argv[:1] == ["api"]:
        return _api(argv, state)
    raise Refused("not answered: gh " + " ".join(argv))


def main(argv: list[str]) -> int:
    state_path = Path(os.environ.get("GH_FAKE_STATE", ""))
    if not state_path.name or not state_path.is_file():
        sys.stderr.write("fake gh: GH_FAKE_STATE names no state file\n")
        return 1
    state = json.loads(state_path.read_text(encoding="utf-8"))
    try:
        out, code, err = answer(argv, state), 0, ""
    except Refused as exc:
        out, code, err = "", 1, f"{exc}\n"
    entry = {"argv": argv, "exit": code,
             "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    with open(state_path.parent / "calls.jsonl", "a", encoding="utf-8") as log:
        log.write(json.dumps(entry) + "\n")
    sys.stdout.write(out)
    sys.stderr.write(err)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
