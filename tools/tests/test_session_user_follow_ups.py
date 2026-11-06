"""The root eval run with --session-user closes six gaps left by the reviews
of the --session-user hardening.

A root run starts each session as a dedicated, unprivileged user, and
detects - never resets - what one run leaves for the next. The reviews of
that change (issue `harness-session-user-hardening`) left six gaps:

1. a folder's mode under the user's Claude configuration was not recorded;
2. the account check ran once, before the first run only;
3. a change made between runs, by a scheduled job, went unseen;
4. root read a watched file whole, whatever its size;
5. a held call whose kill-all failed left its readers and pipes open;
6. two lines had no test that fails without them.

No test here starts a process as another user or ends processes by user, so
all of them run on a developer's machine. `tests/test_harness_root_real.py`
holds the real-root cases.

Scenario id: SF-1 (issue `session-user-follow-ups`).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
import host_launch  # noqa: E402


def _home(tmp_path):
    home = tmp_path / "home"
    (home / ".claude" / "projects" / "-work" / "memory").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{}\n")
    return home


# --- 1: folder modes are recorded -------------------------------------------

@pytest.mark.parametrize("folder", [".claude", ".claude/projects",
                                    ".claude/projects/-work"])
def test_sf_1_a_folder_made_unreadable_is_a_change(tmp_path, folder):
    home = _home(tmp_path)
    before = harness._session_config_fingerprint(home)
    target = home / folder
    os.chmod(target, 0o000)
    try:
        after = harness._session_config_fingerprint(home)
    finally:
        os.chmod(target, 0o755)
    assert folder in harness._config_changes(before, after), (before, after)


# --- 2: the account is checked before every run -----------------------------

class _Stop(Exception):
    pass


def _run_once_until_version(monkeypatch, session_user, run_index=2):
    """Call `run_once` and stop it at its first step after the checks."""
    def stop(*a, **k):
        raise _Stop
    monkeypatch.setattr(harness, "_claude_version", stop)
    with pytest.raises((_Stop, SystemExit)) as raised:
        harness.run_once({"id": "s"}, Path("."), "bare", run_index, "claude",
                         plugin_source=ROOT, plugin_copy_dir=None,
                         r1_scripts_dir=Path("."), child_env={},
                         session_user=session_user)
    return raised


def test_sf_1_a_job_installed_during_a_run_stops_the_next(monkeypatch):
    user = harness.SessionUser("evaluser", 1500, 1500, "/home/evaluser")
    monkeypatch.setattr(harness, "_account_in_use", lambda entry: "a crontab")
    raised = _run_once_until_version(monkeypatch, user)
    assert raised.type is SystemExit
    assert "a crontab" in str(raised.value) and "run 2" in str(raised.value)


def test_sf_1_an_idle_account_lets_the_run_start(monkeypatch):
    user = harness.SessionUser("evaluser", 1500, 1500, "/home/evaluser")
    seen = []
    monkeypatch.setattr(harness, "_account_in_use",
                        lambda entry: seen.append(entry.pw_name))
    raised = _run_once_until_version(monkeypatch, user)
    assert raised.type is _Stop
    assert seen == ["evaluser"]


# --- 3: a change between runs is recorded ------------------------------------

def test_sf_1_a_change_between_runs_is_listed():
    previous_after = {".claude/settings.json": "file:644:aaa"}
    this_before = {".claude/settings.json": "file:644:bbb"}
    listed = harness._between_runs(previous_after, this_before)
    assert listed == ["before this run: .claude/settings.json"]
    assert harness._between_runs(None, this_before) == []
    assert harness._between_runs(this_before, this_before) == []


# --- 4: a watched file has a size cap ----------------------------------------

def test_sf_1_an_oversized_file_is_recorded_as_too_large(tmp_path, monkeypatch):
    home = _home(tmp_path)
    monkeypatch.setattr(harness, "_CONFIG_READ_CAP", 1024)
    (home / "CLAUDE.md").write_bytes(b"x" * 2048)
    found = harness._session_config_fingerprint(home)
    assert found["CLAUDE.md"].endswith(":too-large"), found["CLAUDE.md"]
    (home / "CLAUDE.md").write_bytes(b"x" * 100)
    assert not harness._session_config_fingerprint(home)["CLAUDE.md"].endswith(
        ":too-large")


# --- 5: a held call's readers and pipes are closed ----------------------------

def test_sf_1_a_held_call_whose_kill_all_failed_leaves_no_reader(tmp_path):
    pid_file = tmp_path / "child.pid"
    command = ["sh", "-c", f"echo hi; sleep 60 & echo $! > {pid_file}; exit 0"]
    before = set(threading.enumerate())
    try:
        call = host_launch.run_session_user_call(
            command, end_processes=lambda: None, grace=0.5)
        assert call.held is True
        time.sleep(0.5)
        left = [t for t in set(threading.enumerate()) - before if t.is_alive()]
        assert left == [], left
    finally:
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 9)
            except ProcessLookupError:
                pass


# --- 6: the two lines that had no test ----------------------------------------

def test_sf_1_run_once_clears_the_held_calls_of_the_previous_run(monkeypatch):
    monkeypatch.setattr(harness, "_HELD_CALLS", ["from the previous run"])
    _run_once_until_version(monkeypatch, None, run_index=1)
    assert harness._HELD_CALLS == []


def test_sf_1_a_lone_carriage_return_becomes_a_newline():
    call = host_launch.run_session_user_call(
        ["printf", "a\\rb"], end_processes=lambda: None, grace=1)
    assert call.stdout == "a\nb"


# --- review 1: a new, empty project folder is not a change ---------------------

def test_sf_1_a_new_empty_project_folder_is_not_a_change(tmp_path):
    # Claude creates `~/.claude/projects/<cwd>/memory/` for every session,
    # and each eval run has a fresh cwd. An empty folder steers nothing.
    home = _home(tmp_path)
    before = harness._session_config_fingerprint(home)
    (home / ".claude" / "projects" / "-tmp-run-2" / "memory").mkdir(parents=True)
    after = harness._session_config_fingerprint(home)
    assert harness._run_config_changes(before, after) == []
    (home / ".claude" / "projects" / "-tmp-run-2" / "memory" / "MEMORY.md").write_text("x\n")
    changed = harness._run_config_changes(
        before, harness._session_config_fingerprint(home))
    assert ".claude/projects/-tmp-run-2/memory/MEMORY.md" in changed, changed


def test_sf_1_the_between_runs_record_carries_into_the_next_run(monkeypatch):
    monkeypatch.setattr(harness, "_LAST_CONFIG_AFTER", None)
    first = harness._record_config_changes({"CLAUDE.md": "file:644:a"},
                                           {"CLAUDE.md": "file:644:a"})
    assert first == []
    second = harness._record_config_changes({"CLAUDE.md": "file:644:b"},
                                            {"CLAUDE.md": "file:644:b"})
    assert second == ["before this run: CLAUDE.md"]


def test_sf_1_a_high_file_descriptor_still_returns_the_output():
    import resource
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    if hard != resource.RLIM_INFINITY and hard < 1200:
        pytest.skip("cannot open enough descriptors here")
    resource.setrlimit(resource.RLIMIT_NOFILE, (max(soft, 1200), hard))
    held = [os.open(os.devnull, os.O_RDONLY) for _ in range(1100)]
    try:
        call = host_launch.run_session_user_call(
            ["sh", "-c", "echo high-fd"], end_processes=lambda: None, grace=1)
    finally:
        for fd in held:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    assert call.stdout == "high-fd\n", call
