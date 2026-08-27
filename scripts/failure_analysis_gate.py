#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""failure_analysis_gate.py - force method reasoning after a failed attempt (v2.0.0).

THE PROBLEM THIS SOLVES (user's exact words, in Chinese):
  "目前我们要分析 c2 的网络协议,但是目前失败了,你能说没有网络协议行为,
   然后不分析吗?但是之前的分析办法可能存在问题,这个就需要分析,然后优化"
  ("we need to analyze the C2 network protocol, but it failed so far — can
   you declare there is no network-protocol behavior and stop analyzing?
   But the previous analysis method may itself be flawed; that needs
   analysis and improvement")

A failed analysis attempt is NOT evidence the behavior is absent. It is evidence
the METHOD failed — possibly. The orchestrator must NOT collapse "method failed"
into "sample doesn't do X". Before re-dispatching OR concluding NEGATIVE, it must
reason about WHY the method failed.

This gate does NOT give a fixed taxonomy of failure types (that would be a
checklist the agent picks from without thinking). It forces THREE QUESTIONS whose
answers the agent must generate from the specific situation:

  1. method_assumption   — what did the failed method assume would happen?
  2. assumption_validity — is that assumption justified given what we know?
                           (if not → method failed, not behavior absent)
  3. next_method         — what DIFFERENT method tests a different assumption?
                           (literal "retry the same thing" is forbidden here)

Only if the agent can argue assumption_validity = "justified, method was adequate"
may the claim be marked NEGATIVE — and even then it carries single-method
confidence (a different method can overturn it later).

v2.0.0 (#495 failure→knowledge transducer): the three questions alone are
prose that evaporates — v0.1.1 trajectory-1 had decomposition-level evidence
(JNI bridge works, spawn timeout kills only the spawn path) that never
reached the model because it lived in narrative. A record now must also
carry the THREE FAILURE ARTIFACTS:

  4. validated_capability — what this failure PROVED works (capability ✓)
  5. identified_obstacle  — what specifically blocked you; auto-promoted
                           to a NEW claim (depends_on the failed claim,
                           inherits answers_question) — the DAG grows a node
  6. next_method_source   — provenance of the next method: lesson-hit |
                           reference-hit | web-hit | novel-hypothesis

Recording a failure automatically runs the method-ladder rung the gate can
run mechanically: the lessons library is searched with the obstacle +
assumption error signature (same keyword interface as --search); hits land
in the entry's `candidates`, the query in `method_ladder_query` (auditable).
The search is FAIL-OPEN — a missing library or a crashed search never
blocks the record. `novel-hypothesis` additionally requires non-empty
candidates: at least the lessons rung must have a recorded hit before a
novel experiment may be declared (it occupies budget).

Enforcement: a claim with a prior failed attempt (promotion_attempts > 0,
status non-terminal) that has NO current failure_analysis — or whose
analysis is missing either artifact — is BLOCKED. The orchestrator cannot
re-dispatch through the normal flow until the analysis is recorded.

Each failed attempt needs its own analysis (covers_attempt versioning) — you can't
coast on the reasoning from attempt 1 when attempt 3 also fails.

Usage:
  # check mode — which claims need analysis?
  python scripts/failure_analysis_gate.py <workspace>

  # check one claim
  python scripts/failure_analysis_gate.py <workspace> <C-NN>

  # record an analysis (unblocks re-dispatch or NEGATIVE conclusion)
  python scripts/failure_analysis_gate.py <workspace> <C-NN> --record \
      --assumption "what the failed method assumed" \
      --validity "not-justified | justified-adequate" \
      --next-method "what different method to try (or 'method was adequate' for true negative)" \
      --validated-capability "what this failure PROVED works (#495)" \
      --identified-obstacle "what specifically blocked you (#495, auto-promoted to a claim)" \
      --source "lesson-hit | reference-hit | web-hit | novel-hypothesis (#495)"

  # fill the outcome at claim closure (adds --outcome/--what-happened to the
  # recorded analysis; prior assumption/validity/next_method are preserved)
  python scripts/failure_analysis_gate.py <workspace> <C-NN> --record \
      --outcome "PROVEN | VERIFIED | REFUTED | NEGATIVE" \
      --what-happened "free text: what actually happened"

  # aggregate closed-loop analyses into the global lessons library (#41)
  python scripts/failure_analysis_gate.py <workspace> --lessons \
      [--library DIR] [--reflect-queue FILE]

  # search the lessons library by keywords/claim-tag (no embeddings)
  python scripts/failure_analysis_gate.py --search "frida vm" [--library DIR]

Exit codes:
  0 = OK (no failed attempt pending, or analysis covers it)
  1 = BLOCKED (failed attempt, analysis missing or stale)
  2 = claim not found or terminal (no analysis needed)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from status_defs import TERMINAL

ANALYSES_DIR = "analyses"

# #41: aggregation reads the #35 ledger OUTCOME rows to decide whether a
# NEGATIVE survived red-team (checker=red-team, result=CONFIRMED).
LEDGER_NAME = ".convergence_ledger.jsonl"

# Closed-loop outcomes eligible for the lessons library. Tuple constant on
# purpose — no status-set literal here (test_status_defs grep guard).
OUTCOME_VALUES = ("PROVEN", "VERIFIED", "REFUTED", "NEGATIVE")

# #495: provenance of next_method. The method-ladder is lessons retrieval ->
# re-library retrieval -> WebSearch error signature -> novel hypothesis; the
# gate mechanically runs ONLY the lessons rung (record-time auto-search) —
# rungs 2/3 are declared, the enum + novel precondition are enforced here.
# Tuple constant on purpose (same grep-guard convention as OUTCOME_VALUES).
SOURCE_VALUES = ("lesson-hit", "reference-hit", "web-hit", "novel-hypothesis")

# #41: the lessons library is GLOBAL (cross-sample), never per-workspace —
# default <skill>/references/lessons/ next to case-book.md. --library and
# --reflect-queue override both paths so tests run entirely against tmp.
LESSONS_DIR_DEFAULT = Path.home() / ".claude" / "skills" / "kunglao-agent" / "references" / "lessons"
REFLECT_QUEUE_DEFAULT = Path.home() / ".claude" / "learnings-queue.json"
REFLECT_ITEM_TYPE = "failure-lesson-candidate"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _emit_failure_blocked(workspace: Path, d: dict) -> None:
    """#287/#459 observability: log the gate trigger to the structured event
    log. #495 split (#459): a BLOCKED whose analysis is missing the three
    failure artifacts emits analysis_blocked with the missing list (the
    Orient layer's direct to-do); a pure stale-coverage BLOCKED
    (covers_attempt lags, artifacts all present) keeps failure_blocked —
    one event per BLOCKED, the word carries the reason.

    Guarded — logging must never break the gate (a failed analysis run keeps
    its exit code and BLOCKED output even if the log write fails).
    """
    try:
        from kunglao_log import emit
        missing = d.get("missing_artifacts") or []
        if missing:
            emit(workspace, actor="orchestrator", action="analysis_blocked",
                 claim=d.get("claim_id"),
                 detail=f"missing_artifacts={','.join(missing)} "
                        f"attempts={d.get('promotion_attempts')}")
        else:
            emit(workspace, actor="orchestrator", action="failure_blocked",
                 claim=d.get("claim_id"),
                 detail=f"status={d.get('status')} "
                        f"attempts={d.get('promotion_attempts')}")
    except Exception:
        pass


def _emit_analysis_recorded(workspace: Path, claim_id: str, entry: dict) -> None:
    """#459: the three-artifact LANDING event — what #495 put on disk,
    what the Orient layer (#498) consumes. detail carries the next-method
    provenance and the method-ladder candidate count. Fail-open by contract
    (a record is never undone by a log failure)."""
    try:
        from kunglao_log import emit
        emit(workspace, actor="orchestrator", action="analysis_recorded",
             claim=claim_id,
             detail=f"source={entry.get('next_method_source')} "
                    f"candidates={len(entry.get('candidates') or [])}")
    except Exception:
        pass


def _resolve_ws(arg) -> Path:
    if arg:
        return Path(arg)
    cwd = Path(os.getcwd())
    sub = cwd / "malware-analysis-workspace"
    return sub if (sub / "claim-register.yaml").exists() else cwd


def _load_claims(workspace: Path):
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return [], None
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg


def _analysis_path(workspace: Path, claim_id: str) -> Path:
    return workspace / ANALYSES_DIR / f"failure-{claim_id}.yaml"


def _load_analysis(workspace: Path, claim_id: str):
    p = _analysis_path(workspace, claim_id)
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def _needs_analysis(claim: dict) -> bool:
    """A claim needs failure analysis if it was attempted (promotion_attempts > 0)
    but hasn't reached terminal status — a dispatch happened and didn't close it."""
    status = (claim.get("status") or "UNKNOWN").upper()
    if status in TERMINAL:
        return False
    return int(claim.get("promotion_attempts") or 0) > 0


def _artifact_gaps(analysis: dict) -> list[str]:
    """#495: which of the three failure artifacts the analysis is missing.
    An absent analysis is missing both (it never transduced anything)."""
    if not analysis:
        return ["validated_capability", "identified_obstacle"]
    gaps = []
    for field in ("validated_capability", "identified_obstacle"):
        if not str(analysis.get(field) or "").strip():
            gaps.append(field)
    return gaps


def _analysis_covers(analysis: dict, claim: dict) -> bool:
    """Does the recorded analysis cover the latest failed attempt?
    covers_attempt must match (or exceed) the claim's current promotion_attempts.
    #495: the three failure artifacts must ALSO be present — an analysis that
    answers the three questions in prose but records no validated_capability /
    identified_obstacle is exactly the v0.1.1 trajectory-1 evidence evaporation
    (decomposition-level knowledge lived in narrative and evaporated on pivot);
    it does not unblock re-dispatch."""
    if not analysis:
        return False
    covers = int(analysis.get("covers_attempt") or 0)
    attempts = int(claim.get("promotion_attempts") or 0)
    if covers < attempts:
        return False
    return not _artifact_gaps(analysis)


def check_claim(workspace: Path, claim_id: str, library: Path | None = None) -> dict:
    claims, _ = _load_claims(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if not claim:
        return {"state": "NOT_FOUND", "claim_id": claim_id}

    status = (claim.get("status") or "UNKNOWN").upper()
    if status in TERMINAL:
        return {"state": "TERMINAL", "claim_id": claim_id, "status": status}

    if not _needs_analysis(claim):
        return {"state": "OK_NO_PRIOR_FAILURE", "claim_id": claim_id,
                "promotion_attempts": claim.get("promotion_attempts")}

    analysis = _load_analysis(workspace, claim_id)
    if _analysis_covers(analysis, claim):
        return {"state": "OK_COVERED", "claim_id": claim_id,
                "promotion_attempts": claim.get("promotion_attempts"),
                "analysis": analysis}

    return {
        "state": "BLOCKED",
        "claim_id": claim_id,
        "status": status,
        "promotion_attempts": claim.get("promotion_attempts"),
        "evidence_tier_attempted": claim.get("evidence_tier_attempted"),
        "statement": (claim.get("statement") or "")[:200],
        "evidence": claim.get("evidence") or [],
        "stale_analysis": analysis,
        # #495: which failure artifacts the (stale/partial) analysis lacks —
        # the orchestrator's to-do list for unblocking.
        "missing_artifacts": _artifact_gaps(analysis),
        # #41: guide the orchestrator with up to 3 similar lessons from the
        # global library (keyword overlap on statement + claim id).
        "similar_lessons": _score_lessons(
            f"{(claim.get('statement') or '')} {claim_id}",
            Path(library) if library else LESSONS_DIR_DEFAULT),
    }


def scan_workspace(workspace: Path, library: Path | None = None) -> list:
    """Return all claims that currently BLOCK (failed attempt, no current analysis)."""
    claims, _ = _load_claims(workspace)
    blocked = []
    for c in claims:
        if not _needs_analysis(c):
            continue
        analysis = _load_analysis(workspace, c.get("id"))
        if not _analysis_covers(analysis, c):
            blocked.append(check_claim(workspace, c.get("id"), library=library))
    return blocked


def record_analysis(workspace: Path, claim_id: str, assumption: str,
                    validity: str, next_method: str,
                    outcome: str | None = None,
                    what_happened: str | None = None,
                    validated_capability: str | None = None,
                    identified_obstacle: str | None = None,
                    source: str | None = None,
                    library: Path | None = None,
                    trigger_precision: dict | None = None) -> dict:
    claims, reg = _load_claims(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if not claim:
        return {"recorded": False, "reason": f"claim {claim_id} not found"}

    validity = (validity or "").strip().lower()

    # #495: is this a failure-time record (any of the three question fields
    # explicitly supplied)? Closure-only calls (outcome backfill) must not
    # re-run the ladder nor clobber the failure-time artifacts.
    failure_time = bool((assumption or "").strip() or validity or
                        (next_method or "").strip())

    # #41 claim-closure backfill: when the caller only supplies the outcome
    # (--outcome/--what-happened), preserve the failure-time analysis fields —
    # closure must not clobber what was recorded at failure time.
    prior = _load_analysis(workspace, claim_id) or {}
    if not (assumption or "").strip():
        assumption = prior.get("method_assumption", "")
    if not validity:
        validity = (prior.get("assumption_validity") or "").strip().lower()
    if not (next_method or "").strip():
        next_method = prior.get("next_method", "")
    # #495: the artifacts get the same preserve-from-prior rule.
    if not (validated_capability or "").strip():
        validated_capability = prior.get("validated_capability") or ""
    if not (identified_obstacle or "").strip():
        identified_obstacle = prior.get("identified_obstacle") or ""

    if validity not in ("not-justified", "justified-adequate"):
        return {"recorded": False,
                "reason": "--validity must be 'not-justified' or 'justified-adequate'"}

    # not-justified REQUIRES a real different next_method (not "adequate" hand-wave)
    if validity == "not-justified":
        if not next_method or not next_method.strip():
            return {"recorded": False,
                    "reason": "validity=not-justified requires a --next-method (the different method to try)"}
        if "adequate" in next_method.lower() or "retry" == next_method.strip().lower():
            return {"recorded": False,
                    "reason": "validity=not-justified requires a DIFFERENT method, not 'adequate' or bare 'retry'"}

    # #495 provenance: source is mandatory, inherits from prior on closure.
    source_norm = (source or "").strip().lower()
    if not source_norm:
        source_norm = str(prior.get("next_method_source") or "").strip().lower()
    if not source_norm:
        return {"recorded": False,
                "reason": (f"--source is required (one of {', '.join(SOURCE_VALUES)}) — "
                           "provenance of the next method (#495)")}
    if source_norm not in SOURCE_VALUES:
        return {"recorded": False,
                "reason": f"--source must be one of {', '.join(SOURCE_VALUES)}"}

    # #41 outcome: optional; both-or-neither; one of OUTCOME_VALUES (normalized).
    outcome_norm = None
    if outcome or what_happened:
        if not (outcome and (what_happened or "").strip()):
            return {"recorded": False,
                    "reason": "--outcome and --what-happened must be provided together"}
        outcome_norm = (outcome or "").strip().upper()
        if outcome_norm not in OUTCOME_VALUES:
            return {"recorded": False,
                    "reason": f"--outcome must be one of {', '.join(OUTCOME_VALUES)}"}
        what_happened = what_happened.strip()

    # #495 method-ladder rung 1 (lessons): auto-search at failure time with
    # the obstacle + assumption error signature. FAIL-OPEN — a missing library
    # or a crashed search never blocks the record.
    if failure_time:
        ladder_query = " ".join(x for x in (identified_obstacle, assumption) if x)
        candidates = _ladder_candidates(ladder_query, library)
    else:
        ladder_query = prior.get("method_ladder_query", "")
        candidates = prior.get("candidates") or []
    if source_norm == "novel-hypothesis" and not candidates:
        return {"recorded": False,
                "reason": ("source=novel-hypothesis requires non-empty candidates — "
                           "consult the method ladder (lessons/reference/web) first; a "
                           "novel experiment occupies budget (#495)")}

    adir = workspace / ANALYSES_DIR
    adir.mkdir(parents=True, exist_ok=True)
    entry = {
        "claim": claim_id,
        "covers_attempt": int(claim.get("promotion_attempts") or 0),
        "method_assumption": assumption,
        "assumption_validity": validity,
        "next_method": next_method,
        "next_method_source": source_norm,
        "analyzed_at": prior.get("analyzed_at") or utc_now_iso(),
    }
    # #495 artifacts: written only when non-empty (a closure backfill on a
    # legacy analysis must not fabricate empty strings).
    if (validated_capability or "").strip():
        entry["validated_capability"] = validated_capability
    if (identified_obstacle or "").strip():
        entry["identified_obstacle"] = identified_obstacle
    if failure_time:
        entry["method_ladder_query"] = ladder_query
        entry["candidates"] = candidates
    elif prior.get("method_ladder_query") is not None:
        entry["method_ladder_query"] = prior.get("method_ladder_query", "")
        entry["candidates"] = candidates
    if outcome_norm:
        entry["outcome"] = outcome_norm
        entry["what_happened"] = what_happened
    # #525: trigger_precision is optional at record time (legacy analyses
    # predate the contract); aggregate_lessons gates on it at WRITE time,
    # not here. Preserve from prior on closure backfill so the field
    # survives a re-record.
    if trigger_precision is not None:
        entry["trigger_precision"] = dict(trigger_precision)
    elif prior.get("trigger_precision"):
        entry["trigger_precision"] = prior["trigger_precision"]
    _analysis_path(workspace, claim_id).write_text(
        yaml.safe_dump(entry, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    # #495: the obstacle is the third artifact — promote it to a claim so the
    # DAG grows a node (idempotent on obstacle_for).
    promotion = {"created": False, "id": None}
    if (identified_obstacle or "").strip():
        promotion = _promote_obstacle_claim(workspace, claim_id,
                                            identified_obstacle, claim, claims, reg)
    # #459: the landing event fires after the entry + promotion are on disk
    # (a tail reader never sees a recorded event for a half-written state).
    _emit_analysis_recorded(workspace, claim_id, entry)
    return {"recorded": True, "entry": entry, "obstacle_claim": promotion}


# ===================== #495 failure→knowledge transducer =====================

def _ladder_candidates(query: str, library: Path | None) -> list[dict]:
    """Method-ladder rung 1 (lessons): keyword search over the global library
    with the failure's error signature. Same scoring interface as --search
    (#41). FAIL-OPEN by contract: any failure (missing dir, unreadable files,
    crashed scan) yields [] — the ladder must never block a record."""
    try:
        return _score_lessons(query, Path(library) if library else LESSONS_DIR_DEFAULT)
    except Exception:  # noqa: BLE001 — #495 hard constraint: fail-open
        return []


def _next_claim_id(claims: list) -> str:
    """C-<max numeric suffix + 1>, following the register's id width
    (C-001 style stays zero-padded; C-1 style stays bare)."""
    mx, width = 0, 1
    for c in claims:
        m = re.search(r"(\d+)$", str(c.get("id") or ""))
        if not m:
            continue
        n = int(m.group(1))
        if n > mx:
            mx = n
            width = len(m.group(1))
    return f"C-{mx + 1:0{max(width, 1)}d}"


def _promote_obstacle_claim(workspace: Path, claim_id: str, obstacle: str,
                            parent_claim: dict, claims: list, reg: dict) -> dict:
    """identified_obstacle is the third failure artifact: promote it to a NEW
    claim so the flat DAG grows a node (#495).

    - idempotent: judged by the ownership marker (obstacle_for == failed
      claim id), NOT by text — re-recording with reworded obstacle never
      creates a second node;
    - new claim: OPEN, depends_on the failed claim, answers_question context
      inherited from it, origin=failure-obstacle;
    - claim_deps.yaml gains the real edge (the authoritative dep store that
      plan_drift_detector / refutation_propagate walk).
    """
    existing = next((c for c in claims
                     if c.get("obstacle_for") == claim_id
                     and c.get("origin") == "failure-obstacle"), None)
    if existing:
        return {"created": False, "id": existing.get("id")}

    new_id = _next_claim_id(claims)
    obstacle_text = " ".join((obstacle or "").split())
    new_claim = {
        "id": new_id,
        "status": "OPEN",
        "boundary_type": "obstacle",
        "evidence_tier_attempted": 0,
        "promotion_attempts": 0,
        "depends_on": [claim_id],
        "statement": f"Obstacle (from {claim_id}): {obstacle_text[:160]}",
        "origin": "failure-obstacle",
        "obstacle_for": claim_id,
        "promoted_from": f"{ANALYSES_DIR}/failure-{claim_id}.yaml",
    }
    if (parent_claim or {}).get("answers_question"):
        new_claim["answers_question"] = parent_claim["answers_question"]
    claims.append(new_claim)
    reg["claims"] = claims
    (workspace / "claim-register.yaml").write_text(
        yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    deps_path = workspace / "claim_deps.yaml"
    deps: dict = {}
    if deps_path.exists():
        try:
            loaded = yaml.safe_load(deps_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                deps = loaded
        except Exception:
            deps = {}  # unreadable deps file — rebuild from the edge below
    edges = deps.get("depends_on")
    if not isinstance(edges, dict):
        edges = {}
    parents = edges.get(new_id)
    if not isinstance(parents, list):
        parents = []
    if claim_id not in parents:
        parents.append(claim_id)
    edges[new_id] = parents
    deps["depends_on"] = edges
    deps_path.write_text(
        yaml.safe_dump(deps, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return {"created": True, "id": new_id}


# ===================== #41 failure-lessons library =====================
# Closed-loop outcomes (PROVEN/VERIFIED, or NEGATIVE that survived red-team)
# aggregate into lesson files under a GLOBAL library (cross-sample); everything
# else lands in the /reflect human queue. Retrieval is plain keyword overlap
# (no embeddings — the corpus is dozens of entries).

def _claim_topic(claim: dict | None, claim_id: str) -> str:
    """Claim topic for the failure signature: `topic` field, else the
    normalized statement (first 120 chars), else the claim id."""
    if claim:
        topic = (claim.get("topic") or "").strip()
        if topic:
            return topic
        stmt = (claim.get("statement") or "").strip()
        if stmt:
            return " ".join(stmt.split())[:120]
    return claim_id


def _signature(method_assumption: str, next_method: str, claim_topic: str) -> str:
    """Failure signature = method + assumption + claim topic (issue #41)."""
    norm = lambda s: " ".join((s or "").lower().split())
    return f"{norm(method_assumption)} || {norm(next_method)} || {norm(claim_topic)}"


def _lesson_slug(signature: str) -> str:
    """Deterministic file identity: same signature -> same slug -> idempotent."""
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:10]


def _lesson_filename(signature: str) -> str:
    return f"lesson-{_lesson_slug(signature)}.md"


def _write_lesson(lib: Path, signature: str, topic: str,
                  entries: list[tuple[str, dict]]) -> Path:
    """One lesson file per signature group, listing every source claim."""
    # #525: every lesson starts at stage=draft (nursery, capa analogy). The
    # trigger_precision block is mandatory per #525 — without it, the
    # aggregation layer rejects the entry (gates below in this fn).
    tp_keys = ("tool", "error_signature", "family", "unit")
    tp = entries[0][1].get("trigger_precision") or {}
    missing_tp = [k for k in tp_keys if not (tp.get(k) or "").strip()]
    if missing_tp:
        raise ValueError(
            f"trigger_precision missing fields {missing_tp} on signature {signature}"
        )
    fm = {
        "type": "lesson",
        "stage": "draft",
        "signature": signature,
        "slug": _lesson_slug(signature),
        "method_assumption": entries[0][1].get("method_assumption", ""),
        "assumption_validity": entries[0][1].get("assumption_validity", ""),
        "next_method": entries[0][1].get("next_method", ""),
        "claim_topic": topic,
        "outcome": ", ".join(sorted({e.get("outcome", "") for _, e in entries})),
        "sources": sorted(cid for cid, _ in entries),
        "trigger_precision": dict(tp),
        "created_at": utc_now_iso(),
    }
    lines = ["---", yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip(), "---", ""]
    lines.append(f"# Lesson - {topic}")
    lines.append("")
    lines.append("## Failure signature")
    lines.append(f"- method_assumption: {fm['method_assumption']}")
    lines.append(f"- assumption_validity: {fm['assumption_validity']}")
    lines.append(f"- next_method: {fm['next_method']}")
    lines.append(f"- claim topic: {topic}")
    lines.append("")
    lines.append("## What actually happened (verified conclusions)")
    for cid, entry in sorted(entries):
        lines.append(f"- {cid} ({entry.get('outcome', '')}): {entry.get('what_happened', '')}")
    lines.append("")
    path = lib / _lesson_filename(signature)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _reflect_reason(outcome: str | None, redteam_ok: bool) -> str:
    """Why an entry is NOT library-eligible; '' means it is closed-loop."""
    if outcome is None:
        return "no-outcome"
    if outcome == "REFUTED":
        return "refuted"
    if outcome == "NEGATIVE" and not redteam_ok:
        return "negative-unverified"
    return ""


def _read_lesson_frontmatter(path: Path) -> tuple[str, str, dict]:
    """Return (raw_text, fm_yaml, parsed_dict). Tolerant to malformed."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text, "", {}
    try:
        fm = yaml.safe_load(parts[1]) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    return text, parts[1], fm


def promote_lesson(lesson_path: Path, workspace: Path | None = None,
                   promoted_by: str = "kunglao-verify",
                   evidence: str = "",
                   demote_to: str | None = None) -> dict:
    """#525: flip a lesson's frontmatter stage draft → active, stamp
    promoted_at / promoted_by / promoted_evidence, and emit a
    lesson_stage_transition row to the kunglao_log. Idempotent on
    already-active (no rewrite, no audit row). Demotion is forbidden —
    lessons only retire (separate signal); attempts raise ValueError."""
    if demote_to is not None:
        raise ValueError(
            f"demotion to {demote_to!r} is not supported by promote_lesson; "
            "retire the lesson instead (separate signal, #525).")
    lesson_path = Path(lesson_path)
    text, fm_yaml, fm = _read_lesson_frontmatter(lesson_path)
    current = str(fm.get("stage", "draft")).strip().lower() or "draft"
    if current == "active":
        return {"promoted": False, "already_active": True,
                "lesson": str(lesson_path)}
    fm["stage"] = "active"
    fm["promoted_at"] = utc_now_iso()
    fm["promoted_by"] = promoted_by
    if evidence:
        fm["promoted_evidence"] = evidence
    new_yaml = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    new_text = text.replace(fm_yaml, new_yaml, 1)
    if new_text == text:
        # frontmatter never matched — defensive rewrite
        new_text = "---\n" + new_yaml + "\n---\n" + text.split("---", 2)[-1]
    lesson_path.write_text(new_text, encoding="utf-8")

    # Audit row: lesson_stage_transition, actor=nursery, claim=<first source>.
    sources = fm.get("sources") or []
    claim_id = str(sources[0]) if sources else ""
    detail = (f"draft→active promoted_by={promoted_by}")
    if evidence:
        detail += f" evidence={evidence}"
    try:
        if workspace is not None:
            from kunglao_log import emit
            emit(Path(workspace), actor="nursery",
                 action="lesson_stage_transition", claim=claim_id,
                 detail=detail)
    except Exception:
        pass  # logging never blocks promotion
    return {"promoted": True, "already_active": False,
            "lesson": str(lesson_path),
            "promoted_at": fm["promoted_at"],
            "promoted_by": promoted_by}


def _append_reflect_queue(queue_path: Path, entries: list[dict]) -> int:
    """Append items to the claude-reflect learnings queue (JSON array, plugin
    schema + failure fields); idempotent on claim_id|reason."""
    items: list = []
    if queue_path.exists():
        try:
            loaded = json.loads(queue_path.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                items = loaded
        except (json.JSONDecodeError, OSError):
            items = []
    seen = {f"{i.get('claim_id')}|{i.get('reason')}" for i in items}
    added = 0
    for e in entries:
        key = f"{e['claim_id']}|{e['reason']}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "type": REFLECT_ITEM_TYPE,
            "message": e.get("message", ""),
            "timestamp": utc_now_iso(),
            "project": str(Path.cwd()),
            "claim_id": e["claim_id"],
            "outcome": e.get("outcome"),
            "reason": e["reason"],
            "next_method": e.get("next_method", ""),
            "method_assumption": e.get("method_assumption", ""),
        })
        added += 1
    if added:
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.write_text(json.dumps(items, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    return added


def aggregate_lessons(workspace: Path, library: Path | None = None,
                      reflect_queue: Path | None = None) -> dict:
    """Aggregate analyses/failure-*.yaml into the global lessons library.

    Closed-loop only: PROVEN/VERIFIED always; NEGATIVE only when the #35
    ledger carries a red-team CONFIRMED OUTCOME row for the claim. Every
    other entry goes to the /reflect queue (reason: refuted /
    negative-unverified / no-outcome). Idempotent: an existing lesson file
    for the signature is skipped; queue items dedup on claim_id|reason.
    """
    lib = Path(library) if library else LESSONS_DIR_DEFAULT
    queue = Path(reflect_queue) if reflect_queue else REFLECT_QUEUE_DEFAULT
    claims, _ = _load_claims(workspace)
    claims_by_id = {c.get("id"): c for c in claims}
    try:
        from outcome_capture import read_outcome_rows  # sibling in scripts/
        redteam_ok = {r.get("claim_id") for r in read_outcome_rows(workspace)
                      if r.get("checker") == "red-team" and r.get("result") == "CONFIRMED"}
    except ImportError:
        redteam_ok = set()

    groups: dict[str, list[tuple[str, dict]]] = {}
    topics: dict[str, str] = {}
    queued: list[dict] = []
    adir = workspace / ANALYSES_DIR
    if adir.exists():
        for p in sorted(adir.glob("failure-*.yaml")):
            try:
                entry = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:
                continue  # unreadable / malformed analysis — skip, no crash
            if not isinstance(entry, dict):
                continue
            cid = entry.get("claim") or p.name.removeprefix("failure-").removesuffix(".yaml")
            claim = claims_by_id.get(cid)
            outcome = entry.get("outcome")
            if outcome in ("PROVEN", "VERIFIED") or (
                    outcome == "NEGATIVE" and cid in redteam_ok):
                # #525: nursery gate — every library lesson MUST carry a
                # complete trigger_precision block. Missing or incomplete
                # entries route to /reflect (reason=missing-precision)
                # instead of the library, so the gate is observable AND
                # doesn't block the rest of aggregation.
                tp = entry.get("trigger_precision") or {}
                tp_keys = ("tool", "error_signature", "family", "unit")
                missing_tp = [k for k in tp_keys if not (tp.get(k) or "").strip()]
                if missing_tp:
                    queued.append({
                        "claim_id": cid,
                        "reason": "missing-precision",
                        "outcome": outcome,
                        "next_method": entry.get("next_method", ""),
                        "method_assumption": entry.get("method_assumption", ""),
                        "message": (
                            f"closed-loop analysis for {cid} lacks "
                            f"trigger_precision fields {missing_tp}; "
                            f"backfill the frontmatter (tool/error_signature/"
                            "family/unit) before re-aggregation (#525)."),
                    })
                    continue
                topic = _claim_topic(claim, cid)
                sig = _signature(entry.get("method_assumption", ""),
                                 entry.get("next_method", ""), topic)
                groups.setdefault(sig, []).append((cid, entry))
                topics[sig] = topic
            else:
                reason = _reflect_reason(outcome, cid in redteam_ok)
                if reason:
                    queued.append({
                        "claim_id": cid, "reason": reason, "outcome": outcome,
                        "next_method": entry.get("next_method", ""),
                        "method_assumption": entry.get("method_assumption", ""),
                        "message": (
                            f"failure analysis for claim {cid} did not close a "
                            f"verified loop (reason={reason}); "
                            f"what happened: {entry.get('what_happened', '')}"),
                    })

    written = skipped = 0
    lib.mkdir(parents=True, exist_ok=True)
    for sig, entries in sorted(groups.items()):
        if (lib / _lesson_filename(sig)).exists():
            skipped += 1
            continue
        _write_lesson(lib, sig, topics[sig], entries)
        written += 1
    queue_added = _append_reflect_queue(queue, queued)
    return {"lessons_written": written, "lessons_skipped": skipped,
            "queue_added": queue_added}


TOKEN_RE = re.compile(r"[a-z0-9_]{3,}")


def _tokens(text: str) -> set:
    return set(TOKEN_RE.findall((text or "").lower()))


def _lesson_meta(path: Path) -> dict:
    """Frontmatter + full text of a lesson file; tolerant parse."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    parts = text.split("---", 2)
    meta: dict = {}
    if len(parts) >= 3:
        try:
            parsed = yaml.safe_load(parts[1])
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}
    return {"path": path, "text": text,
            "stage": str(meta.get("stage", "")),
            "outcome": str(meta.get("outcome", "")),
            "next_method": str(meta.get("next_method", "")),
            "claim_topic": str(meta.get("claim_topic", ""))}


def _score_lessons(query: str, library: Path, limit: int = 3) -> list[dict]:
    """Top-N lessons by keyword/token overlap with the query (no embeddings)."""
    q = _tokens(query)
    if not q or not library.exists():
        return []
    scored = []
    for p in sorted(library.glob("lesson-*.md")):
        meta = _lesson_meta(p)
        score = len(q & _tokens(meta["text"]))
        if score:
            scored.append({"file": p.name, "score": score,
                           "stage": meta.get("stage", ""),
                           "outcome": meta["outcome"],
                           "next_method": meta["next_method"],
                           "claim_topic": meta["claim_topic"]})
    scored.sort(key=lambda s: (-s["score"], s["file"]))
    return scored[:limit]


def search_lessons(query: str, library: Path | None = None, limit: int = 3) -> list[dict]:
    """CLI search over the lessons library (keywords/claim-tag, no embeddings)."""
    return _score_lessons(query, Path(library) if library else LESSONS_DIR_DEFAULT, limit)


def _failure_modes_recall() -> tuple[str, ...]:
    """#268: on a BLOCKED row, recall the failure-modes reference files so the
    orchestrator reads the matching failure-modes-{lifecycle,monitoring,state}
    domain file. FAIL_OPEN: any recall failure -> () (recall never blocks the
    gate). Reuses hooks/recall_inject.recall_files — the single recall path."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
        from recall_inject import recall_files
        return recall_files("failure modes")
    except Exception:  # noqa: BLE001 — recall is guidance, never a blocker
        return ()


def _print_blocked(d: dict) -> None:
    cid = d["claim_id"]
    print(f"=== BLOCKED: {cid} (status={d.get('status')}, attempts={d.get('promotion_attempts')}) ===")
    print(f"claim: {d.get('statement','')}")
    if d.get("evidence"):
        print(f"evidence so far: {d['evidence']}")
    if d.get("stale_analysis"):
        print(f"stale analysis (covers attempt {d['stale_analysis'].get('covers_attempt')}): update it")
    print()
    print("Before re-dispatching OR concluding NEGATIVE, answer three questions")
    print("(reason from THIS specific failure - do not pick from a fixed menu):")
    print()
    print("  1. method_assumption   - what did the failed method assume would happen?")
    print("  2. assumption_validity - is that assumption justified given the evidence?")
    print("                           if NOT justified -> the METHOD failed, not the behavior absent")
    print("  3. next_method         - what DIFFERENT method tests a different assumption?")
    print("                           (literal retry is forbidden; 'method was adequate' only if Q2=justified)")
    print()
    print("And transduce the failure into typed artifacts (the analysis does")
    print("not unblock without them):")
    print()
    print("  4. validated_capability - what this failure PROVED works (capability ok)")
    print("  5. identified_obstacle  - what specifically blocked you (auto-promoted")
    print("                           to a new claim depending on this one)")
    print("  6. --source             - provenance: lesson-hit | reference-hit |")
    print("                           web-hit | novel-hypothesis (novel requires the")
    print("                           ladder to have recorded a hit first)")
    if d.get("missing_artifacts"):
        print()
        print(f"  failure artifacts still missing: {', '.join(d['missing_artifacts'])}")
    print()
    print("Record with:")
    print(f"  python scripts/failure_analysis_gate.py <ws> {cid} --record \\")
    print(f"      --assumption \"...\" --validity not-justified|justified-adequate --next-method \"...\" \\")
    print(f"      --validated-capability \"...\" --identified-obstacle \"...\" \\")
    print(f"      --source lesson-hit|reference-hit|web-hit|novel-hypothesis (provenance)")
    sim = d.get("similar_lessons") or []
    if sim:
        print()
        print("Similar lessons from the failure-lessons library (keyword match, #41):")
        for s in sim:
            print(f"  - {s['file']} (score {s['score']}, outcome {s['outcome']}): "
                  f"{s['claim_topic']} -> next: {s['next_method']}")

    fm = _failure_modes_recall()
    if fm:
        print()
        print("See failure-modes reference (recall): " + ", ".join(fm))


def promote_lesson(lesson_path: Path, workspace: Path,
                  promoted_by: str, evidence: str,
                  demote_to: str | None = None) -> dict:
    """Flip a lesson's stage (issue #525 nursery two-stage lifecycle).

    draft → active is the only forward transition: lessons that have been
    mechanically verified (kunglao-verify L1 reproduce, or red-team pass)
    are trusted enough to drop the [unverified] injection tag. The
    transition is audited via kunglao_log.emit(action=lesson_stage_transition).

    Re-promoting an active lesson is an idempotent no-op (already_active).
    Demotion (active → draft) is rejected with ValueError — lessons do not
    regress; retirement is a separate signal.
    """
    if demote_to is not None:
        raise ValueError(
            f"promote_lesson does not support demotion (got demote_to={demote_to!r}); "
            "lessons retire via a separate signal."
        )
    p = Path(lesson_path)
    if not p.exists():
        return {"promoted": False, "reason": f"lesson not found: {p}"}
    text = p.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"promoted": False, "reason": f"lesson lacks frontmatter: {p}"}
    try:
        fm = yaml.safe_load(parts[1]) or {}
        if not isinstance(fm, dict):
            return {"promoted": False, "reason": "lesson frontmatter is not a mapping"}
    except yaml.YAMLError as exc:
        return {"promoted": False, "reason": f"frontmatter parse error: {exc}"}

    sources = fm.get("sources") or []
    current = (fm.get("stage") or "draft").lower()
    if current == "active":
        return {"promoted": False, "already_active": True,
                "promoted_at": fm.get("promoted_at", "")}

    now = utc_now_iso()
    fm["stage"] = "active"
    fm["promoted_at"] = now
    fm["promoted_by"] = promoted_by
    fm["promoted_evidence"] = evidence
    body = parts[2] if len(parts) >= 3 else ""
    new_text = ("---\n" +
                yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip() +
                "\n---" + body)
    p.write_text(new_text, encoding="utf-8")

    # Audit log (#525 — fail-open by contract; never break the promotion).
    try:
        from kunglao_log import emit
        # sources is a list of claim ids; first is the canonical owner
        claim_id = sources[0] if isinstance(sources, list) and sources else None
        emit(workspace, actor="nursery", action="lesson_stage_transition",
             claim=str(claim_id) if claim_id else None,
             tool="failure_analysis_gate",
             artifact=p.name,
             detail=(f"draft→active promoted_by={promoted_by} "
                     f"evidence={evidence}"))
    except Exception:
        pass

    return {"promoted": True, "from_stage": "draft", "to_stage": "active",
            "promoted_at": now}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="kunglao-agent failure-analysis gate - reason before re-dispatch or NEGATIVE")
    parser.add_argument("workspace", nargs="?", default=None, help="workspace root (omit: cwd or ./malware-analysis-workspace)")
    parser.add_argument("claim_id", nargs="?", default=None, help="claim to check (omit to scan all)")
    parser.add_argument("--record", action="store_true", help="record a failure analysis")
    parser.add_argument("--assumption", default=None, help="what the failed method assumed")
    parser.add_argument("--validity", default=None, help="not-justified | justified-adequate")
    parser.add_argument("--next-method", default=None, help="the different method to try next")
    parser.add_argument("--outcome", default=None,
                        help="claim-closure result (#41): PROVEN|VERIFIED|REFUTED|NEGATIVE")
    parser.add_argument("--what-happened", default=None,
                        help="free text: what actually happened (#41, required with --outcome)")
    parser.add_argument("--validated-capability", default=None,
                        help="what this failure PROVED works — capability ok (artifact)")
    parser.add_argument("--identified-obstacle", default=None,
                        help="what specifically blocked you (artifact; auto-promoted to a claim)")
    parser.add_argument("--source", default=None,
                        help="provenance of next_method: "
                             "lesson-hit | reference-hit | web-hit | novel-hypothesis")
    parser.add_argument("--lessons", action="store_true",
                        help="aggregate analyses into the global lessons library (#41)")
    parser.add_argument("--search", metavar="KEYWORDS", default=None,
                        help="search the lessons library by keywords/claim-tag (#41)")
    parser.add_argument("--library", default=None,
                        help="lessons library dir "
             "(default: executing install's references/lessons)")
    parser.add_argument("--reflect-queue", default=None,
                        help="/reflect human queue file (default: ~/.claude/learnings-queue.json)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    workspace = _resolve_ws(args.workspace)

    if args.lessons:
        r = aggregate_lessons(workspace, library=args.library, reflect_queue=args.reflect_queue)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            print(f"lessons written: {r['lessons_written']} "
                  f"(skipped existing: {r['lessons_skipped']}); "
                  f"/reflect queue new entries: {r['queue_added']}")
        return 0

    if args.search:
        hits = search_lessons(args.search, library=args.library)
        if args.json:
            print(json.dumps(hits, indent=2, ensure_ascii=False))
        elif hits:
            for h in hits:
                print(f"{h['file']} (score {h['score']}, outcome {h['outcome']}): "
                      f"{h['claim_topic']} -> next: {h['next_method']}")
        else:
            print("no matching lessons")
        return 0

    if args.record:
        if not args.claim_id:
            print("FAIL: --record requires a claim_id", file=sys.stderr)
            return 64
        r = record_analysis(workspace, args.claim_id, args.assumption or "",
                           args.validity or "", args.next_method or "",
                           args.outcome, args.what_happened,
                           validated_capability=args.validated_capability,
                           identified_obstacle=args.identified_obstacle,
                           source=args.source,
                           library=args.library)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            print("RECORDED" if r.get("recorded") else f"REJECTED: {r.get('reason')}")
            if r.get("entry"):
                print(yaml.safe_dump(r["entry"], allow_unicode=True, sort_keys=False))
            oc = r.get("obstacle_claim") or {}
            if oc.get("id"):
                verb = "promoted new" if oc.get("created") else "existing"
                print(f"obstacle claim ({verb}): {oc['id']}")
        return 0 if r.get("recorded") else 1

    if args.claim_id:
        # #41 fix (orchestrator verification): forward --library so BLOCKED
        # guidance includes similar_lessons — previously dropped here, so the
        # acceptance criterion "BLOCKED output contains 3 similar lessons"
        # (original acceptance wording, in Chinese: "BLOCKED output
        # contains 3 similar lessons") failed via CLI.
        r = check_claim(workspace, args.claim_id, library=args.library)
        if r["state"] == "BLOCKED":
            _emit_failure_blocked(workspace, r)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            if r["state"] == "BLOCKED":
                _print_blocked(r)
            elif r["state"] == "OK_COVERED":
                print(f"OK: {args.claim_id} - analysis covers attempt {r.get('promotion_attempts')}")
            elif r["state"] == "TERMINAL":
                print(f"OK: {args.claim_id} - terminal ({r.get('status')}), no analysis needed")
            elif r["state"] == "OK_NO_PRIOR_FAILURE":
                print(f"OK: {args.claim_id} - no prior failed attempt (attempts={r.get('promotion_attempts')})")
            else:
                print(f"FAIL: claim {args.claim_id} not found")
        return 1 if r["state"] == "BLOCKED" else (2 if r["state"] == "NOT_FOUND" else 0)

    # scan mode
    # #41 fix: forward --library (same regression as the single-claim path).
    blocked = scan_workspace(workspace, library=args.library)
    if args.json:
        print(json.dumps({"blocked": blocked, "count": len(blocked)}, indent=2, ensure_ascii=False))
    elif blocked:
        print(f"=== {len(blocked)} claim(s) BLOCKED (failed attempt, no current analysis) ===\n")
        for d in blocked:
            _emit_failure_blocked(workspace, d)
            _print_blocked(d)
            print()
    else:
        print("OK: no claims need failure analysis right now.")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
