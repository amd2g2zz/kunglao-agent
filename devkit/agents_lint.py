#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agents_lint.py — Gate 6 (Agents Contract) definition-layer lint (#492).

Split from #462. Gate 5 (devkit/subagent_review.py) enforces the 3-element
subagent contract at EXECUTION time (.subagent-review/*.json shape). This
lint enforces it at DEFINITION time on agents/*.md. #462 evidence 2: the
specialist agent files carried 0 of the contract entries kunglao-worker
carries (12 plan + 6 status + 2 tool-reuse) — specialists are the
long-running, high-blast-radius roles that need it most.

Channel choice (user doctrine: structured declaration over prose regex —
enumerating natural-language clauses in any language is unfinishable):
each agent file declares its contract sections with STRUCTURAL markers,
an HTML-comment grammar that is finite and mechanically parseable:

    <!-- contract: plan-to-execute -->   (a) plan before execution
    <!-- contract: status-sync -->       (b) status/artifact file writes
    <!-- contract: tool-discovery -->    (c) tool reuse + no self-invention

The prose under a marker stays free-form (any language). The lint only
checks the marker grammar and that each marked section carries substance:
>= MIN_CONTENT_LINES non-empty lines between the marker and the next
contract marker (or EOF), counted AFTER stripping complete HTML-comment
spans (`<!-- ... -->`) — comment-only filler lines do not count as
substance (fault-inject 9b: two `<!-- -->` lines per marker used to
inflate the count past the hollow floor). A bare marker or a one-line
stub is a hollow declaration — declared != done, same spirit as Gate 5's
anti-self-stamp.

Rules (design.md D2):
  - every occurrence of a marker must be non-hollow (a trailing bare
    duplicate does not ride along on a real section)
  - markers inside fenced code blocks (``` / ~~~) are ignored — a doc
    quoting the grammar must not create phantom markers; an unclosed
    fence swallows the rest of the file (fail-safe: miss, don't misfire)
  - unknown contract elements are ignored (forward-compatible)
  - fail-closed: agents/ missing, zero *.md, unreadable file — all
    violations (rc=1). rc=0 only when every agent file declares all
    three elements with substance.

Usage:
  uv run python devkit/agents_lint.py                # human-readable
  uv run python devkit/agents_lint.py --json         # machine-readable
  uv run python devkit/agents_lint.py --agents-dir <path>

Exit codes: 0 = pass; 1 = violations found; 2 = usage error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The 3-element subagent contract (#462 / #492). Single point of truth —
# #494 extends content under markers, new elements extend this tuple.
CONTRACT_ELEMENTS = ("plan-to-execute", "status-sync", "tool-discovery")

# Minimum non-empty lines between a marker and the next marker / EOF.
# 2 lines: a one-line stub is a declaration without substance.
MIN_CONTENT_LINES = 2

_MARKER_RE = re.compile(
    r"^\s*<!--\s*contract:\s*(" + "|".join(re.escape(e) for e in CONTRACT_ELEMENTS)
    + r")\s*-->\s*$"
)

_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Complete single-line HTML-comment spans. Stripped before the content
# count so `<!-- -->` / `<!-- filler -->` lines cannot fake substance
# (fault-inject 9b hollow-marker bypass). Cross-line comment
# opener/closer fragments have no complete span on their line and are
# left alone (KISS: the proven attack used single-line comments).
_COMMENT_RE = re.compile(r"<!--.*?-->")

RC_PASS = 0
RC_FAIL = 1


def _marker_spans(lines: list[str]) -> list[tuple[int, str]]:
    """Return [(line_index, element)] for every contract marker line,
    skipping fenced code blocks (markers quoted in docs are prose, not
    declarations)."""
    spans: list[tuple[int, str]] = []
    fenced = False
    for i, line in enumerate(lines):
        if _FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        m = _MARKER_RE.match(line)
        if m:
            spans.append((i, m.group(1)))
    return spans


def lint_text(text: str) -> list[dict]:
    """Return violation dicts for one agent file's text (pure function).

    Violation shape: {"element": str, "problem": str}. An element with no
    marker yields one "missing" violation; each hollow marker occurrence
    yields one "non-empty content" violation.
    """
    violations: list[dict] = []
    lines = text.splitlines()
    markers = _marker_spans(lines)
    marker_lines = [i for i, _ in markers]

    for element in CONTRACT_ELEMENTS:
        occurrences = [i for i, e in markers if e == element]
        if not occurrences:
            violations.append({
                "element": element,
                "problem": f"missing <!-- contract: {element} --> marker",
            })
            continue
        for start in occurrences:
            later = [i for i in marker_lines if i > start]
            end = min(later) if later else len(lines)
            content = [ln for ln in lines[start + 1:end]
                       if _COMMENT_RE.sub("", ln).strip()]
            if len(content) < MIN_CONTENT_LINES:
                violations.append({
                    "element": element,
                    "problem": (
                        f"<!-- contract: {element} --> at line {start + 1} "
                        f"has only {len(content)} non-empty content line(s) "
                        f"(need >= {MIN_CONTENT_LINES}; HTML comments "
                        f"stripped before counting) — hollow declaration"
                    ),
                })
    return violations


def lint_dir(agents_dir: Path) -> dict:
    """Lint every agents/*.md. Returns a report dict; never raises for a
    missing/empty dir — that IS a violation (fail-closed)."""
    report: dict = {
        "agents_dir": str(agents_dir),
        "agents": [],
        "violations": [],
    }
    if not agents_dir.is_dir():
        report["violations"].append({
            "file": "<agents-dir>", "element": "-",
            "problem": f"agents directory not found: {agents_dir}",
        })
        report["ok"] = False
        return report
    md_files = sorted(agents_dir.glob("*.md"))
    if not md_files:
        report["violations"].append({
            "file": "<agents-dir>", "element": "-",
            "problem": f"no *.md files under {agents_dir} (nothing to guard)",
        })
        report["ok"] = False
        return report
    for path in md_files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report["agents"].append(
                {"file": path.name, "ok": False, "elements": {}})
            report["violations"].append({
                "file": path.name, "element": "-",
                "problem": f"unreadable: {exc}"})
            continue
        violations = lint_text(text)
        markers = _marker_spans(text.splitlines())
        elements = {
            e: {"present": any(el == e for _, el in markers)}
            for e in CONTRACT_ELEMENTS
        }
        report["agents"].append({
            "file": path.name,
            "ok": not violations,
            "elements": elements,
        })
        for v in violations:
            report["violations"].append({"file": path.name, **v})
    report["ok"] = not report["violations"]
    return report


def check(agents_dir: Path | None = None, as_json: bool = False) -> int:
    """Run the lint, print the report, return the exit code."""
    target = agents_dir if agents_dir is not None else REPO_ROOT / "agents"
    report = lint_dir(target)

    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return RC_PASS if report["ok"] else RC_FAIL

    if report["ok"]:
        print(f"[PASS] Gate 6 agents contract: {len(report['agents'])} "
              f"agent file(s), all 3 markers with substance, 0 violations")
        return RC_PASS

    print(f"HARD_PAUSE Gate 6: {len(report['violations'])} agents-contract "
          f"violation(s) in {target}:")
    for v in report["violations"]:
        print(f"  {v['file']}: [{v['element']}] {v['problem']}")
    print("  Required markers (each followed by >= "
          f"{MIN_CONTENT_LINES} non-empty lines, HTML comments do "
          "not count):")
    for e in CONTRACT_ELEMENTS:
        print(f"    <!-- contract: {e} -->")
    print("  Schema: devkit/agents_lint.py docstring + "
          "openspec/changes/issue-492-agents-lint/design.md")
    return RC_FAIL


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Gate 6 agents-contract lint (#492): structural "
                    "3-element declaration check on agents/*.md")
    p.add_argument("--json", action="store_true",
                   help="machine-readable JSON report on stdout")
    p.add_argument("--agents-dir", type=Path, default=None,
                   help="override the agents/ directory (default: <repo>/agents)")
    args = p.parse_args(argv)
    return check(agents_dir=args.agents_dir, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
