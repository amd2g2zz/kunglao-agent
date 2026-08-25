#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hypothesis_seeder.py — mechanical PQ scaffold seeder (#662).

Issue #662: the hypothesis layer (#528) has storage + rehydrate but no
input side — nothing seeds hypotheses from task_spec, so the layer starts
empty and stays empty unless the orchestrator LLM remembers to fill it.
This seeder closes that gap mechanically: at every cold-start digest
build (and on direct CLI invocation), every task_spec.primary_questions[]
entry gets an open scaffold hypothesis whose body carries the `pq:<qid>`
marker. Scaffolds invent NO analysis content (candidates=[] per #412).

Spec: openspec/changes/issue-662-hypothesis-seed/{proposal,design,specs}.
Design references D1-D8. Fail-open per D7.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

# Canonical PQ parse — same schema rules as convergence_check (issue #77);
# a malformed schema is convergence's INVALID problem, not ours (D7).
from convergence_check import _parse_primary_questions
from hypothesis_store import Hypothesis, HypothesisStore

MARKER_FMT = "pq:{qid}"
PLACEHOLDER_CLAIM = "C-PENDING"


def _load_task_spec(ws: Path) -> dict:
    p = Path(ws) / "task_spec.yaml"
    if not p.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _next_free_id(store: HypothesisStore) -> str:
    used = set()
    for h in store.list_all():
        num = "".join(ch for ch in h.id if ch.isdigit())
        if num:
            used.add(int(num))
    n = 1
    while n in used:
        n += 1
    return f"H-{n:03d}"


def _scaffold_body(qid: str, need: str | None) -> str:
    need_line = f" (need: {need})" if need else ""
    return (
        f"{MARKER_FMT.format(qid=qid)}\n\n"
        f"Seeded from primary_question {qid}{need_line}. Scaffold only —\n"
        "the orchestrator fills `candidates` with competing explanations\n"
        "BEFORE dispatching the first C-NN for this question. Adjudicate by\n"
        "refute (refuting_fact_id) or supersede (superseded_by) per #528.\n"
    )


def seed_from_task_spec(ws: Path) -> List[dict]:
    """Ensure every task_spec primary_question has a hypothesis scaffold.

    Idempotency: a question is already covered when ANY hypothesis (any
    status — adjudicated scaffolds must not resurrect, per #528's
    decided-hypotheses-stay-decided rule) carries the `pq:<qid>` body
    marker. The marker lives in the body because HypothesisStore._write
    drops unknown frontmatter keys on rewrite (design D2).

    Returns the list of created scaffolds: [{"hyp_id", "qid"}, ...].
    Fail-open: missing/malformed task_spec -> [] (never raises).
    """
    ws = Path(ws)
    task_spec = _load_task_spec(ws)
    questions, _err = _parse_primary_questions(task_spec)
    if not questions:
        return []

    store = HypothesisStore(ws / "hypotheses")
    existing = store.list_all()  # any status (see docstring)
    covered = set()
    for h in existing:
        for qid, _need in questions:
            if MARKER_FMT.format(qid=qid) in h.body:
                covered.add(qid)

    created: List[dict] = []
    for qid, need in questions:
        if qid in covered:
            continue
        hyp = Hypothesis(
            id=_next_free_id(store),
            claim_id=PLACEHOLDER_CLAIM,
            competitor_group=f"pq-{qid}",
            candidates=[],
            status="open",
            body=_scaffold_body(qid, need),
        )
        hyp.path = ws / "hypotheses" / f"{hyp.id}.md"
        store._write(hyp)  # store has no public create; _write is the writer
        created.append({"hyp_id": hyp.id, "qid": qid})
        _emit(ws, hyp.id, qid)
    return created


def _emit(ws: Path, hyp_id: str, qid: str) -> None:
    """kunglao_log observability (design D6) — guarded, never raises."""
    try:
        from kunglao_log import emit
        emit(ws, actor="hypothesis_seeder", action="hypothesis_seed",
             detail=f"{hyp_id} pq:{qid}")
    except Exception:  # noqa: BLE001 — logging must never break seeding
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="hypothesis_seeder — seed PQ scaffolds into hypotheses/")
    parser.add_argument("workspace", type=Path, help="workspace root")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)
    created = seed_from_task_spec(args.workspace)
    if args.json:
        print(json.dumps({"created": created, "count": len(created)},
                         ensure_ascii=False, indent=2))
    elif created:
        for c in created:
            print(f"SEEDED: {c['hyp_id']} pq:{c['qid']}")
    else:
        print("OK: nothing to seed (idempotent or no primary_questions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
