#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""formal_code_lint.py — the formal-content hygiene ratchet for issue and
version markers in production code (owner ruling: formal code carries no
issue numbers and no version-number narration — provenance lives in git
history and the tracker, not in the shipped source).

Scope — comments and docstrings ONLY, in the production trees
(scripts/, tools/, hooks/). Strings are NOT scanned: data schema stamps
(posterior-store/1, llm-prior/1, ...) and compatibility guards
(`== "1"`) are functional protocol, not narration. Tests are NOT
scanned: pins cite issues by design (the reproducibility contract of
the test suite).

Detector (comment/docstring text, mechanical):

  - an issue reference: `#NNN` or `issue NNN` / `Issue #NNN`
    (three-or-more digits — the tracker's issue range)
  - a version narration: `vN.N` / `vN.N.N` shapes and `PR-NNN`
  - a date narration in comments: `2026-10-08`-style stamps (git is
    the clock)

Counting unit: one file's total matches (any pattern) = the file's
count, at FILE granularity (the comment_hygiene_lint convention).

Baseline ratchet (scripts/formal_code_baseline.yaml — the house
pattern): existing debt is frozen per file; counts only shrink. A count
above the ledger fails; reaching zero deletes the entry; a partially
reduced entry must be tightened in the same change; a vanished file's
entry is stale and fails; new debt without an entry fails.

Usage:
    python scripts/formal_code_lint.py [--emit-baseline] [--json]
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import time
from pathlib import Path

import lint_protocol  # the shared scan/emit skeleton (repo sibling)

ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("scripts", "tools", "hooks")
BASELINE_REL = ROOT / "scripts" / "formal_code_baseline.yaml"

#: issue references: #NNN (3+ digits), issue NNN, Issue #NNN
RE_ISSUE = re.compile(r"(?:#\s*\d{3,}|\bissue\s*#?\s*\d{3,})", re.IGNORECASE)
#: version narration: v0.1, v2.3.4, PR-NNN
RE_VERSION = re.compile(r"(?:\bv\d+(?:\.\d+){1,2}\b|\bPR-\d+\b)")
#: date narration in comments: 2026-10-08 / 2026/10/08
RE_DATE = re.compile(r"\b20\d{2}[-/]\d{2}[-/]\d{2}\b")


def _docstrings(source: str) -> list[str]:
    """Module/class/function docstrings (first-statement strings) —
    ordinary string expressions (schema stamps, literals) stay out of
    scope: they are protocol, not narration."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.append(body[0].value.value)
    return out


def _comment_text(source: str) -> str:
    """Every `#` comment's text (code side of the line discarded)."""
    out: list[str] = []
    for line in source.splitlines():
        if "#" in line:
            _, _, comment = line.partition("#")
            out.append(comment)
    return "\n".join(out)


def scan_counts(root: Path = ROOT) -> dict[str, int]:
    """Per-file formal-marker counts over the production trees."""
    counts: dict[str, int] = {}
    for rel, path in lint_protocol.iter_py_files(root, SCAN_ROOTS):
        try:
            source = path.read_text(encoding="utf-8",
                                    errors="replace")
        except OSError:
            continue
        text = "\n".join(_docstrings(source)) + "\n" \
            + _comment_text(source)
        n = (len(RE_ISSUE.findall(text))
             + len(RE_VERSION.findall(text))
             + len(RE_DATE.findall(text)))
        if n:
            counts[rel] = n
    return counts


def load_baseline(path: Path = BASELINE_REL) -> dict[str, int]:
    if not path.is_file():
        return {}
    return lint_protocol.load_int_baseline(path)


def emit_baseline(counts: dict[str, int], path: Path = BASELINE_REL) -> None:
    import yaml

    doc = {"files": dict(sorted(counts.items()))}
    path.write_text(yaml.safe_dump(doc, sort_keys=True), encoding="utf-8")


def compare(counts: dict[str, int],
            entries: dict[str, int]) -> list[dict]:
    violations: list[dict] = []
    for fname, n in sorted(counts.items()):
        ledger = entries.get(fname)
        if ledger is None:
            violations.append({"file": fname, "kind": "unbaselined",
                               "detail": f"markers {n} with no ledger entry"})
        elif n > ledger:
            violations.append({"file": fname, "kind": "increase",
                               "detail": f"grew {ledger} -> {n}"})
    for fname in sorted(entries):
        if fname not in counts:
            violations.append({"file": fname, "kind": "stale-entry",
                               "detail": "ledger entry for a file with no "
                                         "markers (delete it)"})
    return violations


def build_report(argv: list[str] | None = None) -> dict:
    ap = argparse.ArgumentParser(prog="formal_code_lint.py")
    ap.add_argument("--emit-baseline", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    counts = scan_counts()
    if args.emit_baseline:
        emit_baseline(counts)
        print(f"formal-code: emitted {BASELINE_REL} "
              f"({len(counts)} files with markers)", file=sys.stderr)
        return {"emitted": True, "files": len(counts)}
    violations = compare(counts, load_baseline())
    return {
        "schema": "formal-code-lint/1",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files_scanned_roots": list(SCAN_ROOTS),
        "files_with_markers": len(counts),
        "violations": violations,
    }


def main(argv: list[str] | None = None) -> int:
    report = build_report(argv)
    if report.get("emitted"):
        return 0
    if "--json" in (argv or []):
        print(json.dumps(report, indent=2))
        return 0
    for v in report["violations"]:
        print(f"{v['kind']}: {v['file']}: {v['detail']}")
    n = len(report["violations"])
    print(f"formal-code: {n} violation(s); "
          f"{report['files_with_markers']} files carry frozen markers")
    return 1 if n else 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    raise SystemExit(main())
