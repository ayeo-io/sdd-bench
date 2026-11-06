"""A root run with a real session user stays contained against a hostile session.

The first implementation of `--session-user` passed its tests and failed an
independent review: root's git refused the folder handed to the session
user, the test command ran the session's code as root, and root followed
links the session planted. Its tests played root with the test user's own
uid, so they could not fail on ownership or privilege.

These tests run only as root, with `COMPASS_ROOT_TEST_USER` naming a real
unprivileged user dedicated to them. The `harness-root` CI job creates that
user and runs this file under sudo; locally, run it in a container.

Scenario ids: HR-G to HR-J (issue `harness-root-sanctioned-path`).
"""
from __future__ import annotations

import json
import os
import pwd
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
from test_eval_harness import (  # noqa: E402
    _configure_fake_claude, _write_fake_claude, _write_plugin_repo,
    _write_scenario, _write_scenario_with_hidden_tests)

USER = os.environ.get("COMPASS_ROOT_TEST_USER", "")
pytestmark = pytest.mark.skipif(
    os.geteuid() != 0 or not USER,
    reason="runs only as root with COMPASS_ROOT_TEST_USER naming a dedicated "
           "unprivileged user (the harness-root CI job)")


@pytest.fixture
def world(tmp_path):
    """Folders the session user can reach (the fake claude, its config and
    its log), and a folder only root can reach (the markers a hostile
    session must not be able to touch)."""
    shared = Path(tempfile.mkdtemp(prefix="hr-shared-"))
    os.chmod(shared, 0o755)
    private = Path(tempfile.mkdtemp(prefix="hr-private-"))
    os.chmod(private, 0o700)
    log_dir = shared / "log"
    log_dir.mkdir()
    os.chmod(log_dir, 0o777)
    claude = _write_fake_claude(shared)
    os.chmod(claude, 0o755)
    scenario = _write_scenario(shared)
    hidden_scenario = _write_scenario_with_hidden_tests(shared)
    plugin = _write_plugin_repo(shared / "plugin-source")
    for path in [shared, *shared.rglob("*")]:
        mode = path.stat().st_mode
        os.chmod(path, mode | 0o055 if path.is_dir() else mode | 0o044)
    yield {"shared": shared, "private": private, "claude": claude,
           "scenario": scenario, "hidden_scenario": hidden_scenario,
           "plugin": plugin, "log": log_dir / "log.jsonl"}
    subprocess.run(["rm", "-rf", str(shared), str(private)], check=False)


def _with_a_terminal():
    """`subprocess` arguments that start the harness in its own session with
    a pseudo-terminal as its controlling terminal, as when root runs it from
    a shell."""
    import fcntl
    import termios
    _master, slave = os.openpty()

    def take_terminal():
        fcntl.ioctl(0, termios.TIOCSCTTY, 0)
    return {"stdin": slave, "start_new_session": True,
            "preexec_fn": take_terminal}


def _harness(world, extra=None, scenario="scenario", terminal=False):
    _configure_fake_claude(world["claude"], world["log"], extra)
    os.chmod(world["claude"].parent / "fake_claude_config.json", 0o644)
    out = world["shared"] / "out"
    env = {k: v for k, v in os.environ.items()
           if k not in ("CI", "COMPASS_UNATTENDED")}
    return subprocess.run(
        [sys.executable, str(ROOT / "harness.py"),
         "--scenario", str(world[scenario]), "--condition", "compass",
         "--claude", str(world["claude"]), "--out", str(out),
         "--plugin-source", str(world["plugin"]), "--session-user", USER],
        env=env, capture_output=True, text=True, timeout=600,
        **(_with_a_terminal() if terminal else {})), out


def _run(world, extra=None, scenario="scenario", terminal=False):
    _configure_fake_claude(world["claude"], world["log"], extra)
    os.chmod(world["claude"].parent / "fake_claude_config.json", 0o644)
    out = world["shared"] / "out"
    env = {k: v for k, v in os.environ.items()
           if k not in ("CI", "COMPASS_UNATTENDED")}
    code = subprocess.run(
        [sys.executable, str(ROOT / "harness.py"),
         "--scenario", str(world[scenario]), "--condition", "compass",
         "--claude", str(world["claude"]), "--out", str(out),
         "--plugin-source", str(world["plugin"]), "--session-user", USER],
        env=env, capture_output=True, text=True, timeout=600,
        **(_with_a_terminal() if terminal else {}))
    assert code.returncode == 0, code.stdout + code.stderr
    return json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))


def test_hr_j_a_real_root_run_is_contained_with_the_edit_in_the_diff(world):
    record = _run(world)
    assert record["session_uid"] == pwd.getpwnam(USER).pw_uid
    assert record["contained"] is True, record.get("escaped_paths")
    assert "seed.txt" in record["changed_paths"]


def test_hr_g_code_the_session_wrote_does_not_run_as_root(world):
    marker = world["private"] / "ran-as-root"
    _run(world, {"plant_test_marker": str(marker)})
    assert not marker.exists(), "the session's test code ran as root"


def test_hr_h_root_does_not_write_through_a_planted_config_link(world):
    victim = world["private"] / "victim.txt"
    victim.write_text("root's own file\n")
    _run(world, {"link_git_config_to": str(victim)})
    assert victim.read_text() == "root's own file\n"


def test_hr_h_root_does_not_read_through_a_planted_manifest_link(world):
    secret = world["private"] / "secret.txt"
    secret.write_text("issue: SECRET-CONTENT\n")
    record = _run(world, {"link_manifest_to": str(secret)})
    assert "SECRET-CONTENT" not in json.dumps(record)


def test_hr_i_a_process_left_running_is_ended(world):
    marker = world["shared"] / "late.txt"
    os.chmod(world["shared"], 0o777)
    _run(world, {"linger_marker": str(marker)})
    time.sleep(4)
    assert not marker.exists(), "a process the session left ran on"


def test_hr_h_root_does_not_write_through_a_planted_hidden_test_link(world):
    victim = world["private"] / "victim.txt"
    victim.write_text("root's own file\n")
    _run(world, {"link_hidden_test_to": str(victim)},
         scenario="hidden_scenario")
    assert victim.read_text() == "root's own file\n"


def test_hr_i_a_process_the_test_command_left_is_ended(world):
    # The session's own test code runs as the session user after the
    # session call; what it leaves running must not outlive it either.
    marker = world["shared"] / "late-test.txt"
    os.chmod(world["shared"], 0o777)
    _run(world, {"plant_test_linger_marker": str(marker)})
    time.sleep(4)
    assert not marker.exists(), "a process the test command left ran on"


def test_hr_i_the_session_cannot_stop_the_kill_all(world):
    # The kill-all is an interpreter started as the session user, so it
    # must not load anything from that user's home.
    marker = world["shared"] / "late-defeat.txt"
    os.chmod(world["shared"], 0o777)
    home = Path(pwd.getpwnam(USER).pw_dir)
    try:
        _run(world, {"defeat_kill_all": True, "linger_marker": str(marker)})
        time.sleep(4)
    finally:
        subprocess.run(["rm", "-rf", str(home / ".local")], check=False)
    assert not marker.exists(), "the session stopped the kill-all"


def test_hr_h_root_does_not_follow_a_linked_git_folder(world):
    # With `.git` itself a link, every path under it is outside the folder.
    target = world["private"] / "gitdir"
    target.mkdir()
    (target / "config").symlink_to("/etc/hostname")
    _run(world, {"link_git_dir_to": str(target)})
    assert (target / "config").is_symlink(), "root deleted a file outside"


def test_hr_g_session_user_processes_cannot_reach_roots_terminal(world):
    # A process with root's controlling terminal can push a line into it,
    # which root's shell runs after the harness exits.
    session_marker = world["shared"] / "tty-session.txt"
    test_marker = world["shared"] / "tty-test.txt"
    os.chmod(world["shared"], 0o777)
    _run(world, {"tty_marker": str(session_marker),
                 "plant_test_tty_marker": str(test_marker)}, terminal=True)
    assert session_marker.read_text() == "none"
    assert test_marker.read_text() == "none"


# --- the session user stays dedicated, unhung and untouched -----------------
# Scenario ids SUH-1 to SUH-5 (issue `harness-session-user-hardening`).

def _outside_projects(tree: dict[str, str]) -> dict[str, str]:
    """The home tree less what a session itself creates: `.claude` and its
    project folders."""
    return {path: value for path, value in tree.items()
            if path not in (".claude", ".claude/projects")
            and not path.startswith(".claude/projects/")}


def _home_tree(home: Path) -> dict[str, str]:
    import hashlib
    tree = {}
    for base, dirs, files in os.walk(home):
        for name in dirs + files:
            path = Path(base) / name
            rel = path.relative_to(home).as_posix()
            if path.is_symlink():
                tree[rel] = "link:" + os.readlink(path)
            elif path.is_file():
                tree[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            else:
                tree[rel] = "dir"
    return tree


def test_suh_1_a_process_holding_the_output_is_ended_not_waited_on(world):
    start = time.monotonic()
    record = _run(world, {"linger_holding_output": True})
    assert time.monotonic() - start < 100, "the harness waited on the survivor"
    assert record["contained"] is False
    assert "session-process:held-output:session" in record["escaped_paths"]


def test_suh_2_a_busy_account_is_refused_before_any_session(world):
    entry = pwd.getpwnam(USER)
    busy = subprocess.Popen(["sleep", "60"], user=entry.pw_uid,
                            group=entry.pw_gid, extra_groups=[])
    try:
        result, out = _harness(world)
    finally:
        busy.kill()
        busy.wait()
    assert result.returncode != 0
    assert "not ready" in (result.stdout + result.stderr)
    assert "running process" in (result.stdout + result.stderr)
    assert not list(out.glob("*.json")), "a session ran on a busy account"


def test_suh_4_a_run_that_writes_the_users_claude_md_is_flagged(world):
    home = Path(pwd.getpwnam(USER).pw_dir)
    try:
        record = _run(world, {"write_home_claude_md": "always do X\n"})
    finally:
        subprocess.run(["rm", "-rf", str(home / ".claude" / "CLAUDE.md")],
                       check=False)
    assert ".claude/CLAUDE.md" in record["session_config_changed"]


def test_suh_5_the_harness_changes_nothing_in_the_users_home(world):
    home = Path(pwd.getpwnam(USER).pw_dir)
    before = _home_tree(home)
    # As a real `claude` does, the session creates a project folder for its
    # cwd; an empty one steers nothing and must not count as a change.
    record = _run(world, {"create_project_folder": True})
    assert record["session_config_changed"] == []
    # Only the session's own project folder may be new; the harness adds,
    # removes and changes nothing.
    assert _outside_projects(_home_tree(home)) == _outside_projects(before)


# --- The follow-ups to the --session-user hardening: SF-1 (issue
# `session-user-follow-ups`)

def test_sf_1_a_run_that_makes_the_users_claude_folder_unreadable_is_flagged(world):
    home = Path(pwd.getpwnam(USER).pw_dir)
    claude = home / ".claude"
    existed = claude.exists()
    mode = claude.stat().st_mode & 0o777 if existed else None
    try:
        record = _run(world, {"chmod_home_claude": 0})
    finally:
        if existed:
            os.chmod(claude, mode)
        else:
            subprocess.run(["rm", "-rf", str(claude)], check=False)
    assert ".claude" in record["session_config_changed"], record["session_config_changed"]


def test_sf_1_a_link_planted_during_a_run_stops_the_next_run(world):
    # Two runs in one harness call. The first run's session plants a link in
    # its own Claude configuration; the account check, now run before every
    # run, must refuse run 2.
    home = Path(pwd.getpwnam(USER).pw_dir)
    link = home / ".claude" / "settings.local.json"
    _configure_fake_claude(world["claude"], world["log"],
                           {"link_home_settings": "/etc/hostname"})
    os.chmod(world["claude"].parent / "fake_claude_config.json", 0o644)
    out = world["shared"] / "out"
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "COMPASS_UNATTENDED")}
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "harness.py"),
             "--scenario", str(world["scenario"]), "--condition", "compass",
             "--claude", str(world["claude"]), "--out", str(out),
             "--plugin-source", str(world["plugin"]), "--session-user", USER,
             "--runs", "2"],
            env=env, capture_output=True, text=True, timeout=600)
    finally:
        if link.is_symlink():
            link.unlink()
    said = result.stdout + result.stderr
    assert result.returncode != 0, said
    assert "refusing run 2" in said and "link" in said, said
    assert len(list(out.glob("*.json"))) == 1


# --- A bare root run mounts its plugin copy read-only (RM-1, issue
# `harness-read-only-bind-mount`)

def test_rm_1_a_root_run_without_a_session_user_mounts_its_copy_read_only(world):
    _configure_fake_claude(world["claude"], world["log"], None)
    os.chmod(world["claude"].parent / "fake_claude_config.json", 0o644)
    out = world["shared"] / "out"
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "COMPASS_UNATTENDED")}
    def tmp_mounts():
        return [line for line in Path("/proc/mounts").read_text().splitlines()
                if " /tmp" in line]
    before = tmp_mounts()
    result = subprocess.run(
        [sys.executable, str(ROOT / "harness.py"),
         "--scenario", str(world["scenario"]), "--condition", "compass",
         "--claude", str(world["claude"]), "--out", str(out),
         "--plugin-source", str(world["plugin"])],
        env=env, capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))
    assert record["plugin_copy_mount"] == "read-only bind"
    assert record["contained"] is True, record.get("escaped_paths")
    assert tmp_mounts() == before, "the mount was left behind"
