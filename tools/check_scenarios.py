"""Check every scenario before it is run against a framework.

For each scenario under scenarios/:
1. its seed/ matches seeds/<seed>/ exactly (the seed is shared);
2. the seed's own tests pass;
3. the hidden tests fail on the untouched seed (so they measure something);
4. the hidden tests and the seed's tests pass on the seed with the
   reference solution under reference/<scenario>/ laid over it.

Usage: python3 tools/check_scenarios.py [--sync]
--sync copies seeds/<seed>/ into each scenario's seed/ first.
"""

from __future__ import annotations

import filecmp
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_OF = {"shop-idempotency": "shop", "shop-tracing": "shop", "shop-forget-user": "shop"}
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache")


def same_tree(a: Path, b: Path) -> bool:
    cmp = filecmp.dircmp(a, b, ignore=["__pycache__", ".pytest_cache"])
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return False
    return all(same_tree(a / d, b / d) for d in cmp.common_dirs)


def pytest(cwd: Path, *args: str) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          cwd=cwd, capture_output=True, text=True).returncode


def main() -> int:
    sync = "--sync" in sys.argv
    ok = True
    for name, seed in SEED_OF.items():
        sdir = ROOT / "scenarios" / name
        src = ROOT / "seeds" / seed
        if sync:
            shutil.rmtree(sdir / "seed", ignore_errors=True)
            shutil.copytree(src, sdir / "seed", ignore=IGNORE)
        checks = {"seed matches": same_tree(src, sdir / "seed")}
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
