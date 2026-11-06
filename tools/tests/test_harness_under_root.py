"""An eval run under root stays contained, and the report says how it ran.

The harness protected its read-only plugin copy by file mode alone. Root
ignores file mode, so in a root sandbox the first Compass session of each
cell wrote bytecode into the copy, and half the Compass runs were recorded
as not contained (issue #370).

Scenario id: HC-1 (issue `harness-containment-under-root`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import harness  # noqa: E402
from test_eval_harness import (  # noqa: E402,F401
    _run_condition, fake_claude, plugin_source_dir, scenario_dir)


@pytest.mark.parametrize("condition", ["compass", "bare", "R1", "R3"])
def test_hc_1_no_session_writes_bytecode(condition, tmp_path):
    env = harness._build_child_env(condition, tmp_path)
    assert env.get("PYTHONDONTWRITEBYTECODE") == "1"


def test_hc_1_a_compass_run_as_root_is_refused(tmp_path):
    problem = harness._root_refusal("compass", tmp_path, allow_root=False,
                                    euid=0)
    assert problem and "root" in problem and "--allow-root" in problem


def test_hc_1_allow_root_or_another_user_or_condition_runs(tmp_path):
    # An empty environment: a person at a terminal. Under CI or
    # COMPASS_UNATTENDED --allow-root is refused (issue
    # harness-root-sanctioned-path, HR-C).
    assert harness._root_refusal("compass", tmp_path, allow_root=True,
                                 euid=0, env={}) is None
    assert harness._root_refusal("compass", tmp_path, allow_root=False,
                                 euid=501) is None
    assert harness._root_refusal("bare", tmp_path, allow_root=False,
                                 euid=0) is None


def test_hc_1_the_record_names_how_it_ran(tmp_path, scenario_dir, fake_claude,
                                          plugin_source_dir, monkeypatch):
    _, record, _ = _run_condition(tmp_path, scenario_dir, fake_claude, "bare",
                                  monkeypatch, plugin_source_dir)
    assert record["ran_as_root"] is False
    assert isinstance(record["uid"], int)
    assert record["python_version"] == "{}.{}.{}".format(*sys.version_info[:3])
