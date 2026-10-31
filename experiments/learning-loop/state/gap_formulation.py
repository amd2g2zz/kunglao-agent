# -*- coding: utf-8 -*-
"""state/gap_formulation.py — the gap-formulation perception face
(#943).

Owner framing (the three-layer responsibility split): PERCEPTION
produces candidate gap formulations — advisory only, no execution
authority; the LOOP decides (budget + salience threshold); DISTILL
executes (#938's contract is unchanged: given a formulation, run the
research). This face is an AGGREGATOR over the existing faces' signals
(it lives in state/ because it reads the state faces' durable
substrates), and it WRITES NOTHING: aggregate() is a pure function of
the workspace — no ledger row, no telemetry, no firing. The loop's
existing decision discipline keeps the firing authority (#938's
shelf-miss trigger stays the loop's choice; this face's candidates are
the loop's ranked advisory input).

The five sources — each an aggregator over an existing face:

  1. SHELF-MISS RECEIPTS  the ledger's ``distill`` action rows (the
     loop's shelf-miss trigger is their only producer — the #938 pin:
     a plain worker never lands one); each row's ``formulation`` is a
     tool gap (gap_type "tool", stage "shelf", subject = the
     formulation string, strength = one receipt).
  2. STAGNATION SIGNALS  the arbiter rows' ``delta_p`` series (the
     rollout dispositions' own audit, loop.py:562-571) run through the
     stagnation face's own receipt machinery (state/stagnation.py) — a
     trailing flat run advises; the signal's stage is the flat
     window's direction (the last assign_step target in the flat
     rollout), strength = the flat-segment length (the receipt's own
     ``flat_segments``).
  3. OPEN-QUESTION ACCUMULATION  the belief snapshot's open_questions
     (state/belief.py — task_spec priority order); the age term is
     DERIVED from the ledger (the workspace's rollout count), never a
     wall clock (the #251 contract): age = AGE_BASE + min(1, rollouts
     / AGE_ROLLOUT_REF). The age is a WORKSPACE-LEVEL term, computed
     once per aggregation and applied uniformly to every open question
     (task_spec carries no per-question timestamps): what ages is the
     workspace — more rollouts completed while the question set stays
     open is a stronger context gap (gap_type "context", stage
     "spec").
  4. REFUTED HYPOTHESES / LOW-CREDIT PATTERNS  the ladder's REFUTED
     class (step_credit's own classification over the fact base's
     frontmatter — a fact whose own proposition was WRONG) plus the
     settlement draft rows' low-credit pattern (credit below
     step_credit's own provisional floor CREDIT_BY_CLASS[UNVERIFIED];
     the deficit magnitude is the strength; the stage is the draft's
     dispatch family, joined through the assign_step rows). Both are
     knowledge gaps (gap_type "knowledge").
  5. MEMORY QUERIES  an INJECTED Callable seam — the real memory
     lookup plugs via #583's bridge later; absent = the source
     contributes nothing (no mock in production). The seam receives
     the candidate's structured draft (the #583 bridge owns the key
     derivation: situation-signature × gap type); a truthy
     ``distilled`` verdict suppresses the candidate — already-distilled
     gaps don't re-trigger (the 蒸馏克制裁定 holds naturally at the
     memory layer). Suppressed candidates move to the report's
     ``memory_suppressed`` list (advisory transparency) and consume no
     formulate_fn budget.

Formulation: signals CLUSTER by (gap_type, stage) — same family/stage
signals merge into one candidate whose subjects enumerate the distinct
objects; the candidate carries the R3-aligned record {schema,
gap_type, stage, subjects, draft, formulation, exploration_direction,
salience, source_receipts, sources}. The prose is an INJECTED LLM seam
(``formulate_fn``): the mechanical face produces the signal clusters
plus the structured gap draft; the LLM turns the draft into the
formulation text. Seam absence = the structured draft lands without
prose (formulation == "" — the honest gap, not a refusal); a present
seam returning whitespace = an honest decline (the empty prose);
a non-string return raises (fail-closed). Both layers fail-closed on
poison signals: a non-finite/non-numeric delta_p or credit, a
non-string shelf formulation, a non-mapping seam return — a poisoned
read must never silently formulate.

Salience: the cluster's summed signal strengths, deterministic and
monotone (more receipts / longer flat tails / older questions / bigger
credit deficits -> strictly higher salience; no saturation constant —
the loop's budget + threshold discipline owns the gate). Candidates
return ranked (salience desc, then key order for determinism). NOT
every signal triggers: the salience threshold is the LOOP's decision —
the face returns candidates ranked; the loop gates.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import consolidated_ledger as _cl  # noqa: E402 — bootstrap first
from rlvr import q_cells  # noqa: E402
from rlvr.step_credit import (  # noqa: E402 — the one pricing authority
    CREDIT_BY_CLASS,
    REFUTED,
    UNVERIFIED,
    classify_verification,
)
from settlement import per_dispatch as _per_dispatch  # noqa: E402

from . import belief as _belief  # noqa: E402
from . import stagnation as _stagnation  # noqa: E402

__all__ = ["SCHEMA", "CANDIDATE_SCHEMA", "SUPPRESS_REASON",
           "AGE_BASE", "AGE_ROLLOUT_REF", "GapFormulationError",
           "aggregate"]

SCHEMA = "gap-formulation/1"
#: one candidate's record schema
CANDIDATE_SCHEMA = "gap-candidate/1"
#: why a memory-suppressed candidate left the ranked list
SUPPRESS_REASON = "already-distilled"

#: the open-question age term's base and rollout reference (documented
#: policy, NOT fitted — the stagnation.STAGNATION_N governance class):
#: a WORKSPACE-LEVEL term, age = AGE_BASE + min(1.0, rollouts /
#: AGE_ROLLOUT_REF) ∈ [1, 2], applied uniformly to every open question
#: (no per-question timestamps exist — what ages is the workspace)
AGE_BASE = 1.0
AGE_ROLLOUT_REF = 4.0

#: the shelf-miss receipt's flat strength (one receipt = one piece of
#: evidence)
RECEIPT_STRENGTH = 1.0

#: the ledger's kind vocabulary this face consumes; every other action
#: kind is another decision family's row — skipped, never folded in
#: (the belief face's read posture)
_ARBITER_KINDS = frozenset({"rollback", "terminate_rollout"})
_ASSIGN_KIND = "assign_step"
_SHELF_KIND = "distill"


class GapFormulationError(ValueError):
    """A gap signal violates the perception face's contract — a
    poisoned read must never silently formulate. Fail-closed."""


def _fail(field: str, why: str) -> GapFormulationError:
    return GapFormulationError(f"state.gap_formulation.{field}: {why}")


def _checked_strength(value: Any, field: str) -> float:
    """The STRENGTH domain (flat_segments, credit deficit): a finite,
    non-negative number — a bool or a NaN/inf would fabricate
    salience."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or value < 0.0:
        raise _fail(field, f"must be a finite number >= 0, got {value!r}")
    return float(value)


def _checked_finite(value: Any, field: str) -> float:
    """The SIGNED domain for arbiter delta_p: finite-numeric only —
    production rollback rows legitimately carry NEGATIVE delta_p (the
    arbiter lands rollback for any non-positive ΔP; progress.delta_P
    prices penalitive/negative edges; the stagnation face's own
    ``_checked_deltas`` domain is any finite signed value). A
    historical regression row must never poison the read."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise _fail(field, f"must be a finite number, got {value!r}")
    return float(value)


# --------------------------------------------------- the ledger reads

def _action_rows(ws: Path) -> list[Mapping]:
    """The ledger's action rows, append order."""
    return [row for row in q_cells.trajectory_rows(ws)
            if row.get("schema") == q_cells.SCHEMA_ACTION_V2]


def _row_receipt(row: Mapping, *fields: str) -> dict:
    """A trimmed provenance receipt — the row's identity fields only
    (the full row stays in the ledger; the candidate cites it)."""
    out = {k: row[k] for k in fields if row.get(k) is not None}
    return out


def _mapping_or_poison(value: Any, field: str) -> Mapping | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _fail(field, f"must be a mapping when present, got "
                           f"{value!r}")
    return value


def _nonempty_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, f"must be a non-empty string, got {value!r}")
    return value


# ------------------------------------------------- source 1: shelf-miss

def _shelf_miss_signals(actions: list[Mapping]) -> list[dict]:
    """The ledger's distill rows -> tool-gap signals (source 1). Each
    row's ``formulation`` param is the capability gap's problem
    statement (the #924 spec wall guarantees the string; the face
    re-validates fail-closed against a hand-poisoned ledger)."""
    out: list[dict] = []
    for row in actions:
        if row.get("kind") != _SHELF_KIND:
            continue
        params = _mapping_or_poison(row.get("params"),
                                    "shelf_miss.params")
        formulation = _nonempty_str((params or {}).get("formulation"),
                                    "shelf_miss.formulation")
        receipt = _row_receipt(row, "rollout_id", "step_id", "target",
                               "ts")
        receipt["formulation"] = formulation
        out.append({"source": "shelf_miss", "gap_type": "tool",
                    "stage": "shelf", "subject": formulation,
                    "strength": RECEIPT_STRENGTH, "receipt": receipt})
    return out


# ------------------------------------------------ source 2: stagnation

def _arbiter_deltas(actions: list[Mapping]) -> tuple[list[float],
                                                     list[str]]:
    """The arbiter rows' per-rollout ΔP series + rollout ids, append
    order — the same series the loop's stagnation posture consumes.
    The domain is SIGNED finite (rollback rows legitimately carry
    negative ΔP; only non-finite values are poison). A terminal row
    without ``delta_p`` (the harness rule-only rows) contributes
    nothing."""
    deltas: list[float] = []
    rids: list[str] = []
    for row in actions:
        if row.get("kind") not in _ARBITER_KINDS:
            continue
        params = _mapping_or_poison(row.get("params"),
                                    "stagnation.params")
        delta = (params or {}).get("delta_p")
        if delta is None:
            continue
        rid = _nonempty_str(row.get("rollout_id"),
                            "stagnation.rollout_id")
        deltas.append(_checked_finite(delta, "stagnation.delta_p"))
        rids.append(rid)
    return deltas, rids


def _rollout_direction(actions: list[Mapping], rid: str) -> str:
    """The flat window's direction: the last assign_step target in that
    rollout; a rollout with no assignment is honest "unknown"."""
    direction = "unknown"
    for row in actions:
        if row.get("kind") == _ASSIGN_KIND \
                and row.get("rollout_id") == rid:
            direction = _nonempty_str(row.get("target"),
                                      "stagnation.assign_target")
    return direction


def _stagnation_signals(actions: list[Mapping]) -> list[dict]:
    """The ΔP series through the stagnation face's own receipt
    machinery (source 2) — the perception face never re-implements the
    trigger; it consumes state/stagnation.py. Strength = the receipt's
    ``flat_segments`` (a longer flat run is a stronger method gap)."""
    deltas, rids = _arbiter_deltas(actions)
    if not deltas:
        return []
    receipt = _stagnation.stagnation_receipt(deltas,
                                             rollout_id=rids[-1])
    if receipt is None:
        return []
    direction = _rollout_direction(actions, rids[-1])
    return [{"source": "stagnation", "gap_type": "method",
             "stage": direction, "subject": rids[-1],
             "strength": float(receipt["flat_segments"]),
             "receipt": receipt}]


# ---------------------------------------------- source 3: open questions

def _rollout_count(actions: list[Mapping]) -> int:
    """The deterministic age base: distinct arbiter rollout ids (the
    ledger's own counter — never a wall clock, the #251 contract)."""
    seen: set[str] = set()
    for row in actions:
        if row.get("kind") in _ARBITER_KINDS:
            rid = _nonempty_str(row.get("rollout_id"),
                                "open_question.rollout_id")
            seen.add(rid)
    return len(seen)


def _open_question_signals(ws: Path,
                           actions: list[Mapping]) -> list[dict]:
    """The belief snapshot's open_questions -> context-gap signals
    (source 3). The age term is a WORKSPACE-LEVEL constant derived
    once per aggregation from the ledger's rollout count (the
    task_spec carries no per-question timestamps): every open question
    rides the same age — more rollouts completed while the question
    set stays open is a stronger context gap."""
    snapshot = _belief.build_snapshot(ws)
    questions = snapshot.get("open_questions") or []
    rollouts = _rollout_count(actions)
    age = AGE_BASE + min(1.0, rollouts / AGE_ROLLOUT_REF)
    out: list[dict] = []
    for q in questions:
        qid = _nonempty_str(q.get("id"), "open_question.id")
        out.append({"source": "open_question", "gap_type": "context",
                    "stage": "spec", "subject": qid, "strength": age,
                    "receipt": {"id": qid,
                                "question": str(q.get("question", "")),
                                "rollouts_observed": rollouts}})
    return out


# -------------------------------------- source 4: refuted / low-credit

def _read_fact_meta(ws: Path) -> list[dict]:
    """The fact base's frontmatter dicts — the belief read posture: a
    file with no parseable frontmatter is not evidence (skip; the lint
    face owns the loudness)."""
    import yaml  # noqa: PLC0415 — the lazy read precedent
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(facts_dir.glob("F*.md")):
        try:
            parts = path.read_text(
                encoding="utf-8", errors="replace").split("---", 2)
            meta = yaml.safe_load(parts[1]) if len(parts) >= 3 else None
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(meta, dict):
            out.append(dict(meta, id=str(meta.get("id") or path.stem)))
    return out


def _assign_family_join(actions: list[Mapping]) -> dict[str, str]:
    """dispatch step_id -> the assigned family (the low-credit draft's
    stage join)."""
    join: dict[str, str] = {}
    for row in actions:
        if row.get("kind") != _ASSIGN_KIND:
            continue
        sid = _nonempty_str(row.get("step_id"),
                            "low_credit.assign_step_id")
        join[sid] = _nonempty_str(row.get("target"),
                                  "low_credit.assign_target")
    return join


def _refuted_credit_signals(ws: Path,
                            actions: list[Mapping]) -> list[dict]:
    """Refuted hypotheses + the low-credit pattern (source 4): a fact
    whose own proposition was WRONG (step_credit's REFUTED class) and
    a settlement draft whose credit sits below step_credit's own
    provisional floor (CREDIT_BY_CLASS[UNVERIFIED]; the deficit is the
    strength, the stage is the draft's dispatch family via the assign
    join). Both are knowledge gaps."""
    out: list[dict] = []
    for meta in _read_fact_meta(ws):
        if classify_verification(meta.get("status"),
                                 meta.get("verify_status")) != REFUTED:
            continue
        fid = _nonempty_str(meta.get("id"), "refuted.fact_id")
        out.append({"source": "refuted_credit", "gap_type": "knowledge",
                    "stage": "claim", "subject": fid,
                    "strength": RECEIPT_STRENGTH,
                    "receipt": {"id": fid,
                                "status": str(meta.get("status")),
                                "verify_status": str(
                                    meta.get("verify_status"))}})
    floor = CREDIT_BY_CLASS[UNVERIFIED]
    join = _assign_family_join(actions)
    drafts = _cl.read(ws, "settlement",
                      schema_prefix=_per_dispatch.DRAFT_SCHEMA)
    for row in drafts:
        credit = _checked_strength(row.get("credit"), "low_credit.credit")
        did = _nonempty_str(row.get("dispatch_id"),
                            "low_credit.dispatch_id")
        if credit >= floor:
            continue
        deficit = round(floor - credit, 6)
        rid = str(row.get("rollout_id") or "")
        out.append({"source": "refuted_credit", "gap_type": "knowledge",
                    "stage": join.get(did, "unknown"), "subject": did,
                    "strength": deficit,
                    "receipt": {"rollout_id": rid, "dispatch_id": did,
                                "credit": credit, "deficit": deficit}})
    return out


# ------------------------------------------------- the clustering wall

def _cluster(signals: list[dict]) -> list[dict]:
    """Merge same-(gap_type, stage) signals into candidates. Deterministic:
    receipts keep append order; subjects sorted; strengths summed per
    source; salience = the summed strengths (monotone — no saturation
    constant; the loop's threshold owns the gate)."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for sig in signals:
        key = (sig["gap_type"], sig["stage"])
        groups.setdefault(key, []).append(sig)
    out: list[dict] = []
    for (gap_type, stage), group in groups.items():
        strengths: dict[str, float] = {}
        for sig in group:
            strengths[sig["source"]] = round(
                strengths.get(sig["source"], 0.0)
                + sig["strength"], 6)
        subjects = sorted({sig["subject"] for sig in group})
        draft = {"gap_type": gap_type, "stage": stage,
                 "subjects": subjects, "strengths": strengths}
        salience = round(sum(strengths.values()), 6)
        out.append({
            "schema": CANDIDATE_SCHEMA,
            "gap_type": gap_type, "stage": stage,
            "subjects": subjects, "draft": draft,
            "formulation": "",
            "exploration_direction": list(subjects),
            "salience": salience,
            "source_receipts": [sig["receipt"] for sig in group],
            "sources": sorted(strengths),
        })
    out.sort(key=lambda c: (-c["salience"], c["gap_type"], c["stage"]))
    return out


# --------------------------------------------------------- the face

def aggregate(ws, *, memory_query: Callable[[Mapping], Any] | None = None,
              formulate_fn: Callable[[Mapping], Any] | None = None
              ) -> dict:
    """Aggregate the five sources' signals into ranked candidate gap
    formulations. ADVISORY ONLY — pure function of the workspace: no
    ledger row, no telemetry, no firing (the loop decides per budget +
    salience; DISTILL keeps the #938 contract). ``memory_query`` and
    ``formulate_fn`` are the injected seams; absent seams contribute
    nothing (no mock in production).

    ``memory_query(draft)`` -> None (unknown) or a Mapping whose truthy
    ``distilled`` suppresses the candidate (already-distilled gaps
    don't re-trigger). ``formulate_fn(draft)`` -> the formulation prose
    (a non-string raises; whitespace = an honest decline). Both receive
    the candidate's structured draft; the #583 bridge owns the memory
    key derivation (situation-signature × gap type)."""
    ws = Path(ws)
    actions = _action_rows(ws)
    signals = [*_shelf_miss_signals(actions),
               *_stagnation_signals(actions),
               *_open_question_signals(ws, actions),
               *_refuted_credit_signals(ws, actions)]
    candidates = _cluster(signals)
    suppressed: list[dict] = []
    survivors: list[dict] = []
    for candidate in candidates:
        if memory_query is not None:
            memory = memory_query(candidate["draft"])
            if memory is not None and not isinstance(memory, Mapping):
                raise _fail("memory_query",
                            f"must return None or a mapping, got "
                            f"{memory!r}")
            if isinstance(memory, Mapping) and memory.get("distilled"):
                suppressed.append({"reason": SUPPRESS_REASON,
                                   "candidate": candidate,
                                   "memory_receipt": dict(memory)})
                continue
        survivors.append(candidate)
    if formulate_fn is not None:
        for candidate in survivors:
            prose = formulate_fn(candidate["draft"])
            if not isinstance(prose, str):
                raise _fail("formulate_fn",
                            f"must return a string, got {prose!r}")
            candidate["formulation"] = prose.strip()
    return {"schema": SCHEMA, "advisory": True,
            "candidates": survivors, "memory_suppressed": suppressed,
            "seams": {"memory_query": memory_query is not None,
                      "formulate_fn": formulate_fn is not None}}
