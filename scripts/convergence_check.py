#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convergence_check.py - the "should I dispatch right now?" decision (v1.9).

Companion to priority_ratio.py:
  priority_ratio.py  → "given I'm dispatching, WHICH claim is highest-value?"
  convergence_check  → "SHOULD I be dispatching at all, or am I converged / saturated / blocked?"

This exists because the #1 failure mode across 8 sessions / 6 workspaces was
notification-driven idling: the agent finished processing a worker result and
went idle with open claims + free slots, waiting to be poked. SKILL.md v1.9
makes convergence-driven dispatch the core behavior; this script is the
executable form of that check, so the agent has a concrete tool rather than
aspirational prose.

Decision matrix:
  open_claims>0 AND free_slots>0           → DISPATCH       (run priority_ratio.py, dispatch top)
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
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import yaml

from status_defs import TERMINAL, IN_PROGRESS_STATUSES, PARTIAL_STATUSES, SUSPENDED
from _hooks_path import load_hooks_lib  # #863 Family B: loader delegation (#671 authority)
# RETRACTED lives in retract_claim.py (retraction domain owner, #331):
# status_defs.TERMINAL is frozen for this change. TERMINAL_WITH_RETRACTED is
# the dispatch-facing terminal set; RETRACTED is a withdrawn verdict, NOT an
# open claim and NOT an orphan (a retracted claim answers no question by design).
from retract_claim import RETRACTED, TERMINAL_WITH_RETRACTED
# #11: worker-death records + artifact snapshot — the resume signal for
# workers that are GONE (silent > DEAD_WORKER_MINUTES, liveness_policy).
# Consumed inside _act_stuck_workers so the dead band rides the existing
# STUCK_WORKERS_PRESENT path (no parallel detector, no second scan pass).
import worker_death as _worker_death
from liveness_policy import DEAD_WORKER_MINUTES as _DEAD_WORKER_MINUTES
# #863 Family C: workspace resolution is single-sourced in ws_layout (this
# module used to be the ONLY manifest-aware copy — now every consumer is).
from ws_layout import resolve_quiet as _resolve_ws

WORKER_CAP = 3

# Exit codes
EXIT_CONVERGED = 0
EXIT_DISPATCH = 1
EXIT_VERIFY = 2
EXIT_SATURATED = 3
EXIT_BLOCKED = 4
EXIT_PARK = 5  # #634: suspended on external gates — legal idle with wake_condition


from harness_common import utc_now  # #863 Family F: single source (was a local def)


def _load_yaml(p: Path):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _load_worker_lib():
    """hooks/lib_kunglao.py — THE worker-liveness protocol owner (#444).

    Parsing of runs/worker-status-*.md (last ``status:`` token wins), the
    .wt-* worktree scan targets, and the W-15 done-artifact check live only
    there; this module is a consumer. By-path under the unique name
    ``lib_kunglao_hooks`` (the external_kicker.should_kick /
    state_anchor._load_drift_lib precedent): bare ``import lib_kunglao`` is
    ambiguous under pytest (pythonpath = . hooks scripts — hooks first)
    because scripts/lib_kunglao.py (drift lib) shares the name. All
    scripts-side consumers use the SAME name, so one process shares one
    module instance.

    Load failure raises instead of falling back to a local copy — a silent
    fallback would resurrect the exact double-representation this change
    removes (#444 AC-1). hooks/ and scripts/ ship together in one skill
    install; a missing file means a broken install, not a degraded mode.

    #863 Family B: the by-path prologue collapsed into the canonical loader
    (hooks/_path_hygiene.load_hooks_lib, via scripts/_hooks_path) — the
    loud-missing guard stays HERE (its message is part of the contract).
    """
    path = Path(__file__).resolve().parent.parent / "hooks" / "lib_kunglao.py"
    if not path.exists():
        raise RuntimeError(
            f"worker-liveness protocol missing: {path} — hooks/ and scripts/ "
            "ship together; reinstall the kunglao-agent skill")
    return load_hooks_lib()


def _scan_workers(workspace: Path):
    """(active, stuck, done_artifact_violations) via the canonical protocol.

    One iter_worker_states pass feeds both aggregates (single read per status
    file). Semantics unchanged from the pre-#444 inline scan: active = last
    status token is in-progress; stuck = active + older than
    lib.STUCK_MINUTES; v1.9.13 worktree isolation (.wt-*/ with
    .kunglao-worktree marker) included. NEW: W-15 done-artifact violations
    (design #444 D3 — diagnostic only, never a decision branch).
    """
    lib = _load_worker_lib()
    states = lib.iter_worker_states(workspace)
    active, stuck = lib.scan_active_workers(workspace, states)
    return active, stuck, lib.scan_done_artifact_violations(workspace, states)


def _open_claims(reg: dict):
    """Return claims that are non-terminal (need work).

    RETRACTED is terminal (#331): a withdrawn claim needs no work and must
    never be re-dispatched."""
    out = []
    for c in (reg.get("claims") or []):
        status = (c.get("status") or "UNKNOWN").upper()
        if status in SUSPENDED:
            continue  # #634: PARK = suspended on external gate, not frontier work
        if status not in TERMINAL_WITH_RETRACTED and status not in IN_PROGRESS_STATUSES:
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
    """Return active blocker ids from blockers/*.md (excluding INVALIDATED).

    README.md is the #538 carrier stub, never a blocker record — skip it
    explicitly (the old code only skipped it by accident: the stub text
    happens to contain the word "INVALIDATED")."""
    bdir = workspace / "blockers"
    if not bdir.exists():
        return []
    out = []
    for p in bdir.glob("*.md"):
        if p.name == "README.md":
            continue
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

    RETRACTED claims are excluded: a withdrawn claim answers no question by
    design (#331) — flagging it as an orphan would BLOCK convergence on
    claims the orchestrator already removed from the delivered set.
    """
    if primary_question_ids is not None and not primary_question_ids:
        # Workspace has primary_questions: [] (feature not used) — skip orphan check
        return []
    out = []
    for c in (reg.get("claims") or []):
        status = (c.get("status") or "UNKNOWN").upper()
        if status not in TERMINAL or status == RETRACTED:
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
        # #331: a RETRACTED claim no longer answers its question — a
        # passes-note on it must not satisfy the note-layer gate.
        if cid and aq and (c.get("status") or "").upper() != RETRACTED:
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


def _dispatched_ids(workspace: Path) -> list:
    """Live claims with dispatch evidence (#2 stuck-vs-queued disambiguation).

    Dispatched = in flight (status in IN_PROGRESS_STATUSES) or with a
    recorded worker attempt (promotion_attempts >= 1). Terminal/PARK claims
    are never live frontier work. Consumer: convergence_health._stuck_claims
    — a claim sitting in open_ids is only "stuck" if it was ever dispatched;
    open_ids minus this set is the never-dispatched queue. Best effort: any
    read/parse failure returns [] (same side-channel posture as the ledger).
    """
    try:
        reg = _load_yaml(workspace / "claim-register.yaml")
        out = []
        for c in (reg.get("claims") or []):
            if not c.get("id"):
                continue
            status = (c.get("status") or "").upper()
            if status in TERMINAL_WITH_RETRACTED or status in SUSPENDED:
                continue
            if status in IN_PROGRESS_STATUSES or int(c.get("promotion_attempts") or 0) >= 1:
                out.append(c["id"])
        return out
    except Exception:  # noqa: BLE001 — side channel, never blocks the decision
        return []


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
            # #2: dispatch evidence per snapshot — lets convergence_health
            # tell "dispatched but flat" (stuck) from "never dispatched"
            # (frontier queue). Old-format readers ignore the extra field.
            "dispatched_ids": _dispatched_ids(workspace),
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


# ===================== #443: decide() explicit state machine =====================
# The pre-#443 decide() was a 13-branch elif pile: order was the semantics,
# comments were the spec, and every incident's cheapest fix was "insert one
# more elif" (D1 mechanism proliferation, issue #443 evidence 1/2). The
# decision is now an explicit (State, Event) machine:
#   - priority / mutual exclusion live in STAGE_PROBES (ordered event lists)
#   - outcomes live in TRANSITIONS ((State, Event) -> (State, action builder))
#   - a new gate is a table row, never a new elif rung
# Gate SEMANTICS and every action string are byte-identical to the
# pre-refactor chain — proven per-case by tests/test_decide_regression_anchor.py
# (frozen snapshot channel; the live-baseline channel retired 2026-09-05,
# see the re-pin header there).


class State(str, Enum):
    """Machine states: 3 evaluation stages + 6 terminal verdicts.

    SCHEMA  — task_spec schema check (fail-closed first: a malformed
              primary_questions means the convergence target is undefined)
    DRAIN   — opens==0 and partials==0: is the loop REALLY done?
              (#17/M2 completeness + #147 completion transaction)
    SCHEDULE — open/partial work exists: can we dispatch right now?
    Terminal states carry the verdict via VERDICTS."""

    SCHEMA = "SCHEMA"
    DRAIN = "DRAIN"
    SCHEDULE = "SCHEDULE"
    INVALID = "INVALID"
    CONVERGED = "CONVERGED"
    DISPATCH = "DISPATCH"
    DISPATCH_VERIFIER = "DISPATCH_VERIFIER"
    SATURATED = "SATURATED"
    BLOCKED = "BLOCKED"
    PARK = "PARK"  # #634: suspended on external gates — legal idle, wake_condition mandatory


class Event(str, Enum):
    """Gate events, named with LANDED vocabulary only (#446 F-lesson: no
    second taxonomy). Sources: #77 schema, #17/M2 completeness, DESIGN S8
    C0 note layer, #147 discovery/contradiction, #495 failure three-artifact
    protocol, #497 ladder flavors."""

    # SCHEMA stage
    SCHEMA_INVALID = "SCHEMA_INVALID"            # #77 malformed primary_questions
    WORK_PENDING = "WORK_PENDING"                # opens or partials non-empty
    DRAINED = "DRAINED"                          # complementary to WORK_PENDING
    # DRAIN stage (probe order = the historical incident order)
    ORPHAN_TERMINAL_CLAIM = "ORPHAN_TERMINAL_CLAIM"    # M2 completeness gate
    PRIMARY_Q_UNVERIFIED = "PRIMARY_Q_UNVERIFIED"      # M2: BLIND-verified PROVEN, not STAMP
    NOTE_LAYER_GAP = "NOTE_LAYER_GAP"                  # DESIGN §8 C0
    OPEN_HYPOTHESIS_AT_CLOSE = "OPEN_HYPOTHESIS_AT_CLOSE"  # #662 unadjudicated hypothesis gate
    DISCOVERY_UNCONSUMED = "DISCOVERY_UNCONSUMED"     # #147 discovery consumption
    GLOBAL_CONTRADICTION = "GLOBAL_CONTRADICTION"     # #147 completion transaction
    ANOMALY_DETECTED = "ANOMALY_DETECTED"           # #663 anomaly observation gate
    DRAIN_CLEAN = "DRAIN_CLEAN"                        # DRAIN catch-all
    # SCHEDULE stage
    WORK_AND_FREE_SLOT = "WORK_AND_FREE_SLOT"
    PARTIALS_AND_FREE_SLOT = "PARTIALS_AND_FREE_SLOT"
    STUCK_WORKERS_PRESENT = "STUCK_WORKERS_PRESENT"   # #595: silent-detect consumes stuck_workers
    WORK_NO_FREE_SLOT = "WORK_NO_FREE_SLOT"
    FAILURE_ARTIFACTS_DUE = "FAILURE_ARTIFACTS_DUE"    # #495: analysis lacks
    #      validated_capability / identified_obstacle (or is absent/stale)
    LADDER_REQUIRED_BLOCKER = "LADDER_REQUIRED_BLOCKER"    # #497 climb flavor
    LADDER_EXHAUSTED_BLOCKER = "LADDER_EXHAUSTED_BLOCKER"  # #497 exhaustion marker
    UNEXPECTED_STATE = "UNEXPECTED_STATE"                  # SCHEDULE catch-all
    # #670 intake-level (NOT in DRAIN) - the REFUSE verdict aborts intake
    # BEFORE convergence_check starts; the name exists for observability.
    JADX_INFEASIBLE = "JADX_INFEASIBLE"


# Terminal state -> (decision, exit_code). Single binding point: a new
# verdict can no longer drift from its exit code.
VERDICTS = {
    State.INVALID: ("INVALID", EXIT_BLOCKED),
    State.CONVERGED: ("CONVERGED", EXIT_CONVERGED),
    State.DISPATCH: ("DISPATCH", EXIT_DISPATCH),
    State.DISPATCH_VERIFIER: ("DISPATCH_VERIFIER", EXIT_VERIFY),
    State.SATURATED: ("SATURATED", EXIT_SATURATED),
    State.BLOCKED: ("BLOCKED", EXIT_BLOCKED),
    State.PARK: ("PARK", EXIT_PARK),
}


@dataclass
class _DecideInputs:
    """Explicit state object for one decide() call (#443 design §4).

    Everything the old chain kept in scattered locals; the machine's
    predicates and action builders read only this. Lazy scans
    (discovery/contradiction/ladder marker) keep the old cost profile:
    computed only when the machine actually reaches the stage that asks.
    """
    workspace: Path
    opens: list
    partials: list
    active: int
    stuck: list
    done_violations: list
    free_slots: int
    blockers: list
    failure_blocked_ids: list
    orphans: list
    unverified_pqs: list
    pq_note_gaps: list
    pq_error: str | None
    blocked_claims: list
    unblocked_open: list
    failure_blocked_open: list
    _discovery_reason: str | None = field(default=None, repr=False)
    _contradiction_reason: str | None = field(default=None, repr=False)
    _ladder_ids: list | None = field(default=None, repr=False)
    _anomalies: list | None = field(default=None, repr=False)
    _open_hyps: list | None = field(default=None, repr=False)

    def open_hypotheses(self) -> list:
        """#662 unadjudicated-hypothesis gate input (lazy + cached).

        Reads hypothesis_store.HypothesisStore.list_open(). Fail-open on
        LAYER ERRORS ONLY (unreadable dir / parse explosion -> [] -> gate
        silent); genuinely-open hypotheses BLOCK at DRAIN — that is the
        feature (design D5/D7), not a failure mode.
        """
        if self._open_hyps is None:
            hyps: list = []
            try:
                from hypothesis_store import HypothesisStore
                hyps = HypothesisStore(self.workspace / "hypotheses").list_open()
            except Exception:
                hyps = []  # layer error — fail-open per design D7
            self._open_hyps = hyps
        return self._open_hyps

    def anomaly_reason(self) -> list:
        """#663 anomaly observation gate (fail-open per design.md D5).

        Lazy + cached. Returns the anomaly list from scripts/anomaly_detector.
        Fail-open: any import / scan error returns [] (the anomaly detector
        is an informational observation, not a correctness gate — a broken
        anomaly detector MUST NOT block convergence, only the contradiction
        gate may block).
        """
        if self._anomalies is None:
            anomalies: list = []
            try:
                import anomaly_detector as ad  # local import; never block
                anomalies = ad.scan_anomalies(
                    self.workspace / "facts" / "_INDEX.md",
                    self.workspace / "facts",
                )
            except Exception:
                anomalies = []  # fail-open per design.md D5
            self._anomalies = anomalies
        return self._anomalies

    def discovery_reason(self) -> str:
        """#147 discovery scan, cached. Computed only when DRAIN asks for it."""
        if self._discovery_reason is None:
            # replay #1: fact body said 'discovered shellcode, downstream
            # payload not analyzed' and the run converged without the
            # obligation — disclosed payloads must be obligations before
            # CONVERGED is possible.
            reason = ""
            try:
                import obligation_discovery as od
                discoveries = od.scan_discoveries(self.workspace / "facts",
                                                  self.workspace / "claim-register.yaml")
                if discoveries:
                    names = ", ".join(d["trigger"] for d in discoveries)
                    reason = (
                        f"{len(discoveries)} unconsumed discovery(s) in {names} "
                        f"-> create child obligations or record materiality rejection")
            except Exception as exc:
                reason = f"discovery scan unavailable ({type(exc).__name__})"
            self._discovery_reason = reason
        return self._discovery_reason

    def contradiction_reason(self) -> str:
        """#147 completion transaction, cached: CONVERGED is not trusted on
        the register's word — recompute global contradictions from facts/.
        A workspace without a facts index has zero facts and cannot hold a
        contradiction."""
        if self._contradiction_reason is None:
            reason = ""
            if (self.workspace / "facts" / "_INDEX.md").exists():
                try:
                    import fact_contradiction_gate as fcg
                    conflicts = fcg.scan_conflicts(self.workspace / "facts" / "_INDEX.md",
                                                   self.workspace / "facts")
                    if conflicts:
                        pairs = "; ".join(
                            f"{c['fact_a']} <-> {c['fact_b']}" for c in conflicts)
                        reason = f"GLOBAL CONTRADICTION: {pairs}"
                except Exception as exc:  # fail-closed: cannot verify → cannot converge
                    reason = f"contradiction scan unavailable ({type(exc).__name__})"
            self._contradiction_reason = reason
        return self._contradiction_reason

    def ladder_exhausted_ids(self) -> list:
        """#497 ladder-exhaustion marker (ask_for_direction_gate.
        find_ladder_exhaustion): promotion_attempts >= 3 with an empty
        method-ladder candidates list — the only blocker flavor that stays
        must-ask. Consumed ONLY to flavor the all-open-blocked event: both
        ladder flavors share one verdict+action today (decide() does not own
        the must-ask/climb split, #497's ask gate does), so an import
        failure degrades the event label, never the decision (fail-open)."""
        if self._ladder_ids is None:
            try:
                import ask_for_direction_gate as afdg
                ids = list(afdg.find_ladder_exhaustion(self.workspace))
            except Exception:
                ids = []
            open_ids = {c["id"] for c in self.opens}
            self._ladder_ids = [i for i in ids if i in open_ids]
        return self._ladder_ids


def _decide_inputs(workspace: Path) -> _DecideInputs:
    """Snapshot one workspace into the explicit state object (#443 design §4).

    Pure reads, same computation order as the pre-refactor decide() prelude;
    no gate logic lives here."""
    reg = _load_yaml(workspace / "claim-register.yaml")
    task_spec = _load_task_spec(workspace)
    pq_questions, pq_error = _parse_primary_questions(task_spec)
    pq_ids = {qid for qid, _ in pq_questions}

    opens = _open_claims(reg)
    partials = _partial_facts(workspace)
    active, stuck, done_violations = _scan_workers(workspace)
    free_slots = max(0, WORKER_CAP - active)
    blockers = _active_blockers(workspace)
    failure_blocked_ids = _failure_blocked(workspace)

    # M2 completeness gates + note layer (diagnostics regardless of verdict)
    orphans = _orphan_terminal_claims(reg, pq_ids)
    unverified_pqs = _unverified_primary_questions(reg, task_spec)
    pq_note_gaps = _note_layer_gaps(workspace, pq_ids, reg)

    blocked_claims = [c for c in opens if c["blocked"]]
    # unblocked_open = open, not infra-blocked, AND not failure-analysis-blocked
    unblocked_open = [c for c in opens if not c["blocked"] and c["id"] not in failure_blocked_ids]
    failure_blocked_open = [c for c in opens if c["id"] in failure_blocked_ids]

    return _DecideInputs(
        workspace=workspace, opens=opens, partials=partials, active=active,
        stuck=stuck, done_violations=done_violations, free_slots=free_slots,
        blockers=blockers, failure_blocked_ids=failure_blocked_ids,
        orphans=orphans, unverified_pqs=unverified_pqs, pq_note_gaps=pq_note_gaps,
        pq_error=pq_error, blocked_claims=blocked_claims,
        unblocked_open=unblocked_open, failure_blocked_open=failure_blocked_open)


# ---- event predicates (each is ONE gate; composition lives in data) ----

def _pq_schema_invalid(s: _DecideInputs) -> bool:
    # #77: a non-empty malformed primary_questions means the run's
    # convergence target is undefined — escalate, never dispatch against it.
    return bool(s.pq_error)


def _work_pending(s: _DecideInputs) -> bool:
    return bool(s.opens or s.partials)


def _drained(s: _DecideInputs) -> bool:
    return not _work_pending(s)


def _orphan_terminal(s: _DecideInputs) -> bool:
    # M2 completeness gate: CONVERGED requires zero orphan terminal claims.
    return bool(s.orphans)


def _pq_unverified(s: _DecideInputs) -> bool:
    # M2: every primary_question needs a BLIND-verified PROVEN answering claim.
    return bool(s.unverified_pqs)


def _note_layer_gap(s: _DecideInputs) -> bool:
    # DESIGN §8 C0: every pq needs a verify_status=passes note.
    return bool(s.pq_note_gaps)


def _open_hypothesis_at_close(s: _DecideInputs) -> bool:
    # #662: unadjudicated competing explanations at delivery — the exact
    # "contradictory self-report" defect class. Layer errors fail-open
    # (empty list); genuinely-open hypotheses fire (design D5).
    return bool(s.open_hypotheses())


def _discovery_unconsumed(s: _DecideInputs) -> bool:
    # #147: disclosed payloads must be obligations before CONVERGED.
    return bool(s.discovery_reason())


def _global_contradiction(s: _DecideInputs) -> bool:
    # #147: any global contradiction downgrades the completion.
    return bool(s.contradiction_reason())


def _anomaly_detected(s: _DecideInputs) -> bool:
    # #663: anomaly facts observed — informational observation that blocks
    # convergence pending analyst review (co-resident note + verify/refute).
    # Per design.md D5 the gate fires only when anomalies exist; empty
    # baseline (cold-start) returns [] and never blocks.
    return bool(s.anomaly_reason())


def _drain_clean(s: _DecideInputs) -> bool:
    return True  # DRAIN catch-all (tail invariant, see tests)


def _work_and_free_slot(s: _DecideInputs) -> bool:
    return bool(s.unblocked_open) and s.free_slots > 0


def _partials_and_free_slot(s: _DecideInputs) -> bool:
    return bool(s.partials) and s.free_slots > 0


def _stuck_workers_present(s: _DecideInputs) -> bool:
    # #595: silent-detect — collected stuck_workers were never consumed by the
    # machine. Firing here escalates to BLOCKED so orchestrator intervention
    # can resolve instead of looping against a frozen worker.
    return bool(s.stuck)


def _work_no_free_slot(s: _DecideInputs) -> bool:
    return bool(s.unblocked_open) and s.free_slots == 0


def _failure_artifacts_due(s: _DecideInputs) -> bool:
    # #495: claims with a failed attempt whose analysis is absent/stale or
    # lacks validated_capability / identified_obstacle cannot be re-dispatched
    # or marked NEGATIVE until reasoned about.
    return bool(s.failure_blocked_open)


def _all_open_blocked(s: _DecideInputs) -> bool:
    return bool(s.opens) and not s.unblocked_open


def _ladder_exhausted_blocker(s: _DecideInputs) -> bool:
    # #497 marker flavor: blocked-open work where the ladder was climbed.
    return _all_open_blocked(s) and bool(s.ladder_exhausted_ids())


def _ladder_required_blocker(s: _DecideInputs) -> bool:
    # #497 climb flavor: blocked-open work, ladder not (yet) exhausted.
    return _all_open_blocked(s) and not s.ladder_exhausted_ids()


def _unexpected_state(s: _DecideInputs) -> bool:
    return True  # SCHEDULE catch-all (tail invariant, see tests)


_EVENT_PREDICATES = {
    Event.SCHEMA_INVALID: _pq_schema_invalid,
    Event.WORK_PENDING: _work_pending,
    Event.DRAINED: _drained,
    Event.ORPHAN_TERMINAL_CLAIM: _orphan_terminal,
    Event.PRIMARY_Q_UNVERIFIED: _pq_unverified,
    Event.NOTE_LAYER_GAP: _note_layer_gap,
    Event.OPEN_HYPOTHESIS_AT_CLOSE: _open_hypothesis_at_close,
    Event.DISCOVERY_UNCONSUMED: _discovery_unconsumed,
    Event.GLOBAL_CONTRADICTION: _global_contradiction,
    Event.ANOMALY_DETECTED: _anomaly_detected,
    Event.DRAIN_CLEAN: _drain_clean,
    Event.WORK_AND_FREE_SLOT: _work_and_free_slot,
    Event.PARTIALS_AND_FREE_SLOT: _partials_and_free_slot,
    Event.STUCK_WORKERS_PRESENT: _stuck_workers_present,
    Event.WORK_NO_FREE_SLOT: _work_no_free_slot,
    Event.FAILURE_ARTIFACTS_DUE: _failure_artifacts_due,
    Event.LADDER_REQUIRED_BLOCKER: _ladder_required_blocker,
    Event.LADDER_EXHAUSTED_BLOCKER: _ladder_exhausted_blocker,
    Event.UNEXPECTED_STATE: _unexpected_state,
}


# ---- action builders (strings byte-identical to the pre-#443 chain) ----

def _act_invalid(s: _DecideInputs) -> str:
    return f"INVALID task_spec primary_questions: {s.pq_error}"


def _act_orphans(s: _DecideInputs) -> str:
    orphan_ids = [o["id"] for o in s.orphans]
    return (f"Cannot CONVERGE: {len(s.orphans)} orphan terminal claim(s) {orphan_ids} "
            f"have no answers_question -> link them to a primary_question or reopen.")


def _act_pq_unverified(s: _DecideInputs) -> str:
    uv_ids = [u["question"] for u in s.unverified_pqs]
    return (f"Cannot CONVERGE: primary_questions {uv_ids} lack PROVEN answering claims "
            f"(need BLIND-verified PROVEN, not STAMP/unverified). "
            f"Dispatch verifier or rework answering claims.")


def _act_note_gap(s: _DecideInputs) -> str:
    return (f"Note-layer (DESIGN S8 C0) not satisfied: primary_questions {s.pq_note_gaps} "
            f"lack a note with verify_status=passes (link: note.claim_id -> claim.answers_question). "
            f"Run verify-note.py before delivery.")


def _scan_proven_facts(workspace: Path) -> dict[str, str]:
    """Lightweight _INDEX scan for PROVEN fact id->conclusion map (fail-open).

    Same pattern as _partial_facts (line 164). No schema validation, no YAML
    parsing, no exceptions on malformed rows."""
    idx = workspace / "facts" / "_INDEX.md"
    if not idx.exists():
        return {}
    proven: dict[str, str] = {}
    try:
        text = idx.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        if parts[1].upper() == "PROVEN":
            proven[parts[0]] = parts[3]
    return proven


# Negation keywords for Path B (candidate heuristic). Lowercase; matched
# after lowercasing the conclusion text.
_NEGATION_KEYWORDS = ("not ", "never ", "rather than ", "instead of ", "is not ", "are not ")


def _detect_contradiction(hyp_body: str, candidates: list[str],
                          proven: dict[str, str]) -> str | None:
    """Return an annotation snippet if hyp_body / candidates are contradicted
    by a PROVEN fact, else None.

    Path A — explicit PROVEN fact reference in hypothesis body:
      scans hyp_body for F<digits> patterns, verifies each is in `proven`.
    Path B — candidate negation heuristic:
      for each PROVEN fact conclusion containing a negation keyword,
      checks whether a candidate appears after the negation keyword.
    Both paths are fail-open: any exception produces None."""
    try:
        # Path A: explicit fact ID in body
        for m in re.finditer(r"F[-\s]?(\d+)", hyp_body):
            fid = f"F{m.group(1)}"
            if fid in proven:
                snippet = proven[fid][:80]
                return f"Contradicted: {fid} (conclusion: {snippet})"
        # Path B: candidate negation
        for fid, conclusion in proven.items():
            lc = conclusion.lower()
            for kw in _NEGATION_KEYWORDS:
                idx2 = lc.find(kw)
                if idx2 >= 0:
                    after = lc[idx2 + len(kw):].rstrip(".,;")
                    for cand in candidates:
                        if cand.lower() == after:
                            snippet = conclusion[:80]
                            return f"Contradicted: {fid} ({kw.rstrip()} {cand}, conclusion: {snippet})"
    except Exception:
        pass
    return None


def _act_open_hypothesis(s: _DecideInputs) -> str:
    hyps = s.open_hypotheses()
    ids = ", ".join(h.id for h in hyps)
    base = (f"Cannot CONVERGE: {len(hyps)} open hypothesis(ies) {ids} — "
            f"adjudicate before delivery (refute via refuting_fact_id / "
            f"supersede via superseded_by, per #528 state machine). Scaffold "
            f"candidates=[] must be filled or refuted.")
    # Scan PROVEN facts for contradiction annotations
    try:
        proven = _scan_proven_facts(s.workspace)
    except Exception:
        proven = {}
    annotations: list[str] = []
    for h in hyps:
        ann = _detect_contradiction(h.body, h.candidates, proven)
        if ann:
            annotations.append(f"  {h.id}: {ann}")
    if annotations:
        return base + "\n" + "\n".join(annotations)
    return base


def _act_discovery(s: _DecideInputs) -> str:
    return f"Cannot CONVERGE: {s.discovery_reason()}"


def _act_contradiction(s: _DecideInputs) -> str:
    return (f"Cannot CONVERGE: {s.contradiction_reason()} -> resolve via "
            f"fact_contradiction_gate or supersedes links.")


def _act_anomaly(s: _DecideInputs) -> str:
    anomalies = s.anomaly_reason()
    items = "; ".join(
        f"{a['fact_id']} score={a['score']:.3f} ({a['top_dimension']})"
        for a in anomalies
    )
    return (f"Cannot CONVERGE: {len(anomalies)} anomaly fact(s) above threshold "
            f"(review or refute; co-resident notes in notes/<fact_id>.md): {items}")


def _act_converged(s: _DecideInputs) -> str:
    return ("Claim loop done - all open claims closed, partials verified, primary_questions PROVEN "
            "with verify_status=passes notes, completion transaction clean (zero global "
            "contradictions, zero unconsumed discoveries, PROVEN provenance). STOP dispatch; deliver")


def _act_dispatch_top(s: _DecideInputs) -> str:
    return (f"Run priority_ratio.py and dispatch the top claim. "
            f"{len(s.unblocked_open)} unblocked open claim(s), {s.free_slots} free slot(s).")


def _act_verify_partials(s: _DecideInputs) -> str:
    return (f"Dispatch a verifier for {len(s.partials)} partial fact(s). "
            f"Do NOT declare PROVEN without sign-off.")


def _act_saturated_queue(s: _DecideInputs) -> str:
    return (f"All {WORKER_CAP} slots busy with {len(s.unblocked_open)} open claim(s) queued. "
            f"Poll workers - do not wait idly.")


def _act_stuck_workers(s: _DecideInputs) -> str:
    """#595: a worker older than STUCK_MINUTES is the loud signal we were
    silently collecting. Escalate to BLOCKED + drop a per-workspace
    ``runs/.stuck-report.md`` so the orchestrator can see WHICH worker is
    stuck and for HOW LONG. Report write is non-fatal (try/except) — the
    state machine must still return a verdict even on a read-only filesystem
    or a permission error. Order probe (SCHEDULE index 2) gates this: it
    fires BEFORE WORK_NO_FREE_SLOT/FAILURE/LADDER/UNEXPECTED, so a stuck
    worker always wins over those flavors.

    #11 composition: stuck entries flagged ``dead`` (silent >
    DEAD_WORKER_MINUTES — the worker is GONE, backtrack_gate territory ends)
    additionally get a death record with the artifact snapshot
    (runs/.worker-death-<stem>.json) BEFORE the reopen, so the report, the
    summary, and the reopened claim's history line all reference it: the
    resume contract is continue-from-the-snapshot, not redo-from-zero."""
    stems = ", ".join(f"{w['worker']} ({w['age_min']}m)" for w in s.stuck)
    summary = (f"Stuck worker(s) detected: {stems}. "
               f"Older than {_load_worker_lib().STUCK_MINUTES}m with status "
               f"in-progress. Orchestrator intervention required before any "
               f"further dispatch.")
    dead = [w for w in s.stuck if w.get("dead")]
    death_paths: list = []
    if dead:
        try:
            death_paths = _worker_death.write_death_records(s.workspace, dead)
        except OSError:
            death_paths = []
    try:
        report = s.workspace / "runs" / ".stuck-report.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"# Stuck Workers Report (#595)", ""]
        lines.append(f"Workspace: {s.workspace}")
        lines.append(f"Detected: {len(s.stuck)} worker(s) older than "
                     f"{_load_worker_lib().STUCK_MINUTES}m still in-progress.")
        lines.append("")
        lines.append("## Workers")
        for w in s.stuck:
            suffix = ""
            if w.get("dead"):
                suffix = (f" — **DEAD** (silent > {_DEAD_WORKER_MINUTES}m, "
                          f"death record: runs/"
                          f"{_worker_death.RECORD_NAME.format(stem=w['worker'])})")
            lines.append(f"- **{w['worker']}** — age {w['age_min']} min{suffix}")
        lines.append("")
        if dead:
            lines.append("## Dead workers (#11)")
            for w in dead:
                rec = _worker_death.record_path(s.workspace, w["worker"])
                lines.append(f"- **{w['worker']}** — gone (no writes > "
                             f"{_DEAD_WORKER_MINUTES}m). Death record: "
                             f"{rec.name} carries the artifact snapshot "
                             f"(已完成产物清单).")
            lines.append("")
        lines.append("## Action")
        lines.append("Investigate each worker above. Either: (a) restart the "
                     "worker if it is genuinely hung, or (b) close the worker "
                     "if the claim should be re-dispatched. Do NOT dispatch "
                     "more work while stuck workers remain.")
        if dead:
            lines.append("")
            lines.append("### Death-resume contract (#11)")
            lines.append("For each DEAD worker above: its claim was flipped "
                         "back to OPEN with the death record referenced. "
                         "Dispatch a RESUME claim that reads the death "
                         "record's artifacts list first — verify and absorb "
                         "the existing products, continue from where the "
                         "worker died. Do NOT redo from zero.")
        report.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        # Non-fatal: the verdict and summary still surface to the caller.
        pass
    if dead:
        # #11: the guidance line matters as much as the mechanism — name the
        # records and the continue-from contract right in the decide summary.
        rec_names = ", ".join(
            f"runs/{_worker_death.RECORD_NAME.format(stem=w['worker'])}"
            for w in dead)
        summary += (f" Dead worker(s) (no writes > {_DEAD_WORKER_MINUTES}m): "
                    f"{len(dead)}. Death record(s) with artifact snapshot: "
                    f"{rec_names}. Resume contract: dispatch a RESUME claim "
                    f"referencing the artifacts list — continue from where "
                    f"the worker died, do not redo from zero.")
        if death_paths:
            summary += f" ({len(death_paths)} record(s) written this scan.)"
    # #607 闭环: a stuck worker must FREE its claim — claim_expiry covers
    # IN_PROGRESS but has zero mechanical callers, so the loop had NO machine
    # path out of IN_PROGRESS. Reopen stuck workers' IN_PROGRESS claims →
    # OPEN with an audit comment. Fail-open: register IO must not block the
    # verdict. Never touches PROVEN/terminal claims.
    try:
        reopened = _reopen_stuck_claims(s)
        if reopened:
            summary += (f" Reopened {len(reopened)} stuck IN_PROGRESS claim(s) "
                        f"→ OPEN for re-dispatch: {', '.join(reopened)}.")
    except OSError:
        pass
    return summary


def _reopen_stuck_claims(s: _DecideInputs) -> list[str]:
    """#607: map stuck worker stems → claim ids → flip IN_PROGRESS → OPEN.

    Worker stem convention is ``worker-status-<claim-ish>-<suffix>``; match by
    prefix (``worker-status-C-400*`` → claim ``C-400``). Returns the reopened
    claim ids; OSError family propagates to the caller's fail-open.
    #11: claims reopened from DEAD workers get a death-record-referencing
    history line — that reference IS the resume signal."""
    import yaml as _yaml
    reg = s.workspace / "claim-register.yaml"
    if not reg.exists():
        return []
    data = _yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    claims = data.get("claims") or []
    prefixes = []
    dead_prefixes: dict[str, str] = {}
    for w in s.stuck:
        stem = w["worker"].removeprefix("worker-status-")
        # strip ONE trailing retry/version token (C-400v2 → C-400, C400v2 →
        # C400) but never the id's own digits (C-400 stays C-400: only a
        # trailing [vV]<digits> suffix or a separate hyphenated numeric tail
        # is removed).
        m = re.search(r"^(.*?)[vV]\d+$", stem) or re.search(r"^(.*)-\d+$", stem)
        pfx = m.group(1) if m and m.group(1) else stem
        prefixes.append(pfx)
        if w.get("dead"):
            dead_prefixes[_worker_death.norm_key(pfx)] = w["worker"]
    reopened: list[str] = []
    now = utc_now()
    norm = lambda x: x.replace("-", "").replace("_", "").lower()
    for c in claims:
        cid = c.get("id")
        if not cid or c.get("status") != "IN_PROGRESS":
            continue
        # shape-insensitive compare: C400 ≡ C-400 (worker stems drop the id's hyphen)
        matched_dead = next((stem for pfx_key, stem in dead_prefixes.items()
                             if norm(cid) == pfx_key
                             or norm(cid).startswith(pfx_key)
                             or pfx_key.startswith(norm(cid))), None)
        if any(norm(cid) == norm(p) or norm(cid).startswith(norm(p))
               or norm(p).startswith(norm(cid)) for pfx in prefixes for p in [pfx]):
            c["status"] = "OPEN"
            hist = c.setdefault("history", [])
            if matched_dead:
                hist.append(
                    f"#11 death-resume reopened from IN_PROGRESS (worker dead; "
                    f"record: runs/"
                    f"{_worker_death.RECORD_NAME.format(stem=matched_dead)}) "
                    f"{now}")
            else:
                hist.append(f"#607 reopened from IN_PROGRESS (worker stuck) {now}")
            reopened.append(cid)
    if reopened:
        data["_audit"] = (data.get("_audit") or []) + [
            f"#607 stuck-worker reopen: {', '.join(reopened)} @ {now}"]
        reg.write_text(_yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return reopened


def _act_failure_analysis(s: _DecideInputs) -> str:
    return (f"{len(s.failure_blocked_open)} claim(s) have a failed attempt with no "
            f"failure_analysis: {s.failure_blocked_ids}. "
            f"Run failure_analysis_gate.py <ws> to reason about WHY the method failed before "
            f"re-dispatch or NEGATIVE.")


def _act_all_blocked(s: _DecideInputs) -> str:
    # Shared by both #497 ladder flavors (same verdict today; the flavor
    # split point for a future must-ask/climb fork is one table row).
    return (f"All {len(s.opens)} open claim(s) are blocked. "
            f"Resolve blockers: {s.blockers or 'none on disk'}.")


def _act_unexpected(s: _DecideInputs) -> str:
    return "Unexpected state - investigate manually."


# ---- the declared composition: probe order + transitions (all data) ----

STAGE_PROBES = {
    # SCHEMA: fail-closed schema check FIRST (a malformed convergence target
    # must never reach dispatch), then the work/drain fork.
    State.SCHEMA: [Event.SCHEMA_INVALID, Event.WORK_PENDING, Event.DRAINED],
    # DRAIN: the pre-#443 completion-transaction order, frozen by the
    # regression anchor (orphan > unverified > note-gap > discovery >
    # contradiction > clean).
    State.DRAIN: [Event.ORPHAN_TERMINAL_CLAIM, Event.PRIMARY_Q_UNVERIFIED,
                  Event.NOTE_LAYER_GAP, Event.OPEN_HYPOTHESIS_AT_CLOSE,
                  Event.DISCOVERY_UNCONSUMED,
                  Event.GLOBAL_CONTRADICTION, Event.ANOMALY_DETECTED,
                  Event.DRAIN_CLEAN],
    # SCHEDULE: dispatchable work first, then saturation, then WHY nothing
    # is dispatchable (#495 failure artifacts, #497 ladder flavors), then
    # the catch-all (reachable: opens==0 + partials>0 + slots==0).
    # #595: STUCK_WORKERS_PRESENT at index 2 — silent-detect fires BEFORE
    # the saturation/failure/ladder tail so a stuck worker can never be
    # masked by an unblocked-open claim whose dispatch would collide.
    State.SCHEDULE: [Event.WORK_AND_FREE_SLOT, Event.PARTIALS_AND_FREE_SLOT,
                     Event.STUCK_WORKERS_PRESENT, Event.WORK_NO_FREE_SLOT,
                     Event.FAILURE_ARTIFACTS_DUE,
                     Event.LADDER_EXHAUSTED_BLOCKER, Event.LADDER_REQUIRED_BLOCKER,
                     Event.UNEXPECTED_STATE],
}

TRANSITIONS = {
    (State.SCHEMA, Event.SCHEMA_INVALID): (State.INVALID, _act_invalid),
    (State.SCHEMA, Event.WORK_PENDING): (State.SCHEDULE, None),
    (State.SCHEMA, Event.DRAINED): (State.DRAIN, None),
    (State.DRAIN, Event.ORPHAN_TERMINAL_CLAIM): (State.BLOCKED, _act_orphans),
    (State.DRAIN, Event.PRIMARY_Q_UNVERIFIED): (State.SATURATED, _act_pq_unverified),
    (State.DRAIN, Event.NOTE_LAYER_GAP): (State.DISPATCH_VERIFIER, _act_note_gap),
    (State.DRAIN, Event.OPEN_HYPOTHESIS_AT_CLOSE): (State.BLOCKED, _act_open_hypothesis),
    (State.DRAIN, Event.DISCOVERY_UNCONSUMED): (State.DISPATCH, _act_discovery),
    (State.DRAIN, Event.GLOBAL_CONTRADICTION): (State.BLOCKED, _act_contradiction),
    (State.DRAIN, Event.ANOMALY_DETECTED): (State.BLOCKED, _act_anomaly),
    (State.DRAIN, Event.DRAIN_CLEAN): (State.CONVERGED, _act_converged),
    (State.SCHEDULE, Event.WORK_AND_FREE_SLOT): (State.DISPATCH, _act_dispatch_top),
    (State.SCHEDULE, Event.PARTIALS_AND_FREE_SLOT): (State.DISPATCH_VERIFIER, _act_verify_partials),
    (State.SCHEDULE, Event.STUCK_WORKERS_PRESENT): (State.BLOCKED, _act_stuck_workers),
    (State.SCHEDULE, Event.WORK_NO_FREE_SLOT): (State.SATURATED, _act_saturated_queue),
    (State.SCHEDULE, Event.FAILURE_ARTIFACTS_DUE): (State.BLOCKED, _act_failure_analysis),
    (State.SCHEDULE, Event.LADDER_REQUIRED_BLOCKER): (State.BLOCKED, _act_all_blocked),
    (State.SCHEDULE, Event.LADDER_EXHAUSTED_BLOCKER): (State.BLOCKED, _act_all_blocked),
    (State.SCHEDULE, Event.UNEXPECTED_STATE): (State.SATURATED, _act_unexpected),
}

# SCHEMA -> one stage -> verdict; the bound is a cycle guard, not a semantic.
_MACHINE_MAX_STEPS = 4


def _run_machine(snap: _DecideInputs):
    """Drive the declared machine over one snapshot: probe the stage's
    events in STAGE_PROBES order, take the first fire, follow TRANSITIONS,
    stop at a verdict state. Fail-closed on table gaps → the pre-#443
    'Unexpected state' fallback (never silently report progress)."""
    state = State.SCHEMA
    for _ in range(_MACHINE_MAX_STEPS):
        event = None
        for candidate in STAGE_PROBES[state]:
            if _EVENT_PREDICATES[candidate](snap):
                event = candidate
                break
        transition = TRANSITIONS.get((state, event)) if event is not None else None
        if transition is None:
            break  # undeclared (state, event): conservative fallback below
        state, build_action = transition
        if state in VERDICTS:
            return state, build_action(snap)
    return State.SATURATED, _act_unexpected(snap)


def decide(workspace: Path, *, emit_snapshot: bool = True) -> dict:
    snap = _decide_inputs(workspace)
    state, action = _run_machine(snap)
    decision, exit_code = VERDICTS[state]
    decision = {
        "decision": decision,
        "exit_code": exit_code,
        "action": action,
        "open_claims": snap.opens,
        "open_count": len(snap.opens),
        "unblocked_open_count": len(snap.unblocked_open),
        "blocked_open_count": len(snap.blocked_claims),
        "failure_blocked": snap.failure_blocked_ids,
        "partial_facts": snap.partials,
        "partial_count": len(snap.partials),
        "anomalies": snap.anomaly_reason(),
        "anomaly_count": len(snap.anomaly_reason()),
        "open_hypotheses": [{"id": h.id, "claim_id": h.claim_id,
                             "competitor_group": h.competitor_group}
                            for h in snap.open_hypotheses()],
        "open_hypothesis_count": len(snap.open_hypotheses()),
        "active_workers": snap.active,
        "free_slots": snap.free_slots,
        "worker_cap": WORKER_CAP,
        "stuck_workers": snap.stuck,
        # W-15 (#444): workers reporting done whose declared artifacts: files
        # are missing / explicitly none. Diagnostic field — decision branches
        # untouched. schema-safe:
        # schemas/convergence-check-output.json additionalProperties: true.
        "done_artifact_violations": snap.done_violations,
        "active_blockers": snap.blockers,
        # M2 completeness diagnostics
        "orphan_claims": snap.orphans,
        "unverified_primary_qs": snap.unverified_pqs,
        "note_layer_gaps": snap.pq_note_gaps,
        "pq_parse_error": snap.pq_error,
    }
    # #634 Part A: PARK — every open claim waits on an EXTERNAL gate
    # (blocker external:true), no active workers, no partials pending.
    # That is legal idle, not a coerced BLOCKED/DISPATCH that burns ticks
    # on dispatch_gate rejections. Emits reason + wake_condition drawn
    # from the external blockers (revive via mission_stall.revive).
    if decision["decision"] in ("BLOCKED", "DISPATCH"):
        try:
            reg_p = _load_yaml(Path(workspace) / "claim-register.yaml")
            opens_p = [c for c in (reg_p.get("claims") or [])
                       if str(c.get("status") or "").upper() == "OPEN"]
            ext = [c for c in opens_p
                   if c.get("blocked") and c.get("external")]
            if (opens_p and len(ext) == len(opens_p)
                    and not snap.partials and snap.active == 0):
                wake = "; ".join(
                    f"{c.get('id')}: {c.get('blocker')}" for c in ext)
                decision["decision"] = "PARK"
                decision["exit_code"] = EXIT_PARK
                decision["reason"] = ("all open claims gated on external "
                                      "blockers; no active workers; no "
                                      "pending partials")
                decision["wake_condition"] = wake
        except Exception:  # noqa: BLE001 — downgrade is advisory-safe
            pass
    # #634: mission-level stall fingerprint — ΔV_m flat K checkpoints while
    # open work remains. Proposal semantics: annotate + emit, never mutate
    # the verdict (P3's Q-table consumes it for ordering). Key attached ONLY
    # when stalled (byte-frozen anchors stay identical otherwise — #829
    # conditional-key precedent).
    try:
        from mission_stall import stall_mission
        ms = stall_mission(workspace)
        if ms.get("stalled"):
            decision["mission_stall"] = ms
            # #823-P3: stall response face — THINK bet guidance (always-on
            # since #51). Conditional-key (anchored snapshots stay identical
            # when no stall is present).
            try:
                from think_seat import bets_owed as _bets_owed
                decision["stall_response"] = {
                    "bets_owed": _bets_owed(Path(workspace)),
                    "guidance": ("stall confirmed - file a falsifiable "
                                 "bet via think_seat.file_bet "
                                 "(predicted_observation required); the "
                                 "bet leads the next dispatch"),
                }
            except Exception:  # noqa: BLE001 — advisory face only
                pass
            if emit_snapshot:
                from kunglao_log import emit as _emit_stall
                _emit_stall(workspace, actor="convergence_check",
                            action="mission_stall",
                            detail=json.dumps(ms, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — fingerprint unavailable → no annotation
        pass
    # #823 A2: N-arm first-order value signals — shadow posture (always-on
    # since #51: the dict gains the `value_signals` key and one shadow emit).
    import rho_checkpoint
    # #829: cross-carrier consistency — CONVERGED may not stand on drifting
    # carriers. Checker exception counts as drift (fail-closed for the
    # CONVERGED verdict only; other decisions unaffected, no deadlock).
    if decision["decision"] == "CONVERGED":
        try:
            from carrier_consistency import check as _carrier_check
            cv = _carrier_check(workspace)
        except Exception as exc:  # noqa: BLE001 — drift includes checker error
            cv = {"ok": False,
                  "violations": ["(x) carrier checker error: " + str(exc)]}
        if not cv.get("ok", True):
            if emit_snapshot:
                from kunglao_log import emit as _emit_drift
                _emit_drift(workspace, actor="convergence_check",
                            action="carrier_drift",
                            detail=json.dumps(
                                {"violations": cv["violations"]},
                                ensure_ascii=False))
            decision["decision"] = "DISPATCH"
            decision["exit_code"] = 1
            decision["carrier_drift"] = cv["violations"]
    # #618: dead-window alarm off the durable heartbeat sidecar (#830
    # substrate). Annotation + event only — never mutates the verdict
    # (unattended dead-window must be VISIBLE, and P3's value ordering
    # consumes the signal). alarm=None (no sidecar) stays silent — absence
    # of a heartbeat face is a registration-check verdict, not deadness.
    try:
        from heartbeat import gap_alarm as _gap_alarm
        gap = _gap_alarm(Path(workspace))
    except Exception:  # noqa: BLE001 — advisory-safe, never deadlock decide
        gap = None
    if gap is not None and gap.get("alarm") is True:
        decision["heartbeat_gap"] = gap
        if emit_snapshot:
            from kunglao_log import emit as _emit_gap
            _emit_gap(workspace, actor="convergence_check",
                      action="heartbeat_gap",
                      detail=json.dumps(gap, ensure_ascii=False))
    # emit_snapshot=False (resume's #466 read-only contract) must quiesce
    # the #51 always-on recording too: signals are computed and attached
    # identically, but the value/rho persistence stays off (#51 regression:
    # resume appended rho rows + wrote runs/infeasible-state.json).
    result = rho_checkpoint.attach_signals(workspace, decision,
                                           emit=emit_snapshot)
    if emit_snapshot:
        _emit_decision_snapshot(workspace, result)
    return result


def _emit_decision_snapshot(ws, d: dict) -> None:
    """#818 batch-1: ONE decision_snapshot event per verdict (actor=
    convergence_check): claims status counts + top-5 priority (id, score).
    Fail-open — logging must never block the decision (#287 contract)."""
    try:
        reg = _load_yaml(Path(ws) / "claim-register.yaml")
        claims = reg.get("claims") or []
        counts: dict = {}
        for c in claims:
            st = (c.get("status") or "UNKNOWN").upper()
            counts[st] = counts.get(st, 0) + 1
        top: list = []
        try:
            import priority_ratio as pr
            rows = pr.priority_ratio(claims, {}, pr.EvidenceView())
            top = [{"id": r.claim_id, "score": round(float(r.score), 4)}
                   for r in rows[:5]]
        except Exception:
            top = []
        from kunglao_log import emit
        emit(ws, actor="convergence_check", action="decision_snapshot",
             detail=json.dumps({
                 "decision": d.get("decision"),
                 "status_counts": counts,
                 "top_priorities": top,
             }, ensure_ascii=False))
    except Exception:
        pass


def _human(d: dict) -> str:
    lines = []
    lines.append(f"=== CONVERGENCE CHECK: {d['decision']} ===")
    lines.append(f"action: {d['action']}")
    lines.append("")
    lines.append(f"open claims:    {d['open_count']} ({d['unblocked_open_count']} unblocked, {d['blocked_open_count']} blocked)")
    lines.append(f"partial facts:  {d['partial_count']}")
    lines.append(f"workers:        {d['active_workers']}/{d['worker_cap']} active -> {d['free_slots']} free slot(s)")
    if d["stuck_workers"]:
        lines.append(f"stuck (> {_load_worker_lib().STUCK_MINUTES}m): {d['stuck_workers']}")
    if d.get("done_artifact_violations"):
        w15 = [f"{v['worker']} ({v['kind']}: {', '.join(v['missing']) or 'no files'})"
               for v in d["done_artifact_violations"]]
        lines.append(f"w15 (done without files): {'; '.join(w15)}")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="kunglao-agent convergence check - should I dispatch?")
    parser.add_argument("workspace", nargs="?", default=None, help="workspace root")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    workspace = _resolve_ws(args.workspace)
    if not (workspace / "claim-register.yaml").exists():
        print(f"FAIL: no claim-register.yaml under {workspace}", file=sys.stderr)
        return 64

    d = decide(workspace)
    _append_ledger(workspace, d)  # silent side channel for convergence_health.py
    # #287 observability: mirror the convergence decision to the structured
    # event log. #459: detail now carries the decision plus the counts a
    # `kunglao_log --tail` diagnosis needs (no second read of the register).
    # Guarded — logging must never block the decision.
    try:
        from kunglao_log import emit
        emit(workspace, actor="orchestrator", action="converge",
             detail=(f"{d['decision']} open={d['open_count']} "
                     f"partial={d['partial_count']} slots={d['free_slots']} "
                     f"workers={d['active_workers']}"),
             exit=d["exit_code"])
    except Exception:
        pass
    if args.json:
        print(json.dumps(d, indent=2, ensure_ascii=False))
    else:
        print(_human(d))
    return d["exit_code"]


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
