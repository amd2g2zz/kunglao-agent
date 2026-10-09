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

import ast
import sys
from pathlib import Path

import lint_protocol  # the shared scan/emit skeleton (repo sibling)

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
    for rel, path in lint_protocol.iter_py_files(root, SCAN_ROOTS, ALLOWLIST):
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
    return lint_protocol.load_int_baseline(path)


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
    lint_protocol.emit_ratchet_doc(files, path, BASELINE_SCHEMA,
                                   _LEDGER_UNIT, _LEDGER_POLICY)


# ------------------------------------------------------------ gate faces

_LEDGER_UNIT = ("per-file count of silent-swallow except handlers "
                "(no-op body, no raise, no trace call)")
_LEDGER_POLICY = (
    "ratchet only shrinks: a count above the ledger fails; an entry "
    "whose count reaches zero is deleted; a partially cleared entry "
    "is tightened in the same change; an entry whose file is gone "
    "is stale and fails; new debt without an entry fails")


def build_report(argv: list[str] | None = None) -> dict:
    """Evaluate every pass and return {"violations": [...], "exit": 0|1}."""
    return lint_protocol.ratchet_report(
        argv,
        description="Silent-swallow ratchet gate over scripts/ and hooks/.",
        default_root=str(REPO_ROOT),
        default_baseline_rel=DEFAULT_BASELINE_REL,
        scan=scan_counts,
        load_baseline=load_baseline,
        compare=compare,
        emit=emit_baseline,
        debt_of=lambda counts: sum(counts.values()),
        debt_noun="silent handlers")


def main(argv: list[str] | None = None) -> int:
    return lint_protocol.gate_main(argv, build_report, "silent-except")


if __name__ == "__main__":
    sys.exit(main())
