#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_split_lint.py — anti-overfit mining/holdout firewall (#518 PR-1).

The capability mainline injects expert priors mined from the corpus; the
interpolation holdout (eval/v1/split.yaml) is the only surface capability
verdicts are judged on. This lint makes overfitting a MECHANICAL failure
instead of a discipline: any holdout instance constant (raw string or the
even-hex decimal-int form the checkers accept) or any holdout unit-id
that reaches a prior_store_root file fails CI with a LEAK[...] row.

Usage:
  python scripts/eval_split_lint.py [--patterns-root <dir>]
Exit codes: 0 clean / 1 leak-or-registry-violation.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# Short constants (bits, small ints) substring-match everything — dates,
# counts, durations. Below this length a "leak" is noise, not signal.
_MIN_FORM_LEN = 4


def _constant_forms(value) -> set[str]:
    """Every textual form a constant can surface as: the raw string plus,
    for even-length hex, the big-endian decimal int (the same alternate
    form eval checkers accept — a leaked key can hide as an int literal)."""
    forms: set[str] = set()
    s = str(value).strip()
    if len(s) < _MIN_FORM_LEN:
        return forms
    forms.add(s.lower())
    # even length + all-hex makes bytes.fromhex total here; the int form
    # is how a leaked key hides as an int literal (the same alternate
    # form the eval checkers grade)
    if len(s) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in s):
        forms.add(str(int.from_bytes(bytes.fromhex(s), "big")))
    return forms


def _walk_constants(node) -> list[str]:
    """Flatten a ground_truth constants block (possibly nested) to scalars."""
    if isinstance(node, dict):
        out: list[str] = []
        for v in node.values():
            out.extend(_walk_constants(v))
        return out
    if isinstance(node, list):
        out = []
        for v in node:
            out.extend(_walk_constants(v))
        return out
    if isinstance(node, (str, int, float)):
        return [str(node)]
    return []


# corpus tiers, release first (the interpolation holdout lives there);
# extrapolation units may live in any tier (the #546 blocked-path units
# live under toolflex)
_TIERS: tuple[str, ...] = ("release", "smoke", "misdirection", "toolflex",
                           "chain")


def _holdout_gt(repo: Path, unit: str) -> Path | None:
    """A holdout unit's ground_truth.json, resolved across corpus tiers."""
    for tier in _TIERS:
        p = repo / "eval" / "v1" / "tasks" / tier / unit / "ground_truth.json"
        if p.is_file():
            return p
    return None


def _scan_unit(repo: Path, unit: str,
               texts: dict) -> list[str]:
    """One holdout unit against every prior-store file: constants (all
    forms) and the unit-id itself. Missing/unreadable ground_truth is its
    own violation — an unlintable holdout is an unauditable holdout."""
    gt = _holdout_gt(repo, unit)
    if gt is None:
        return [f"LEAK[HOLDOUT_GT_MISSING] {unit}: no ground_truth.json — "
                f"an unlintable holdout is an unauditable holdout"]
    try:
        consts = json.loads(gt.read_text(encoding="utf-8")).get(
            "constants") or {}
    except (OSError, ValueError) as exc:
        return [f"LEAK[HOLDOUT_GT_MISSING] {unit}: {exc}"]
    forms: set[str] = set()
    for raw in _walk_constants(consts):
        forms |= _constant_forms(raw)
    uid = unit.lower()
    out: list[str] = []
    for _p, (name, low) in texts.items():
        hit = next((f for f in sorted(forms) if f in low), None)
        if hit is not None:
            out.append(
                f"LEAK[CONSTANT] {unit}: constant form {hit[:28]!r} "
                f"appears in {name} — a prior that has seen the "
                f"holdout's answer is the answer key, not a prior")
        if uid in low:
            out.append(
                f"LEAK[UNIT_ID] {unit}: unit-id in {name} — priors are "
                f"feature-keyed, never identity-keyed (#518)")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    repo = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(prog="eval_split_lint")
    ap.add_argument("--patterns-root", default=None,
                    help="override the prior-store root (default: the "
                         "prior_store_roots union from split.yaml)")
    args = ap.parse_args(argv)

    split_path = repo / "eval" / "v1" / "split.yaml"
    try:
        doc = yaml.safe_load(split_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"LEAK[REGISTRY] split.yaml unreadable: {exc}")
        return 1
    hold = (doc.get("holdout") or {})
    interp = list(hold.get("interpolation") or [])
    extrap = list(hold.get("extrapolation") or [])
    roots = [repo / p for p in (doc.get("prior_store_roots") or [])]
    if args.patterns_root:
        roots = [Path(args.patterns_root)]

    violations: list[str] = []
    if set(interp) & set(extrap):
        violations.append("LEAK[REGISTRY] a unit is in both holdout tiers")

    files: list[Path] = []
    for root in roots:
        if root.is_dir():
            files += sorted(p for p in root.rglob("*") if p.is_file())
    texts = {p: (p.name, p.read_text(encoding="utf-8", errors="replace").lower())
             for p in files}

    for unit in interp + extrap:
        violations += _scan_unit(repo, unit, texts)

    if violations:
        print("\n".join(violations))
        return 1
    print(f"eval_split_lint: clean ({len(files)} prior-store file(s), "
          f"{len(interp)}+{len(extrap)} holdout units checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
