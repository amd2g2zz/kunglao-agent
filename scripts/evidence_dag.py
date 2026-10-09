#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence_dag.py — the evidence DAG view (artifact -> fact -> claim ->
question), projected from ledgers that already exist.

Layers and their sources (a read-only view — no new truth, no writes):
  artifacts   evidence/_index.json entries (eid, path, type,
              source_reliability)
  facts       facts/*.md frontmatter: the fact's provenance[] refs give the
              artifact edges (eid or path resolved through the index); its
              claim refs give the claim edges
  claims      claim-register.yaml rows: status + answers_question
  questions   task_spec.yaml primary_questions

The red-team face (and any human) currently rebuilds this chain by hand;
the view renders it mechanically and checks its one invariant: every fact
node reachable FROM its artifacts and TO its claim (and through it to a
question). A fact with no artifact edge, or no claim edge, is reported —
the chain is only as strong as its weakest link.

Usage:
  python scripts/evidence_dag.py <workspace> [--json] [--check]
Exit codes: 0 ok / 2 usage or unreadable workspace / 3 --check violations.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def _load_index(ws: Path) -> dict[str, dict]:
    """eid -> index entry (absent index is a cold-start face; a corrupt one
    leaves one canonical trace and degrades to {})."""
    rel = ws / "evidence" / "_index.json"
    if not rel.is_file():
        return {}
    try:
        doc = json.loads(rel.read_text(encoding="utf-8"))
    except FileNotFoundError:
        doc = {}
    except (OSError, ValueError) as exc:
        from kunglao_log import warn
        warn("evidence_dag", f"evidence index unreadable: {exc}")
        doc = {}
    out: dict[str, dict] = {}
    for e in (doc.get("entries") or []):
        if isinstance(e, dict) and e.get("eid"):
            out[str(e["eid"])] = e
    return out


def _index_by_path(index: dict[str, dict]) -> dict[str, str]:
    return {str(e.get("path")): eid for eid, e in index.items()
            if e.get("path")}


def _fact_provenance_refs(body_or_fm) -> list[dict]:
    """The fact's provenance refs (eid/path shapes) — provenance_gate owns
    the block dialect; degrade to [] when absent or unreadable."""
    try:
        from provenance_gate import extract_provenance_refs
    except ImportError:
        return []
    if isinstance(body_or_fm, str):
        return extract_provenance_refs(body_or_fm)
    prov = body_or_fm.get("provenance")
    return prov if isinstance(prov, list) else []


def _build_facts(ws: Path, index: dict[str, dict],
                 by_path: dict[str, str]) -> dict[str, dict]:
    """facts/*.md -> {status, artifacts, claims} (a broken fact renders
    skipped — the view never fabricates nodes)."""
    facts: dict[str, dict] = {}
    try:
        from lint_facts import _load_fact
        from register_proven_gate import _fact_claim_refs
    except ImportError:
        return facts
    facts_dir = ws / "facts"
    if not facts_dir.is_dir():
        return facts
    for p in sorted(facts_dir.glob("*.md")):
        if p.name.startswith("_"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            fm = _load_fact(p)
        except Exception:  # noqa: BLE001 — a broken fact renders skipped
            continue
        if not isinstance(fm, dict):
            continue
        fid = str(fm.get("id") or p.stem)
        eids: list[str] = []
        for ref in _fact_provenance_refs(fm) or \
                _fact_provenance_refs(text):
            eid = ref.get("eid")
            if eid and eid in index:
                eids.append(str(eid))
            elif ref.get("path") and str(ref["path"]) in by_path:
                eids.append(by_path[str(ref["path"])])
        facts[fid] = {"status": str(fm.get("status") or ""),
                      "artifacts": sorted(set(eids)),
                      "claims": sorted(set(_fact_claim_refs(fm)))}
    return facts


def _build_claims(ws: Path, facts: dict[str, dict]) -> dict[str, dict]:
    """claim-register rows -> {status, question, facts} (cold start silent;
    a corrupt register leaves one canonical trace)."""
    claims: dict[str, dict] = {}
    reg_path = ws / "claim-register.yaml"
    if not reg_path.is_file():
        return claims
    try:
        reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
        for c in (reg.get("claims") or []):
            if isinstance(c, dict) and c.get("id"):
                cid = str(c["id"])
                citing = sorted(f for f, d in facts.items()
                                if cid in d["claims"])
                claims[cid] = {
                    "status": str(c.get("status") or ""),
                    "question": (str(c["answers_question"])
                                 if c.get("answers_question") else None),
                    "facts": citing,
                }
    except (OSError, yaml.YAMLError) as exc:
        from kunglao_log import warn
        warn("evidence_dag", f"claim register unreadable: {exc}")
    return claims


def _build_questions(ws: Path, claims: dict[str, dict]) -> dict[str, dict]:
    """task_spec primary_questions -> {question, claims} (same posture)."""
    questions: dict[str, dict] = {}
    spec_path = ws / "task_spec.yaml"
    if not spec_path.is_file():
        return questions
    try:
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
        for q in (spec.get("primary_questions") or []):
            if isinstance(q, dict) and q.get("id"):
                qid = str(q["id"])
                questions[qid] = {
                    "question": str(q.get("question") or ""),
                    "claims": sorted(c for c, d in claims.items()
                                     if d["question"] == qid),
                }
    except (OSError, yaml.YAMLError) as exc:
        from kunglao_log import warn
        warn("evidence_dag", f"task spec unreadable: {exc}")
    return questions


def build(ws) -> dict:
    """The DAG view over one workspace (tolerant: a missing layer renders
    empty — the view never fabricates nodes)."""
    ws = Path(ws)
    index = _load_index(ws)
    facts = _build_facts(ws, index, _index_by_path(index))
    claims = _build_claims(ws, facts)
    questions = _build_questions(ws, claims)
    return {"artifacts": index, "facts": facts, "claims": claims,
            "questions": questions}


def unreachable(dag: dict) -> list[str]:
    """The one invariant, as violations: every fact reachable from its
    artifacts and to its claim/question."""
    out: list[str] = []
    for fid, d in sorted((dag.get("facts") or {}).items()):
        if not d.get("artifacts"):
            out.append(f"{fid}: no artifact edge (provenance resolves to no "
                       "indexed evidence)")
        if not d.get("claims"):
            out.append(f"{fid}: no claim edge (cites no register claim)")
    return out


def render_text(dag: dict) -> str:
    """The human face: the four layers with their edges."""
    lines = ["# evidence DAG (artifact -> fact -> claim -> question)", ""]
    lines.append(f"artifacts ({len(dag.get('artifacts') or {})}):")
    for eid, e in sorted((dag.get("artifacts") or {}).items()):
        lines.append(f"  {eid}  {e.get('path')}  [{e.get('type')}|"
                     f"{e.get('source_reliability')}]")
    lines.append(f"facts ({len(dag.get('facts') or {})}):")
    for fid, d in sorted((dag.get("facts") or {}).items()):
        lines.append(f"  {fid} [{d['status']}] <- "
                     f"{', '.join(d['artifacts']) or '(none)'} -> "
                     f"{', '.join(d['claims']) or '(none)'}")
    lines.append(f"claims ({len(dag.get('claims') or {})}):")
    for cid, d in sorted((dag.get("claims") or {}).items()):
        lines.append(f"  {cid} [{d['status']}] <- "
                     f"{', '.join(d['facts']) or '(none)'} -> "
                     f"{d['question'] or '(no question)'}")
    lines.append(f"questions ({len(dag.get('questions') or {})}):")
    for qid, d in sorted((dag.get("questions") or {}).items()):
        lines.append(f"  {qid}  {d['question']}  <- "
                     f"{', '.join(d['claims']) or '(none)'}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="render the evidence DAG view for one workspace")
    ap.add_argument("workspace")
    ap.add_argument("--json", action="store_true",
                    help="machine face (default: human text)")
    ap.add_argument("--check", action="store_true",
                    help="report unreachable fact nodes (rc 3 on violations)")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not ws.is_dir():
        print(f"no such workspace: {ws}", file=sys.stderr)
        return 2
    dag = build(ws)
    if args.json:
        print(json.dumps(dag, ensure_ascii=False, indent=2))
    else:
        print(render_text(dag), end="")
    if args.check:
        bad = unreachable(dag)
        for b in bad:
            print(f"DAG: {b}", file=sys.stderr)
        return 3 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
