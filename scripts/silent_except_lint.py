#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""silent_except_lint.py — silent-swallow ratchet gate for scripts/ and hooks/.

Policy (issue 275): fail-open is the correct liveness posture for hooks,
but fail-open without a trace is telemetry by omission — the twin of
built-but-unwired. A fail-open handler must leave exactly ONE runtime
trace: an emit event, a null_reasons/sidecar entry, or a rate-limited
WARN. Bare `except: pass` is banned; the documented-contract exemption
is reserved for owner-blessed cases (the issue states none exist today).

Detector rule (exact, mechanical, AST-only — no regex):

  An `except` handler (ast.ExceptHandler under ast.Try or ast.TryStar)
  is a SILENT SWALLOW iff every statement in its body is a no-op shape:

    - ast.Pass                                   (`pass`)
    - ast.Expr whose value is ast.Constant        (`...`, a bare string)

  A no-op body cannot raise or emit, so by construction such a handler
  swallows without leaving a runtime trace. The scan nevertheless walks
  each handler body for ast.Raise nodes and for ast.Call nodes whose
  terminal callee identifier is in TRACE_TERMINALS — belt-and-suspenders
  audit face; either hit forces the handler out of the silent class.

  Deliberate boundaries (documented, not accidental):

  - Comments do NOT exempt a handler. A comment records intent; it is
    not a runtime trace. Calibrated against the issue's quantified
    evidence: with a comment exemption the inventory collapses from 220
    to 97 and the worst-file table inverts (convergence_check.py 10 -> 2
    — the issue names it worst precisely for its annotated pass sites).
  - Control-flow no-ops (`continue`/`break`), default-assignment
    (`x = None`) and default-return (`return []`) bodies are OUT of
    scope: the ledger freezes the issue's quantified `except: pass`
    surface, not the wider fail-open family. Widening the shape set is
    a deliberate later-batch act that re-seeds the ledger.
  - Scan roots are scripts/ + hooks/ — the issue's quantified sweep
    surface. tests/ is not scanned.

  Counting unit: one silent handler per file (mirrors the one-unit
  convention of comment_hygiene_lint).

Baseline ratchet (scripts/silent_except_baseline.yaml — house pattern of
scripts/hygiene_baseline.yaml): the ledger only shrinks. A count above
the ledger fails; an entry whose count reaches zero must be deleted; a
partially reduced entry must be tightened in the same change; an entry
whose file is gone is stale and fails; new debt without an entry fails.

Usage:
  python scripts/silent_except_lint.py
  python scripts/silent_except_lint.py --emit-baseline
  python scripts/silent_except_lint.py --json
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCAN_ROOTS = ("scripts", "hooks")
DEFAULT_BASELINE_REL = "scripts/silent_except_baseline.yaml"

BASELINE_SCHEMA = "silent-except-baseline/1"

# Generated files are exempt via the ALLOWLIST constant, never via the ledger.
ALLOWLIST: frozenset[str] = frozenset()

# Runtime-trace vocabulary: a Call whose terminal callee identifier is in
# this set leaves the one trace the policy demands. Audit face only — a
# no-op-shaped body admits no calls at all (see the detector rule above).
TRACE_TERMINALS = frozenset({
    "emit", "log", "warn", "warning", "debug", "info", "critical",
    "error", "print", "record", "record_event", "note", "trace", "notify",
})

_TRY_NODES = (ast.Try, getattr(ast, "TryStar", ast.Try))


# ------------------------------------------------------------- scanning

def _iter_py_files(root: Path):
    for rel_dir in SCAN_ROOTS:
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in ALLOWLIST:
                continue
            yield rel, path


def _terminal_name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_noop_statement(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    return (isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant))


def _handler_is_silent(handler: ast.ExceptHandler) -> bool:
    """The detector rule: no-op body only; no raise; no trace call."""
    body = handler.body
    if not all(_is_noop_statement(stmt) for stmt in body):
        return False
    scope = ast.Module(body=body, type_ignores=[])
    for node in ast.walk(scope):
        if isinstance(node, ast.Raise):
            return False
        if (isinstance(node, ast.Call)
                and _terminal_name(node.func) in TRACE_TERMINALS):
            return False
    return True


def scan_counts(root: Path) -> tuple[dict[str, int], list[dict]]:
    """Per-file silent-handler counts plus fail-closed structural findings."""
    counts: dict[str, int] = {}
    structural: list[dict] = []
    for rel, path in _iter_py_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (UnicodeDecodeError, OSError) as exc:
            structural.append({"kind": "unreadable", "file": rel,
                               "detail": str(exc)})
            continue
        except (SyntaxError, ValueError) as exc:
            structural.append({"kind": "syntax", "file": rel,
                               "detail": str(exc)})
            continue
        silent = 0
        for node in ast.walk(tree):
            if isinstance(node, _TRY_NODES):
                for handler in node.handlers:
                    if _handler_is_silent(handler):
                        silent += 1
        counts[rel] = silent
    return counts, structural


# ------------------------------------------------------- baseline ratchet

def load_baseline(path: Path) -> dict[str, int]:
    """Parse the ledger file into {rel_path: count}."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    files = doc.get("files") or {}
    return {str(rel): int(count) for rel, count in files.items()}


def compare(counts: dict[str, int], entries: dict[str, int]) -> list[dict]:
    """Shrink-only ratchet: increase / zero-clear / loose-tighten / stale."""
    out: list[dict] = []
    for rel in sorted(set(counts) | set(entries)):
        if rel not in counts:
            out.append({"kind": "stale-entry", "file": rel,
                        "detail": "ledger entry for a file that no longer exists"})
            continue
        current = counts[rel]
        entry = entries.get(rel)
        if entry is None:
            if current > 0:
                out.append({"kind": "unbaselined", "file": rel,
                            "detail": f"silent handlers: {current} "
                                      "with no ledger entry"})
            continue
        if current > entry:
            out.append({"kind": "increase", "file": rel,
                        "detail": f"grew: {entry} -> {current}"})
        elif current == 0:
            out.append({"kind": "cleared-entry", "file": rel,
                        "detail": "count reached zero: delete the ledger entry"})
        elif current < entry:
            out.append({"kind": "loose-entry", "file": rel,
                        "detail": "partially cleared: tighten the ledger entry"})
    return out


def emit_baseline(counts: dict[str, int], path: Path) -> None:
    """Write the ledger from current counts; only debt files get entries."""
    files = {rel: n for rel, n in sorted(counts.items()) if n > 0}
    doc = {
        "schema": BASELINE_SCHEMA,
        "unit": "per-file count of silent-swallow except handlers "
                "(no-op body, no raise, no trace call)",
        "policy": (
            "ratchet only shrinks: a count above the ledger fails; an entry "
            "whose count reaches zero is deleted; a partially cleared entry "
            "is tightened in the same change; an entry whose file is gone "
            "is stale and fails; new debt without an entry fails"
        ),
        "files": files,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


# ------------------------------------------------------------ gate faces

def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Silent-swallow ratchet gate over scripts/ and hooks/.")
    parser.add_argument("--root", default=str(REPO_ROOT),
                        help="repository root to scan (default: this repo)")
    parser.add_argument("--baseline", default=None,
                        help=f"ledger path (default: <root>/{DEFAULT_BASELINE_REL})")
    parser.add_argument("--emit-baseline", action="store_true",
                        help="write the ledger from current counts and exit")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable payload on stdout")
    return parser.parse_args(argv)


def build_report(argv: list[str] | None = None) -> dict:
    """Evaluate every pass and return {"violations": [...], "exit": 0|1}."""
    args = _parse_args(argv)
    root = Path(args.root).resolve()
    baseline_path = (Path(args.baseline) if args.baseline
                     else root / DEFAULT_BASELINE_REL)
    counts, structural = scan_counts(root)
    violations = list(structural)
    debt = sum(counts.values())
    if args.emit_baseline:
        if violations:
            return {"violations": violations, "exit": 1,
                    "summary": "refused to emit: structural errors above"}
        emit_baseline(counts, baseline_path)
        return {"violations": [], "exit": 0,
                "summary": f"emitted {baseline_path} ({len(counts)} files scanned)"}
    if not baseline_path.is_file():
        if debt:
            violations.append({"kind": "no-baseline",
                               "file": baseline_path.as_posix(),
                               "detail": "debt present but no ledger at "
                                         f"{baseline_path}"})
    else:
        try:
            entries = load_baseline(baseline_path)
        except (yaml.YAMLError, OSError, ValueError) as exc:
            violations.append({"kind": "baseline-parse",
                               "file": baseline_path.as_posix(),
                               "detail": str(exc)})
        else:
            violations.extend(compare(counts, entries))
    exit_code = 1 if violations else 0
    clean = "clean" if not violations else f"{len(violations)} violation(s)"
    return {"violations": violations, "exit": exit_code,
            "summary": f"{clean}; {len(counts)} files scanned, "
                       f"{debt} silent handlers"}


def _print_report(payload: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for v in payload["violations"]:
        print(f"{v['kind']}: {v['file']}: {v['detail']}")
    print(f"silent-except: {payload['summary']}")


def main(argv: list[str] | None = None) -> int:
    payload = build_report(argv)
    _print_report(payload, "--json" in (argv or sys.argv[1:]))
    return payload["exit"]


if __name__ == "__main__":
    sys.exit(main())
