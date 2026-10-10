"""Score a finished tree against its scenario's target state (target.md).

A tree is a copy of the seed after a session (or a person) has made the
change. The score has seven parts, and the tree is at target only when all
seven pass:

1. behaviour     every criterion's hidden tests pass (tests are named
                 test_<criterion id>_...);
2. regression    the seed's own tests, as the seed shipped them, still pass;
3. own tests     the tree's own test suite passes;
4. static        `ruff check` (the seed's ruff.toml) and `mypy --strict shop`
                 report nothing on the lines the change added;
5. coverage      the tree's own tests run at least COVERAGE_BAR of the
                 executable lines the change added in shop/;
6. mutation      the tree's own tests fail for at least MUTATION_BAR of small
                 deliberate bugs planted in the lines the change added;
7. conventions   services do not import each other, handlers do not swallow
                 errors, and no personal data reaches the log, the audit
                 trail or an event.

Usage:
  python3 tools/score.py --scenario shop-tracing --tree DIR [--seed DIR] [--json OUT]
  python3 tools/score.py --scenario shop-tracing --record HARNESS.json --seed DIR

--seed is the seed the change was made against (default: the scenario's
seed/). --record rebuilds the tree by applying the record's diff to it.
"""

from __future__ import annotations

import argparse
import ast
import copy
import difflib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COVERAGE_BAR = 0.90
MUTATION_BAR = 0.80
MAX_MUTANTS = 60
SERVICES = ("users", "orders", "subscriptions")
IGNORE = shutil.ignore_patterns("__pycache__", ".pytest_cache", ".git")


def run(cmd: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", "timeout")


def pytest_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", *args]


# ---------------------------------------------------------------- the change

def added_lines(seed: Path, tree: Path) -> dict[str, set[int]]:
    """Line numbers, per file under shop/, that the change added or rewrote."""
    out: dict[str, set[int]] = {}
    for path in sorted((tree / "shop").rglob("*.py")):
        rel = str(path.relative_to(tree))
        new = path.read_text().splitlines()
        old_path = seed / rel
        old = old_path.read_text().splitlines() if old_path.exists() else []
        lines: set[int] = set()
        sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
        for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
            if tag in ("replace", "insert"):
                lines.update(range(j1 + 1, j2 + 1))
        if lines:
            out[rel] = lines
    return out


def own_test_files(tree: Path) -> list[str]:
    return sorted(str(p.relative_to(tree)) for p in (tree / "tests").rglob("test_*.py")
                  if not p.name.startswith("test_hidden_"))


# ---------------------------------------------------------------- the parts

def behaviour(tree: Path, scenario: Path) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp())
    shutil.copytree(tree, work / "t", ignore=IGNORE)
    shutil.copytree(scenario / "hidden_tests", work / "t", dirs_exist_ok=True)
    hidden = next((scenario / "hidden_tests" / "tests").glob("test_*.py")).name
    xml = work / "r.xml"
    run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"tests/{hidden}", f"--junitxml={xml}"], work / "t")
    results: dict[str, bool] = {}
    if xml.exists():
        for case in ET.parse(xml).iter("testcase"):
            m = re.match(r"test_([a-z]\d+)_", case.get("name", ""))
            if not m:
                continue
            ok = not any(child.tag in ("failure", "error") for child in case)
            crit = m.group(1).upper()
            results[crit] = results.get(crit, True) and ok
    shutil.rmtree(work, ignore_errors=True)
    criteria = sorted(set(re.findall(r"def test_([a-z]\d+)_",
                                     (scenario / "hidden_tests" / "tests" / hidden).read_text())))
    per = {c.upper(): results.get(c.upper(), False) for c in criteria}
    return {"pass": all(per.values()), "criteria": per,
            "met": sum(per.values()), "of": len(per)}


def regression(tree: Path, seed: Path) -> dict[str, Any]:
    work = Path(tempfile.mkdtemp())
    shutil.copytree(tree, work / "t", ignore=IGNORE)
    reg = work / "t" / "bench_regression"
    shutil.copytree(seed / "tests", reg, ignore=IGNORE)
    r = run(pytest_cmd("bench_regression"), work / "t")
    shutil.rmtree(work, ignore_errors=True)
    return {"pass": r.returncode == 0}


def own_tests(tree: Path) -> dict[str, Any]:
    files = own_test_files(tree)
    r = run(pytest_cmd(*files), tree) if files else None
    return {"pass": bool(r and r.returncode == 0), "files": files}


def static(tree: Path, seed: Path, changed: dict[str, set[int]]) -> dict[str, Any]:
    config = seed / "ruff.toml"
    ruff = run(["ruff", "check", "--output-format", "json", "--no-cache",
                *(["--config", str(config)] if config.exists() else []), "shop"], tree)
    findings = []
    for f in json.loads(ruff.stdout or "[]"):
        rel = str(Path(f["filename"]).resolve().relative_to(tree.resolve()))
        if f["location"]["row"] in changed.get(rel, set()):
            findings.append(f"ruff {f['code']} {rel}:{f['location']['row']}")
    mypy = run([sys.executable, "-m", "mypy", "--strict", "--no-incremental",
                "--cache-dir", "/dev/null", "shop"], tree)
    for line in mypy.stdout.splitlines():
        m = re.match(r"(shop/\S+\.py):(\d+): error: (.*)", line)
        if m and int(m.group(2)) in changed.get(m.group(1), set()):
            findings.append(f"mypy {m.group(1)}:{m.group(2)} {m.group(3)[:80]}")
    return {"pass": not findings, "findings": findings}


def coverage(tree: Path, changed: dict[str, set[int]]) -> dict[str, Any]:
    files = own_test_files(tree)
    if not changed:
        return {"pass": False, "ratio": 0.0, "note": "no change in shop/"}
    work = Path(tempfile.mkdtemp())
    shutil.copytree(tree, work / "t", ignore=IGNORE)
    run([sys.executable, "-m", "coverage", "run", "--branch", "--source=shop",
         "-m", "pytest", "-q", "-p", "no:cacheprovider", *files], work / "t")
    run([sys.executable, "-m", "coverage", "json", "-o", "cov.json"], work / "t")
    data = json.loads((work / "t" / "cov.json").read_text()) if (work / "t" / "cov.json").exists() else {}
    shutil.rmtree(work, ignore_errors=True)
    hit = total = 0
    missed: list[str] = []
    for rel, lines in changed.items():
        info = data.get("files", {}).get(rel)
        if not info:
            continue
        executable = set(info["executed_lines"]) | set(info["missing_lines"])
        for n in sorted(lines & executable):
            total += 1
            if n in info["executed_lines"]:
                hit += 1
            else:
                missed.append(f"{rel}:{n}")
    ratio = hit / total if total else 1.0
    return {"pass": ratio >= COVERAGE_BAR, "ratio": round(ratio, 3),
            "lines": total, "missed": missed[:20]}


# ---------------------------------------------------------------- mutation

_SWAP = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq, ast.Lt: ast.GtE, ast.GtE: ast.Lt,
         ast.Gt: ast.LtE, ast.LtE: ast.Gt, ast.In: ast.NotIn, ast.NotIn: ast.In,
         ast.Is: ast.IsNot, ast.IsNot: ast.Is}


def _mutants(source: str, lines: set[int]) -> list[tuple[str, str]]:
    """(description, mutated source) for small bugs on the given lines."""
    tree = ast.parse(source)
    targets: list[tuple[str, Any]] = []
    docstrings = {id(n.body[0]) for n in ast.walk(tree)
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module))
                  and n.body and isinstance(n.body[0], ast.Expr)
                  and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
    for node in ast.walk(tree):
        line = getattr(node, "lineno", None)
        if line not in lines:
            continue
        if isinstance(node, ast.Compare) and type(node.ops[0]) in _SWAP:
            targets.append(("flip comparison", node))
        elif isinstance(node, ast.BoolOp):
            targets.append(("swap and/or", node))
        elif isinstance(node, (ast.If, ast.While)):
            targets.append(("negate condition", node))
        elif isinstance(node, ast.Return) and node.value is not None:
            targets.append(("return None", node))
        elif isinstance(node, (ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Raise)) \
                and id(node) not in docstrings:
            targets.append(("delete statement", node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, bool):
            targets.append(("flip boolean", node))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            targets.append(("change number", node))
    out = []
    for i, (kind, _node) in enumerate(targets):
        mutated = copy.deepcopy(tree)
        node = [n for n in ast.walk(mutated)][[n for n in ast.walk(tree)].index(targets[i][1])]
        if kind == "flip comparison":
            node.ops[0] = _SWAP[type(node.ops[0])]()
        elif kind == "swap and/or":
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        elif kind == "negate condition":
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        elif kind == "return None":
            node.value = ast.Constant(value=None)
        elif kind == "delete statement":
            for parent in ast.walk(mutated):
                for field in ("body", "orelse", "finalbody", "handlers"):
                    seq = getattr(parent, field, None)
                    if isinstance(seq, list) and node in seq:
                        seq[seq.index(node)] = ast.Pass()
        elif kind == "flip boolean":
            node.value = not node.value
        elif kind == "change number":
            node.value = node.value + 1
        ast.fix_missing_locations(mutated)
        out.append((f"{kind} at line {getattr(targets[i][1], 'lineno', '?')}", ast.unparse(mutated)))
    return out


def mutation(tree: Path, changed: dict[str, set[int]]) -> dict[str, Any]:
    files = own_test_files(tree)
    plans = []
    for rel, lines in sorted(changed.items()):
        src = (tree / rel).read_text()
        try:
            plans += [(rel, d, s) for d, s in _mutants(src, lines)]
        except SyntaxError:
            continue
    if not plans:
        return {"pass": False, "score": 0.0, "mutants": 0, "note": "nothing to mutate"}
    if len(plans) > MAX_MUTANTS:
        step = len(plans) / MAX_MUTANTS
        plans = [plans[int(i * step)] for i in range(MAX_MUTANTS)]

    def one(plan: tuple[str, str, str]) -> tuple[str, bool]:
        rel, desc, src = plan
        work = Path(tempfile.mkdtemp())
        shutil.copytree(tree, work / "t", ignore=IGNORE)
        (work / "t" / rel).write_text(src)
        r = run(pytest_cmd(*files), work / "t", timeout=60)
        shutil.rmtree(work, ignore_errors=True)
        return f"{rel}: {desc}", r.returncode != 0

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, plans))
    killed = sum(k for _, k in results)
    score = killed / len(results)
    return {"pass": score >= MUTATION_BAR, "score": round(score, 3), "mutants": len(results),
            "survived": [d for d, k in results if not k][:20]}


# ---------------------------------------------------------------- conventions

CONVENTION_TEST = '''
from shop import audit, log
from shop.app import build


def test_no_personal_data_leaves_the_user_service():
    s = build()
    uid = s.users.create_user("Grace Hopper", "grace@example.org")
    s.bus.run_pending()
    s.orders.create_order(uid, 100)
    s.subscriptions.subscribe(uid, "offers")
    s.bus.run_pending()
    if hasattr(s.users, "delete_user"):
        s.users.delete_user(uid)
        s.bus.run_pending()
    text = str(log.RECORDS) + str(audit.ENTRIES) + str(s.bus.published)
    assert "Grace" not in text and "grace@example.org" not in text
'''


def conventions(tree: Path) -> dict[str, Any]:
    problems = []
    for svc in SERVICES:
        path = tree / "shop" / f"{svc}.py"
        if not path.exists():
            continue
        mod = ast.parse(path.read_text())
        imported = {n.module for n in ast.walk(mod) if isinstance(n, ast.ImportFrom)}
        imported |= {a.name for n in ast.walk(mod) if isinstance(n, ast.Import) for a in n.names}
        for other in SERVICES:
            if other != svc and f"shop.{other}" in imported:
                problems.append(f"shop/{svc}.py imports shop.{other}")
    for path in sorted((tree / "shop").rglob("*.py")):
        if path.name == "bus.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ExceptHandler):
                broad = node.type is None or (isinstance(node.type, ast.Name)
                                              and node.type.id in ("Exception", "BaseException"))
                reraises = any(isinstance(n, ast.Raise) for n in ast.walk(node))
                if broad and not reraises:
                    problems.append(f"{path.relative_to(tree)}:{node.lineno} swallows every error")
    work = Path(tempfile.mkdtemp())
    shutil.copytree(tree, work / "t", ignore=IGNORE)
    (work / "t" / "bench_conventions").mkdir()
    (work / "t" / "bench_conventions" / "test_conventions.py").write_text(CONVENTION_TEST)
    r = run(pytest_cmd("bench_conventions"), work / "t")
    shutil.rmtree(work, ignore_errors=True)
    if r.returncode != 0:
        problems.append("personal data reached the log, the audit trail or an event")
    return {"pass": not problems, "problems": problems}


# ---------------------------------------------------------------- main

def tree_from_record(record: Path, seed: Path) -> Path:
    data = json.loads(record.read_text())
    work = Path(tempfile.mkdtemp()) / "t"
    shutil.copytree(seed, work, ignore=IGNORE)
    run(["git", "init", "-q"], work)
    patch = work.parent / "change.diff"
    patch.write_text(data.get("diff") or "")
    r = run(["git", "apply", "--whitespace=nowarn", str(patch)], work)
    if r.returncode != 0:
        raise SystemExit(f"could not apply the record's diff: {r.stderr[:300]}")
    shutil.rmtree(work / ".git", ignore_errors=True)
    return work


def score(scenario_id: str, tree: Path, seed: Path) -> dict[str, Any]:
    scenario = ROOT / "scenarios" / scenario_id
    changed = added_lines(seed, tree)
    parts = {
        "behaviour": behaviour(tree, scenario),
        "regression": regression(tree, seed),
        "own_tests": own_tests(tree),
        "static": static(tree, seed, changed),
        "coverage": coverage(tree, changed),
        "mutation": mutation(tree, changed),
        "conventions": conventions(tree),
    }
    return {"scenario": scenario_id, "at_target": all(p["pass"] for p in parts.values()),
            "parts": parts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--tree", type=Path)
    src.add_argument("--record", type=Path)
    ap.add_argument("--seed", type=Path)
    ap.add_argument("--overlay", type=Path, help="files laid over the tree before scoring")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    seed = a.seed or ROOT / "scenarios" / a.scenario / "seed"
    tree = a.tree if a.tree else tree_from_record(a.record, seed)
    if a.overlay:
        shutil.copytree(a.overlay, tree, dirs_exist_ok=True)
    result = score(a.scenario, tree, seed)
    if a.json:
        a.json.write_text(json.dumps(result, indent=2))
    b = result["parts"]["behaviour"]
    print(f"{a.scenario}: at target {result['at_target']}; behaviour {b['met']}/{b['of']}")
    for name, part in result["parts"].items():
        extra = {k: v for k, v in part.items() if k not in ("pass", "criteria", "files")}
        print(f"  {name:12} {'ok' if part['pass'] else 'NOT MET'}  {json.dumps(extra)[:300]}")
    return 0 if result["at_target"] else 1


if __name__ == "__main__":
    sys.exit(main())
