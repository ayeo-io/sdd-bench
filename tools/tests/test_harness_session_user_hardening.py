"""A root run with --session-user cannot be hung, needs a dedicated account,
and shows when one run left Claude configuration that could steer the next.

The reviews of the first --session-user change left four routes open. A
process the session started could hold a call's output open, so the harness
waited as long as that process lived. The account could be busy with other
work, which the kill-all would end. One run could leave settings or
instructions in the account's home that steered the next, unseen. And the
privilege-drop arguments were built in three places that could drift apart.

The maintainer chose to detect, never reset: the harness changes nothing in
the session user's account (5 October 2026). `tests/test_harness_root_real.py`
covers the same scenarios as real root.

Scenario ids: SUH-1 to SUH-6 (issue `harness-session-user-hardening`).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
import host_launch  # noqa: E402


# --- SUH-1: a survivor holding the output cannot hang a call ----------------

def _holding_command(pid_file: Path) -> list[str]:
    """A shell that prints, starts a child holding the same output, records
    the child's pid and exits at once."""
    return ["sh", "-c", f"echo hi; sleep 60 & echo $! > {pid_file}; exit 3"]


def test_suh_1_a_survivor_holding_the_output_is_ended_not_waited_on(tmp_path):
    pid_file = tmp_path / "child.pid"
    ended = []

    def end_processes():
        pid = int(pid_file.read_text())
        ended.append(pid)
        os.kill(pid, 9)

    start = time.monotonic()
    call = host_launch.run_session_user_call(
        _holding_command(pid_file), end_processes=end_processes, grace=1)
    assert time.monotonic() - start < 20, "the call waited on the survivor"
    assert call.held is True
    assert ended, "the survivor was not ended"
    assert call.returncode == 3
    assert call.stdout.strip() == "hi"


def test_suh_1_a_call_with_no_survivor_is_not_held(tmp_path):
    call = host_launch.run_session_user_call(
        ["sh", "-c", "echo out; echo err >&2"],
        end_processes=lambda: pytest.fail("nothing was holding the output"),
        grace=5)
    assert (call.held, call.returncode) == (False, 0)
    assert call.stdout.strip() == "out" and call.stderr.strip() == "err"


def test_suh_1_a_large_output_does_not_block_the_call():
    # The output is read while the call runs, so a child that writes more
    # than a pipe holds is never stuck waiting for the harness to read.
    call = host_launch.run_session_user_call(
        [sys.executable, "-c", "print('x' * 1_000_000)"],
        end_processes=lambda: None, grace=5)
    assert call.held is False and len(call.stdout.strip()) == 1_000_000


def test_suh_1_a_held_test_command_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "_SESSION_FOLDER", (tmp_path, (1500, 1500)))
    monkeypatch.setattr(harness, "_HELD_CALLS", [])
    monkeypatch.setattr(
        harness.host_launch, "run_session_user_call",
        lambda *a, **k: host_launch.SessionCall(0, "", "", True))
    monkeypatch.setattr(harness, "_end_session_user_processes",
                        lambda *a, **k: None)
    harness._run_test_command("python3 run_tests.py", tmp_path, {})
    harness._run_git(["status"], tmp_path, {})
    assert harness._HELD_CALLS == ["test command", "git status"]


# --- SUH-2 and SUH-3: the account must be dedicated -------------------------

class _User:
    pw_name, pw_uid, pw_gid, pw_dir = "evaluser", 1500, 1500, "/home/evaluser"


def _runner(results):
    """A stand-in for `subprocess.run` answering each probe by its command."""
    def run(command, **kwargs):
        for prefix, (code, out, err) in results.items():
            if command[0] == prefix:
                return subprocess.CompletedProcess(command, code, out, err)
        raise FileNotFoundError(command[0])
    return run


IDLE = {"pgrep": (1, "", ""), "crontab": (1, "", "no crontab for evaluser\n"),
        "atq": (0, "", "")}


def test_suh_2_an_idle_account_is_accepted():
    assert harness._account_in_use(_User, run=_runner(IDLE)) is None


def test_suh_2_an_account_with_running_processes_is_refused():
    reason = harness._account_in_use(
        _User, run=_runner({**IDLE, "pgrep": (0, "101\n202\n", "")}))
    assert reason and "2 running processes" in reason


def test_suh_3_an_account_with_a_crontab_is_refused():
    reason = harness._account_in_use(
        _User, run=_runner({**IDLE, "crontab": (0, "* * * * * true\n", "")}))
    assert reason and "a crontab" in reason


def test_suh_3_an_account_with_a_queued_at_job_is_refused():
    queue = "7\tMon Oct  6 09:00:00 2026 a evaluser\n8\tMon Oct  6 09:00:00 2026 a other\n"
    reason = harness._account_in_use(
        _User, run=_runner({**IDLE, "atq": (0, queue, "")}))
    assert reason and "1 queued at job" in reason


def test_suh_3_a_probe_that_fails_refuses_rather_than_passing():
    reason = harness._account_in_use(
        _User, run=_runner({**IDLE, "crontab": (1, "", "permission denied\n")}))
    assert reason and "could not check" in reason


def test_suh_3_a_scheduler_that_is_not_installed_holds_no_jobs():
    # No `atq` or `crontab` on the machine means nothing can be queued.
    reason = harness._account_in_use(_User, run=_runner({"pgrep": (1, "", "")}))
    assert reason is None


def test_suh_2_the_refusal_names_the_account_and_why(monkeypatch):
    reason = harness._root_refusal(
        "compass", None, allow_root=False, euid=0, session_user="evaluser",
        env={}, lookup=lambda name: _User,
        probe=lambda entry: "2 running processes")
    assert reason and "evaluser" in reason and "2 running processes" in reason


# --- SUH-4: a changed Claude configuration is flagged -----------------------

def _home(tmp_path):
    home = tmp_path / "home"
    (home / ".claude" / "projects" / "p" / "memory").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{}\n")
    (home / ".claude" / ".credentials.json").write_text("secret\n")
    (home / ".claude" / "projects" / "p" / "memory" / "m.md").write_text("a\n")
    (home / ".claude" / "projects" / "p" / "session.jsonl").write_text("t\n")
    return home


def test_suh_4_a_changed_instruction_or_memory_is_listed(tmp_path):
    home = _home(tmp_path)
    before = harness._session_config_fingerprint(home)
    (home / ".claude" / "CLAUDE.md").write_text("always do X\n")
    (home / ".claude" / "projects" / "p" / "memory" / "m.md").write_text("b\n")
    after = harness._session_config_fingerprint(home)
    assert harness._config_changes(before, after) == [
        ".claude/CLAUDE.md", ".claude/projects/p/memory/m.md"]


def test_suh_4_credentials_and_transcripts_are_not_watched(tmp_path):
    home = _home(tmp_path)
    before = harness._session_config_fingerprint(home)
    (home / ".claude" / ".credentials.json").write_text("rotated\n")
    (home / ".claude" / "projects" / "p" / "session.jsonl").write_text("u\n")
    assert harness._config_changes(
        before, harness._session_config_fingerprint(home)) == []


def test_suh_4_a_link_in_the_home_is_not_followed(tmp_path):
    home = _home(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("root's own file\n")
    (home / "CLAUDE.md").symlink_to(outside)
    print_ = harness._session_config_fingerprint(home)
    assert "CLAUDE.md" in print_
    assert print_["CLAUDE.md"] != harness._session_config_fingerprint(
        tmp_path / "nowhere").get("CLAUDE.md")
    outside.write_text("changed\n")
    # The link is recorded as a link; what it names is never read.
    assert harness._session_config_fingerprint(home)["CLAUDE.md"] == print_["CLAUDE.md"]


# --- SUH-6: one helper builds the privilege drop -----------------------------

def test_suh_6_git_and_the_tests_use_the_helper(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "_SESSION_FOLDER", (tmp_path, (1500, 1501)))
    assert harness._as_session_user(tmp_path) == host_launch.session_user_args(1500, 1501)


def test_suh_6_the_kill_all_uses_the_helper(monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(harness.subprocess, "run", run)
    harness._end_session_user_processes(1500, 1501, {})
    for key, value in host_launch.session_user_args(1500, 1501).items():
        assert seen.get(key) == value, key


def test_suh_6_the_session_launch_uses_the_helper(monkeypatch, tmp_path):
    seen = {}

    def call(command, **kwargs):
        seen.update(kwargs)
        return host_launch.SessionCall(0, "", "", False)

    monkeypatch.setattr(host_launch, "run_session_user_call", call)
    host_launch.launch_claude("claude", "hi", [], tmp_path, {},
                              user=(1500, 1501), end_processes=lambda: None)
    for key, value in host_launch.session_user_args(1500, 1501).items():
        assert seen.get(key) == value, key


# --- output that is not UTF-8, interrupts and linked folders ---------------

def _finishes_within(seconds, fn):
    import threading
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("v", fn()),
                              daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"still running after {seconds} s"
    return result["v"]


def test_suh_1_output_that_is_not_utf8_cannot_hang_the_call():
    # One bad byte must not stop the reading: a child that then writes more
    # than a pipe holds would block for good. An ordinary Latin-1 file in a
    # `git diff` is enough.
    code = "import sys; sys.stdout.buffer.write(b'\\xff' + b'x' * 1_000_000)"
    call = _finishes_within(30, lambda: host_launch.run_session_user_call(
        [sys.executable, "-c", code], end_processes=lambda: None, grace=5))
    assert call.held is False
    assert len(call.stdout) >= 1_000_000


def test_suh_1_an_interrupt_ends_the_call_and_the_users_processes(monkeypatch):
    ended = []
    real_wait = subprocess.Popen.wait

    raised = []

    def interrupted(self, *args, **kwargs):
        # Only the first wait is interrupted, so the clean-up's own wait
        # reaps the child as it would after a real Ctrl-C.
        if not raised:
            raised.append(True)
            raise KeyboardInterrupt
        return real_wait(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupted)
    started = []
    real_init = subprocess.Popen.__init__

    def keep(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        started.append(self)

    monkeypatch.setattr(subprocess.Popen, "__init__", keep)
    with pytest.raises(KeyboardInterrupt):
        host_launch.run_session_user_call(
            ["sleep", "60"], end_processes=lambda: ended.append(True), grace=1)
    assert ended == [True]
    assert started and started[0].returncode is not None, (
        "the call was left running")


def test_suh_4_a_linked_folder_is_recorded_as_a_link(tmp_path):
    home = _home(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    before = harness._session_config_fingerprint(home)
    (home / ".claude" / "skills").mkdir()
    (home / ".claude" / "skills" / "linked").symlink_to(outside)
    (home / ".claude" / "projects" / "p" / "memory" / "more").symlink_to(outside)
    (home / ".claude" / "projects" / "q").symlink_to(outside)
    changes = harness._config_changes(
        before, harness._session_config_fingerprint(home))
    # The skills folder is new as well, and a folder is recorded too.
    assert changes == [".claude/projects/p/memory/more",
                       ".claude/projects/q", ".claude/skills",
                       ".claude/skills/linked"]


def test_suh_4_a_run_without_a_session_user_records_not_checked(
        tmp_path, monkeypatch):
    from test_eval_harness import (_run_condition, _write_fake_claude,
                                   _write_plugin_repo, _write_scenario)
    _, record, _ = _run_condition(
        tmp_path, _write_scenario(tmp_path), _write_fake_claude(tmp_path),
        "bare", monkeypatch, _write_plugin_repo(tmp_path / "plugin-source"))
    assert record["session_config_changed"] is None


@pytest.mark.parametrize("linked", [".claude", ".claude/projects"])
def test_suh_4_a_linked_folder_above_the_watched_paths_is_recorded(
        tmp_path, linked):
    # Wherever a link stops the fingerprint from looking further, the link
    # itself is recorded, at any level.
    home = _home(tmp_path)
    before = harness._session_config_fingerprint(home)
    outside = tmp_path / "outside"
    import shutil
    shutil.copytree(home / linked, outside)
    shutil.rmtree(home / linked)
    (home / linked).symlink_to(outside)
    changes = harness._config_changes(
        before, harness._session_config_fingerprint(home))
    assert linked in changes


def test_suh_1_line_endings_read_as_subprocess_run_reads_them():
    call = host_launch.run_session_user_call(
        ["printf", "a\\r\\nb\\n"], end_processes=lambda: None, grace=5)
    assert call.stdout == subprocess.run(
        ["printf", "a\\r\\nb\\n"], capture_output=True, text=True).stdout


def test_suh_4_a_changed_settings_file_is_listed(tmp_path):
    home = _home(tmp_path)
    before = harness._session_config_fingerprint(home)
    (home / ".claude" / "settings.json").write_text('{"model": "other"}\n')
    assert harness._config_changes(
        before, harness._session_config_fingerprint(home)) == [".claude/settings.json"]


@pytest.mark.parametrize("change", ["mode", "fifo", "folder-mode"])
def test_suh_4_a_changed_permission_or_file_type_is_listed(tmp_path, change):
    # Unreadable settings or a named pipe where an instruction file was
    # can change how the next session behaves as much as new contents.
    home = _home(tmp_path)
    (home / ".claude" / "skills").mkdir()
    before = harness._session_config_fingerprint(home)
    if change == "mode":
        (home / ".claude" / "settings.json").chmod(0o000)
        expected = ".claude/settings.json"
    elif change == "fifo":
        os.mkfifo(home / "CLAUDE.md")
        expected = "CLAUDE.md"
    else:
        (home / ".claude" / "skills").chmod(0o000)
        expected = ".claude/skills"
    try:
        changes = harness._config_changes(
            before, harness._session_config_fingerprint(home))
    finally:
        (home / ".claude" / "settings.json").chmod(0o644)
        (home / ".claude" / "skills").chmod(0o755)
    assert expected in changes


@pytest.mark.parametrize("linked", ["CLAUDE.md", ".claude"])
def test_suh_2_a_linked_configuration_path_refuses_the_account(tmp_path, linked):
    # A link in place before a run would hide every edit made behind it.
    home = _home(tmp_path)
    target = tmp_path / "elsewhere"
    if linked == ".claude":
        import shutil
        shutil.move(str(home / ".claude"), str(target))
    else:
        target.write_text("notes\n")
    (home / linked).symlink_to(target)

    class Linked(_User):
        pw_dir = str(home)

    reason = harness._account_in_use(Linked, run=_runner(IDLE))
    assert reason and linked in reason and "link" in reason


def test_suh_1_an_interrupt_ends_the_call_at_once(monkeypatch):
    # Without the kill the `sleep 60` would run on; the clean-up's wait
    # would then take a minute.
    raised = []
    real_wait = subprocess.Popen.wait

    def interrupted(self, *args, **kwargs):
        if not raised:
            raised.append(True)
            raise KeyboardInterrupt
        return real_wait(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "wait", interrupted)
    start = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        host_launch.run_session_user_call(
            ["sleep", "60"], end_processes=lambda: None, grace=1)
    assert time.monotonic() - start < 10, "the call was not ended"


def test_suh_4_a_link_from_an_earlier_run_is_listed_in_every_later_run(tmp_path):
    # The link refusal runs once, before the first run. A link the first
    # run plants hides what later runs write behind it, so a path that is a
    # link when a run starts is listed for that run: it cannot be checked.
    home = _home(tmp_path)
    notes = tmp_path / "notes.md"
    notes.write_text("before\n")
    (home / ".claude" / "CLAUDE.md").symlink_to(notes)
    before = harness._session_config_fingerprint(home)
    notes.write_text("always do X\n")
    after = harness._session_config_fingerprint(home)
    assert harness._run_config_changes(before, after) == [".claude/CLAUDE.md"]


def test_suh_4_a_run_with_no_links_lists_only_real_changes(tmp_path):
    home = _home(tmp_path)
    before = harness._session_config_fingerprint(home)
    assert harness._run_config_changes(
        before, harness._session_config_fingerprint(home)) == []
