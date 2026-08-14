# -*- coding: utf-8 -*-
"""reuse_gate.py - enforce reuse-before-recompute on every dispatch.

User pain point (verbatim, in Chinese): "考虑工作积累喜欢做一些一次性工作但是对后面分析没有太大帮助和复用性"
("for accumulating work: it likes one-off work that neither helps later
analysis nor is reusable")

Before dispatching a claim, this gate scans facts/ for related evidence
(keyword match on claim statement + statement_keywords) and emits a list of
candidate fact IDs. Worker MUST cite at least one candidate OR explicitly
justify why fresh work is needed (no relevant existing fact).

Usage:
  python reuse_gate.py <workspace> <claim_id>
Exit codes:
  0 = claim has candidates OR no candidates exist (no constraint)
  1 = candidates exist but worker has not cited or justified
  2 = worker justified fresh work AND orchestrator accepted
"""
from __future__ import annotations
import gate_telemetry as _gt
import hook_activation as ha


import argparse
import re
import sys
from pathlib import Path

import yaml

JUSTIFY_MARKER = "## justify_fresh_work"
CITE_MARKER = "## reused_facts"
MIN_OVERLAP = 2


def _load_yaml(p):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def get_claim(workspace: Path, claim_id: str) -> dict | None:
    reg = _load_yaml(workspace / "claim-register.yaml")
    for c in (reg or {}).get("claims", []) or []:
        if c.get("id") == claim_id:
            return c
    return None


def extract_keywords(text: str) -> set:
    return set(re.findall(r"\w{3,}", (text or "").lower()))


def find_candidate_facts(workspace: Path, claim: dict) -> list:
    """Find facts/ files with overlapping keywords (>= MIN_OVERLAP)."""
    facts_dir = workspace / "facts"
    if not facts_dir.exists():
        return []
    claim_kw = extract_keywords(claim.get("statement", "") + " " +
                                " ".join(claim.get("statement_keywords", []) or []))
    if not claim_kw:
        return []
    out = []
    for p in facts_dir.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        overlap = extract_keywords(text) & claim_kw
        if len(overlap) >= MIN_OVERLAP:
            out.append({"file": p.name, "overlap_count": len(overlap),
                        "overlap_sample": sorted(overlap)[:5]})
    out.sort(key=lambda x: x["overlap_count"], reverse=True)
    return out[:5]


@_gt.telemetry('reuse_gate')
def check(workspace: Path, claim_id: str, status_file: Path | None = None) -> int:
    claim = get_claim(workspace, claim_id)
    if claim is None:
        print(f"NOOP: claim {claim_id} not found in claim-register.yaml")
        return 0

    candidates = find_candidate_facts(workspace, claim)
    if not candidates:
        print(f"OK: no existing facts relevant to {claim_id} (no candidates above threshold {MIN_OVERLAP})")
        return 0

    if status_file is None or not status_file.exists():
        print(f"REJECT: {len(candidates)} candidate fact(s) exist for {claim_id}; worker must cite or justify")
        for c in candidates:
            print(f"  - {c['file']} (overlap={c['overlap_count']}, sample={c['overlap_sample']})")
        print(f"  Worker must add one of:")
        print(f"    ## reused_facts  # list fact IDs + 1-line reason each")
        print(f"    ## justify_fresh_work  # 1-line why existing facts don't apply")
        return 1

    text = status_file.read_text(encoding="utf-8", errors="replace")
    has_cite = CITE_MARKER in text
    has_justify = JUSTIFY_MARKER in text

    if has_cite:
        m = re.search(r"## reused_facts\s*(.+?)(?:\n## |\Z)", text, re.DOTALL)
        cited = m.group(1).strip() if m else ""
        print(f"OK: {claim_id} cites reused_facts: {cited[:80]}")
        return 0

    if has_justify:
        m = re.search(r"## justify_fresh_work\s*(.+?)(?:\n## |\Z)", text, re.DOTALL)
        reason = m.group(1).strip() if m else ""
        print(f"OK: {claim_id} justifies fresh work: {reason[:80]}")
        return 0

    print(f"REJECT: {len(candidates)} candidate fact(s) exist for {claim_id}; worker has not cited or justified")
    for c in candidates:
        print(f"  - {c['file']} (overlap={c['overlap_count']}, sample={c['overlap_sample']})")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Reuse gate - reuse existing facts before recompute")

    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("claim_id", help="claim being dispatched")
    parser.add_argument("--status-file", type=str, default=None,
                        help="worker-status file to check for cite/justify sections")
    args = parser.parse_args()

    # F-10 selective activation: skip if hook is paused
    if not ha.is_active(Path(args.workspace), "reuse_gate"):
        print("SKIP: reuse_gate is paused (check .hook_state.json)")
        return 0
    sf = Path(args.status_file) if args.status_file else None
    return check(Path(args.workspace), args.claim_id, status_file=sf)


if __name__ == "__main__":
    sys.exit(main())