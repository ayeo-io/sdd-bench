"""Tests for tools/check_record.py, on small issue records built in a temporary
workspace. The 8.x fixture copies the shape of a real Compass 8.0.4 record:
red and green files that hold `tree_id`, `changes_id` and `content_digest`,
and a manifest with `scenarios:`, `evidence:` and `land_commit`. The 9.0.0
fixture copies the shape Compass 9.0.0 writes (checked on the `v9` release
candidate): red and green files with `file_sha256` and a `test_files` list,
a manifest with `request:`, `pull_request:`, a `pr-approval` record and
`landed_with_record: true`, committed with the code and squash-merged."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import check_record  # noqa: E402

TEST_FILE = "tests/test_forget.py"
TEST_TEXT = "def test_trc_a1():\n    assert True\n"


def git(ws: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(ws), *args], check=True, capture_output=True,
                         text=True, env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                         "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                                         "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})
    return out.stdout.strip()


def sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def run_record(scenario: str | None, passed: bool, when: str, *,
               digests: dict[str, str] | None = None) -> dict[str, Any]:
    """A red or green record. With no digests it has the 8.x shape."""
    record: dict[str, Any] = {
        "command": "python3 -m pytest -q", "scenario": scenario,
        "exit_code": 0 if passed else 1, "passed": passed, "timestamp": when,
        "tree_id": "8c71f85bdb7b34d39fbcf402029a54afc8f06d36",
        "changes_id": "15ac820e4ac58ae4019afc99efab4183b1de55ce",
        "record_id": "a6a1809ec1c34773",
        "content_digest": "sha256:" + "0" * 64,
    }
    if digests is not None:
        record["test_files"] = digests
    return record


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A repository with one commit holding the test file."""
    ws = tmp_path / "ws"
    (ws / "tests").mkdir(parents=True)
    (ws / TEST_FILE).write_text(TEST_TEXT)
    git(ws, "init", "-q", "-b", "main")
    git(ws, "add", TEST_FILE)
    git(ws, "commit", "-q", "-m", "change")
    return ws


def write_issue(ws: Path, manifest: dict[str, Any],
                records: dict[str, dict[str, Any]], slug: str = "forget-user") -> Path:
    issue = ws / ".compass" / "work" / slug
    (issue / "evidence").mkdir(parents=True)
    (issue / "manifest.yml").write_text(yaml.safe_dump(manifest))
    for name, record in records.items():
        (issue / "evidence" / name).write_text(json.dumps(record))
    return issue


def good_manifest(ws: Path, **changes: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "issue": "forget-user",
        "assessment": {"labels": ["personal-data"]},
        "github": {"repo": "acme/shop", "number": 12},
        "checkpoints": [],
        "scenarios": [{"id": "TRC-A1", "tests": [f"{TEST_FILE}::test_trc_a1"]},
                      {"id": "TRC-A2", "tests": [f"{TEST_FILE}::test_trc_a1"]}],
        "evidence": [{"id": "EV-G5", "type": "human-approval", "guardrail": "G5",
                      "approver": "sdd-bench-approver", "role": "owner",
                      "scope": "delete a user", "decision": "approved",
                      "timestamp": "2026-10-31T09:30:00Z", "via": "terminal"}],
        "land_commit": git(ws, "rev-parse", "HEAD"),
    }
    manifest.update(changes)
    return manifest


def good_records() -> dict[str, dict[str, Any]]:
    digests = {TEST_FILE: sha(TEST_TEXT)}
    return {
        "red-TRC-A1.json": run_record("TRC-A1", False, "2026-10-31T10:00:00+00:00",
                                      digests=digests),
        "red-TRC-A2.json": run_record("TRC-A2", False, "2026-10-31T10:01:00Z",
                                      digests=digests),
        "green-TRC-A1.json": run_record("TRC-A1", True, "2026-10-31T10:05:00+00:00",
                                        digests=digests),
        "green.json": run_record(None, True, "2026-10-31T10:10:00+00:00", digests=digests),
    }


def statuses(ws: Path) -> dict[str, str]:
    report = check_record.check_workspace(ws)
    assert len(report["issues"]) == 1
    return {k: v["status"] for k, v in report["issues"][0]["checks"].items()}


def test_a_complete_record_passes_every_check(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace), good_records())
    assert statuses(workspace) == {**dict.fromkeys(check_record.CHECKS, "pass"),
                                   "ship-approval": "not-applicable"}
    assert check_record.main(["--workspace", str(workspace)]) == 0


def test_an_8x_record_reports_digests_not_checkable(workspace: Path) -> None:
    records = {name: {k: v for k, v in r.items() if k != "test_files"}
               for name, r in good_records().items()}
    write_issue(workspace, good_manifest(workspace), records)
    report = check_record.check_workspace(workspace)
    digest = report["issues"][0]["checks"]["test-digests"]
    assert digest["status"] == "not-checkable"
    assert "tree_id" in digest["detail"] and "content_digest" in digest["detail"]
    assert report["passed"] is False


def test_a_scenario_with_no_red_fails(workspace: Path) -> None:
    records = good_records()
    del records["red-TRC-A2.json"]
    write_issue(workspace, good_manifest(workspace), records)
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["red-before-green"]
    assert check["status"] == "fail"
    assert check["scenarios"]["TRC-A2"]["detail"] == "no red on record"
    assert check["scenarios"]["TRC-A1"]["status"] == "pass"


def test_a_red_after_the_first_green_fails(workspace: Path) -> None:
    records = good_records()
    records["red-TRC-A1.json"]["timestamp"] = "2026-10-31T10:06:00Z"
    write_issue(workspace, good_manifest(workspace), records)
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["red-before-green"]
    assert check["status"] == "fail"
    assert "not before first green" in check["scenarios"]["TRC-A1"]["detail"]


def test_a_suite_green_counts_for_a_scenario_with_no_green_of_its_own(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace), good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["red-before-green"]
    assert check["scenarios"]["TRC-A2"]["first_green"][1] == "evidence/green.json"


def test_a_manifest_with_no_scenarios_fails(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace, scenarios=[]), good_records())
    assert statuses(workspace)["red-before-green"] == "fail"


def test_a_test_file_changed_after_its_digest_fails(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace), good_records())
    (workspace / TEST_FILE).write_text(TEST_TEXT + "# edited\n")
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["test-digests"]
    assert check["status"] == "fail"
    assert all("digest differs" in m for m in check["mismatches"])


def test_a_digest_naming_a_path_outside_the_workspace_fails(workspace: Path) -> None:
    records = good_records()
    records["green.json"]["test_files"] = {"../outside.py": sha("x")}
    write_issue(workspace, good_manifest(workspace), records)
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["test-digests"]
    assert check["status"] == "fail"
    assert any("outside the workspace" in m for m in check["mismatches"])


def test_a_missing_request_link_fails(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    del manifest["github"]
    write_issue(workspace, manifest, good_records())
    assert statuses(workspace)["request-link"] == "fail"


def test_a_personal_data_label_with_no_sign_off_fails(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace, evidence=[]), good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert check["status"] == "fail"
    assert "labeled personal-data" in check["detail"]


def test_an_approval_given_for_a_check_is_not_the_sign_off(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    manifest["evidence"][0]["check"] = "dod-reviewed"
    write_issue(workspace, manifest, good_records())
    assert statuses(workspace)["approvals"] == "fail"


def test_a_sign_off_by_the_agent_fails(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    manifest["evidence"][0]["approver"] = "agent"
    write_issue(workspace, manifest, good_records())
    assert statuses(workspace)["approvals"] == "fail"


def test_an_unlabeled_change_requires_no_approval(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace, assessment={"labels": []}, evidence=[]),
                good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert check == {"status": "pass", "detail": "the record requires no approval"}


def test_a_listed_checkpoint_needs_its_approval(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace, checkpoints=["define"]), good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert check["status"] == "fail"
    assert "checkpoint:define" in check["detail"]


def test_evidence_required_names_an_approval_type(workspace: Path) -> None:
    manifest = good_manifest(workspace, assessment={"labels": []}, evidence=[],
                             evidence_required=["test-run", {"type": "human-approval"}])
    write_issue(workspace, manifest, good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert check["status"] == "fail"
    assert [a["required"] for a in check["approvals"]] == ["type:human-approval"]


def test_a_land_commit_not_on_the_branch_fails(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    git(workspace, "checkout", "-q", "-b", "side")
    (workspace / "side.txt").write_text("x")
    git(workspace, "add", "side.txt")
    git(workspace, "commit", "-q", "-m", "side")
    manifest["land_commit"] = git(workspace, "rev-parse", "HEAD")
    git(workspace, "checkout", "-q", "main")
    write_issue(workspace, manifest, good_records())
    report = check_record.check_workspace(workspace, branch="main")
    check = report["issues"][0]["checks"]["land-commit"]
    assert check["status"] == "fail" and "is not on main" in check["detail"]


def test_a_land_commit_that_is_no_commit_fails(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace, land_commit="dd4b453d"), good_records())
    assert statuses(workspace)["land-commit"] == "fail"


def test_no_land_commit_fails(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    del manifest["land_commit"]
    write_issue(workspace, manifest, good_records())
    assert statuses(workspace)["land-commit"] == "fail"


def test_a_workspace_with_no_git_reports_land_commit_not_checkable(tmp_path: Path) -> None:
    ws = tmp_path / "copy"
    ws.mkdir()
    write_issue(ws, {"scenarios": [], "land_commit": "abc"}, {})
    assert statuses(ws)["land-commit"] == "not-checkable"


def test_a_workspace_with_no_record_exits_2(tmp_path: Path) -> None:
    assert check_record.main(["--workspace", str(tmp_path)]) == 2


def test_the_cli_writes_a_json_report(workspace: Path, tmp_path: Path,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    write_issue(workspace, good_manifest(workspace, evidence=[]), good_records())
    out = tmp_path / "report.json"
    assert check_record.main(["--workspace", str(workspace), "--json", str(out)]) == 1
    assert json.loads(out.read_text())["issues"][0]["checks"]["approvals"]["status"] == "fail"
    assert "approvals         fail" in capsys.readouterr().out


def test_the_checker_imports_nothing_from_compass() -> None:
    source = (Path(check_record.__file__)).read_text()
    assert "compass_pkg" not in source
    assert "import compass" not in source


# --- the rules added for the 9.0.0 measurement --------------------------------

def test_a_red_that_names_no_scenario_is_reported_as_such(workspace: Path) -> None:
    records = good_records()
    del records["red-TRC-A2.json"]
    records["red.json"] = run_record(None, False, "2026-10-31T10:00:30Z")
    write_issue(workspace, good_manifest(workspace), records)
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["red-before-green"]
    assert check["scenarios"]["TRC-A2"]["detail"] == (
        "no red names this scenario; 1 red(s) on record name no scenario")


def test_the_request_link_must_be_the_expected_one(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace), good_records())
    ok = check_record.check_workspace(workspace, expect_request="acme/shop#12")
    other = check_record.check_workspace(workspace, expect_request="acme/shop#13")
    assert ok["issues"][0]["checks"]["request-link"]["status"] == "pass"
    check = other["issues"][0]["checks"]["request-link"]
    assert check == {"status": "fail", "detail": "links acme/shop#12, not the request acme/shop#13"}


def test_a_request_link_url_alone_counts(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    del manifest["github"]
    manifest["request"] = {"link": "https://github.com/acme/shop/issues/12",
                           "requester": "Sam Taylor"}
    write_issue(workspace, manifest, good_records())
    report = check_record.check_workspace(workspace, expect_request="acme/shop#12")
    assert report["issues"][0]["checks"]["request-link"]["status"] == "pass"


def test_a_request_link_that_is_not_a_github_issue_fails(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    del manifest["github"]
    manifest["request"] = {"link": "https://tracker.example/T-12", "requester": "Sam"}
    write_issue(workspace, manifest, good_records())
    assert statuses(workspace)["request-link"] == "fail"


def test_the_cli_refuses_a_malformed_expected_request(workspace: Path) -> None:
    with pytest.raises(SystemExit):
        check_record.main(["--workspace", str(workspace), "--expect-request", "shop#12"])


def test_a_sign_off_after_the_first_green_fails(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    manifest["evidence"][0]["timestamp"] = "2026-10-31T10:30:00Z"
    write_issue(workspace, manifest, good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert check["status"] == "fail"
    assert "not before the first green at 2026-10-31T10:05:00+00:00" in check["detail"]


def test_a_typed_ship_approval_is_not_the_sign_off(workspace: Path) -> None:
    manifest = good_manifest(workspace)
    manifest["evidence"][0]["ship"] = "forget-user"
    write_issue(workspace, manifest, good_records())
    assert statuses(workspace)["approvals"] == "fail"


def test_a_pull_request_review_is_not_the_sign_off(workspace: Path) -> None:
    manifest = good_manifest(workspace, evidence=[{
        "id": "EV-PR-APPROVAL-1", "type": "pr-approval", "decision": "approved",
        "pull_request": {"repo": "acme/shop", "number": 13},
        "approver": "sdd-bench-approver", "pr_author": "sdd-bench-author",
        "timestamp": "2026-10-31T09:00:00Z"}])
    write_issue(workspace, manifest, good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert check["status"] == "fail"
    assert "no approved human-approval for the sign-off" in check["detail"]


def test_scenario_approval_needs_the_specify_checkpoint_before_code(workspace: Path) -> None:
    manifest = good_manifest(workspace, evidence_required=["scenario-approval"])
    write_issue(workspace, manifest, good_records())
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert [a["required"] for a in check["approvals"]] == ["sign-off", "checkpoint:specify"]
    assert check["status"] == "fail"
    manifest["evidence"].append({
        "id": "EV-CHECKPOINT-specify-1", "type": "checkpoint-approval",
        "checkpoint": "specify", "approver": "sdd-bench-approver",
        "decision": "approved", "timestamp": "2026-10-31T10:06:00Z"})
    (workspace / ".compass/work/forget-user/manifest.yml").write_text(yaml.safe_dump(manifest))
    check = check_record.check_workspace(workspace)["issues"][0]["checks"]["approvals"]
    assert check["status"] == "fail" and "not before the first green" in check["detail"]


def test_a_land_commit_at_the_base_fails(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace), good_records())
    base = git(workspace, "rev-parse", "HEAD")
    check = check_record.check_workspace(workspace, base=base)["issues"][0]["checks"][
        "land-commit"]
    assert check["status"] == "fail" and "cannot hold the change" in check["detail"]


def test_a_land_commit_before_the_base_fails(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace), good_records())
    (workspace / "later.txt").write_text("x")
    git(workspace, "add", "later.txt")
    git(workspace, "commit", "-q", "-m", "later")
    base = git(workspace, "rev-parse", "HEAD")
    check = check_record.check_workspace(workspace, base=base)["issues"][0]["checks"][
        "land-commit"]
    assert check["status"] == "fail"


# A hand-written record in the shape Compass 9.0.0 writes, landed with the
# code on a branch and squash-merged into main by the bench.

V9_STAMP = "2026-11-09T10:20:00+00:00"


def v9_run_record(scenario: str, passed: bool, when: str, text: str) -> dict[str, Any]:
    return {"command": f"python3 -m pytest -q {TEST_FILE}", "scenario": scenario,
            "loop": "outer", "exit_code": 0 if passed else 1, "passed": passed,
            "timestamp": when, "tree_id": "77b694087952af4b2ac2e75fcf83c8e912c02afb",
            "file_sha256": {TEST_FILE: hashlib.sha256(text.encode()).hexdigest(),
                            "shop/orders.py": "0" * 64},
            "file_modes": {TEST_FILE: "100644"}, "test_files": [TEST_FILE],
            "record_id": "34ed65ce02ef41e3", "content_digest": "sha256:" + "1" * 64}


def v9_manifest(merge: str, **changes: Any) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "schema_version": "3.0", "issue": "idem",
        "assessment": {"risk": "contained", "labels": []},
        "github": {"repo": "acme-shop/shop", "number": 41},
        "request": {"link": "https://github.com/acme-shop/shop/issues/41",
                    "requester": "Sam Taylor", "recorded_by": "compass quick-fix start"},
        "evidence_required": ["request", "scenarios", "red-before-green", "suite-green",
                              "correctness", "governance", "traceability", "outer-loop",
                              "ship-approval"],
        "scenarios": [{"id": "TRC-001", "tests": [TEST_FILE]}],
        "status": "done", "land_timestamp": V9_STAMP, "landed_with_record": True,
        "pull_request": {"repo": "acme-shop/shop", "number": 42,
                         "merged_at": "2026-11-09T10:30:00Z", "merge_commit": merge,
                         "author": "sdd-bench-author"},
        "evidence": [{
            "id": "EV-PR-APPROVAL-1", "type": "pr-approval",
            "pull_request": {"repo": "acme-shop/shop", "number": 42},
            "review_id": 9000042, "approver": "sdd-bench-approver",
            "pr_author": "sdd-bench-author", "decision": "approved",
            "timestamp": "2026-11-09T10:29:00Z", "merge_commit": merge,
            "merged_at": "2026-11-09T10:30:00Z", "read_as": "sdd-bench-author",
            "via": "github", "issue": "idem", "generation": 1}],
    }
    manifest.update(changes)
    return manifest


@pytest.fixture
def v9_workspace(tmp_path: Path) -> dict[str, Any]:
    """The seed on main; a branch whose one commit holds the change and the
    record with `land_timestamp`; main squash-merged from it; the working
    tree left on the branch, with the post-merge fields in the manifest."""
    ws = tmp_path / "v9"
    (ws / "tests").mkdir(parents=True)
    (ws / "README.md").write_text("shop\n")
    git(ws, "init", "-q", "-b", "main")
    git(ws, "add", "README.md")
    git(ws, "commit", "-q", "-m", "Initial commit")
    seed = git(ws, "rev-parse", "HEAD")
    git(ws, "checkout", "-q", "-b", "fix/idempotency")
    (ws / TEST_FILE).write_text(TEST_TEXT)
    records = {
        "red-TRC-001.outer.json": v9_run_record("TRC-001", False, "2026-11-09T10:00:00+00:00",
                                                TEST_TEXT),
        "green-TRC-001.outer.json": v9_run_record("TRC-001", True, "2026-11-09T10:10:00+00:00",
                                                  TEST_TEXT)}
    landed = v9_manifest("", evidence=[])
    for key in ("pull_request",):
        del landed[key]
    issue = write_issue(ws, landed, records, slug="idem")
    git(ws, "add", "-A")
    git(ws, "commit", "-q", "-m", "Make create_order idempotent")
    head = git(ws, "rev-parse", "HEAD")
    tree = git(ws, "rev-parse", "HEAD^{tree}")
    merge = git(ws, "commit-tree", tree, "-p", seed, "-m", "Make create_order idempotent (#42)")
    git(ws, "update-ref", "refs/heads/main", merge)
    (issue / "manifest.yml").write_text(yaml.safe_dump(v9_manifest(merge)))
    return {"ws": ws, "seed": seed, "head": head, "merge": merge, "issue": issue}


def v9_check(world: dict[str, Any], **kw: Any) -> dict[str, Any]:
    report = check_record.check_workspace(world["ws"], "main", base=world["seed"],
                                          expect_request="acme-shop/shop#41", **kw)
    assert len(report["issues"]) == 1
    return report["issues"][0]


def rewrite(world: dict[str, Any], manifest: dict[str, Any]) -> None:
    (world["issue"] / "manifest.yml").write_text(yaml.safe_dump(manifest))


def test_a_9x_record_passes_every_check(v9_workspace: dict[str, Any]) -> None:
    item = v9_check(v9_workspace)
    assert {k: v["status"] for k, v in item["checks"].items()} == dict.fromkeys(
        check_record.CHECKS, "pass")
    assert item["checks"]["land-commit"]["land_commit"] == v9_workspace["merge"]
    assert "read from git" in item["checks"]["land-commit"]["detail"]
    assert item["passed"] is True


def test_a_9x_land_commit_is_not_the_branch_commit(v9_workspace: dict[str, Any]) -> None:
    # On the session's branch the commit that added the stamp is the branch
    # commit; on main it is the squash commit.
    report = check_record.check_workspace(v9_workspace["ws"], "fix/idempotency",
                                          base=v9_workspace["seed"])
    check = report["issues"][0]["checks"]["land-commit"]
    assert check["land_commit"] == v9_workspace["head"]


def test_a_9x_record_never_merged_fails_land_commit(v9_workspace: dict[str, Any]) -> None:
    git(v9_workspace["ws"], "update-ref", "refs/heads/main", v9_workspace["seed"])
    check = v9_check(v9_workspace)["checks"]["land-commit"]
    assert check["status"] == "fail" and "no commit on main added" in check["detail"]


def test_a_9x_digest_that_differs_from_the_file_fails(v9_workspace: dict[str, Any]) -> None:
    (v9_workspace["ws"] / TEST_FILE).write_text(TEST_TEXT + "# edited\n")
    check = v9_check(v9_workspace)["checks"]["test-digests"]
    assert check["status"] == "fail"
    assert len(check["mismatches"]) == 2  # only the test file, in each record


def test_a_9x_record_linking_another_request_fails(v9_workspace: dict[str, Any]) -> None:
    rewrite(v9_workspace, v9_manifest(v9_workspace["merge"],
                                      github={"repo": "acme-shop/shop", "number": 99}))
    assert v9_check(v9_workspace)["checks"]["request-link"]["status"] == "fail"


def test_a_9x_record_with_no_ship_approval_fails(v9_workspace: dict[str, Any]) -> None:
    rewrite(v9_workspace, v9_manifest(v9_workspace["merge"], evidence=[]))
    check = v9_check(v9_workspace)["checks"]["ship-approval"]
    assert check["status"] == "fail" and "owed" in check["detail"]


@pytest.mark.parametrize("change, words", [
    ({"approver": "sdd-bench-author"}, "the approver is the pull request's author"),
    ({"approver": "agent"}, "the approver is not a person"),
    ({"pull_request": {"repo": "acme-shop/shop", "number": 7}}, "not the linked"),
    ({"timestamp": None}, "no time"),
])
def test_a_9x_pr_approval_that_does_not_count_fails(v9_workspace: dict[str, Any],
                                                    change: dict[str, Any], words: str) -> None:
    manifest = v9_manifest(v9_workspace["merge"])
    manifest["evidence"][0].update(change)
    rewrite(v9_workspace, manifest)
    check = v9_check(v9_workspace)["checks"]["ship-approval"]
    assert check["status"] == "fail" and words in check["detail"]


def test_a_typed_ship_approval_counts(v9_workspace: dict[str, Any]) -> None:
    rewrite(v9_workspace, v9_manifest(v9_workspace["merge"], evidence=[{
        "id": "EV-APPROVAL-SHIP-1", "type": "human-approval", "ship": "idem",
        "approver": "sdd-bench-approver", "role": "owner", "decision": "approved",
        "timestamp": "2026-11-09T10:29:00Z", "issue": "idem", "generation": 1}]))
    assert v9_check(v9_workspace)["checks"]["ship-approval"]["status"] == "pass"


def test_a_record_not_owing_a_ship_approval_can_be_required_to(workspace: Path) -> None:
    write_issue(workspace, good_manifest(workspace), good_records())
    report = check_record.check_workspace(workspace, require_ship_approval=True)
    assert report["issues"][0]["checks"]["ship-approval"]["status"] == "fail"
    assert report["passed"] is False


def test_the_cli_takes_the_9x_options(v9_workspace: dict[str, Any], tmp_path: Path,
                                      capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "check.json"
    code = check_record.main(["--workspace", str(v9_workspace["ws"]), "--branch", "main",
                              "--base", v9_workspace["seed"],
                              "--expect-request", "acme-shop/shop#41", "--json", str(out)])
    assert code == 0
    report = json.loads(out.read_text())
    assert report["base"] == v9_workspace["seed"]
    assert "ship-approval     pass" in capsys.readouterr().out
