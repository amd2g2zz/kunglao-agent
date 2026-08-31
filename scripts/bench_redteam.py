#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_redteam.py — L2 arm-blind red-team pipeline (B6, #823 AB-VALUE).

Only DIVERGENT items get reviewed (never a full re-judge): a PQ is
divergent when the mechanical L1 result disagrees with what the run
CLAIMED as evidence-backed. Briefs are arm-blind and sample-blind —
the reviewer sees opaque_id + PQ text + the extracted answer, nothing
that reveals which arm ran or which sample it was. Verdicts merge back
as overrides on the L1 result (L2 wins: it attacks raw evidence).

The real reviewer is the kunglao-redteam agent, dispatched by the
experiment operator; dispatch_stub() stands in for tests/dry-runs.

Usage: bench_redteam.py --brief <f> --verdicts-out <f>   (operator loop)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def divergent_items(l1: dict, claimed: dict[str, bool]) -> list[str]:
    """PQ ids where L1's mechanical verdict != the run's evidence claim.
    Sortable + stable, so briefs are reproducible."""
    per_pq = l1.get("per_pq") or {}
    return sorted(pid for pid, claim in (claimed or {}).items()
                  if pid in per_pq and bool(per_pq[pid]) != bool(claim))


def build_task_brief(opaque_id: str, pq_ids: list[str],
                     questions: dict[str, str],
                     answers: dict) -> dict:
    """Arm-blind, sample-blind review packet. No field carries the arm,
    the sample id, or any provenance — only opaque_id + PQ text."""
    return {
        "opaque_id": opaque_id,
        "instruction": ("Attack-test each answer against the run's raw "
                        "evidence. CONFIRM only if you independently "
                        "derive the same answer; REFUTE otherwise."),
        "pqs": [{"pq_id": pid,
                 "question": questions.get(pid, ""),
                 "answer": answers.get(pid)} for pid in pq_ids],
    }


def dispatch_stub(brief: dict) -> dict[str, bool]:
    """Dry-run reviewer: confirms every briefed PQ. Real dispatches
    replace this with the kunglao-redteam agent's verdicts."""
    return {pq["pq_id"]: True for pq in brief.get("pqs", [])}


def merge_verdicts(l1: dict, l2: dict[str, bool]) -> dict:
    """L2 overrides L1 per PQ; success/partial recomputed from the merged
    per-PQ view. Every override is recorded."""
    per_pq = dict(l1.get("per_pq") or {})
    overrides = {pid: bool(v) for pid, v in (l2 or {}).items()
                 if pid in per_pq and per_pq[pid] != bool(v)}
    per_pq.update({pid: bool(v) for pid, v in (l2 or {}).items()
                   if pid in per_pq})
    n = len(per_pq) or 1
    matched = sum(1 for ok in per_pq.values() if ok)
    return {"per_pq": per_pq,
            "success": bool(per_pq) and all(per_pq.values()),
            "partial_score": round(matched / n, 4),
            "outcome": l1.get("outcome", "done"),
            "l2_overrides": overrides}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_redteam.py",
                                 description="L2 arm-blind red-team pipeline")
    ap.add_argument("--brief", required=True, help="brief JSON path")
    ap.add_argument("--verdicts-out", required=True,
                    help="where the reviewer's {pq_id: bool} JSON lands")
    ap.add_argument("--stub", action="store_true",
                    help="use dispatch_stub instead of a real reviewer")
    args = ap.parse_args(argv)
    brief = json.loads(Path(args.brief).read_text(encoding="utf-8"))
    verdicts = dispatch_stub(brief) if args.stub else {}
    out = Path(args.verdicts_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdicts, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"{len(verdicts)} verdict(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
