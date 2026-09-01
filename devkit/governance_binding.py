#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""governance_binding.py — Gate 8 Governance Binding (issue #867).

Machine-binds the governance WORDING of the repo to its code (the #819
closeout-audit generalization: "the repo asserts A, the code does B").
Three sub-checks:

  (a) deprecated live callers — delegates to scripts/retirement_gate.py
      (the #861 mechanism: RETIRED regex copies + DEPRECATED=True modules
      with live importers), keeping its baseline ratchet semantics. The
      #867 closeout cleared the last baselined debt
      (priority <- external_kicker), so any finding is a violation.
  (b) SKILL teaching shape vs detector — every `kunglao_dispatch` JSON
      envelope sample taught in skills/kunglao-agent/SKILL.md must be
      PARSED BY the detector itself (hooks/lib_kunglao.py:
      parse_dispatch_json) — teaching shape and detector are the same
      source, not parallel regex copies. Placeholder schema shapes
      (C-NN / <N> / [...]) are tolerated via mechanical substitution
      before parsing. Any line teaching the legacy v0 prefix shape must
      carry a replay-only / legacy marker on the same line.
  (c) evals expectations vs deprecation status — evals/*.json must not
      pin a DEPRECATED module's ordering as expected behavior. The
      deprecated registry is derived mechanically (scripts/*.py carrying
      `DEPRECATED = True`); references in eval string fields are
      violations unless allow-listed in devkit/governance-exceptions.json.

Fail-closed: a missing SKILL.md / evals file / zero envelope samples is a
violation, not a pass. Stdlib-only (devkit convention).

Usage:
  uv run python devkit/governance_binding.py                # all checks
  uv run python devkit/governance_binding.py --check skill  # one check
Exit codes: 0 = pass; 1 = violations; 2 = usage.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# #863 Family B: reach the canonical by-path loader in hooks/. devkit is its
# own sys.path domain, so bridge once here — guarded APPEND (never insert(0):
# reordering hooks/ ahead of scripts/ is the #671 shared-name-twin shadow).
_HOOKS_DIR = str(Path(__file__).resolve().parent.parent / "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.append(_HOOKS_DIR)
from _path_hygiene import load_module_by_path  # noqa: E402  (#671 authority)

REPO_ROOT = Path(__file__).resolve().parent.parent

SKILL_REL = "skills/kunglao-agent/SKILL.md"
BASELINE_REL = "scripts/.retirement-gate-baseline.txt"
EXCEPTIONS_REL = "devkit/governance-exceptions.json"
EVALS_DIR = "evals"
SELF = "devkit/governance_binding.py"

V0_SHAPE_RE = re.compile(r"\[T\d*N?[^ \]]*\s+tools=", re.IGNORECASE)
V0_MARKER_RE = re.compile(r"replay|legacy", re.IGNORECASE)
# Placeholder tokens tolerated inside SCHEMA shapes taught as documentation
# (the concrete-example samples parse without substitution).
_PLACEHOLDER_SUBS = (
    ("C-NN", "C-001"),
    ("<N>", "1"),
    ("<tier>", "1"),
    ("[...]", "[]"),
    ("<tools>", "[]"),
    ("<agent>", "w"),
)


def _load_module(name: str, path: Path):
    """#863 Family B: delegate to the canonical by-path loader (the util
    adds sys.modules registration under the unique govbind names — pure-def
    modules, cached reuse is behavior-equivalent)."""
    return load_module_by_path(name, path)


def _retirement_gate(root: Path):
    return _load_module("retirement_gate_govbind", root / "scripts" / "retirement_gate.py")


def _hooks_lib(root: Path):
    # lib_kunglao self-bootstraps its _path_hygiene dependency when loaded
    # by path (see hooks/lib_kunglao.py import fallback).
    return _load_module("lib_kunglao_govbind", root / "hooks" / "lib_kunglao.py")


def _baseline_entries(root: Path) -> list:
    bp = root / BASELINE_REL
    if not bp.exists():
        return []
    return [ln.strip() for ln in bp.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")]


# ---------- (a) deprecated live callers (retirement_gate ratchet) ----------

def check_callers(root: Path, verbose: bool = True) -> list:
    """Return violation strings for sub-check (a)."""
    rg = _retirement_gate(root)
    r = rg.scan(root, _baseline_entries(root))
    if r["ok"] and not r["findings"]:
        if verbose:
            print("  [ok] (a) no deprecated live callers, baseline empty")
        return []
    violations = []
    for k in r["new_findings"]:
        violations.append(f"(a) NEW retired/deprecated usage: {k}")
    for k in r["findings"]:
        if k not in r["new_findings"]:
            violations.append(f"(a) baselined debt present (ratchet non-empty): {k}")
    return violations


# ---------- (b) SKILL teaching shape vs detector ----------

def _envelope_samples(lib, text: str) -> list:
    """Extract balanced `{"kunglao_dispatch": ...}` samples from text."""
    out = []
    for m in lib.DISPATCH_JSON_START_RE.finditer(text):
        end = lib._balanced_json_at(text, m.start())
        if end < 0:
            out.append(None)  # unbalanced — reported as a violation
            continue
        out.append(text[m.start():end])
    return out


def _parses_via_detector(lib, sample: str) -> bool:
    """True when the sample (or its placeholder-substituted form) matches
    the v1 canonical envelope through the real detector."""
    if lib.parse_dispatch_json(sample)[2] is not None:
        return True
    sub = sample
    for token, repl in _PLACEHOLDER_SUBS:
        sub = sub.replace(token, repl)
    return lib.parse_dispatch_json(sub)[2] is not None


def check_skill_teaching(root: Path, verbose: bool = True) -> list:
    """Return violation strings for sub-check (b)."""
    skill_path = root / SKILL_REL
    if not skill_path.exists():
        return [f"(b) {SKILL_REL} missing — nothing teaches the envelope"]
    text = skill_path.read_text(encoding="utf-8", errors="replace")
    lib = _hooks_lib(root)
    violations = []
    samples = _envelope_samples(lib, text)
    concrete = 0
    for s in samples:
        if s is None:
            violations.append(
                "(b) unbalanced kunglao_dispatch envelope sample in SKILL.md")
            continue
        if not _parses_via_detector(lib, s):
            violations.append(
                f"(b) SKILL.md envelope sample does not match the detector: {s!r}")
            continue
        concrete += 1
    if not samples:
        violations.append(
            "(b) SKILL.md teaches no kunglao_dispatch envelope — the v1 "
            "canonical shape must stay taught (fail-closed)")
    for i, line in enumerate(text.splitlines(), 1):
        if V0_SHAPE_RE.search(line) and not V0_MARKER_RE.search(line):
            violations.append(
                f"(b) SKILL.md:{i} teaches the legacy v0 prefix shape "
                f"without a replay-only/legacy marker: {line.strip()!r}")
    if verbose and not violations:
        print(f"  [ok] (b) {len(samples)} envelope sample(s) parse via "
              f"lib_kunglao.parse_dispatch_json; v0 mentions marked replay-only")
    return violations


# ---------- (c) evals expectations vs deprecation status ----------

def _deprecated_stems(root: Path) -> list:
    """scripts/*.py modules declaring module-level `DEPRECATED = True`.

    AST-based (not line regex): a prose line inside a docstring that merely
    STARTS with "DEPRECATED=True" (e.g. scripts/retirement_gate.py's
    header) must not register a deprecation. Module-level assignments only.
    """
    import ast

    scripts = root / "scripts"
    if not scripts.is_dir():
        return []
    stems = []
    for f in sorted(scripts.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in tree.body:  # module-level only
            if (isinstance(node, ast.Assign)
                    and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "DEPRECATED"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value is True):
                stems.append(f.stem)
                break
    return stems


def _load_exceptions(root: Path) -> dict:
    ep = root / EXCEPTIONS_REL
    if not ep.exists():
        return {}
    try:
        return json.loads(ep.read_text(encoding="utf-8")) or {}
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{EXCEPTIONS_REL} is not valid JSON: {exc}")


def _string_values(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _string_values(v)
    elif isinstance(node, list):
        for v in node:
            yield from _string_values(v)


def check_evals(root: Path, verbose: bool = True) -> list:
    """Return violation strings for sub-check (c)."""
    stems = _deprecated_stems(root)
    if not stems:
        if verbose:
            print("  [ok] (c) no DEPRECATED modules registered — nothing to reconcile")
        return []
    evals_dir = root / EVALS_DIR
    if not evals_dir.is_dir():
        return [f"(c) {EVALS_DIR}/ missing — eval manifest must exist (fail-closed)"]
    allowed = _load_exceptions(root).get("evals_allowed_refs", [])
    violations = []
    seen_any = False
    for ef in sorted(evals_dir.glob("*.json")):
        try:
            data = json.loads(ef.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            violations.append(f"(c) {ef.name} is not valid JSON: {exc}")
            continue
        seen_any = True
        rel = ef.relative_to(root).as_posix()
        for s in _string_values(data):
            for stem in stems:
                for pat in (rf"\b{re.escape(stem)}\.py\b",
                            rf"scripts/{re.escape(stem)}\b"):
                    if not re.search(pat, s):
                        continue
                    if any(a.get("file") == rel and a.get("pattern", stem) in s
                           for a in allowed):
                        continue  # allow-listed exception
                    violations.append(
                        f"(c) {rel} pins a reference to DEPRECATED module "
                        f"{stem!r}: {s[:120]!r}")
    if not seen_any:
        violations.append(f"(c) no eval JSON found under {EVALS_DIR}/ (fail-closed)")
    if verbose and not violations:
        print(f"  [ok] (c) evals reference no DEPRECATED module "
              f"(registry: {stems})")
    return violations


CHECKS = {
    "callers": check_callers,
    "skill": check_skill_teaching,
    "evals": check_evals,
}


def check(selected: "list[str] | None" = None, root: Path | None = None,
          verbose: bool = True) -> int:
    """Gate entry point: run the selected sub-checks (default: all).

    Returns 0 (pass) or 1 (violations) — the quality_gates.GATES rc contract.
    """
    root = root or REPO_ROOT
    names = selected or list(CHECKS)
    unknown = [n for n in names if n not in CHECKS]
    if unknown:
        raise SystemExit(f"unknown check(s): {unknown} (choose from {list(CHECKS)})")
    violations = []
    for n in names:
        violations.extend(CHECKS[n](root, verbose=verbose))
    if violations:
        for v in violations:
            print(f"  [fail] {v}")
        print(f"FAIL Gate 8 governance binding: {len(violations)} violation(s) "
              f"({' + '.join(names)})")
        return 1
    print("[PASS] Gate 8 governance binding: " + " + ".join(names))
    return 0


def main(argv: "list[str] | None" = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", nargs="*", default=None,
                    help=f"sub-checks to run (default: all of {list(CHECKS)})")
    ap.add_argument("--repo", default=".")
    a = ap.parse_args(argv)
    return check(a.check, root=Path(a.repo).resolve())


if __name__ == "__main__":
    sys.exit(main())
