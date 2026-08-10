#!/usr/bin/env python3
"""convergence_check.py - the "should I dispatch right now?" decision (v1.9).

Companion to priority.py:
  priority.py        → "given I'm dispatching, WHICH claim is highest-value?"
  convergence_check  → "SHOULD I be dispatching at all, or am I converged / saturated / blocked?"

This exists because the #1 failure mode across 8 sessions / 6 workspaces was
notification-driven idling: the agent finished processing a worker result and
went idle with open claims + free slots, waiting to be poked. SKILL.md v1.9
makes convergence-driven dispatch the core behavior; this script is the
executable form of that check, so the agent has a concrete tool rather than
aspirational prose.

Decision matrix:
  open_claims>0 AND free_slots>0           → DISPATCH       (run priority.py, dispatch top)
  partial_facts>0 AND free_slots>0         → DISPATCH_VERIFIER
  open_claims>0 AND free_slots==0          → SATURATED      (poll workers, don't idle)
  open_claims==0 AND partial_facts==0      → CONVERGED      (loop done, write report)
  open_claims>0 AND all open are blocked   → BLOCKED        (escalate with specifics)

Exit codes (machine-readable for hooks):
  0 = CONVERGED (nothing to do)
  1 = DISPATCH (open work + free slots)
  2 = DISPATCH_VERIFIER (partial facts need checking)
  3 = SATURATED (busy, poll)
  4 = BLOCKED (open work but all blocked — escalate)

Usage:
  python scripts/convergence_check.py [workspace]          # human-readable
  python scripts/convergence_check.py [workspace] --json   # machine-readable
Workspace defaults to $PWD/malware-analysis-workspace if it has claim-register.yaml, else $PWD.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

WORKER_CAP = 3
STUCK_MINUTES = 20
TERMINAL = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED"}
PARTIAL_STATUSES = {"PARTIALLY-VERIFIED", "PARTIAL", "PARTIALLY_VERIFIED"}

# Exit codes
EXIT_CONVERGED = 0
EXIT_DISPATCH = 1
EXIT_VERIFY = 2
EXIT_SATURATED = 3
EXIT_BLOCKED = 4


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _load_yaml(p: Path):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _resolve_ws(arg) -> Path:
    if arg:
        return Path(arg)
    cwd = Path(os.getcwd())
    sub = cwd / "malware-analysis-workspace"
    return sub if (sub / "claim-register.yaml").exists() else cwd


def _scan_active_workers(workspace: Path):
    """Count in-flight + stuck workers from runs/worker-status-*.md.

    v1.9.13 (worktree isolation): worker state lives in EACH worker's git
    worktree (.wt-*/malware-analysis-workspace/runs/), NOT the main workspace
    (merged status files are removed from the main tree). Scan the main
    workspace runs/ PLUS every .wt-*/ worktree runs/ dir.

    Status files are append-only logs ("[ts] step: ... | status: in-progress"
    ... "| status: done") — a worker is ACTIVE only if its LAST status line
    is in-progress. Files whose last status is done/blocked (or that contain
    no status line) are NOT counted, even if earlier lines say in-progress
    (worktree snapshots carry historical files from HEAD).
    """
    import re as _re
    _status_line = _re.compile(r"status:\s*(\S+)")
    dirs = [workspace / "runs"]
    try:
        for wt in workspace.parent.glob(".wt-*/malware-analysis-workspace/runs"):
            dirs.append(wt)
    except OSError:
        pass
    active = 0
    stuck = []
    cutoff = timedelta(minutes=STUCK_MINUTES)
    now = utc_now()
    for runs in dirs:
        if not runs.exists():
            continue
        for p in runs.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # last status line decides activity
            last_status = None
            for line in text.splitlines():
                m = _status_line.search(line)
                if m:
                    last_status = m.group(1).lower()
            if last_status != "in-progress":
                continue
            active += 1
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if (now - mtime) > cutoff:
                stuck.append({"worker": p.stem, "age_min": int((now - mtime).total_seconds() // 60)})
    return active, stuck


def _open_claims(reg: dict):
    """Return claims that are non-terminal (need work)."""
    out = []
    for c in (reg.get("claims") or []):
        status = (c.get("status") or "UNKNOWN").upper()
        if status not in TERMINAL and status != "IN_PROGRESS":
            out.append({"id": c.get("id"), "status": status, "blocked": bool(c.get("blocked"))})
    return out


def _partial_facts(workspace: Path):
    """Count facts needing verification from facts/_INDEX.md."""
    idx = workspace / "facts" / "_INDEX.md"
    if not idx.exists():
        return []
    partial = []
    for line in idx.read_text(encoding="utf-8", errors="replace").splitlines():
        # Format per SKILL.md: F<id> | <status> | <claim_id> | <conclusion>
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        status = parts[1].upper()
        if any(s in status for s in PARTIAL_STATUSES):
            partial.append({"fact": parts[0], "status": parts[1]})
    return partial


def _active_blockers(workspace: Path):
    """Return active blocker ids from blockers/*.md (excluding INVALIDATED)."""
    bdir = workspace / "blockers"
    if not bdir.exists():
        return []
    out = []
    for p in bdir.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "INVALIDATED" in text.upper():
            continue
        out.append(p.stem)
    return out


def _count_facts(workspace: Path) -> int:
    """Total facts on disk (for churn detection — facts growing without claims closing).

    v1.9.8 fix: real workspaces name facts `F001-<slug>.md` (NO hyphen after F —
    e.g. F001-chemistry-as-mapassign-literal.md), while test_workspace used
    `F-001-*.md`. The old glob `F-*.md` matched only the test convention, so
    facts_total was always 0 in production → the SPINNING churn branch
    ("facts grew 5+ while open_count held") could never fire. Count BOTH."""
    fdir = workspace / "facts"
    if not fdir.exists():
        return 0
    return sum(1 for p in fdir.glob("F*.md")
               if p.is_file() and p.name.upper().startswith("F"))


LEDGER_NAME = ".convergence_ledger.jsonl"

# STAMP = claimed-but-unverified (from blind_gate.py M1). These are NOT PROVEN.
NON_PROVEN_ANSWER = {"STAMP", "UNVERIFIED"}


def _orphan_terminal_claims(reg: dict, primary_question_ids: set | None = None) -> list:
    """Find terminal claims that have no answers_question linking to a primary_question.

    An orphan = a claim in TERMINAL status with no `answers_question` field.
    Only checked when primary_questions exist (if the workspace doesn't use
    the primary_questions feature, all claims are inherently question-less
    and that's fine).

    Returns list of {"id": ..., "status": ...} dicts for orphan terminal claims.
    """
    if primary_question_ids is not None and not primary_question_ids:
        # Workspace has primary_questions: [] (feature not used) — skip orphan check
        return []
    out = []
    for c in (reg.get("claims") or []):
        status = (c.get("status") or "UNKNOWN").upper()
        if status not in TERMINAL:
            continue
        aq = c.get("answers_question")
        if not aq:
            out.append({"id": c.get("id"), "status": status})
    return out


def _unverified_primary_questions(reg: dict, task_spec: dict) -> list:
    """Find primary_questions that have NO PROVEN answering claim.

    A primary_question is "verified" only when a claim with
    answers_question == q.id has status == PROVEN (BLIND-verified per M1).
    STAMP, UNVERIFIED, VERIFIED, NEGATIVE etc. do NOT satisfy — M2 requires
    BLIND-verified answers.

    Returns list of {"question": q_id, "answering_claims": [...]} dicts.
    """
    pqs = task_spec.get("primary_questions") or []
    if not pqs:
        return []

    # Extract question IDs (support both "qid: description" dict and plain string forms)
    pq_ids = []
    for q in pqs:
        if isinstance(q, dict):
            pq_ids.extend(q.keys())
        elif isinstance(q, str):
            pq_ids.append(q)

    claims = reg.get("claims") or []
    unverified = []
    for qid in pq_ids:
        answering = [
            {"id": c.get("id"), "status": (c.get("status") or "UNKNOWN").upper()}
            for c in claims
            if c.get("answers_question") == qid
        ]
        has_proven = any(a["status"] == "PROVEN" for a in answering)
        if not has_proven:
            unverified.append({"question": qid, "answering_claims": answering})
    return unverified


def _load_task_spec(workspace: Path) -> dict:
    """Load task_spec.yaml for primary_questions. Returns {} if missing."""
    return _load_yaml(workspace / "task_spec.yaml")


def _pq_ids(task_spec: dict) -> set:
    """Extract the set of primary_question IDs from task_spec."""
    pqs = task_spec.get("primary_questions") or []
    ids = set()
    for q in pqs:
        if isinstance(q, dict):
            ids.update(q.keys())
        elif isinstance(q, str):
            ids.add(q)
    return ids


def _append_ledger(workspace: Path, d: dict) -> None:
    """Append one state snapshot per call. convergence_health.py reads the trajectory.

    Silent side-effect by design: the ledger builds itself from the every-turn
    convergence_check call, without depending on orchestrator discipline. One
    JSON line per call; hidden file so it doesn't clutter the workspace.
    """
    try:
        entry = {
            "ts": utc_now().isoformat(timespec="seconds"),
            "decision": d["decision"],
            "open_count": d["open_count"],
            "open_ids": [c["id"] for c in d["open_claims"]],
            "partial_count": d["partial_count"],
            "active_workers": d["active_workers"],
            "blockers": d["active_blockers"],
            "facts_total": _count_facts(workspace),
        }
        with open(workspace / LEDGER_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        # ledger is a side channel — never block the decision on it
        pass


def _failure_blocked(workspace: Path) -> list:
    """Claims with a failed attempt but no current failure_analysis.
    These cannot be re-dispatched or marked NEGATIVE until reasoned about.
    Imports failure_analysis_gate (sibling script); returns [] if unavailable."""
    try:
        import failure_analysis_gate as fag  # sibling in scripts/
    except ImportError:
        return []
    try:
        return [b["claim_id"] for b in fag.scan_workspace(workspace) if b.get("state") == "BLOCKED"]
    except Exception:
        return []


def decide(workspace: Path) -> dict:
    reg = _load_yaml(workspace / "claim-register.yaml")
    task_spec = _load_task_spec(workspace)
    pq_ids = _pq_ids(task_spec)

    opens = _open_claims(reg)
    partials = _partial_facts(workspace)
    active, stuck = _scan_active_workers(workspace)
    free_slots = max(0, WORKER_CAP - active)
    blockers = _active_blockers(workspace)
    failure_blocked_ids = _failure_blocked(workspace)

    # M2 completeness gate: check before declaring CONVERGED
    orphans = _orphan_terminal_claims(reg, pq_ids if pq_ids is not None else None)
    unverified_pqs = _unverified_primary_questions(reg, task_spec)

    blocked_claims = [c for c in opens if c["blocked"]]
    # unblocked_open = open, not infra-blocked, AND not failure-analysis-blocked
    unblocked_open = [c for c in opens if not c["blocked"] and c["id"] not in failure_blocked_ids]
    failure_blocked_open = [c for c in opens if c["id"] in failure_blocked_ids]

    # Decision matrix (order matters)
    if not opens and not partials:
        # M2 completeness gate: CONVERGED requires primary_questions all PROVEN
        # AND zero orphan terminal claims. Otherwise downgrade.
        if orphans:
            orphan_ids = [o["id"] for o in orphans]
            decision, exit_code, action = "BLOCKED", EXIT_BLOCKED, \
                f"Cannot CONVERGE: {len(orphans)} orphan terminal claim(s) {orphan_ids} " \
                f"have no answers_question — link them to a primary_question or reopen."
        elif unverified_pqs:
            uv_ids = [u["question"] for u in unverified_pqs]
            decision, exit_code, action = "SATURATED", EXIT_SATURATED, \
                f"Cannot CONVERGE: primary_questions {uv_ids} lack PROVEN answering claims " \
                f"(need BLIND-verified PROVEN, not STAMP/unverified). " \
                f"Dispatch verifier or rework answering claims."
        else:
            decision, exit_code, action = "CONVERGED", EXIT_CONVERGED, \
                "No open claims, no partial facts. All primary_questions PROVEN, zero orphans. " \
                "Loop is done — write the report."
    elif unblocked_open and free_slots:
        decision, exit_code, action = "DISPATCH", EXIT_DISPATCH, \
            f"Run priority.py and dispatch the top claim. {len(unblocked_open)} unblocked open claim(s), {free_slots} free slot(s)."
    elif partials and free_slots:
        decision, exit_code, action = "DISPATCH_VERIFIER", EXIT_VERIFY, \
            f"Dispatch a verifier for {len(partials)} partial fact(s). Do NOT declare PROVEN without sign-off."
    elif unblocked_open and not free_slots:
        decision, exit_code, action = "SATURATED", EXIT_SATURATED, \
            f"All {WORKER_CAP} slots busy with {len(unblocked_open)} open claim(s) queued. Poll workers — do not idle."
    elif failure_blocked_open:
        decision, exit_code, action = "BLOCKED", EXIT_BLOCKED, \
            f"{len(failure_blocked_open)} claim(s) have a failed attempt with no failure_analysis: {failure_blocked_ids}. " \
            f"Run failure_analysis_gate.py <ws> to reason about WHY the method failed before re-dispatch or NEGATIVE."
    elif opens and not unblocked_open:
        decision, exit_code, action = "BLOCKED", EXIT_BLOCKED, \
            f"All {len(opens)} open claim(s) are blocked. Resolve blockers: {blockers or 'none on disk'}."
    else:
        # Fallback (should not normally reach here)
        decision, exit_code, action = "SATURATED", EXIT_SATURATED, \
            "Unexpected state — investigate manually."

    return {
        "decision": decision,
        "exit_code": exit_code,
        "action": action,
        "open_claims": opens,
        "open_count": len(opens),
        "unblocked_open_count": len(unblocked_open),
        "blocked_open_count": len(blocked_claims),
        "failure_blocked": failure_blocked_ids,
        "partial_facts": partials,
        "partial_count": len(partials),
        "active_workers": active,
        "free_slots": free_slots,
        "worker_cap": WORKER_CAP,
        "stuck_workers": stuck,
        "active_blockers": blockers,
        # M2 completeness diagnostics
        "orphan_claims": orphans,
        "unverified_primary_qs": unverified_pqs,
    }


def _human(d: dict) -> str:
    lines = []
    lines.append(f"=== CONVERGENCE CHECK: {d['decision']} ===")
    lines.append(f"action: {d['action']}")
    lines.append("")
    lines.append(f"open claims:    {d['open_count']} ({d['unblocked_open_count']} unblocked, {d['blocked_open_count']} blocked)")
    lines.append(f"partial facts:  {d['partial_count']}")
    lines.append(f"workers:        {d['active_workers']}/{d['worker_cap']} active → {d['free_slots']} free slot(s)")
    if d["stuck_workers"]:
        lines.append(f"stuck (> {STUCK_MINUTES}m): {d['stuck_workers']}")
    if d["active_blockers"]:
        lines.append(f"blockers:       {d['active_blockers']}")
    if d.get("failure_blocked"):
        lines.append(f"failure-blocked: {d['failure_blocked']} (run failure_analysis_gate.py <ws> before re-dispatch or NEGATIVE)")
    if d["open_claims"] and d["open_count"] <= 12:
        lines.append("")
        lines.append("open claims:")
        for c in d["open_claims"]:
            flags = []
            if c["blocked"]:
                flags.append("blocked")
            if c["id"] in d.get("failure_blocked", []):
                flags.append("failure-blocked")
            flag = f" [{','.join(flags)}]" if flags else ""
            lines.append(f"  {c['id']:>8}  {c['status']}{flag}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="kunglao-agent convergence check — should I dispatch?")
    parser.add_argument("workspace", nargs="?", default=None, help="workspace root")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    workspace = _resolve_ws(args.workspace)
    if not (workspace / "claim-register.yaml").exists():
        print(f"FAIL: no claim-register.yaml under {workspace}", file=sys.stderr)
        return 64

    d = decide(workspace)
    _append_ledger(workspace, d)  # silent side channel for convergence_health.py
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        print(_human(d))
    return d["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
