#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
  non-empty malformed primary_questions    → INVALID        (escalate, target undefined)

Exit codes (machine-readable for hooks):
  0 = CONVERGED (nothing to do)
  1 = DISPATCH (open work + free slots)
  2 = DISPATCH_VERIFIER (partial facts need checking)
  3 = SATURATED (busy, poll)
  4 = BLOCKED (open work but all blocked — escalate); INVALID (bad task_spec) reuses this
     so hooks that accept returncodes 0–4 keep parsing the JSON decision.
  64 = MISSING_WORKSPACE (no claim-register.yaml found — caller passed wrong path)

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

from status_defs import TERMINAL, IN_PROGRESS_STATUSES, PARTIAL_STATUSES

WORKER_CAP = 3
STUCK_MINUTES = 20

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
    worktree (.wt-*/ with .kunglao-worktree marker/), NOT the main workspace
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
        for wt in workspace.parent.glob(".wt-*/.kunglao-worktree"):
            runs_dir = wt.parent / "malware-analysis-workspace" / "runs"
            if runs_dir.exists():
                dirs.append(runs_dir)
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
        if status not in TERMINAL and status not in IN_PROGRESS_STATUSES:
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
    """Find primary_questions that have NO answering claim.

    A primary_question is "verified" when a claim with
    answers_question == q.id has a terminal status appropriate to the
    question's need:
      - model_selection / protocol_description: status == PROVEN
        (BLIND-verified per M1).
      - yes_no_with_evidence: any terminal status answering the
        yes/no question (PROVEN / VERIFIED / NEGATIVE / REFUTED).
    STAMP, UNVERIFIED, PARTIAL etc. do NOT satisfy.

    Returns list of {"question": q_id, "answering_claims": [...]} dicts.
    """
    pqs, _ = _parse_primary_questions(task_spec)
    if not pqs:
        return []

    # Map question id -> need (single canonical parse, issue #77)
    question_need = dict(pqs)

    claims = reg.get("claims") or []
    unverified = []
    for qid, need in question_need.items():
        answering = [
            {"id": c.get("id"), "status": (c.get("status") or "UNKNOWN").upper()}
            for c in claims
            if c.get("answers_question") == qid
        ]
        if need == "yes_no_with_evidence":
            terminal_ok = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED"}
            satisfied = any(a["status"] in terminal_ok for a in answering)
        else:
            satisfied = any(a["status"] == "PROVEN" for a in answering)
        if not satisfied:
            unverified.append({"question": qid, "answering_claims": answering})
    return unverified


def _note_layer_gaps(workspace: Path, pq_ids: set, reg: dict) -> list:
    """DESIGN §8 C0 note-layer gate: every primary_question needs a note with
    verify_status=passes whose claim_id answers that question.

    Link chain: note.claim_id -> claim.answers_question -> q_id
    (notes carry no direct answers_question field; the link is via the claim).

    Returns pq_ids lacking such a note. Skip (return []) when notes/ is absent
    or no primary_questions are defined (feature unused -> no regression)."""
    if not pq_ids or not (workspace / "notes").exists():
        return []
    import re as _re
    claim_answers = {}
    for c in (reg.get("claims") or []):
        cid = c.get("id")
        aq = c.get("answers_question")
        if cid and aq:
            claim_answers[str(cid).strip()] = str(aq).strip()
    answered = set()
    for p in (workspace / "notes").glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not text.lstrip().startswith("---"):
            continue
        parts = text.split("---", 2)
        if len(parts) < 3:
            continue
        fm = parts[1]
        vs = _re.search(r"^verify_status:\s*(\S+)", fm, _re.M)
        cid_m = _re.search(r"^claim_id:\s*([^\n]+)", fm, _re.M)
        if not (vs and cid_m):
            continue
        if vs.group(1).strip().lower() != "passes":
            continue
        cid = cid_m.group(1).strip().strip("[]").split(",")[0].strip()
        qid = claim_answers.get(cid)
        if qid:
            answered.add(qid)
    return [q for q in pq_ids if q not in answered]


def _load_task_spec(workspace: Path) -> dict:
    """Load task_spec.yaml for primary_questions. Returns {} if missing."""
    return _load_yaml(workspace / "task_spec.yaml")


def _parse_pq_item(q: dict) -> tuple[str | None, str | None, str | None]:
    """Parse ONE primary_questions list item (canonical or legacy form).

    Returns (qid, need, error) — a parse error leaves qid/need as None.
      - canonical (template) form: dict with a non-empty string `id` key;
        extra keys (`q`, `need`, `candidates`, ...) are allowed.
      - legacy one-key mapping: dict WITHOUT `id` and with exactly one
        string key — the key is the question id and the value is a free-text
        description (need=None), NOT a `need` enum.
    """
    if "id" in q:
        qid = q["id"]
        if not isinstance(qid, str) or not qid:
            return None, None, f"'id' must be a non-empty string, got {qid!r}"
        need = q.get("need")
        if need is not None and not isinstance(need, str):
            return None, None, f"'need' must be a string, got {need!r}"
        return qid, need, None
    if len(q) == 0:
        return None, None, "empty mapping (expected 'id' or one-key legacy form)"
    if len(q) > 1:
        return None, None, \
            f"mapping without 'id' has {len(q)} keys {list(q)!r}; " \
            f"use {{id: ..., need: ...}} or the one-key legacy form"
    k = next(iter(q))
    if not isinstance(k, str):
        return None, None, f"mapping key {k!r} is not a string"
    v = q[k]
    if v is not None and not isinstance(v, str):
        return None, None, f"mapping value {v!r} is not a string or null"
    return k, None, None


def _parse_primary_questions(task_spec: dict) -> tuple[list, str | None]:
    """Canonical parse of task_spec.primary_questions (issue #77 follow-up).

    ONE schema at the load boundary: every consumer — _pq_ids(),
    _unverified_primary_questions(), the orphan check and the note-layer
    check — derives from the SAME parsed list, so a mapping-shaped
    `primary_questions` can never silently degrade to an empty question set
    (the pre-fix bug: c3be3c6 made extraction `q.get("id")`-only, which
    skipped the legacy one-key mapping and disabled the M2 gates).

    Accepted shapes (deterministic):
      - key absent / `[]` / `{}`      → feature unused: ([], None)
      - list items: plain string, canonical dict with `id`, legacy one-key
        mapping (see _parse_pq_item)
      - top-level non-empty mapping   → one (qid, None) per string key
        (pre-regression behavior: keys were iterated as ids)

    Returns (questions, error): questions is a list of (qid, need) tuples
    (need None when unspecified), [] on error; error is None on success else
    a human-readable reason naming the offending item/field. A NON-EMPTY
    malformed / mixed-with-malformed / unrecognized input NEVER yields an
    empty set without an error — decide() escalates INVALID.
    """
    raw = task_spec.get("primary_questions")
    if raw is None:
        return [], None
    if raw == [] or raw == {}:
        return [], None

    if isinstance(raw, dict):
        # top-level mapping: keys are question ids (pre-regression behavior)
        norm = []
        for k, v in raw.items():
            if not isinstance(k, str):
                return [], f"top-level mapping key {k!r} is not a string"
            if v is not None and not isinstance(v, str):
                return [], f"top-level mapping key {k!r} has non-string value {v!r}"
            norm.append({k: v})
        raw = norm

    if not isinstance(raw, list):
        return [], f"expected a list or mapping of questions, got {type(raw).__name__} ({raw!r})"

    questions: list = []
    seen: set = set()
    for i, q in enumerate(raw):
        if isinstance(q, str):
            if not q:
                return [], f"item {i} is an empty string"
            qid, need = q, None
        elif isinstance(q, dict):
            qid, need, err = _parse_pq_item(q)
            if err:
                return [], f"item {i}: {err}"
        else:
            return [], f"item {i} is {type(q).__name__} ({q!r}); expected a string or mapping"
        if qid in seen:
            return [], f"duplicate question id {qid!r} (item {i})"
        seen.add(qid)
        questions.append((qid, need))
    return questions, None


def _pq_ids(task_spec: dict) -> set:
    """Extract the set of primary_question IDs from task_spec.

    Thin wrapper over the single canonical parse (issue #77). On a malformed
    NON-EMPTY schema the set is empty ONLY because decide() escalates
    INVALID before any gate consults it — the parse error is never silently
    swallowed there (the bug this follow-up fixes).
    """
    return {qid for qid, _ in _parse_primary_questions(task_spec)[0]}


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


def record_operator_action(workspace, action: str, actor: str = "orchestrator",
                           claim_id: str = "", reason: str = "",
                           before: str = "", after: str = "") -> None:
    """Append an OPERATOR_ACTION row to the convergence ledger (#142).

    Records who changed what and why: defer/override_proven/weight_change/claim_edit.
    Writes directly to the ledger (not via _append_ledger which expects snapshot fields).
    """
    from status_defs import LedgerLineType
    entry = {
        "type": LedgerLineType.OPERATOR_ACTION,
        "action": action,
        "actor": actor,
        "claim_id": claim_id,
        "reason": reason,
        "before": before,
        "after": after,
        "ts": utc_now().isoformat(timespec="seconds"),
    }
    try:
        newline_char = chr(10)
        with open(workspace / LEDGER_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + newline_char)
    except OSError:
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
    pq_questions, pq_error = _parse_primary_questions(task_spec)
    pq_ids = {qid for qid, _ in pq_questions}

    opens = _open_claims(reg)
    partials = _partial_facts(workspace)
    active, stuck = _scan_active_workers(workspace)
    free_slots = max(0, WORKER_CAP - active)
    blockers = _active_blockers(workspace)
    failure_blocked_ids = _failure_blocked(workspace)

    # M2 completeness gate: check before declaring CONVERGED
    orphans = _orphan_terminal_claims(reg, pq_ids)
    unverified_pqs = _unverified_primary_questions(reg, task_spec)
    # DESIGN §8 C0 note-layer gate: every pq needs a verify_status=passes note
    pq_note_gaps = _note_layer_gaps(workspace, pq_ids, reg)

    blocked_claims = [c for c in opens if c["blocked"]]
    # unblocked_open = open, not infra-blocked, AND not failure-analysis-blocked
    unblocked_open = [c for c in opens if not c["blocked"] and c["id"] not in failure_blocked_ids]
    failure_blocked_open = [c for c in opens if c["id"] in failure_blocked_ids]

    # Decision matrix (order matters). INVALID schema first (fail-closed):
    # a non-empty malformed primary_questions means the run's convergence
    # target is undefined — escalate, never dispatch against it (issue #77).
    if pq_error:
        decision, exit_code, action = "INVALID", EXIT_BLOCKED, \
            f"INVALID task_spec primary_questions: {pq_error}"
    elif not opens and not partials:
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
        elif pq_note_gaps:
            decision, exit_code, action = "DISPATCH_VERIFIER", EXIT_VERIFY, \
                f"Note-layer (DESIGN §8 C0) not satisfied: primary_questions {pq_note_gaps} " \
                f"lack a note with verify_status=passes (link: note.claim_id -> claim.answers_question). " \
                f"Run verify-note.py before delivery."
        else:
            # #147: discovery consumption — disclosed payloads must be
            # obligations before CONVERGED is possible (replay #1: fact body
            # said 'discovered shellcode, downstream payload not analyzed'
            # and the run converged without the obligation).
            discovery_reason = ""
            try:
                import obligation_discovery as od
                discoveries = od.scan_discoveries(workspace / "facts",
                                                  workspace / "claim-register.yaml")
                if discoveries:
                    names = ", ".join(d["trigger"] for d in discoveries)
                    discovery_reason = (
                        f"{len(discoveries)} unconsumed discovery(s) in {names} "
                        f"— create child obligations or record materiality rejection")
            except Exception as exc:
                discovery_reason = f"discovery scan unavailable ({type(exc).__name__})"
            if discovery_reason:
                decision, exit_code, action = "DISPATCH", EXIT_DISPATCH, \
                    f"Cannot CONVERGE: {discovery_reason}"
            else:
                # #147: completion transaction — CONVERGED is not trusted on the
                # register's word. Recompute global contradictions from facts/.
                # Any contradiction downgrades the decision (replay #2). A
                # workspace without a facts index has zero facts and cannot hold
                # a contradiction.
                contradiction_reason = ""
                if (workspace / "facts" / "_INDEX.md").exists():
                    try:
                        import fact_contradiction_gate as fcg
                        conflicts = fcg.scan_conflicts(workspace / "facts" / "_INDEX.md",
                                                       workspace / "facts")
                        if conflicts:
                            pairs = "; ".join(
                                f"{c['fact_a']} <-> {c['fact_b']}" for c in conflicts)
                            contradiction_reason = f"GLOBAL CONTRADICTION: {pairs}"
                    except Exception as exc:  # fail-closed: cannot verify → cannot converge
                        contradiction_reason = f"contradiction scan unavailable ({type(exc).__name__})"
                if contradiction_reason:
                    decision, exit_code, action = "BLOCKED", EXIT_BLOCKED, \
                        f"Cannot CONVERGE: {contradiction_reason} — resolve via " \
                        f"fact_contradiction_gate or supersedes links."
                else:
                    decision, exit_code, action = "CONVERGED", EXIT_CONVERGED, \
                        "Claim loop done — all open claims closed, partials verified, primary_questions PROVEN " \
                        "with verify_status=passes notes, completion transaction clean (zero global " \
                        "contradictions, zero unconsumed discoveries, PROVEN provenance). STOP dispatch; deliver"
    elif unblocked_open and free_slots:
        decision, exit_code, action = "DISPATCH", EXIT_DISPATCH, \
            f"Run priority.py and dispatch the top claim. {len(unblocked_open)} unblocked open claim(s), {free_slots} free slot(s)."
    elif partials and free_slots:
        decision, exit_code, action = "DISPATCH_VERIFIER", EXIT_VERIFY, \
            f"Dispatch a verifier for {len(partials)} partial fact(s). Do NOT declare PROVEN without sign-off."
    elif unblocked_open and not free_slots:
        decision, exit_code, action = "SATURATED", EXIT_SATURATED, \
            f"All {WORKER_CAP} slots busy with {len(unblocked_open)} open claim(s) queued. Poll workers — do not wait idly."
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
        "note_layer_gaps": pq_note_gaps,
        "pq_parse_error": pq_error,
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
