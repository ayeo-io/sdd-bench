"""Tests for tools/check_record.py, on small issue records built in a temporary
workspace. The 8.x fixture copies the shape of a real Compass 8.0.4 record:
red and green files that hold `tree_id`, `changes_id` and `content_digest`,
and a manifest with `scenarios:`, `evidence:` and `land_commit`."""

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
                      "timestamp": "2026-10-31T10:30:00Z", "via": "terminal"}],
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
    assert statuses(workspace) == dict.fromkeys(check_record.CHECKS, "pass")
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
