"""A root eval run on Linux mounts its plugin copy read-only.

Root ignores the file modes that keep a session from editing the plugin
copy, so a root run needs a sanctioned path: each session as an
unprivileged user, or the copy on a read-only mount. Where the platform
allows it, the harness makes the mount itself - a bind mount remounted
read-only - before any session, and removes it at the end. When it cannot,
it falls back to the refusal; it never runs unprotected without saying so.

These tests drive the mount through a recorded runner, so nothing is
mounted here; `tests/test_harness_root_real.py` mounts for real as root.

Scenario id: RM-1 (issue `harness-read-only-bind-mount`).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402


def _runner(fail_on=()):
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        code = 32 if any(word in command for word in fail_on) else 0
        return subprocess.CompletedProcess(command, code, "", "denied" if code else "")
    return run, calls


def test_rm_1_root_on_linux_bind_mounts_then_remounts_read_only(tmp_path):
    run, calls = _runner()
    assert harness._mount_read_only(tmp_path, euid=0, platform="linux", run=run)
    assert calls == [["mount", "--bind", str(tmp_path), str(tmp_path)],
                     ["mount", "-o", "remount,bind,ro", str(tmp_path), str(tmp_path)]]


def test_rm_1_not_root_or_not_linux_mounts_nothing(tmp_path):
    for euid, platform in ((1000, "linux"), (0, "darwin")):
        run, calls = _runner()
        assert not harness._mount_read_only(tmp_path, euid=euid, platform=platform, run=run)
        assert calls == []


def test_rm_1_a_failed_remount_undoes_the_bind_and_reports_no_mount(tmp_path):
    run, calls = _runner(fail_on=("remount,bind,ro",))
    assert not harness._mount_read_only(tmp_path, euid=0, platform="linux", run=run)
    assert calls[-1] == ["umount", str(tmp_path)]


def test_rm_1_a_failed_bind_tries_nothing_more(tmp_path):
    run, calls = _runner(fail_on=("--bind",))
    assert not harness._mount_read_only(tmp_path, euid=0, platform="linux", run=run)
    assert len(calls) == 1


def test_rm_1_the_mount_is_removed_before_the_copy_is_deleted(tmp_path):
    copy = tmp_path / "copy"
    copy.mkdir()
    (copy / "f").write_text("x")
    run, calls = _runner()
    harness._release_plugin_copy(copy, mounted=True, run=run)
    assert calls == [["umount", str(copy)]]
    assert not copy.exists()


# --- review 1: a mount that will not come off ------------------------------------

def test_rm_1_a_busy_mount_is_detached_lazily(tmp_path):
    copy = tmp_path / "copy"
    copy.mkdir()
    run, calls = _runner(fail_on=())
    busy = []

    def runner(command, **kwargs):
        if command == ["umount", str(copy)]:
            busy.append(command)
            return subprocess.CompletedProcess(command, 32, "", "target is busy")
        return run(command, **kwargs)
    harness._release_plugin_copy(copy, mounted=True, run=runner)
    assert calls == [["umount", "-l", str(copy)]]
    assert not copy.exists()


def test_rm_1_a_mount_that_cannot_be_removed_keeps_the_copy_and_says_so(tmp_path, capsys):
    copy = tmp_path / "copy"
    copy.mkdir()
    run, calls = _runner(fail_on=("umount",))
    harness._release_plugin_copy(copy, mounted=True, run=run)
    assert copy.exists(), "a copy still mounted read-only cannot be deleted"
    said = capsys.readouterr().err
    assert str(copy) in said and "umount" in said, said


def test_rm_1_an_interrupt_after_the_bind_undoes_it(tmp_path):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        if "remount,bind,ro" in command:
            raise KeyboardInterrupt
        return subprocess.CompletedProcess(command, 0, "", "")
    try:
        harness._mount_read_only(tmp_path, euid=0, platform="linux", run=runner)
    except KeyboardInterrupt:
        pass
    assert calls[-1] == ["umount", str(tmp_path)]
