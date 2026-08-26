#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_gates.py — multi-gate quality framework runner (cross-platform, #463).

Runs the registered quality gates (Requirement Correctness / Regression
Safety / Engineering Quality / Test Effectiveness / Subagent Review /
Agents Contract) against the current working tree. The GATES registry
below is the single source of truth for the gate count — docstrings and
hook templates must not hardcode a number that can drift (G-class
lesson, #498). Exit 0 only if all gates pass. Fault-injection fixtures
are Phase 2 (documented, not yet automated here — see
devkit/docs/quality_gates.md "故障注入").

Cross-platform: pure Python stdlib + optional `mutmut` for Gate 4. No
bash-only constructs so it runs identically on Windows / Linux / macOS.

Usage:
  uv run python devkit/quality_gates.py            # all registered gates
  uv run python devkit/quality_gates.py 1 2        # only gates 1 + 2
  uv run python devkit/quality_gates.py --quiet    # terse mode

Exit codes: 0 = all pass; 1 = at least one gate failed; 2 = usage.

Per devkit/docs/quality_gates.md: 覆盖率与测试数是观测不是门槛 — this script
reports them but does NOT fail on coverage %.

Gate semantics:
  1. Requirement Correctness — contract modules present + importable
     (scripts/decision_pending.py, init_state.py, log_setup.py). Catches
     "feature X shipped but its module is missing".
  2. Regression Safety — `pytest -q` must exit 0. Baseline failures
     are tracked separately (devkit/docs/defect_escape_rate.md).
  3. Engineering Quality — `pytest --collect-only -q` must succeed
     (import errors, syntax errors, missing modules all fail).
  4. Test Effectiveness — `import mutmut` succeeds (mutation testing
     tool available locally). Phase 1 only verifies tool availability;
     Phase 2 will run mutmut on PR diff and enforce a threshold.
  5. Subagent Review — execution-layer maker-checker evidence: commits
     touching domain paths need a valid .subagent-review/*.json
     (devkit/subagent_review.py, #462).
  6. Agents Contract — definition-layer twin of Gate 5: agents/*.md
     must declare the 3-element contract (plan-to-execute / status-sync
     / tool-discovery) via structural markers (devkit/agents_lint.py,
     #492).
  7. Doc Sync — writing-layer drift guard: numeric gate-count claims on
     the devkit/workflows face, un-re-pinned references/ edits,
     unregistered new scripts, and ext-index inconsistency (devkit/
     doc_sync.py, #446 + #476).
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Contract surfaces (modules that MUST exist for the product to function)
CONTRACT_MODULES = ("decision_pending", "init_state", "log_setup")


def _gate1_requirement_correctness(verbose: bool = True) -> bool:
    """Contract modules present + importable from scripts/.

    Catches: feature shipped without its module, broken __init__,
    syntax errors in any contract module. Does NOT catch semantic
    wrongness — that's covered by Gate 2 (regression tests).
    """
    scripts_dir = REPO_ROOT / "scripts"
    if not scripts_dir.is_dir():
        print(f"  [fail] scripts/ directory missing at {scripts_dir}",
              file=sys.stderr)
        return False
    missing: list[str] = []
    for name in CONTRACT_MODULES:
        spec = importlib.util.find_spec(name)
        if spec is None:
            direct = scripts_dir / f"{name}.py"
            if not direct.is_file():
                missing.append(name)
    if missing:
        print(f"  [fail] contract modules missing: {missing}",
              file=sys.stderr)
        return False
    if verbose:
        print(f"  [ok] contract modules present: "
              f"{', '.join(CONTRACT_MODULES)}")
    return True


def _gate2_regression_safety(verbose: bool = True) -> bool:
    """Full pytest must exit 0.

    Uses `pytest -q` with --junitxml so the observation step has data
    to parse. Honors PYTEST_ADDOPTS if the user has set it.
    """
    junit_path = REPO_ROOT / ".pytest-result.xml"
    cmd = [sys.executable, "-m", "pytest", "-q",
           "--junitxml", str(junit_path)]
    if verbose:
        print(f"  [run] {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=REPO_ROOT)
    return r.returncode == 0


def _gate3_engineering_quality(verbose: bool = True) -> bool:
    """`pytest --collect-only` must succeed.

    Cheapest signal for "all modules import cleanly". Import errors /
    syntax errors / missing modules all fail here before any test runs.
    """
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q"]
    if verbose:
        print(f"  [run] {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=REPO_ROOT,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def _gate4_test_effectiveness(verbose: bool = True) -> bool:
    """`import mutmut` must succeed.

    Phase 1 only verifies the tool is installed locally; we do NOT
    enforce a mutation score threshold (no baseline established).
    Phase 2 will run mutmut on the PR diff and add a threshold.
    """
    spec = importlib.util.find_spec("mutmut")
    if spec is None:
        print("  [warn] mutmut not installed — "
              "`uv pip install mutmut` (dev dep in pyproject.toml)")
        return True  # NOT a fail — Phase 1 tool-adoption only
    if verbose:
        print("  [ok] mutmut available — run `mutmut run` for baseline")
    return True


def _gate5_subagent_review(verbose: bool = True) -> bool:
    """Subagent Review (Maker-Checker) — Gate 5 (issue #462).

    Specialist agents (ghidra-light / floss-filter / pefile-signature /
    go-symbols / verdict-scorer) currently lack the 3-element subagent
    contract (plan-to-execute / state-sync / tool-discovery + no-self-
    invention) that kunglao-worker has. Gate 5 enforces it mechanically
    for any commit touching domain paths: a .subagent-review/*.json
    file with all required fields must exist, and verified_by must
    not be the orchestrator's own handle (anti-self-stamp).

    N/A when staged changes don't touch domain paths (e.g. openspec
    scaffolding or pyproject bumps). Trivially passes.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "devkit"))
        from subagent_review import check as _subagent_check
    except Exception as exc:
        print(f"  [fail] subagent_review import error: {exc!r}")
        return False
    rc = _subagent_check()
    # subagent_review.check() returns 0 (pass) or 2 (HARD_PAUSE).
    # The runner treats any truthy ok as PASS — bool(rc==0) is required
    # so rc=2 doesn't accidentally register as PASS.
    return bool(rc == 0)


def _gate6_agents_contract(verbose: bool = True) -> bool:
    """Agents Contract — Gate 6 (issue #492, split from #462).

    Definition-layer twin of Gate 5: where Gate 5 checks the EXECUTION
    evidence (.subagent-review/*.json), Gate 6 statically lints the
    agent DEFINITIONS (agents/*.md) for the 3-element contract via
    structural markers — structured declaration over prose regex (user
    doctrine: enumerating natural-language clauses is unfinishable in
    any language). agents/*.md are standing assets, so this runs on
    every invocation (cheap static read), not on domain-path triggers.

    Fail-closed: agents/ missing / zero *.md / any agent missing a
    marker or carrying a hollow marker → FAIL.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "devkit"))
        from agents_lint import check as _agents_check
    except Exception as exc:
        print(f"  [fail] agents_lint import error: {exc!r}")
        return False
    rc = _agents_check()
    # agents_lint.check() returns 0 (pass) or 1 (violations).
    # bool(rc==0) — same truthiness trap guard as Gate 5.
    return bool(rc == 0)


def _gate7_doc_sync(verbose: bool = True) -> bool:
    """Doc Sync — Gate 7 (issue #446, G-class writing-layer drift).

    Three sub-checks (devkit/doc_sync.py):
      (a) numeric gate-count claims on devkit/** + .github/workflows/**
          are violations — the GATES registry is the count's only source
          (number-free wording required; even a correct number is a
          drift seed for the next registered gate);
      (b) staged references/*.md without a staged, pin-accurate
          references/_INDEX.yaml → HARD_PAUSE (re_pin_references.py
          joins the pre-commit chain — the 7th live drift, 2026-08-19);
      (c) staged NEW scripts/*.py unmentioned in references/_INDEX.md →
          WARN (three-piece mechanism registration ledger).

    N/A when nothing is staged (manual runs): the references check
    passes trivially; the face scan is cheap and always runs.
    """
    try:
        sys.path.insert(0, str(REPO_ROOT / "devkit"))
        from doc_sync import check as _doc_sync_check
    except Exception as exc:
        print(f"  [fail] doc_sync import error: {exc!r}")
        return False
    rc = _doc_sync_check()
    # doc_sync.check() returns 0 (pass), 1 (violations), 2 (HARD_PAUSE).
    # bool(rc==0) — same truthiness trap guard as Gates 5 and 6.
    return bool(rc == 0)


def _observation_pass_rate(verbose: bool = True) -> None:
    """Print pass-rate metric from .pytest-result.xml if present.

    NOT a gate — observation per devkit/docs/quality_gates.md "Coverage /
    Test Count = observation only". Skipped silently when junit absent.
    """
    junit_path = REPO_ROOT / ".pytest-result.xml"
    if not junit_path.is_file():
        if verbose:
            print("  [skip] .pytest-result.xml not present — "
                  "pass rate observation skipped")
        return
    try:
        tree = ET.parse(junit_path)
    except ET.ParseError as exc:
        print(f"  [warn] {junit_path} parse error: {exc}", file=sys.stderr)
        return
    root = tree.getroot()
    tests = int(root.get("tests", 0))
    failures = int(root.get("failures", 0))
    errors = int(root.get("errors", 0))
    skipped = int(root.get("skipped", 0))
    passed = tests - failures - errors - skipped
    rate = (passed / tests * 100.0) if tests else 0.0
    print(f"  [observe] pass_rate={rate:.2f}% "
          f"({passed}/{passed + failures + errors + skipped}; "
          f"failed={failures + errors} skipped={skipped})")


GATES = {
    1: ("Requirement Correctness", _gate1_requirement_correctness),
    2: ("Regression Safety",      _gate2_regression_safety),
    3: ("Engineering Quality",    _gate3_engineering_quality),
    4: ("Test Effectiveness",     _gate4_test_effectiveness),
    5: ("Subagent Review",        _gate5_subagent_review),
    6: ("Agents Contract",        _gate6_agents_contract),
    7: ("Doc Sync",               _gate7_doc_sync),
}


# #563: named selector for the CI quick path — positional ids renumber on
# registry growth; --quick is stable.
QUICK_GATES = [1, 3, 4]


def _observation_artifact_budget(verbose: bool = True,
                                 repo_root: Path | None = None,
                                 sink=None) -> None:
    """Artifact-budget observation (#720): net NEW specs/tests/files added by
    the current task vs gc-harness/config.yaml budgets.

    NOT a gate — WARN-level observation per #720 P1 (HARD-ification is a
    data-driven decision for a later release). Counts ADDED paths against a
    diff base of origin/dev (fallback: HEAD — i.e. uncommitted work).
    Over-budget without .agent/budget_justification.md content -> [warn]
    with the required justification template; with justification -> [observe].
    """
    root = repo_root or REPO_ROOT
    out = sink if sink is not None else print

    def _git(*args: str) -> str:
        r = subprocess.run(["git", "-C", str(root), *args],
                           capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    base = "origin/dev" if _git("rev-parse", "-q", "--verify",
                                "origin/dev").strip() else "HEAD"
    names = _git("diff", "--name-status", "-r", base)
    added = [ln.split("\t", 1)[1].strip()
             for ln in names.splitlines()
             if ln.startswith("A") and "\t" in ln]
    # untracked files are the most common mid-task state for NEW artifacts —
    # `git diff` never sees them. Union both surfaces (exclude-standard keeps
    # gitignored noise like .agent/ out).
    untracked = _git("ls-files", "--others", "--exclude-standard").splitlines()
    added = list(dict.fromkeys(added + [u.strip() for u in untracked if u.strip()]))
    new_specs = {p.split("/", 2)[1] for p in added
                 if p.startswith("openspec/changes/") and p.count("/") >= 3}
    new_tests = [p for p in added
                 if p.startswith("tests/") and Path(p).name.startswith("test_")]
    cfg_path = root / "gc-harness" / "config.yaml"
    budgets = {"max_new_spec": 1, "max_new_test": 5, "max_new_files": 20}
    if cfg_path.is_file():
        try:
            import yaml  # local import: repo-wide use-site convention
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            budgets.update((loaded or {}).get("budget", {}))
        except Exception:  # noqa: BLE001 — observation must never raise
            pass
    counts = {
        "max_new_spec": len(new_specs),
        "max_new_test": len(new_tests),
        "max_new_files": len(added),
    }
    over = {k: (counts[k], int(budgets[k]))
            for k in counts if counts[k] > int(budgets[k])}
    just = root / ".agent" / "budget_justification.md"
    has_just = just.is_file() and bool(just.read_text(
        encoding="utf-8", errors="replace").strip())
    summary = (f"artifact budget: new_specs={counts['max_new_spec']}/"
               f"{budgets['max_new_spec']} new_tests={counts['max_new_test']}/"
               f"{budgets['max_new_test']} new_files={counts['max_new_files']}/"
               f"{budgets['max_new_files']} (base={base})")
    if not over:
        if verbose:
            out(f"  [observe] {summary}")
        return
    detail = "; ".join(f"{k}: {v[0]}/{v[1]}" for k, v in over.items())
    if has_just:
        out(f"  [observe] {summary} — over budget WITH justification "
            f"(.agent/budget_justification.md): {detail}")
    else:
        out(f"  [warn] {summary} — OVER BUDGET without justification: {detail}")
        out("  [warn] required in .agent/budget_justification.md:\n"
            "        Existing artifact cannot satisfy because: <reason>\n"
            "        New artifact justification: <reason>")


def _build_parser() -> argparse.ArgumentParser:
    """Parser factory (test seam). NOTE (#758 G1a fallout): argparse on the
    PINNED py3.11 validates an empty `nargs="*"` against `choices` and dies
    on a bare `quality_gates.py` invocation, so gate-range validation moved
    out of choices into main() — behavior-neutral elsewhere."""
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("gates", nargs="*", type=int,
                   help="which gates to run (default: all)")
    p.add_argument("--quick", action="store_true",
                   help=f"run the CI quick set {QUICK_GATES} (stable name)")
    p.add_argument("--quiet", action="store_true",
                   help="suppress per-gate verbose output")
    return p


def main(argv: list[str] | None = None) -> int:
    p = _build_parser()
    args = p.parse_args(argv)
    bad = [g for g in args.gates if g not in GATES]
    if bad:
        p.error(f"invalid gate(s): {bad} (choose from {sorted(GATES)})")

    verbose = not args.quiet
    if getattr(args, "quick", False) and args.gates:
        p.error("--quick and positional gates are mutually exclusive")
    selected = QUICK_GATES if getattr(args, "quick", False) else (args.gates or sorted(GATES))
    print(f"quality_gates: repo={REPO_ROOT} gates={selected}")

    failed: list[int] = []
    for g in selected:
        name, fn = GATES[g]
        print(f"\n=== Gate {g}: {name} ===")
        try:
            ok = fn(verbose=verbose)
        except Exception as exc:
            print(f"  [fail] Gate {g} raised: {exc}", file=sys.stderr)
            ok = False
        if ok:
            print(f"[PASS] Gate {g}")
        else:
            print(f"[FAIL] Gate {g}", file=sys.stderr)
            failed.append(g)

    print("\n--- observation only (not a gate) ---")
    _observation_pass_rate(verbose=verbose)
    _observation_artifact_budget(verbose=verbose)

    if failed:
        print(f"\n=== result: FAIL (gates {failed} failed) ===",
              file=sys.stderr)
        return 1
    print("\n=== result: ALL-PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())