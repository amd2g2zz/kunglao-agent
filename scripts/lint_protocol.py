#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_protocol.py — the shared scan/emit skeleton of the ledger lint trio.

comment_hygiene_lint, silent_except_lint and formal_code_lint are one
gate shape: walk the scan roots for python files, count per-file
findings, apply the shrink-only baseline ratchet over a YAML ledger, and
emit or compare that ledger on demand. This module holds ONLY the
boilerplate the gates shared verbatim; each lint keeps its detector (the
counting rule), its ledger literals (schema/unit/policy texts) and any
gate-specific extra pass. Every user-visible string arrives from the
caller, so each gate's output text and exit codes stay byte-identical.

stdlib + pyyaml. A repo-face module (the lints import repo siblings),
NOT a _common.py resident — the leaf stays numpy+stdlib-only.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

import yaml


# ------------------------------------------------------------- file walk
def iter_py_files(root: Path, scan_roots: tuple[str, ...],
                  allowlist: frozenset[str] = frozenset()
                  ) -> list[tuple[str, Path]]:
    """(rel_posix, path) for every .py under the scan roots, sorted,
    minus the allowlist (generated files are exempt by list, never by
    ledger entry)."""
    out: list[tuple[str, Path]] = []
    for rel_dir in scan_roots:
        base = root / rel_dir
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in allowlist:
                continue
            out.append((rel, path))
    return out


# ------------------------------------------------------- baseline ratchet
def load_int_baseline(path: Path) -> dict[str, int]:
    """Parse the ledger file into {rel_path: count} (the int-count
    variant used by the silent-except and formal-code gates)."""
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    files = doc.get("files") or {}
    return {str(rel): int(count) for rel, count in files.items()}


def emit_ratchet_doc(files: dict, path: Path, schema: str, unit: str,
                     policy: str) -> None:
    """Write the ledger doc (schema/unit/policy/files, in that key
    order) from the caller's debt-only files mapping."""
    doc = {
        "schema": schema,
        "unit": unit,
        "policy": policy,
        "files": files,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True),
        encoding="utf-8")


# ------------------------------------------------------------ gate faces
def parse_gate_args(argv: list[str] | None, description: str,
                    default_root: str,
                    default_baseline_rel: str) -> argparse.Namespace:
    """The gate CLI: --root / --baseline / --emit-baseline / --json."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--root", default=default_root,
                        help="repository root to scan (default: this repo)")
    parser.add_argument(
        "--baseline", default=None,
        help=f"ledger path (default: <root>/{default_baseline_rel})")
    parser.add_argument("--emit-baseline", action="store_true",
                        help="write the ledger from current counts and exit")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable payload on stdout")
    return parser.parse_args(argv)


def ratchet_report(argv: list[str] | None, *, description: str,
                   default_root: str, default_baseline_rel: str,
                   scan: Callable[[Path], tuple[dict, list[dict]]],
                   load_baseline: Callable[[Path], dict],
                   compare: Callable[[dict, dict], list[dict]],
                   emit: Callable[[dict, Path], None],
                   debt_of: Callable[[dict], int], debt_noun: str,
                   extra_violations: Callable[[Path],
                                              list[dict]] | None = None
                   ) -> dict:
    """The shared gate flow: scan, emit-or-compare the ledger, then the
    gate-specific pass (mapping/frontmatter for the hygiene gate, none
    for the silent-except gate). Returns the payload dict both gates
    printed before the extraction."""
    args = parse_gate_args(argv, description, default_root,
                           default_baseline_rel)
    root = Path(args.root).resolve()
    baseline_path = (Path(args.baseline) if args.baseline
                     else root / default_baseline_rel)
    counts, structural = scan(root)
    violations = list(structural)
    debt = debt_of(counts)
    if args.emit_baseline:
        if violations:
            return {"violations": violations, "exit": 1,
                    "summary": "refused to emit: structural errors above"}
        emit(counts, baseline_path)
        return {"violations": [], "exit": 0,
                "summary": f"emitted {baseline_path} "
                           f"({len(counts)} files scanned)"}
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
    if extra_violations is not None:
        violations.extend(extra_violations(root))
    exit_code = 1 if violations else 0
    clean = "clean" if not violations else f"{len(violations)} violation(s)"
    return {"violations": violations, "exit": exit_code,
            "summary": f"{clean}; {len(counts)} files scanned, "
                       f"{debt} {debt_noun}"}


def print_report(payload: dict, as_json: bool, gate_name: str) -> None:
    """The shared stdout face: violation lines then the prefixed
    summary, or the sorted JSON payload."""
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for v in payload["violations"]:
        print(f"{v['kind']}: {v['file']}: {v['detail']}")
    print(f"{gate_name}: {payload['summary']}")


def gate_main(argv: list[str] | None, build: Callable[..., dict],
              gate_name: str) -> int:
    """The shared entry: build the payload, print it, return its exit."""
    payload = build(argv)
    print_report(payload, "--json" in (argv or sys.argv[1:]), gate_name)
    return payload["exit"]
