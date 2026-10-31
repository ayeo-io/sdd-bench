"""Check a finished run's issue record using only the files in its workspace.

A framework that claims a proof trail must leave one that a reviewer can check
without the framework installed. This checker reads the workspace a run left
behind (the repository, with its `.git`, and the record under `.compass/`)
and imports nothing from the framework it checks. It runs `git` only to read
the repository's own objects.

Five checks, one result each, for every issue under `.compass/work/`:

1. red-before-green   every scenario in the manifest has a failing run on
                      record, timed before that scenario's first passing run;
2. test-digests       every test-file digest in a red or green record matches
                      the file in the workspace;
3. request-link       the manifest links the request (`github: {repo, number}`);
4. approvals          every approval the record says is required is on record;
5. land-commit        `land_commit` names a commit on the result branch.

Each check reports `pass`, `fail` or `not-checkable`. `not-checkable` means
the record holds no data in a form this checker can check, for example digests
stored only as git tree ids. It is never counted as a pass.

Usage:
  python3 tools/check_record.py --workspace DIR [--branch REF] [--issue SLUG]
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
  on each red or green record, the form the 9.0.0 record is to use. A digest
  of any other form (a git tree id, or a digest over re-serialized JSON) is
  not a digest of a file, so a record with only those is `not-checkable`.
- Required approvals are taken from the record itself: the labels
  `auth`, `payments`, `personal-data` and `migrations` require a person's
  sign-off (a `human-approval` record for guardrail G5); each stage under
  `checkpoints:` requires a `checkpoint-approval`; and each approval type
  listed under `evidence_required:` requires an approved record of that type.
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

PASS, FAIL, NOT_CHECKABLE = "pass", "fail", "not-checkable"
CHECKS = ("red-before-green", "test-digests", "request-link", "approvals", "land-commit")

#: Labels whose change cannot be undone at merge, so a person signs it off.
SIGN_OFF_LABELS = frozenset({"auth", "payments", "personal-data", "migrations"})

#: Evidence types that record a person's decision.
APPROVAL_TYPES = frozenset({"human-approval", "checkpoint-approval", "artifact-approval"})

#: Keys that say a `human-approval` was given for something other than the
#: G5 sign-off, so it does not count as that sign-off.
SUBJECT_KEYS = ("check", "waiver", "checkpoint", "artifact", "decisions")

#: Fields a sign-off needs to say who approved, in what role, what and when.
SIGN_OFF_FIELDS = ("approver", "role", "scope", "timestamp")

SHA256 = re.compile(r"^(?:sha256:)?([0-9a-f]{64})$")


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
    per_scenario: dict[str, dict[str, Any]] = {}
    for sid in ids:
        reds = timed("red", sid)
        greens = sorted(timed("green", sid) + suite_greens)
        entry: dict[str, Any] = {
            "red": (reds[0][0].isoformat(), reds[0][1]) if reds else None,
            "first_green": (greens[0][0].isoformat(), greens[0][1]) if greens else None}
        if not reds:
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


def check_test_digests(workspace: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Every `test_files` digest on a red or green record matches the file."""
    if not records:
        return result(NOT_CHECKABLE, "no red or green records")
    with_digests = [r for r in records if isinstance(r.get("test_files"), dict)
                    and r["test_files"]]
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
        for rel, digest in sorted(record["test_files"].items()):
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


def check_request_link(manifest: dict[str, Any]) -> dict[str, Any]:
    """The manifest links the request it was made for."""
    link = manifest.get("github")
    if isinstance(link, dict) and link.get("repo") and link.get("number"):
        return result(PASS, f"{link['repo']}#{link['number']}")
    if link:
        return result(FAIL, f"`github:` is incomplete: {link!r}")
    return result(FAIL, "the manifest has no `github:` request link")


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
    return needed


def find_approval(manifest: dict[str, Any], what: str) -> tuple[bool, str]:
    """Whether the approval `what` is on record, and the record or the gap."""
    if what == "sign-off":
        signs = [e for e in approved(manifest, "human-approval")
                 if not any(k in e for k in SUBJECT_KEYS)
                 and e.get("guardrail", "G5") == "G5"]
        for entry in signs:
            missing = [k for k in SIGN_OFF_FIELDS if not entry.get(k)]
            if not missing and str(entry.get("approver")).lower() != "agent":
                return True, f"{entry.get('id', '?')} by {entry['approver']}"
        if signs:
            return False, "a sign-off record is incomplete or names the approver `agent`"
        return False, "no approved human-approval for the sign-off"
    if what.startswith("checkpoint:"):
        stage = what.split(":", 1)[1]
        for entry in approved(manifest, "checkpoint-approval"):
            if str(entry.get("checkpoint")) == stage and entry.get("approver"):
                return True, f"{entry.get('id', '?')} by {entry['approver']}"
        return False, f"no approved checkpoint-approval for {stage}"
    kind = what.split(":", 1)[1]
    found = [e for e in approved(manifest, kind) if e.get("approver")]
    if found:
        return True, f"{found[0].get('id', '?')} by {found[0]['approver']}"
    return False, f"no approved {kind} record"


def check_approvals(manifest: dict[str, Any]) -> dict[str, Any]:
    """Every approval the record says is required is on record."""
    needed = required_approvals(manifest)
    if not needed:
        return result(PASS, "the record requires no approval")
    rows = []
    for what, why in needed:
        ok, detail = find_approval(manifest, what)
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


def check_land_commit(manifest: dict[str, Any], workspace: Path, branch: str) -> dict[str, Any]:
    """`land_commit` names a commit reachable from the result branch."""
    sha = manifest.get("land_commit")
    if not sha:
        return result(FAIL, "the manifest has no `land_commit`")
    if not (workspace / ".git").exists():
        return result(NOT_CHECKABLE, "the workspace has no .git to look the commit up in")
    sha = str(sha)
    if git(workspace, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        return result(FAIL, f"{sha} is not a commit in the repository")
    tip = git(workspace, "rev-parse", "--verify", f"{branch}^{{commit}}")
    if tip.returncode != 0:
        return result(NOT_CHECKABLE, f"the result branch {branch!r} does not exist")
    if git(workspace, "merge-base", "--is-ancestor", sha, branch).returncode != 0:
        return result(FAIL, f"{sha} is not on {branch}")
    return result(PASS, f"{sha} is on {branch}")


def check_issue(issue_dir: Path, workspace: Path, branch: str) -> dict[str, Any]:
    """All five checks for one issue."""
    manifest = load_manifest(issue_dir / "manifest.yml")
    records, unreadable = run_records(issue_dir)
    checks = {
        "red-before-green": check_red_before_green(manifest, records, unreadable),
        "test-digests": check_test_digests(workspace, records),
        "request-link": check_request_link(manifest),
        "approvals": check_approvals(manifest),
        "land-commit": check_land_commit(manifest, workspace, branch),
    }
    return {"issue": issue_dir.name,
            "passed": all(c["status"] == PASS for c in checks.values()),
            "checks": checks}


def check_workspace(workspace: Path, branch: str = "HEAD",
                    issue: str | None = None) -> dict[str, Any]:
    """The report for every issue record in the workspace (or the one named)."""
    work = workspace / ".compass" / "work"
    dirs = sorted(p.parent for p in work.glob("*/manifest.yml")) if work.is_dir() else []
    if issue is not None:
        dirs = [d for d in dirs if d.name == issue]
    issues = [check_issue(d, workspace, branch) for d in dirs]
    return {"workspace": str(workspace), "branch": branch, "issues": issues,
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
            lines.append(f"  {name:<17} {check['status']:<13} {check['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True, type=Path,
                        help="the finished run's repository, holding .git and .compass/")
    parser.add_argument("--branch", default="HEAD",
                        help="the result branch land_commit must be on (default HEAD)")
    parser.add_argument("--issue", default=None, help="check only this issue slug")
    parser.add_argument("--json", type=Path, default=None, help="also write the report here")
    args = parser.parse_args(argv)
    report = check_workspace(args.workspace, args.branch, args.issue)
    print(render(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["issues"]:
        return 2
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
