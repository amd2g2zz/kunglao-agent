#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subagent_review.py — Gate 5 (Subagent Review / Maker-Checker) (#462).

Issue evidence: the 3-element subagent contract (plan-to-execute /
state-sync / tool-discovery + no-self-invention) is enforced for
kunglao-worker but is missing from the FIVE specialist agents
(ghidra-light / go-symbols / floss-filter / pefile-signature /
verdict-scorer). Specialists are the long-running, high-blast-radius
agents — exactly the ones that need the contract.

Local-pre-commit mechanical enforcement:
  - if the staged change touches scripts/ / hooks/ / docs/ / tests/,
    there MUST be at least one .subagent-review/*.json in the working
    tree (uncommitted is fine — the review is in-flight evidence)
  - the JSON's required fields must all be present
  - the `verified_by` field must NOT be the orchestrator's own
    handle — that's the maker-checker anti-self-stamp rule

When the staged change does NOT touch domain paths (e.g. pure
pyproject / openspec / devkit scaffolding), Gate 5 is N/A — passes
trivially. This keeps the rule targeted: we only enforce it where
subagent delegation is the natural work shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Domain paths that warrant subagent review. Matched as a prefix on the
# changed-file path; one match → Gate 5 enforces, no match → Gate 5 N/A.
DOMAIN_PREFIXES = (
    "scripts/",
    "hooks/",
    "docs/",
    "tests/",
    "references/",
    "skills/",
)

# Required fields in .subagent-review/*.json
REQUIRED_FIELDS = (
    "agent",
    "plan",
    "status_sync",
    "tools_used",
    "verified_by",
)

# Forbidden values of verified_by — the orchestrator's own handle must
# not self-stamp. The full list lives in .claude/settings.json; this
# substring list catches the common cases without re-reading the file.
SELF_VERIFIERS = (
    "kunglao-agent",
    "main",
    "anthropic",
    "claude",
)


def _staged_files() -> list[str]:
    """Return the list of staged (cached) file paths relative to repo root."""
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
        capture_output=True, text=True, cwd=REPO_ROOT,
        errors="replace")
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _is_domain_path(path: str) -> bool:
    return any(path.startswith(p) or path == p.rstrip("/") for p in DOMAIN_PREFIXES)


def _review_files() -> list[Path]:
    """Return .subagent-review/*.json in the working tree (uncommitted fine)."""
    rev_dir = REPO_ROOT / ".subagent-review"
    if not rev_dir.is_dir():
        return []
    return sorted(rev_dir.glob("*.json"))


def _validate_one(path: Path) -> tuple[bool, str]:
    """Return (ok, message). ok=False if a required field is missing,
    JSON is malformed, or verified_by self-stamps."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"  {path.name}: JSON parse error: {exc}"
    if not isinstance(data, dict):
        return False, f"  {path.name}: top-level is not a dict"
    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
    if missing:
        return False, f"  {path.name}: missing fields {missing}"
    vb = str(data.get("verified_by", "")).lower()
    if any(s in vb for s in SELF_VERIFIERS):
        return False, (
            f"  {path.name}: verified_by={data['verified_by']!r} "
            f"looks like self-stamp (must be an INDEPENDENT verifier)")
    if not data.get("tools_used"):
        # tools_used is required; #462 evidence 3 — self-invention is the
        # biggest regression vector. Empty list is a soft fail.
        return False, f"  {path.name}: tools_used is empty (no reuse record)"
    return True, ""


def check() -> int:
    staged = _staged_files()
    domain_touched = [p for p in staged if _is_domain_path(p)]
    if not domain_touched:
        # Gate 5 N/A: no domain paths changed → pass trivially.
        print("[PASS] Gate 5 (no domain paths staged; subagent review N/A)")
        return 0

    reviews = _review_files()
    if not reviews:
        print("HARD_PAUSE Gate 5: domain paths staged, no .subagent-review/*.json found")
        print("  Touched:")
        for p in domain_touched:
            print(f"    {p}")
        print("  Required: at least one .subagent-review/<id>.json in the working tree")
        print("  with fields: agent / plan / status_sync / tools_used / verified_by")
        print("  Schema: see devkit/docs/subagent-review.md")
        return 2

    failures: list[str] = []
    for r in reviews:
        ok, msg = _validate_one(r)
        if not ok:
            failures.append(msg)

    if failures:
        print(f"HARD_PAUSE Gate 5: {len(failures)} review(s) failed validation:")
        for f in failures:
            print(f)
        print("  Schema: see devkit/docs/subagent-review.md")
        return 2

    print(f"[PASS] Gate 5 ({len(reviews)} review file(s) valid)")
    return 0


def main(argv: list[str] | None = None) -> int:
    return check()


if __name__ == "__main__":
    sys.exit(main())