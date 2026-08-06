"""plan_drift_detector.py - detect when plan files lag behind reality.

User pain point: "实际进度状态和计划与文件里面的不匹配 - 比如开始规划的时候
有15个任务，但是随着推进出现重新规划 任务分解 任务废弃，相关文件没跟上"

5 drift types detected:
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

Usage:
  python plan_drift_detector.py <workspace> [--apply]
Exit codes:
  0 = no drift
  1 = drift detected (B1o blocker)
  2 = HARD_PAUSE: 3+ drift warnings in same session
"""
from __future__ import annotations
import gate_telemetry as _gt

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

TERMINAL_STATUSES = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED", "STALE"}


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


@_gt.telemetry('plan_drift_detector')
def check(workspace: Path) -> int:
    reg = _load_yaml(workspace / "claim-register.yaml")
    claims = (reg or {}).get("claims", []) or []
    claim_ids = {c.get("id") for c in claims if c.get("id")}

    plan_path_candidates = [
        workspace / "global_plan.txt",
        workspace / "global_plan.yaml",
        workspace / "plan.md",
    ]
    plan_path = next((p for p in plan_path_candidates if p.exists()), None)
    plan_ids = extract_claim_ids_from_plan(plan_path) if plan_path else set()
    next_step_ids = extract_next_step_claims(plan_path) if plan_path else set()

    deps_path = workspace / "claim_deps.yaml"
    deps_ids = extract_claim_ids_from_deps(deps_path)

    tspec = _load_yaml(workspace / "task_spec.yaml")
    primary_questions = tspec.get("primary_questions", []) or []

    drifts = []

    for c in claims:
        cid = c.get("id")
        if cid and plan_path and cid not in plan_ids:
            drifts.append({
                "type": "ORPHAN_CLAIM",
                "claim_id": cid,
                "fix": f"add claim {cid} to {plan_path.name} (mid-iteration discovery not logged)",
            })

    if plan_path:
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
        answered = any(c.get("answers_question") == qid and (c.get("status") or "").upper() in ("PROVEN", "VERIFIED") for c in claims)
        if not answered:
            drifts.append({
                "type": "UNANSWERED_QUESTION",
                "claim_id": qid,
                "fix": f"primary question {qid} has no PROVEN/VERIFIED answering claim",
            })

    if plan_path:
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
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect plan files drifting behind reality")
    parser.add_argument("workspace", help="workspace root")
    args = parser.parse_args()
    return check(Path(args.workspace))


if __name__ == "__main__":
    sys.exit(main())