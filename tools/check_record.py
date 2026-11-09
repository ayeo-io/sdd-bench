"""Check a finished run's issue record using only the files in its workspace.

A framework that claims a proof trail must leave one that a reviewer can check
without the framework installed. This checker reads the workspace a run left
behind (the repository, with its `.git`, and the record under `.compass/`)
and imports nothing from the framework it checks. It runs `git` only to read
the repository's own objects.

Six checks, one result each, for every issue under `.compass/work/`:

1. red-before-green   every scenario in the manifest has a failing run on
                      record, timed before that scenario's first passing run;
2. test-digests       every test-file digest in a red or green record matches
                      the file in the workspace;
3. request-link       the manifest links the request (`github: {repo, number}`
                      or `request.link`), and with `--expect-request` it is
                      that request;
4. approvals          every approval the record says is required is on record,
                      and a sign-off before code was given before the first
                      green;
5. land-commit        the land commit is on the result branch, and with
                      `--base` it comes after that commit;
6. ship-approval      a person other than the pull request's author approved
                      the change at ship.

Each check reports `pass`, `fail`, `not-checkable` or `not-applicable`.
`not-checkable` means the record holds no data in a form this checker can
check, for example digests stored only as git tree ids. It is never counted as
a pass. `not-applicable` means the record does not owe the check: only
`ship-approval` reports it, for a record from before Compass 9.0.0.

Usage:
  python3 tools/check_record.py --workspace DIR [--branch REF] [--base REF]
                                [--expect-request OWNER/REPO#N]
                                [--require-ship-approval] [--issue SLUG]
                                [--json OUT]

Exit status: 0 when every check of every issue passes, 1 otherwise, 2 when the
workspace holds no issue record.

What the checker reads, and the limits of each check:

- Red and green runs are the JSON files under `evidence/` whose name starts
  with `red` or `green`. A record's `scenario` field names its scenario. A
  green with no scenario (a whole-suite run) counts as a green for every
  scenario. A record has one timestamp, so when a framework rewrites a record
  on a re-run, "first green" is the earliest green still on disk.
- Test-file digests are read from a `test_files` map, `{path: "sha256:<hex>"}`,
  or, in the form Compass 9.0.0 writes, from the `file_sha256` map
  `{path: "<hex>"}` for each path the record's `test_files` list names. A
  digest of any other form (a git tree id, or a digest over re-serialized
  JSON) is not a digest of a file, so a record with only those is
  `not-checkable`.
- Required approvals are taken from the record itself: the labels
  `auth`, `payments`, `personal-data` and `migrations` require a person's
  sign-off (a `human-approval` record for guardrail G5); each stage under
  `checkpoints:` requires a `checkpoint-approval`; each approval type
  listed under `evidence_required:` requires an approved record of that type;
  and the 9.0.0 token `scenario-approval` requires the `specify` checkpoint's
  approval. A `pr-approval` record, or a typed approval at ship (`ship:`), is
  never the G5 sign-off. The G5 sign-off and the `specify` approval are given
  before code, so each must be timed before the first green on record.
- The land commit is the stored `land_commit`. A 9.0.0 record committed with
  the code (`landed_with_record: true`) stores none; then it is the newest
  commit on the result branch that added the manifest's `land_timestamp`
  line, as Compass reads it. With `--base`, a land commit that is that
  commit, or before it, fails: it cannot hold the change.
- The ship approval is owed when the record's `evidence_required` lists
  `ship-approval` (Compass 9.0.0 and later), or with
  `--require-ship-approval`. It is met by an approved `pr-approval` record
  for the pull request the manifest's `pull_request:` names, with a time and
  an approver who is not the agent and not the pull request's author, or by
  an approved `human-approval` record with `ship:` naming the issue.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PASS, FAIL, NOT_CHECKABLE, NOT_APPLICABLE = "pass", "fail", "not-checkable", "not-applicable"
CHECKS = ("red-before-green", "test-digests", "request-link", "approvals", "land-commit",
          "ship-approval")
#: The statuses that do not fail an issue.
CLEARS = (PASS, NOT_APPLICABLE)

#: Labels whose change cannot be undone at merge, so a person signs it off.
SIGN_OFF_LABELS = frozenset({"auth", "payments", "personal-data", "migrations"})

#: Evidence types that record a person's decision.
APPROVAL_TYPES = frozenset({"human-approval", "checkpoint-approval", "artifact-approval"})

#: Keys that say a `human-approval` was given for something other than the
#: G5 sign-off, so it does not count as that sign-off.
SUBJECT_KEYS = ("check", "waiver", "checkpoint", "artifact", "decisions", "ship")

#: Fields a sign-off needs to say who approved, in what role, what and when.
SIGN_OFF_FIELDS = ("approver", "role", "scope", "timestamp")

SHA256 = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")
REQUEST = re.compile(r"^([A-Za-z0-9-]+/[A-Za-z0-9._-]+)#([0-9]+)$")
ISSUE_URL = re.compile(r"^https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)/issues/([0-9]+)/?$")
#: Approver names that are not a person.
NOT_A_PERSON = frozenset({"agent", ""})


def result(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    """One check's outcome."""
    return {"status": status, "detail": detail, **extra}


def load_manifest(path: Path) -> dict[str, Any]:
    """The manifest as a map; an empty map when the file is not a YAML map."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def run_records(issue_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """The red and green run records under `evidence/`, and the names of any
    that could not be read. Each record gains `_file` and `_kind`."""
    records: list[dict[str, Any]] = []
    unreadable: list[str] = []
    evidence = issue_dir / "evidence"
    if not evidence.is_dir():
        return records, unreadable
    for path in sorted(evidence.glob("*.json")):
        kind = "red" if path.name.startswith("red") else (
            "green" if path.name.startswith("green") else None)
        if kind is None:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            unreadable.append(path.name)
            continue
        if not isinstance(data, dict):
            unreadable.append(path.name)
            continue
        data["_file"] = f"evidence/{path.name}"
        data["_kind"] = kind
        records.append(data)
    return records, unreadable


def scenario_ids(manifest: dict[str, Any]) -> list[str]:
    """The ids of the manifest's `scenarios:` list, in order."""
    ids = []
    for entry in manifest.get("scenarios") or []:
        if isinstance(entry, dict) and entry.get("id"):
            ids.append(str(entry["id"]))
        elif isinstance(entry, str):
            ids.append(entry)
    return ids


def parse_time(value: Any) -> datetime | None:
    """A record's timestamp as an aware time; None when it does not parse.
    A time with no zone is read as UTC, so records can be compared."""
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def check_red_before_green(manifest: dict[str, Any],
                           records: list[dict[str, Any]],
                           unreadable: list[str]) -> dict[str, Any]:
    """Every scenario has a red timed before its first green."""
    ids = scenario_ids(manifest)
    if not ids:
        return result(FAIL, "the manifest lists no scenarios")

    def timed(kind: str, scenario: str | None) -> list[tuple[datetime, str]]:
        return sorted((when, r["_file"]) for r in records
                      if r["_kind"] == kind and r.get("scenario") == scenario
                      and (when := parse_time(r.get("timestamp"))) is not None)

    suite_greens = timed("green", None)
    unbound_reds = timed("red", None)
    per_scenario: dict[str, dict[str, Any]] = {}
    for sid in ids:
        reds = timed("red", sid)
        greens = sorted(timed("green", sid) + suite_greens)
        entry: dict[str, Any] = {
            "red": (reds[0][0].isoformat(), reds[0][1]) if reds else None,
            "first_green": (greens[0][0].isoformat(), greens[0][1]) if greens else None}
        if not reds and unbound_reds:
            entry["status"], entry["detail"] = FAIL, (
                f"no red names this scenario; {len(unbound_reds)} red(s) on record "
                "name no scenario")
        elif not reds:
            entry["status"], entry["detail"] = FAIL, "no red on record"
        elif not greens:
            entry["status"], entry["detail"] = FAIL, "no green on record"
        elif reds[0][0] < greens[0][0]:
            entry["status"], entry["detail"] = PASS, (
                f"red {reds[0][0].isoformat()} before green {greens[0][0].isoformat()}")
        else:
            entry["status"], entry["detail"] = FAIL, (
                f"first red {reds[0][0].isoformat()} is not before first green "
                f"{greens[0][0].isoformat()}")
        per_scenario[sid] = entry
    failed = [sid for sid, e in per_scenario.items() if e["status"] != PASS]
    note = f"; unreadable records: {', '.join(unreadable)}" if unreadable else ""
    if failed:
        reasons = "; ".join(f"{sid}: {per_scenario[sid]['detail']}" for sid in failed[:5])
        if len(failed) > 5:
            reasons += f"; and {len(failed) - 5} more (see the JSON report)"
        return result(FAIL, f"{len(failed)} of {len(ids)} scenarios fail: {reasons}{note}",
                      scenarios=per_scenario)
    return result(PASS, f"all {len(ids)} scenarios have a red before their first green{note}",
                  scenarios=per_scenario)


def sha256_of(path: Path) -> str:
    """The SHA-256 of a file's bytes, as `sha256sum` prints it."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_digests(record: dict[str, Any]) -> dict[str, str]:
    """`{path: digest}` for the test files a red or green record names: the
    `test_files` map, or the 9.0.0 `file_sha256` entries of the paths its
    `test_files` list names."""
    named = record.get("test_files")
    if isinstance(named, dict):
        return {str(k): str(v) for k, v in named.items()}
    sums = record.get("file_sha256")
    if isinstance(named, list) and isinstance(sums, dict):
        return {str(path): str(sums.get(path, "")) for path in named}
    return {}


def check_test_digests(workspace: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Every test-file digest on a red or green record matches the file."""
    if not records:
        return result(NOT_CHECKABLE, "no red or green records")
    with_digests = [r for r in records if test_digests(r)]
    if not with_digests:
        forms = sorted({key for r in records
                        for key in ("tree_id", "changes_id", "content_digest") if key in r})
        held = f" (the records hold {', '.join(forms)} only)" if forms else ""
        return result(NOT_CHECKABLE,
                      f"no record stores a digest of a test file{held}; a git tree id "
                      "or a digest over re-serialized JSON cannot be checked against "
                      "the files")
    mismatches: list[str] = []
    checked = 0
    root = workspace.resolve()
    for record in with_digests:
        for rel, digest in sorted(test_digests(record).items()):
            match = SHA256.match(str(digest))
            target = (workspace / rel).resolve()
            if not match:
                mismatches.append(f"{record['_file']}: {rel}: not a SHA-256 digest")
            elif root not in target.parents:
                mismatches.append(f"{record['_file']}: {rel}: outside the workspace")
            elif not target.is_file():
                mismatches.append(f"{record['_file']}: {rel}: file missing")
            elif sha256_of(target) != match.group(1):
                mismatches.append(f"{record['_file']}: {rel}: digest differs from the file")
            checked += 1
    without = len(records) - len(with_digests)
    note = f"; {without} record(s) store no test-file digests" if without else ""
    if mismatches:
        return result(FAIL, f"{len(mismatches)} of {checked} digests do not match{note}",
                      mismatches=mismatches)
    if without:
        return result(FAIL, f"all {checked} digests match{note}")
    return result(PASS, f"all {checked} digests match their files")


def linked_request(manifest: dict[str, Any]) -> tuple[str | None, str]:
    """`owner/repo#n` of the request the manifest links, from `github:` or
    from a GitHub issue URL in `request.link`, and a note on what is
    missing or incomplete."""
    link = manifest.get("github")
    if isinstance(link, dict) and link.get("repo") and link.get("number"):
        return f"{link['repo']}#{link['number']}", ""
    request = manifest.get("request")
    url = request.get("link") if isinstance(request, dict) else None
    found = ISSUE_URL.match(str(url or ""))
    if found:
        return f"{found.group(1)}#{found.group(2)}", ""
    if link:
        return None, f"`github:` is incomplete: {link!r}"
    if url:
        return None, f"`request.link` is not a GitHub issue: {url!r}"
    return None, "the manifest has no `github:` or `request.link` request link"


def check_request_link(manifest: dict[str, Any], expect: str | None = None
                       ) -> dict[str, Any]:
    """The manifest links the request it was made for: with `expect`, that
    request and no other."""
    found, gap = linked_request(manifest)
    if found is None:
        return result(FAIL, gap)
    if expect is not None and found.lower() != expect.lower():
        return result(FAIL, f"links {found}, not the request {expect}")
    return result(PASS, found)


def labels_of(manifest: dict[str, Any]) -> set[str]:
    """Every label the record's assessments name."""
    labels: set[str] = set()
    for key in ("assessment", "evaluated_assessment"):
        block = manifest.get(key)
        if isinstance(block, dict):
            labels.update(str(label) for label in block.get("labels") or [])
    return labels


def approved(manifest: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """The approved evidence records of one type."""
    return [e for e in manifest.get("evidence") or []
            if isinstance(e, dict) and e.get("type") == kind
            and e.get("decision") == "approved"]


def required_approvals(manifest: dict[str, Any]) -> list[tuple[str, str]]:
    """`(what, why)` for each approval the record says it needs."""
    needed: list[tuple[str, str]] = []
    hit = sorted(labels_of(manifest) & SIGN_OFF_LABELS)
    if hit:
        needed.append(("sign-off", f"labeled {', '.join(hit)}"))
    for stage in manifest.get("checkpoints") or []:
        needed.append((f"checkpoint:{stage}", "listed under `checkpoints:`"))
    for item in manifest.get("evidence_required") or []:
        kind = item.get("type") if isinstance(item, dict) else item
        if kind in APPROVAL_TYPES:
            needed.append((f"type:{kind}", "listed under `evidence_required:`"))
        elif kind == "scenario-approval" and "checkpoint:specify" not in [
                w for w, _ in needed]:
            needed.append(("checkpoint:specify", "`scenario-approval` is listed under "
                           "`evidence_required:`"))
    return needed


#: The approvals given before code, so each must come before the first green.
BEFORE_CODE = ("sign-off", "checkpoint:specify")


def find_approval(manifest: dict[str, Any], what: str
                  ) -> tuple[bool, str, dict[str, Any] | None]:
    """Whether the approval `what` is on record, the record or the gap, and
    the record that meets it."""
    if what == "sign-off":
        signs = [e for e in approved(manifest, "human-approval")
                 if not any(k in e for k in SUBJECT_KEYS)
                 and e.get("guardrail", "G5") == "G5"]
        for entry in signs:
            missing = [k for k in SIGN_OFF_FIELDS if not entry.get(k)]
            if not missing and str(entry.get("approver")).lower() != "agent":
                return True, f"{entry.get('id', '?')} by {entry['approver']}", entry
        if signs:
            return (False, "a sign-off record is incomplete or names the approver `agent`",
                    None)
        return False, "no approved human-approval for the sign-off", None
    if what.startswith("checkpoint:"):
        stage = what.split(":", 1)[1]
        for entry in approved(manifest, "checkpoint-approval"):
            if str(entry.get("checkpoint")) == stage and entry.get("approver"):
                return True, f"{entry.get('id', '?')} by {entry['approver']}", entry
        return False, f"no approved checkpoint-approval for {stage}", None
    kind = what.split(":", 1)[1]
    # A typed approval at ship is a `human-approval` too, but it answers the
    # ship approval, not this one.
    found = [e for e in approved(manifest, kind) if e.get("approver") and "ship" not in e]
    if found:
        return True, f"{found[0].get('id', '?')} by {found[0]['approver']}", found[0]
    return False, f"no approved {kind} record", None


def first_green(records: list[dict[str, Any]]) -> datetime | None:
    """The time of the earliest green on record, of any scenario."""
    times = [when for r in records if r["_kind"] == "green"
             and (when := parse_time(r.get("timestamp"))) is not None]
    return min(times) if times else None


def check_approvals(manifest: dict[str, Any],
                    records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every approval the record says is required is on record, and each one
    given before code was given before the first green."""
    needed = required_approvals(manifest)
    if not needed:
        return result(PASS, "the record requires no approval")
    green = first_green(records or [])
    rows = []
    for what, why in needed:
        ok, detail, entry = find_approval(manifest, what)
        if ok and entry is not None and what in BEFORE_CODE and green is not None:
            when = parse_time(entry.get("timestamp"))
            if when is None:
                ok, detail = False, f"{detail}, with no time, so not shown before code"
            elif when >= green:
                ok, detail = False, (f"{detail} at {when.isoformat()}, not before the "
                                     f"first green at {green.isoformat()}")
        rows.append({"required": what, "because": why, "met": ok, "detail": detail})
    unmet = [r for r in rows if not r["met"]]
    if unmet:
        text = "; ".join(f"{r['required']} ({r['because']}): {r['detail']}" for r in unmet)
        return result(FAIL, f"{len(unmet)} of {len(rows)} required approvals missing: {text}",
                      approvals=rows)
    return result(PASS, f"all {len(rows)} required approvals on record", approvals=rows)


def git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """A read-only git command in the workspace."""
    return subprocess.run(["git", "-C", str(workspace), *args],
                          capture_output=True, text=True, timeout=60)


def landed_with_record(manifest: dict[str, Any], manifest_path: Path, workspace: Path,
                       branch: str) -> tuple[str | None, str]:
    """The land commit of a record committed with the code: the newest commit
    on `branch` that added the manifest's `land_timestamp` line and still
    holds it. Returns the commit, or None and the reason."""
    stamp = manifest.get("land_timestamp")
    if not isinstance(stamp, str) or not stamp:
        return None, "the record landed with the code but has no `land_timestamp`"
    rel = manifest_path.relative_to(workspace).as_posix()
    pattern = "^land_timestamp: .?%s.?$" % re.escape(stamp)
    listed = git(workspace, "log", "--format=%H", "-G", pattern, branch, "--", rel)
    if listed.returncode != 0:
        return None, f"git log on {branch!r} failed"
    for commit in listed.stdout.split():
        shown = git(workspace, "show", f"{commit}:{rel}")
        if shown.returncode == 0 and stamp in shown.stdout:
            return commit, ""
    return None, (f"no commit on {branch} added `land_timestamp: {stamp}`; the record "
                  "landed with the code, so its land commit must be there")


def check_land_commit(manifest: dict[str, Any], workspace: Path, branch: str,
                      base: str | None = None, manifest_path: Path | None = None
                      ) -> dict[str, Any]:
    """The land commit is on the result branch and, with `base`, after it."""
    sha = manifest.get("land_commit")
    from_git = not sha and manifest.get("landed_with_record") is True
    if not sha and not from_git:
        return result(FAIL, "the manifest has no `land_commit`")
    if not (workspace / ".git").exists():
        return result(NOT_CHECKABLE, "the workspace has no .git to look the commit up in")
    tip = git(workspace, "rev-parse", "--verify", f"{branch}^{{commit}}")
    if tip.returncode != 0:
        return result(NOT_CHECKABLE, f"the result branch {branch!r} does not exist")
    how = ""
    if from_git:
        found, gap = landed_with_record(manifest, manifest_path or workspace, workspace, branch)
        if found is None:
            return result(FAIL, gap)
        sha, how = found, " (read from git: the record landed with the code)"
    sha = str(sha)
    if git(workspace, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return result(FAIL, f"{sha} is not a commit in the repository")
    if git(workspace, "merge-base", "--is-ancestor", sha, branch).returncode != 0:
        return result(FAIL, f"{sha} is not on {branch}")
    if base is not None:
        if git(workspace, "rev-parse", "--verify", f"{base}^{{commit}}").returncode != 0:
            return result(NOT_CHECKABLE, f"the base {base!r} is not a commit")
        if git(workspace, "merge-base", "--is-ancestor", sha, base).returncode == 0:
            return result(FAIL, f"{sha}{how} is the base {base[:12]} or before it, so it "
                                "cannot hold the change")
    return result(PASS, f"{sha} is on {branch}{how}"
                  + (f", after the base {base[:12]}" if base else ""), land_commit=sha)


def check_ship_approval(manifest: dict[str, Any], slug: str, require: bool = False
                        ) -> dict[str, Any]:
    """A person other than the pull request's author approved the change at
    ship: an approved `pr-approval` record for the linked pull request, or
    a typed `human-approval` record with `ship:` for this issue."""
    owed = "ship-approval" in [item.get("type") if isinstance(item, dict) else item
                               for item in manifest.get("evidence_required") or []]
    if not (owed or require):
        return result(NOT_APPLICABLE, "the record does not owe a ship approval (before 9.0.0)")
    pr = manifest.get("pull_request")
    linked = ((pr.get("repo"), pr.get("number"))
              if isinstance(pr, dict) and pr.get("repo") and pr.get("number") else None)
    gaps: list[str] = []
    for entry in approved(manifest, "pr-approval"):
        named = entry.get("pull_request")
        names = ((named.get("repo"), named.get("number")) if isinstance(named, dict)
                 else None)
        who = str(entry.get("approver") or "")
        if linked is None:
            gaps.append(f"{entry.get('id', '?')}: the manifest links no `pull_request`")
        elif names != linked:
            gaps.append(f"{entry.get('id', '?')}: names {names}, not the linked "
                        f"pull request {linked}")
        elif who.lower() in NOT_A_PERSON:
            gaps.append(f"{entry.get('id', '?')}: the approver is not a person")
        elif who.lower() == str(entry.get("pr_author") or "").lower():
            gaps.append(f"{entry.get('id', '?')}: the approver is the pull request's author")
        elif not entry.get("timestamp"):
            gaps.append(f"{entry.get('id', '?')}: no time")
        else:
            return result(PASS, f"{entry.get('id', '?')}: {who} approved pull request "
                                f"{linked[0]}#{linked[1]} at {entry['timestamp']}")
    for entry in approved(manifest, "human-approval"):
        if entry.get("ship") != slug:
            continue
        who = str(entry.get("approver") or "")
        if who.lower() in NOT_A_PERSON or not entry.get("timestamp"):
            gaps.append(f"{entry.get('id', '?')}: a typed ship approval with no person "
                        "or no time")
            continue
        return result(PASS, f"{entry.get('id', '?')}: {who} approved the change at ship "
                            f"at {entry['timestamp']}")
    why = "owed (`evidence_required` lists ship-approval)" if owed else "required"
    return result(FAIL, f"a ship approval is {why}, and none is on record"
                  + (f": {'; '.join(gaps)}" if gaps else ""))


def check_issue(issue_dir: Path, workspace: Path, branch: str, *,
                base: str | None = None, expect_request: str | None = None,
                require_ship_approval: bool = False) -> dict[str, Any]:
    """All six checks for one issue."""
    manifest = load_manifest(issue_dir / "manifest.yml")
    records, unreadable = run_records(issue_dir)
    checks = {
        "red-before-green": check_red_before_green(manifest, records, unreadable),
        "test-digests": check_test_digests(workspace, records),
        "request-link": check_request_link(manifest, expect_request),
        "approvals": check_approvals(manifest, records),
        "land-commit": check_land_commit(manifest, workspace, branch, base,
                                         issue_dir / "manifest.yml"),
        "ship-approval": check_ship_approval(manifest, issue_dir.name,
                                             require_ship_approval),
    }
    return {"issue": issue_dir.name,
            "passed": all(c["status"] in CLEARS for c in checks.values()),
            "checks": checks}


def check_workspace(workspace: Path, branch: str = "HEAD", issue: str | None = None, *,
                    base: str | None = None, expect_request: str | None = None,
                    require_ship_approval: bool = False) -> dict[str, Any]:
    """The report for every issue record in the workspace (or the one named)."""
    work = workspace / ".compass" / "work"
    dirs = sorted(p.parent for p in work.glob("*/manifest.yml")) if work.is_dir() else []
    if issue is not None:
        dirs = [d for d in dirs if d.name == issue]
    issues = [check_issue(d, workspace, branch, base=base, expect_request=expect_request,
                          require_ship_approval=require_ship_approval) for d in dirs]
    return {"workspace": str(workspace), "branch": branch, "base": base,
            "expect_request": expect_request, "issues": issues,
            "passed": bool(issues) and all(i["passed"] for i in issues)}


def render(report: dict[str, Any]) -> str:
    """The report as plain text, one line per check."""
    if not report["issues"]:
        return f"{report['workspace']}: no issue record under .compass/work/"
    lines = []
    for item in report["issues"]:
        lines.append(f"{item['issue']}: {'PASS' if item['passed'] else 'FAIL'}")
        for name in CHECKS:
            check = item["checks"][name]
            lines.append(f"  {name:<17} {check['status']:<14} {check['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True, type=Path,
                        help="the finished run's repository, holding .git and .compass/")
    parser.add_argument("--branch", default="HEAD",
                        help="the result branch land_commit must be on (default HEAD)")
    parser.add_argument("--base", default=None,
                        help="the seed commit: a land commit at or before it fails")
    parser.add_argument("--expect-request", default=None, metavar="OWNER/REPO#N",
                        help="the request the record must link; another link fails")
    parser.add_argument("--require-ship-approval", action="store_true",
                        help="require the ship approval even when the record does not "
                             "list it as owed")
    parser.add_argument("--issue", default=None, help="check only this issue slug")
    parser.add_argument("--json", type=Path, default=None, help="also write the report here")
    args = parser.parse_args(argv)
    if args.expect_request is not None and not REQUEST.match(args.expect_request):
        parser.error("--expect-request takes owner/repo#number")
    report = check_workspace(args.workspace, args.branch, args.issue, base=args.base,
                             expect_request=args.expect_request,
                             require_ship_approval=args.require_ship_approval)
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["issues"]:
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
