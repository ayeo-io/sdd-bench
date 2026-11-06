"""A root sandbox has a sanctioned, contained way to run sessions with Compass.

A compass run as root is refused unless the plugin copy is on a read-only
mount or `--allow-root` is given. The weekly routine runs only as
root, so it could not measure sessions with Compass, and once used
`--allow-root` to get through. `--session-user` runs each session as an
unprivileged user instead, and `--allow-root` is refused where `CI` or
`COMPASS_UNATTENDED` says nobody is at the terminal.

Scenario ids: HR-A to HR-F (issue `harness-root-sanctioned-path`).
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
import host_launch  # noqa: E402
from test_eval_harness import (  # noqa: E402,F401
    _configure_fake_claude, fake_claude, plugin_source_dir, scenario_dir)


class _User:
    def __init__(self, name, uid, gid, home):
        self.pw_name, self.pw_uid, self.pw_gid, self.pw_dir = name, uid, gid, home


def _lookup(users):
    def lookup(name):
        if name not in users:
            raise KeyError(name)
        return users[name]
    return lookup


SESSION = _User("evaluser", 1500, 1500, "/home/evaluser")
ROOT_USER = _User("root", 0, 0, "/root")
USERS = _lookup({"evaluser": SESSION, "root": ROOT_USER})


def _refusal(**kw):
    # The account check is stubbed idle here; its own tests are in
    # tests/test_harness_session_user_hardening.py.
    base = dict(allow_root=False, euid=0, session_user=None, env={},
                lookup=USERS, probe=lambda entry: None)
    base.update(kw)
    return harness._root_refusal("compass", None, **base)


# --- HR-B: no sanctioned path is refused, naming the sanctioned paths first --

def test_hr_b_a_root_run_with_no_path_is_refused_naming_the_paths_in_order():
    problem = _refusal()
    assert problem
    assert problem.index("--session-user") < problem.index("--allow-root")
    assert problem.index("read-only mount") < problem.index("--allow-root")
    assert "person" in problem[problem.index("--allow-root"):]


# --- HR-C: --allow-root is a person's decision -------------------------------

@pytest.mark.parametrize("env", [{"CI": "true"}, {"COMPASS_UNATTENDED": "1"}])
def test_hr_c_allow_root_is_refused_when_nobody_is_at_the_terminal(env):
    problem = _refusal(allow_root=True, env=env)
    assert problem and "--allow-root" in problem and "scheduled" in problem


def test_hr_c_allow_root_still_works_for_a_person():
    assert _refusal(allow_root=True, env={}) is None


# --- HR-D and HR-E: a session user must be real, unprivileged and needed ---

def test_hr_d_a_session_user_that_is_root_is_refused():
    problem = _refusal(session_user="root")
    assert problem and "root" in problem


def test_hr_d_an_unknown_session_user_is_refused():
    problem = _refusal(session_user="nobody-here")
    assert problem and "nobody-here" in problem


def test_hr_e_a_session_user_without_root_is_refused():
    problem = _refusal(session_user="evaluser", euid=501)
    assert problem and "root" in problem


def test_hr_a_a_valid_session_user_is_a_sanctioned_path():
    assert _refusal(session_user="evaluser") is None


# --- HR-A: the session runs as the user, with its own home and folder -------

def test_hr_a_the_launcher_starts_the_session_as_the_user(monkeypatch, tmp_path):
    seen = {}

    def fake_call(command, **kwargs):
        seen.update(kwargs)
        return host_launch.SessionCall(0, "", "", False)

    monkeypatch.setattr(host_launch, "run_session_user_call", fake_call)
    host_launch.launch_claude("claude", "hi", [], tmp_path, {}, user=(1500, 1500))
    assert seen["user"] == 1500 and seen["group"] == 1500


def test_hr_a_the_launcher_without_a_user_is_unchanged(monkeypatch, tmp_path):
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(host_launch.subprocess, "run", fake_run)
    host_launch.launch_claude("claude", "hi", [], tmp_path, {})
    assert "user" not in seen and "group" not in seen


def test_hr_a_the_session_gets_the_users_home_not_roots(monkeypatch):
    monkeypatch.setenv("HOME", "/root")
    monkeypatch.setenv("TMPDIR", "/root/tmp")
    env = harness._build_child_env("compass", None,
                                   session_user=harness.SessionUser.of(SESSION))
    assert env["HOME"] == "/home/evaluser" and env["USER"] == "evaluser"
    assert "TMPDIR" not in env


def test_hr_a_the_read_only_copies_open_for_reading_only(tmp_path):
    copy = tmp_path / "copy"
    (copy / "bin").mkdir(parents=True)
    (copy / "bin" / "tool").write_text("x")
    os.chmod(copy, 0o700)
    harness._open_for_session_user(copy)
    for path in (copy, copy / "bin"):
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode & stat.S_IROTH and mode & stat.S_IXOTH, oct(mode)
        assert not mode & (stat.S_IWGRP | stat.S_IWOTH), oct(mode)


def test_hr_a_a_root_run_with_a_session_user_records_the_session_uid(
        tmp_path, scenario_dir, fake_claude, plugin_source_dir, monkeypatch):
    # Root and the session user are both played by the user running the
    # tests: the run takes the root path, and every session starts as
    # "evaluser", whose uid is the test user's own, so no real privilege
    # change is needed for the run to complete.
    home = tmp_path / "evaluser-home"
    home.mkdir()
    me = _User("evaluser", os.getuid(), os.getgid(), str(home))
    monkeypatch.setattr(harness, "_euid", lambda: 0)
    monkeypatch.setattr(harness, "_account_in_use", lambda entry: None)
    monkeypatch.setattr(harness, "_lookup_user", _lookup({"evaluser": me}))
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("COMPASS_UNATTENDED", raising=False)
    log_path, out_dir = tmp_path / "log.jsonl", tmp_path / "out"
    _configure_fake_claude(fake_claude, log_path, None)
    code = harness.main(["--scenario", str(scenario_dir), "--condition", "compass",
                         "--claude", str(fake_claude), "--out", str(out_dir),
                         "--plugin-source", str(plugin_source_dir),
                         "--session-user", "evaluser"])
    assert code == 0
    record = json.loads(next(out_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert record["session_uid"] == os.getuid()
    assert record["contained"] is True


# --- HR-F: no session user, no change ----------------------------------------

def test_hr_f_without_a_session_user_the_session_uid_is_the_harness_uid(
        tmp_path, scenario_dir, fake_claude, plugin_source_dir):
    log_path, out_dir = tmp_path / "log.jsonl", tmp_path / "out"
    _configure_fake_claude(fake_claude, log_path, None)
    code = harness.main(["--scenario", str(scenario_dir), "--condition", "bare",
                         "--claude", str(fake_claude), "--out", str(out_dir),
                         "--plugin-source", str(plugin_source_dir)])
    assert code == 0
    record = json.loads(next(out_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert record["session_uid"] == os.geteuid() == record["uid"]


# --- HR-G to HR-I: the mechanisms, checked without root ---------------------
# `tests/test_harness_root_real.py` runs them as real root against a hostile
# session; these keep each rule under every CI job.

def test_hr_g_calls_inside_the_session_folder_run_as_the_user(tmp_path, monkeypatch):
    folder = tmp_path / "session"
    (folder / "sub").mkdir(parents=True)
    monkeypatch.setattr(harness, "_SESSION_FOLDER", (folder, (1500, 1501)))
    inside = harness._as_session_user(folder / "sub")
    assert inside["user"] == 1500 and inside["group"] == 1501
    assert harness._as_session_user(tmp_path) == {}
    monkeypatch.setattr(harness, "_SESSION_FOLDER", None)
    assert harness._as_session_user(folder) == {}


def test_hr_g_git_and_the_tests_ask_for_the_session_user(tmp_path, monkeypatch):
    seen = []

    def fake_run(command, **kwargs):
        seen.append(kwargs.get("user"))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(harness, "_SESSION_FOLDER", (tmp_path, (1500, 1500)))
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    monkeypatch.setattr(harness.host_launch, "run_session_user_call",
                        lambda command, **kwargs: fake_run(command, **kwargs)
                        and host_launch.SessionCall(0, "", "", False))
    harness._run_git(["status"], tmp_path, {})
    harness._run_test_command("python3 run_tests.py", tmp_path, {})
    # Each call is followed by the kill-all, which also runs as the user.
    assert seen and set(seen) == {1500}


def test_hr_h_a_path_through_a_link_is_refused(tmp_path):
    folder = tmp_path / "session"
    (folder / "real").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (folder / "linked").symlink_to(outside)
    assert harness._inside_without_links(folder, folder / "real" / "f")
    assert not harness._inside_without_links(folder, folder / "linked" / "f")
    assert not harness._inside_without_links(folder, tmp_path / "elsewhere")


def test_hr_h_a_linked_config_is_read_as_a_link_and_not_written_through(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_bytes(b"[core]\n")
    snapshot = harness._snapshot_git_config(repo)
    victim = tmp_path / "victim"
    victim.write_text("keep me\n")
    (repo / ".git" / "config").unlink()
    (repo / ".git" / "config").symlink_to(victim)
    tampered = harness._restore_tampered_git_config(repo, snapshot)
    assert ".git/config" in tampered
    assert victim.read_text() == "keep me\n"
    assert not (repo / ".git" / "config").is_symlink()
    assert (repo / ".git" / "config").read_bytes() == b"[core]\n"


def test_hr_h_a_linked_manifest_is_not_read(tmp_path):
    repo = tmp_path / "repo"
    work = repo / ".compass" / "work" / "leak"
    work.mkdir(parents=True)
    secret = tmp_path / "secret"
    secret.write_text("SECRET\n")
    (work / "manifest.yml").symlink_to(secret)
    assert harness._manifests(repo) == {}


def test_hr_i_each_session_call_ends_the_users_processes(tmp_path, monkeypatch):
    calls = []

    def fake_launch(*args, **kwargs):
        return host_launch.Launch(0, "", "", False)

    def fake_run(command, **kwargs):
        calls.append((command, kwargs.get("user")))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(harness.host_launch, "launch_claude", fake_launch)
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    state = harness._new_run_state()
    state["as_user"] = (1500, 1500)
    harness._invoke_claude("claude", "hi", [], tmp_path, state, resume=None,
                           remaining_budget=1.0, env={})
    assert len(calls) == 1 and calls[0][1] == 1500
    assert "os.kill(-1" in calls[0][0][-1]


def _kill_alls(calls):
    return [c for c in calls if "os.kill(-1" in c[0][-1]]


def test_hr_i_git_and_the_tests_end_the_users_processes(tmp_path, monkeypatch):
    # The test command runs code the session wrote, and git runs hooks and
    # filters it may name; either can leave a process running.
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs.get("user")))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(harness, "_SESSION_FOLDER", (tmp_path, (1500, 1500)))
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    monkeypatch.setattr(harness.host_launch, "run_session_user_call",
                        lambda command, **kwargs: fake_run(command, **kwargs)
                        and host_launch.SessionCall(0, "", "", False))
    harness._run_git(["status"], tmp_path, {})
    assert [user for _, user in _kill_alls(calls)] == [1500]
    harness._run_test_command("python3 run_tests.py", tmp_path, {})
    assert [user for _, user in _kill_alls(calls)] == [1500, 1500]
    assert calls[-1] == _kill_alls(calls)[-1], "the kill-all runs last"


def test_hr_i_a_kill_all_that_fails_stops_the_run(monkeypatch):
    # A kill-all that could not run leaves the processes it was for.
    monkeypatch.setattr(
        harness.subprocess, "run",
        lambda command, **k: subprocess.CompletedProcess(command, 1, "", "boom"))
    with pytest.raises(SystemExit, match="could not end"):
        harness._end_session_user_processes(1500, 1500, {})


def test_hr_i_the_kill_all_accepts_a_user_with_nothing_left_running():
    # `os.kill(-1, ...)` raises ProcessLookupError when the user has no
    # process left, the usual case. Checked on the code, never run here.
    assert "ProcessLookupError" in harness._KILL_ALL_CODE


@pytest.mark.parametrize("own_or_root", ["own", "root"])
def test_hr_i_the_kill_all_never_runs_as_the_harness_uid_or_root(
        tmp_path, monkeypatch, own_or_root):
    # Run as the harness's own uid, the kill-all ended the operator's whole
    # login session, including the terminal running the tests.
    calls = []
    monkeypatch.setattr(harness.host_launch, "launch_claude",
                        lambda *a, **k: host_launch.Launch(0, "", "", False))
    monkeypatch.setattr(harness.subprocess, "run",
                        lambda command, **k: calls.append(command))
    uid = os.geteuid() if own_or_root == "own" else 0
    state = harness._new_run_state()
    state["as_user"] = (uid, uid)
    harness._invoke_claude("claude", "hi", [], tmp_path, state, resume=None,
                           remaining_budget=1.0, env={})
    assert calls == []


# --- HR-J: a CI job runs the real-root tests as root -------------------------

# --- HR-H: hard links, named pipes and `.git/HEAD` --------------------------

def _reads_without_blocking(fn, unblock):
    import threading
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("v", fn()),
                              daemon=True)
    thread.start()
    thread.join(5)
    if thread.is_alive():
        unblock()
        thread.join(5)
        pytest.fail("the read waited on a named pipe")
    return result.get("v")


def _fifo(path):
    os.mkfifo(path)

    def unblock():
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
    return unblock


def test_hr_h_a_piped_manifest_is_not_waited_on(tmp_path):
    work = tmp_path / "repo" / ".compass" / "work" / "pipe"
    work.mkdir(parents=True)
    unblock = _fifo(work / "manifest.yml")
    assert _reads_without_blocking(
        lambda: harness._manifests(tmp_path / "repo"), unblock) == {}


def test_hr_h_a_piped_interruptions_log_is_not_waited_on(tmp_path):
    compass = tmp_path / "repo" / ".compass"
    compass.mkdir(parents=True)
    unblock = _fifo(compass / "interruptions.log")
    assert _reads_without_blocking(
        lambda: harness._interruptions(tmp_path / "repo"), unblock) == {
            "hook_blocks": 0, "check_failures": 0}


def test_hr_h_a_piped_git_config_is_not_waited_on(tmp_path):
    git = tmp_path / "repo" / ".git"
    git.mkdir(parents=True)
    unblock = _fifo(git / "config")
    _reads_without_blocking(
        lambda: harness._snapshot_git_config(tmp_path / "repo"), unblock)


def test_hr_h_a_linked_head_is_not_read(tmp_path):
    git = tmp_path / "repo" / ".git"
    git.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("ref: refs/heads/main\n")
    (git / "HEAD").symlink_to(outside)
    assert harness._git_head_is_valid(tmp_path / "repo") is False


def test_hr_h_a_piped_head_is_not_waited_on(tmp_path):
    git = tmp_path / "repo" / ".git"
    git.mkdir(parents=True)
    unblock = _fifo(git / "HEAD")
    assert _reads_without_blocking(
        lambda: harness._git_head_is_valid(tmp_path / "repo"), unblock) is False


def test_hr_h_the_hidden_test_copy_does_not_write_through_a_hard_link(tmp_path):
    # A hard link has no link to refuse; writing into the existing file
    # would change the file it shares with.
    source = tmp_path / "hidden"
    source.mkdir()
    (source / "test_h.py").write_text("hidden\n")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    dest = tmp_path / "repo"
    dest.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep me\n")
    os.link(victim, dest / "test_h.py")
    harness._copy_tracked_files(source, dest, dict(os.environ))
    assert victim.read_text() == "keep me\n"
    assert (dest / "test_h.py").read_text() == "hidden\n"


def test_hr_h_the_hidden_test_copy_does_not_write_through_a_link(tmp_path):
    source = tmp_path / "hidden"
    source.mkdir()
    (source / "test_h.py").write_text("hidden\n")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    dest = tmp_path / "repo"
    dest.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep me\n")
    (dest / "test_h.py").symlink_to(victim)
    harness._copy_tracked_files(source, dest, dict(os.environ))
    assert victim.read_text() == "keep me\n"
    assert not (dest / "test_h.py").is_symlink()


# --- HR-D: the account that started the harness through sudo ----------------

def test_hr_d_the_account_that_ran_sudo_is_refused():
    # The kill-all ends every process the session user has: as the
    # operator's own account it would end their whole login session.
    reason = _refusal(session_user="evaluser", env={"SUDO_UID": "1500"})
    assert reason and "sudo" in reason
    assert _refusal(session_user="evaluser", env={"SUDO_UID": "1600"}) is None


def test_hr_i_the_kill_all_loads_nothing_the_session_user_controls(monkeypatch):
    # Isolated mode skips the user's site folder and every PYTHON* variable,
    # where a session could plant code that stops the kill-all.
    calls = []
    monkeypatch.setattr(
        harness.subprocess, "run",
        lambda command, **k: calls.append((command, k))
        or subprocess.CompletedProcess(command, 0, "", ""))
    harness._end_session_user_processes(1500, 1500, {"PYTHONPATH": "/x",
                                                     "HOME": "/home/evaluser"})
    command, kwargs = calls[0]
    assert command[1:3] == ["-I", "-S"]
    assert not any(k.startswith("PYTHON") for k in kwargs["env"])
    assert "HOME" not in kwargs["env"]


def test_hr_h_the_hidden_test_copy_sets_its_mode_on_the_file_it_made(
        tmp_path, monkeypatch):
    # A process that swaps the new file for a link while it is written must
    # not get root to change the mode of the file the link names.
    source = tmp_path / "hidden"
    source.mkdir()
    (source / "test_h.py").write_text("hidden\n")
    os.chmod(source / "test_h.py", 0o644)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    dest = tmp_path / "repo"
    dest.mkdir()
    victim = tmp_path / "victim"
    victim.write_text("keep me\n")
    os.chmod(victim, 0o600)
    real_copy = harness.shutil.copyfileobj

    def swap_while_copying(src, out):
        real_copy(src, out)
        (dest / "test_h.py").unlink()
        (dest / "test_h.py").symlink_to(victim)

    monkeypatch.setattr(harness.shutil, "copyfileobj", swap_while_copying)
    harness._copy_tracked_files(source, dest, dict(os.environ))
    assert stat.S_IMODE(victim.stat().st_mode) == 0o600


def test_hr_h_a_config_turned_into_a_folder_is_tampering_not_a_crash(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_bytes(b"[core]\n")
    snapshot = harness._snapshot_git_config(repo)
    (repo / ".git" / "config").unlink()
    (repo / ".git" / "config" / "inner").mkdir(parents=True)
    assert ".git/config" in harness._restore_tampered_git_config(repo, snapshot)


def test_hr_g_session_user_calls_start_without_roots_terminal(tmp_path, monkeypatch):
    monkeypatch.setattr(harness, "_SESSION_FOLDER", (tmp_path, (1500, 1500)))
    as_user = harness._as_session_user(tmp_path)
    assert as_user["start_new_session"] is True
    assert as_user["stdin"] == subprocess.DEVNULL


def test_hr_g_the_launcher_starts_a_session_user_without_roots_terminal(
        monkeypatch, tmp_path):
    seen = {}

    def fake_call(command, **kwargs):
        seen.update(kwargs)
        return host_launch.SessionCall(0, "", "", False)

    monkeypatch.setattr(host_launch, "run_session_user_call", fake_call)
    host_launch.launch_claude("claude", "hi", [], tmp_path, {},
                              user=(1500, 1500))
    assert seen["start_new_session"] is True


def test_hr_i_the_kill_all_starts_without_roots_terminal(monkeypatch):
    calls = []
    monkeypatch.setattr(
        harness.subprocess, "run",
        lambda command, **k: calls.append(k)
        or subprocess.CompletedProcess(command, 0, "", ""))
    harness._end_session_user_processes(1500, 1500, {})
    assert calls[0]["start_new_session"] is True


def _linked_git(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_bytes(b"[core]\n")
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    snapshot = harness._snapshot_git_config(repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "config").symlink_to(tmp_path / "anything")
    (outside / "HEAD").write_text("ref: refs/heads/main\n")
    import shutil
    shutil.rmtree(repo / ".git")
    (repo / ".git").symlink_to(outside)
    return repo, snapshot, outside


def test_hr_h_a_linked_git_folder_is_tampering_and_nothing_outside_changes(tmp_path):
    repo, snapshot, outside = _linked_git(tmp_path)
    tampered = harness._restore_tampered_git_config(repo, snapshot)
    assert ".git/config" in tampered
    assert (outside / "config").is_symlink()


def test_hr_h_a_head_under_a_linked_git_folder_is_not_read(tmp_path):
    repo, _, _ = _linked_git(tmp_path)
    assert harness._git_head_is_valid(repo) is False
