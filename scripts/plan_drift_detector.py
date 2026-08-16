# -*- coding: utf-8 -*-
"""plan_drift_detector.py - detect when plan files lag behind reality.

User pain point (verbatim, in Chinese): "实际进度状态和计划与文件里面的不匹配 - 比如开始规划的时候
有15个任务，但是随着推进出现重新规划 任务分解 任务废弃，相关文件没跟上"
("actual progress state and the plan disagree with the files — e.g. 15 tasks
at planning time, but re-planning/decomposition/obsolescence as work
progressed while the files never caught up")

6 drift types detected:
  1. ORPHAN_CLAIM: claim in claim-register.yaml but NOT in global_plan.txt
     (mid-iteration discovery not logged in plan)
  2. STALE_PLAN_ENTRY: global_plan.txt lists claim that no longer exists
     in claim-register.yaml (abandoned/decomposed, not removed)
  3. MISSING_DEP_LINK: claim has parent_claim but claim_deps.yaml doesn't
     link it (decomposition not reflected in DAG)
  4. UNANSWERED_QUESTION: primary_question in task_spec has no PROVEN
     claim answering it (plan assumes answer that won't come)
  5. STALE_NEXT_STEP: global_plan.txt "next steps" section references
     claim with terminal status (plan still thinks claim is OPEN)
  6. UNVERIFIED_EVIDENCE (#241): claim is status: PROVEN but has no
     runs/verify-redteam-*.md reality check, or its supporting fact
     (facts/F*.md with claim_id frontmatter) carries a low confidence
     tier — the first 5 classes are all "file A vs file B" consistency;
     this one asks whether the STATE FILE itself is wrong (files agree
     but reality was never verified)

Usage:
  python plan_drift_detector.py <workspace> [--apply]
Exit codes:
  0 = no drift
  1 = drift detected (B1o blocker)
  2 = HARD_PAUSE: 3+ drift warnings in same session
"""
from __future__ import annotations
import gate_telemetry as _gt
from status_defs import TERMINAL

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

TERMINAL_STATUSES = TERMINAL  # #34: single source of truth (was a 6-value literal here)

# #241: a PROVEN claim is only as good as its reality check. Confidence tiers
# below even odds (ICD-203 7-tier ladder, scripts/confidence_schema.py) mean
# the fact is not reality-verified evidence; "suspected" is the legacy name
# mapping to roughly_even. literal "low" accepted for 3-tier legacy facts.
LOW_CONFIDENCE = frozenset({
    "low", "roughly_even", "unlikely", "very_unlikely", "almost_no_chance",
    "suspected",
})

# #241: only maker-stamped PROVEN claims are checked — VERIFIED means an
# independent checker already ran; REFUTED/NEGATIVE are closed by definition.
UNVERIFIED_CHECK_STATUSES = frozenset({"PROVEN"})


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml(p):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _read_text(p):
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def extract_claim_ids_from_plan(plan_path: Path) -> set:
    if not plan_path.exists():
        return set()
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r"C-\d+", text))


def extract_claim_ids_from_deps(deps_path: Path) -> set:
    if not deps_path.exists():
        return set()
    deps = _load_yaml(deps_path)
    out = set()
    for child, parents in (deps or {}).get("depends_on", {}).items():
        out.add(child)
        for p in (parents or []):
            out.add(p)
    return out


def extract_next_step_claims(plan_path: Path) -> set:
    if not plan_path.exists():
        return set()
    text = plan_path.read_text(encoding="utf-8", errors="replace")
    in_next = False
    out = set()
    for line in text.splitlines():
        if re.search(r"^##\s*(next step|next:|next iter|next claim)", line, re.IGNORECASE):
            in_next = True
            continue
        if in_next and line.startswith("## "):
            in_next = False
        if in_next:
            out.update(re.findall(r"C-\d+", line))
    return out


def _normalize_cid(raw: str) -> str:
    """Normalize any claim-id spelling to canonical C-NNN form.

    Register ids are C-NNN (dashed) but verify/plan file names spell ids
    both ways — runs/verify-redteam-C335.md (undashed, real workspace),
    verify-redteam-C001.md, verify-redteam-C-7.md. Comparison happens in
    canonical form so all three count as the same claim.
    """
    m = re.search(r"C-?(\d+)", raw or "")
    return f"C-{m.group(1)}" if m else (raw or "")


def _read_frontmatter(p: Path) -> dict:
    """YAML frontmatter of a facts/F*.md file; {} when absent/unparseable."""
    text = p.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        return yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return {}


def extract_verified_claim_ids(runs_dir: Path) -> set:
    """Claim ids covered by runs/verify-redteam-*.md files (canonical form).

    A redteam verify run is the independent reality check behind a PROVEN
    claim (maker-checker: worker=maker, verifier=checker). Presence of the
    file is the mechanical proxy for "the check happened" — its verdict
    content is outcome_capture.py's business.
    """
    out = set()
    if not runs_dir.exists():
        return out
    for p in runs_dir.glob("verify-redteam-*.md"):
        m = re.search(r"C-?\d+", p.name)
        if m:
            out.add(_normalize_cid(m.group(0)))
    return out


def extract_low_confidence_claim_ids(facts_dir: Path) -> set:
    """Claim ids whose fact files carry low-confidence frontmatter.

    A fact is facts/F<NNN>*.md with YAML frontmatter (id/status/confidence/
    claim_id). A supporting fact at or below even odds means the claim is
    PROVEN on shaky ground — file-level consistency says nothing about it.
    """
    out = set()
    if not facts_dir.exists():
        return out
    for p in sorted(facts_dir.glob("F*.md")):
        fm = _read_frontmatter(p)
        cid = fm.get("claim_id")
        conf = fm.get("confidence")
        if cid and conf and str(conf).strip().lower() in LOW_CONFIDENCE:
            out.add(_normalize_cid(str(cid)))
    return out


@_gt.telemetry('plan_drift_detector')
def check(workspace: Path, active_only: bool = False) -> int:
    reg = _load_yaml(workspace / "claim-register.yaml")
    claims = (reg or {}).get("claims", []) or []
    claim_ids = {c.get("id") for c in claims if c.get("id")}

    # --active-only: check the current plan file only; otherwise all plan
    # candidates. (Phase-level plans that use a different claim-id namespace
    # are handled by `plan_refers_to_register` below, not by globbing.)
    if active_only:
        plan_path_candidates = [workspace / "global_plan.txt"]
    else:
        plan_path_candidates = [
            workspace / "global_plan.txt",
            workspace / "global_plan.yaml",
            workspace / "plan.md",
        ]
    plan_path = next((p for p in plan_path_candidates if p.exists()), None)
    plan_ids = extract_claim_ids_from_plan(plan_path) if plan_path else set()
    next_step_ids = extract_next_step_claims(plan_path) if plan_path else set()

    # v1.9.29: a plan that shares NO claim-id namespace with the register is a
    # phase-level / legacy plan — ORPHAN_CLAIM and STALE_PLAN_ENTRY would be
    # structural false positives (e.g. plan cites C-07 while register uses
    # C-200+). Plan-level drift is only meaningful when plan and register
    # reference the same claim ids.
    plan_refers_to_register = bool(plan_ids & claim_ids)

    deps_path = workspace / "claim_deps.yaml"
    deps_ids = extract_claim_ids_from_deps(deps_path)

    tspec = _load_yaml(workspace / "task_spec.yaml")
    primary_questions = tspec.get("primary_questions", []) or []

    drifts = []

    if plan_refers_to_register:
        for c in claims:
            cid = c.get("id")
            if cid and plan_path and cid not in plan_ids:
                drifts.append({
                    "type": "ORPHAN_CLAIM",
                    "claim_id": cid,
                    "fix": f"add claim {cid} to {plan_path.name} (mid-iteration discovery not logged)",
                })

    if plan_path and plan_refers_to_register:
        for cid in plan_ids:
            if cid not in claim_ids:
                drifts.append({
                    "type": "STALE_PLAN_ENTRY",
                    "claim_id": cid,
                    "fix": f"remove claim {cid} from {plan_path.name} (no longer in claim-register)",
                })

    for c in claims:
        cid = c.get("id")
        parent = c.get("parent_claim")
        if cid and parent and deps_path.exists():
            deps = _load_yaml(deps_path)
            depends_on = (deps or {}).get("depends_on", {}) or {}
            if parent not in depends_on.get(cid, []):
                drifts.append({
                    "type": "MISSING_DEP_LINK",
                    "claim_id": cid,
                    "fix": f"add '{parent}' to depends_on[{cid}] in {deps_path.name} (decomposition not in DAG)",
                })

    for q in primary_questions:
        qid = q.get("id") if isinstance(q, dict) else None
        if not qid:
            continue
        # a primary question is ANSWERED when an answering claim reached any
        # terminal status — PROVEN/VERIFIED confirm, REFUTED/NEGATIVE answer
        # "no", DEFERRED/STALE record a dead-end. (v1.9.29: TERMINAL_STATUSES
        # already includes REFUTED/NEGATIVE; previously only PROVEN/VERIFIED
        # counted, so a yes/no question answered "no" flagged as unanswered.)
        answered = any(c.get("answers_question") == qid and (c.get("status") or "").upper() in TERMINAL_STATUSES for c in claims)
        if not answered:
            drifts.append({
                "type": "UNANSWERED_QUESTION",
                "claim_id": qid,
                "fix": f"primary question {qid} has no terminal-status answering claim",
            })

    if plan_path and plan_refers_to_register:
        for cid in next_step_ids:
            c = next((c for c in claims if c.get("id") == cid), None)
            if c is None:
                continue
            status = (c.get("status") or "").upper()
            if status in TERMINAL_STATUSES:
                drifts.append({
                    "type": "STALE_NEXT_STEP",
                    "claim_id": cid,
                    "fix": f"remove claim {cid} from 'next step' section (status={status})",
                })

    # #241: UNVERIFIED_EVIDENCE — the first 5 classes check whether the PLAN
    # files agree with each other; none asks whether the REGISTER itself is
    # wrong. A claim at status: PROVEN is drift when its reality check never
    # happened (no runs/verify-redteam-*.md on disk) or when its supporting
    # facts carry low confidence (PROVEN on shaky ground).
    verified_ids = extract_verified_claim_ids(workspace / "runs")
    low_confidence_ids = extract_low_confidence_claim_ids(workspace / "facts")
    for c in claims:
        cid = c.get("id")
        if (c.get("status") or "").upper() not in UNVERIFIED_CHECK_STATUSES:
            continue
        if cid not in verified_ids:
            drifts.append({
                "type": "UNVERIFIED_EVIDENCE",
                "claim_id": cid,
                "fix": f"claim {cid} is PROVEN but has no runs/verify-redteam-*.md file (reality check missing)",
            })
        if cid in low_confidence_ids:
            drifts.append({
                "type": "UNVERIFIED_EVIDENCE",
                "claim_id": cid,
                "fix": f"claim {cid} is PROVEN but a supporting fact carries low confidence",
            })

    if not drifts:
        print("OK: no plan drift detected")
        return 0

    by_type = {}
    for d in drifts:
        by_type.setdefault(d["type"], []).append(d)

    print(f"REJECT: {len(drifts)} plan-drift(s) detected (B1o plan-drift blocker):")
    for dtype, items in sorted(by_type.items()):
        print(f"\n  {dtype} ({len(items)}):")
        for d in items[:5]:
            print(f"    - {d['claim_id']}: {d['fix']}")
        if len(items) > 5:
            print(f"    ... and {len(items) - 5} more")
    # v1.9.29: 3+ drift warnings in the same run = HARD_PAUSE (exit 2),
    # per the docstring contract that the implementation previously lacked.
    return 2 if len(drifts) >= 3 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect plan files drifting behind reality")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--active-only", action="store_true",
                        help="check only the current plan file (global_plan.txt), not all candidates")
    args = parser.parse_args()
    return check(Path(args.workspace), active_only=args.active_only)


if __name__ == "__main__":
    sys.exit(main())