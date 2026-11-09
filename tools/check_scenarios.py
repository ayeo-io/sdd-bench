"""Check every scenario before it is run against a framework.

For each scenario under scenarios/:
1. its seed/ matches seeds/<seed>/ exactly (the seed is shared);
2. the seed's own tests pass;
3. the hidden tests fail on the untouched seed (so they measure something);
4. the hidden tests and the seed's tests pass on the seed with the
   reference solution under reference/<scenario>/ laid over it;
5. the prompt's last line links the request that scenario.yml's `request:`
   block names, in the form `Request: <issue URL> (from <requester>)`, and
   the repository is not this benchmark's own.

Usage: python3 tools/check_scenarios.py [--sync] [SCENARIO ...]
--sync copies seeds/<seed>/ into each scenario's seed/ first. Naming
scenarios checks only those; with none named, every scenario is checked.
"""

from __future__ import annotations

import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SEED_OF = {"shop-idempotency": "shop", "shop-tracing": "shop", "shop-forget-user": "shop",
           "shop-change-email": "shop"}
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache")


def same_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".pytest_cache"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(same_tree(a / d, b / d) for d in cmp.common_dirs)


def request_line(scenario: dict) -> str | None:
    """The link line the prompt must end with, or None when `request:` is
    missing or names this benchmark's repository."""
    request = scenario.get("request")
    if not isinstance(request, dict):
        return None
    repo, number, who = request.get("repo"), request.get("number"), request.get("requester")
    if not (isinstance(repo, str) and "/" in repo and isinstance(number, int) and who):
        return None
    if "sdd-bench" in repo.lower():
        return None
    return f"Request: https://github.com/{repo}/issues/{number} (from {who})"


def links_request(sdir: Path) -> bool:
    """The prompt's last non-blank line is the request's link line."""
    scenario = yaml.safe_load((sdir / "scenario.yml").read_text(encoding="utf-8"))
    lines = [line.strip() for line in str(scenario.get("prompt", "")).splitlines()
             if line.strip()]
    wanted = request_line(scenario)
    return wanted is not None and bool(lines) and lines[-1] == wanted


def pytest(cwd: Path, *args: str) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=cwd, capture_output=True, text=True).returncode


def main() -> int:
    sync = "--sync" in sys.argv
    named = [a for a in sys.argv[1:] if not a.startswith("--")]
    unknown = [n for n in named if n not in SEED_OF]
    if unknown:
        print(f"unknown scenario: {', '.join(unknown)}")
        return 1
    ok = True
    for name, seed in SEED_OF.items():
        if named and name not in named:
            continue
        sdir = ROOT / "scenarios" / name
        src = ROOT / "seeds" / seed
        if sync:
            shutil.rmtree(sdir / "seed", ignore_errors=True)
            shutil.copytree(src, sdir / "seed", ignore=IGNORE)
        checks = {"seed matches": same_tree(src, sdir / "seed"),
                  "prompt links the request": links_request(sdir)}
        hidden = next((sdir / "hidden_tests" / "tests").glob("test_*.py")).name
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "w"
            shutil.copytree(sdir / "seed", work, ignore=IGNORE)
            checks["seed tests pass"] = pytest(work) == 0
            shutil.copytree(sdir / "hidden_tests", work, dirs_exist_ok=True)
            checks["hidden fail on seed"] = pytest(work, f"tests/{hidden}") != 0
            shutil.copytree(ROOT / "reference" / name, work, dirs_exist_ok=True)
            checks["hidden pass with reference"] = pytest(work, f"tests/{hidden}") == 0
            checks["seed tests pass with reference"] = pytest(work, "--ignore", f"tests/{hidden}") == 0
        for k, v in checks.items():
            print(f"{name}: {k}: {'ok' if v else 'FAIL'}")
            ok = ok and v
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
