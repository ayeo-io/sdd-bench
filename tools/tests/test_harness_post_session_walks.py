"""What a session leaves in its folder cannot stop a run without a record.

After a session, the harness copies the hidden tests in and lists the
session's `.compass` files. A session that planted a folder where a hidden
test goes, or replaced `.compass` with a link to `/`, used to end the run
with an exception and no record. The run now finishes: the planted folder is
recorded as not contained, by path, and a linked `.compass` lists nothing.

Scenario ids: PSW-1 and PSW-2 (issue `harness-post-session-walks`).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
from test_eval_harness import (  # noqa: E402,F401
    _run_condition, _write_scenario_with_hidden_tests, fake_claude,
    plugin_source_dir, scenario_dir)

HIDDEN = "tests/test_hidden_feature.py"


def test_psw_1_a_folder_at_a_hidden_test_path_is_recorded_not_a_crash(
        tmp_path, fake_claude, plugin_source_dir, monkeypatch):
    scenario = _write_scenario_with_hidden_tests(tmp_path)
    _, record, _ = _run_condition(
        tmp_path, scenario, fake_claude, "bare", monkeypatch,
        plugin_source_dir, extra_config={"dir_at_hidden_test": HIDDEN})
    assert record["contained"] is False
    assert f"hidden-test:{HIDDEN}" in record["escaped_paths"]


def test_psw_1_the_copy_returns_what_it_refused(tmp_path):
    source = tmp_path / "hidden"
    (source / "tests").mkdir(parents=True)
    (source / "tests" / "test_h.py").write_text("hidden\n")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    dest = tmp_path / "repo"
    (dest / "tests" / "test_h.py" / "inner").mkdir(parents=True)
    refused = harness._copy_tracked_files(source, dest, {"PATH": "/usr/bin:/bin"})
    assert refused == ["tests/test_h.py"]


def test_psw_2_a_linked_compass_folder_lists_nothing_outside(
        tmp_path, scenario_dir, fake_claude, plugin_source_dir, monkeypatch):
    outside = tmp_path / "outside"
    (outside / "work").mkdir(parents=True)
    (outside / "work" / "secret.txt").write_text("outside the folder\n")
    _, record, _ = _run_condition(
        tmp_path, scenario_dir, fake_claude, "compass", monkeypatch,
        plugin_source_dir, extra_config={"link_compass_to": str(outside)})
    assert not any("secret" in path for path in record["compass_files"])


def test_psw_2_a_linked_compass_folder_is_not_walked(tmp_path):
    # A folder the harness may list but not enter: checking a file inside
    # it fails, so walking through the link at all ends the run.
    outside = tmp_path / "outside"
    (outside / "locked").mkdir(parents=True)
    (outside / "locked" / "f.txt").write_text("x\n")
    (outside / "locked").chmod(0o444)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".compass").symlink_to(outside)
    try:
        assert harness._compass_files(repo) == []
    finally:
        (outside / "locked").chmod(0o755)


def test_psw_2_a_link_inside_compass_is_not_followed(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".compass" / "work").mkdir(parents=True)
    (repo / ".compass" / "work" / "kept.txt").write_text("in the folder\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("outside\n")
    (repo / ".compass" / "elsewhere").symlink_to(outside)
    assert harness._compass_files(repo) == [".compass/work/kept.txt"]
