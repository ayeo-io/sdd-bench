"""Tests for tools/fake_gh.py, the `gh` the harness puts first on a session's
PATH. Each call runs the file as the wrapper does, `python3 -I`, with
`GH_FAKE_STATE` naming a state file, and no real `gh` is ever started."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

FAKE = Path(__file__).resolve().parent.parent / "fake_gh.py"
REVIEWS_JQ = (".[] | {id, state, submitted_at, commit_id, html_url, "
              "user: {login: .user.login, type: .user.type}}")
PR = {"number": 42, "title": "Make create_order idempotent", "state": "MERGED",
      "mergeCommit": {"oid": "b" * 40}, "mergedAt": "2026-11-09T10:30:00Z",
      "author": {"login": "sdd-bench-author"}, "headRefOid": "a" * 40,
      "headRefName": "fix/idem", "baseRefName": "main",
      "url": "https://github.com/acme-shop/shop/pull/42"}
REVIEW = {"id": 9000042, "state": "APPROVED", "submitted_at": "2026-11-09T10:29:00Z",
          "commit_id": "a" * 40, "html_url": PR["url"] + "#pullrequestreview-9000042",
          "user": {"login": "sdd-bench-approver", "type": "User"}}


@pytest.fixture
def state(tmp_path: Path) -> Path:
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "repo": "acme-shop/shop", "login": "sdd-bench-author",
        "issues": {"acme-shop/shop#41": {"number": 41, "title": "Duplicate orders",
                                         "state": "OPEN"}},
        "prs": {"acme-shop/shop#42": PR}, "reviews": {"acme-shop/shop#42": [REVIEW]}}))
    return path


def gh(state: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ.get("PATH", ""), "GH_FAKE_STATE": str(state)}
    return subprocess.run([sys.executable, "-I", str(FAKE), *argv], capture_output=True,
                          text=True, env=env)


def calls(state: Path) -> list[dict]:
    return [json.loads(line) for line in (state.parent / "calls.jsonl").read_text().splitlines()]


def test_pr_view_prints_only_the_fields_asked_for(state: Path) -> None:
    done = gh(state, "pr", "view", "42", "--repo", "acme-shop/shop",
              "--json", "number,state,mergeCommit,mergedAt,author,headRefOid,url")
    assert done.returncode == 0
    assert json.loads(done.stdout) == {k: PR[k] for k in (
        "number", "state", "mergeCommit", "mergedAt", "author", "headRefOid", "url")}


def test_a_pull_request_not_yet_merged_is_not_found(state: Path) -> None:
    done = gh(state, "pr", "view", "43", "--repo", "acme-shop/shop", "--json", "number")
    assert done.returncode == 1 and "Could not resolve" in done.stderr


def test_the_reviews_call_prints_one_object_a_line(state: Path) -> None:
    done = gh(state, "api", "--paginate", "repos/acme-shop/shop/pulls/42/reviews",
              "--jq", REVIEWS_JQ)
    assert done.returncode == 0
    assert [json.loads(line) for line in done.stdout.splitlines()] == [REVIEW]


def test_the_user_call_prints_the_login(state: Path) -> None:
    done = gh(state, "api", "user", "--jq", ".login")
    assert (done.returncode, done.stdout) == (0, "sdd-bench-author\n")


def test_issue_view_answers_the_request(state: Path) -> None:
    done = gh(state, "issue", "view", "41", "--repo", "acme-shop/shop", "--json", "title")
    assert json.loads(done.stdout) == {"title": "Duplicate orders"}


@pytest.mark.parametrize("argv", [
    ("pr", "review", "42", "--approve"),
    ("api", "--method", "POST", "repos/acme-shop/shop/pulls/42/reviews", "-f",
     "event=APPROVE"),
    ("api", "repos/acme-shop/shop/issues/41/comments", "-f", "body=hi"),
    ("api", "repos/acme-shop/shop/pulls/42/reviews", "--jq", ".[0]"),
    ("auth", "status"),
    ("--version",),
])
def test_anything_else_exits_1_and_is_logged(state: Path, argv: tuple[str, ...]) -> None:
    done = gh(state, *argv)
    assert done.returncode == 1 and done.stdout == ""
    assert calls(state)[-1] == {"argv": list(argv), "exit": 1, "at": calls(state)[-1]["at"]}


def test_every_call_is_logged(state: Path) -> None:
    gh(state, "api", "user", "--jq", ".login")
    gh(state, "pr", "view", "42", "--json", "number")
    assert [c["argv"][:2] for c in calls(state)] == [["api", "user"], ["pr", "view"]]
    assert [c["exit"] for c in calls(state)] == [0, 0]


def test_no_state_file_exits_1(tmp_path: Path) -> None:
    done = gh(tmp_path / "missing.json", "api", "user")
    assert done.returncode == 1 and "GH_FAKE_STATE" in done.stderr


# --- how the harness sets it up ----------------------------------------------

sys.path.insert(0, str(FAKE.parent))
import harness  # noqa: E402


def test_the_harness_puts_the_fake_first_with_no_login(tmp_path: Path) -> None:
    env = {"PATH": "/usr/bin:/bin", "GH_TOKEN": "secret", "GITHUB_TOKEN": "secret"}
    root = harness._sdd_fake_github(env)
    try:
        assert env["PATH"].split(os.pathsep)[0] == str(root / "bin")
        assert list(Path(env["GH_CONFIG_DIR"]).iterdir()) == []
        assert "GH_TOKEN" not in env and "GITHUB_TOKEN" not in env
        harness._sdd_reset_github(root, {
            "id": "shop-idempotency", "prompt": "Retry.\n\nRequest: x",
            "request": {"repo": "acme-shop/shop", "number": 41, "requester": "Sam Taylor"}})
        done = subprocess.run(["gh", "issue", "view", "41", "--json", "author,body"],
                              capture_output=True, text=True, env=env)
        assert json.loads(done.stdout) == {"author": {"login": "sam-taylor"},
                                           "body": "Retry."}
        assert len((root / "calls.jsonl").read_text().splitlines()) == 1
    finally:
        import shutil
        shutil.rmtree(root)


def test_the_seed_repository_has_main_and_a_local_push_url(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("a\n")
    env = {"PATH": os.environ.get("PATH", "")}
    seed = harness._git_init_and_commit(repo, env, origin="https://github.com/acme-shop/shop.git",
                                        push_url=tmp_path / "remote.git")

    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                              text=True).stdout.strip()

    assert git("symbolic-ref", "--short", "HEAD") == "main"
    assert git("config", "--get", "remote.origin.url") == "https://github.com/acme-shop/shop.git"
    assert git("config", "--get", "remote.origin.pushurl") == str(tmp_path / "remote.git")
    assert git("rev-parse", "refs/remotes/origin/main") == seed
    assert git("symbolic-ref", "refs/remotes/origin/HEAD") == "refs/remotes/origin/main"
