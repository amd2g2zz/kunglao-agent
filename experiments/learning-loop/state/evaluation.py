# -*- coding: utf-8 -*-
"""state/evaluation.py — the structured trajectory-evaluation document
(the scope-verifier's output CONTRACT as data) (#898).

The scope-verifier's output is DATA, never authority: this module holds
the ``trajectory-evaluation/1`` schema — ``new_facts`` /
``validated_hypotheses`` / ``rejected_hypotheses`` / ``unresolved_questions``
/ ``exploration_progress`` (0-1) / ``redundancy`` (0-1) /
``possible_new_directions`` — plus the fail-closed validator and the
machine-actionable ``proposals`` list (the subgoal status moves the
evaluation proposes).

Two walls, both pinned here:

- **the evidence-banking rule** (#799 posture): a proposal into a
  cross-validated status ({PROVEN, VERIFIED, NEGATIVE}) MUST carry
  evidence_refs. A worker-typed / LLM-claimed transition without the
  evidence class banks NOTHING — the validator refuses it, so the state
  never exists and P never moves.
- **the single-authority wall**: the evaluation document does NOT bank P
  by itself — it PROPOSES subgoal status moves. The LLM's own
  ``exploration_progress`` / ``redundancy`` scores are validated
  TELEMETRY (stagnation/review inputs) and never price P; P only moves
  when ``apply_proposals`` moves a subgoal on a ladder-supported,
  evidence-carrying proposal. LLM proposes, the ladder disposes.

``rejected_hypotheses`` is the feed the Φ-tree ledger consumes (the
hypothesis-accounting half — elimination rows — lives in
``scripts/rlvr/phi_tree.py``; this face only certifies the list's shape).
"""
from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from rlvr import q_cells  # noqa: E402 — the path bootstrap lands first

from . import progress as _progress  # noqa: E402

SCHEMA = "trajectory-evaluation/1"

#: the seven structured fields (the scope-verifier's output contract)
STRING_LIST_FIELDS = ("new_facts", "validated_hypotheses",
                      "rejected_hypotheses", "unresolved_questions",
                      "possible_new_directions")
SCORE_FIELDS = ("exploration_progress", "redundancy")

#: statuses a proposal may bank INTO only with evidence refs — the
#: cross-validated band. A proposal to UNVERIFIED (a reset/down-weight)
#: needs no refs: it banks no progress by construction.
BANKING_STATUSES = _progress.STATUSES - {_progress.STATUS_UNVERIFIED}

SOURCE = _progress.SOURCE
METHOD_FAMILY_EVALUATION = "state-evaluation"
REASON_EVALUATION = "trajectory-evaluation-proposal"


class EvaluationError(ValueError):
    """A document is not a legal `trajectory-evaluation/1`. The message
    names the offending field (fail-closed, machine-readable)."""


def _fail(field: str, why: str) -> EvaluationError:
    return EvaluationError(f"state.evaluation.{field}: {why}")


def _string_list(doc: Mapping, field: str) -> None:
    items = doc.get(field)
    if not isinstance(items, list):
        raise _fail(field, "must be a list")
    for i, item in enumerate(items):
        if not isinstance(item, str) or not item.strip():
            raise _fail(field, f"[{i}] must be a non-empty string, "
                               f"got {item!r}")


def _unit_score(doc: Mapping, field: str) -> None:
    value = doc.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise _fail(field, "must be a finite number in [0, 1]")


def _checked_proposal(proposal: Any, index: int) -> dict:
    if not isinstance(proposal, Mapping):
        raise _fail("proposals", f"[{index}] not a mapping")
    gid = proposal.get("subgoal_id")
    if not isinstance(gid, str) or not gid.strip():
        raise _fail(f"proposals[{index}].subgoal_id",
                    "must be a non-empty string")
    to_status = proposal.get("to_status")
    if to_status not in _progress.STATUSES:
        raise _fail(f"proposals[{index}].to_status",
                    f"must be one of {sorted(_progress.STATUSES)}, "
                    f"got {to_status!r}")
    refs = proposal.get("evidence_refs", ())
    if isinstance(refs, (str, bytes)) or not isinstance(refs, Sequence):
        raise _fail(f"proposals[{index}].evidence_refs",
                    "must be a sequence of non-empty strings")
    clean = tuple(refs)
    if any(not isinstance(r, str) or not r.strip() for r in clean):
        raise _fail(f"proposals[{index}].evidence_refs",
                    "each ref must be a non-empty string")
    if to_status in BANKING_STATUSES and not clean:
        # the #799 posture: an LLM-claimed transition into the
        # cross-validated band without the evidence class banks NOTHING
        raise _fail(f"proposals[{index}].evidence_refs",
                    f"a proposal into {to_status} must carry at least "
                    "one evidence ref (a claim without evidence class "
                    "is refused, never banked)")
    return {"subgoal_id": gid, "to_status": to_status,
            "evidence_refs": clean}


def _checked_proposals(doc: Mapping) -> list[dict]:
    proposals = doc.get("proposals", [])
    if not isinstance(proposals, list):
        raise _fail("proposals", "must be a list when present")
    return [_checked_proposal(p, i) for i, p in enumerate(proposals)]


def validate_evaluation(doc) -> dict:
    """Validate one trajectory-evaluation document. Returns the document
    on success; raises EvaluationError naming the offending field
    otherwise. Pure — no IO, no mutation (returns the input reference)."""
    if not isinstance(doc, Mapping):
        raise _fail("(root)", "not a mapping")
    if doc.get("schema") != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA!r}")
    for field in STRING_LIST_FIELDS:
        _string_list(doc, field)
    for field in SCORE_FIELDS:
        _unit_score(doc, field)
    _checked_proposals(doc)
    return doc


def apply_proposals(subgoals: Sequence, doc: Mapping) -> tuple:
    """The single seam where an evaluation touches P: apply the doc's
    validated proposals to the goal tree and return the NEW tree (the
    input sequence is never mutated). Fail-closed: an unknown subgoal id
    or two proposals for one subgoal refuse (silently skipping would
    fabricate progress; silently merging would hide an ambiguity)."""
    # EVIDENCE WALL SCOPE (pinned for the loop-wiring card): this
    # face checks the evidence_refs NAME SHAPE — the byte-anchor
    # EXISTENCE check (refs must resolve into the fact base) is the
    # loop's duty before apply_proposals runs; a fabricated ref that
    # never resolves must refuse there, never bank here.
    checked = validate_evaluation(doc).get("proposals", [])
    by_id = {s.id: s for s in subgoals}
    if len(by_id) != len(subgoals):
        raise _fail("(tree)", "duplicate subgoal ids in the input tree")
    moved: dict[str, dict] = {}
    for p in checked:
        if p["subgoal_id"] not in by_id:
            raise _fail("proposals",
                        f"unknown subgoal {p['subgoal_id']!r} "
                        "(a proposal names a subgoal outside the tree)")
        if p["subgoal_id"] in moved:
            raise _fail("proposals",
                        f"two proposals target {p['subgoal_id']!r} "
                        "(ambiguous — refuse)")
        moved[p["subgoal_id"]] = p
    out = []
    for s in subgoals:
        p = moved.get(s.id)
        if p is None:
            out.append(s)
            continue
        merged = list(s.evidence_refs)
        for ref in p["evidence_refs"]:
            if ref not in merged:
                merged.append(ref)
        out.append(_progress.Subgoal(id=s.id, status=p["to_status"],
                                     evidence_refs=tuple(merged),
                                     confidence=s.confidence))
    return tuple(out)


def evaluation_digest(doc: Mapping) -> str:
    """Content digest of a validated document (never clock-derived, the
    #251 contract)."""
    payload = json.dumps(validate_evaluation(doc), sort_keys=True,
                         separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def record_evaluation(ws, doc: Mapping, *, claim: str | None = None,
                      dispatch_id: str | None = None) -> dict:
    """Append ONE observation row for a validated evaluation —
    ``credit=None`` by construction (no credit column -> the fold banks
    no posterior mass; the evaluation proposes, settlement credits)."""
    validate_evaluation(doc)
    return q_cells.append_observation(
        ws, evaluation_digest(doc), METHOD_FAMILY_EVALUATION,
        credit=None, source=SOURCE, claim=claim, dispatch_id=dispatch_id,
        reason=REASON_EVALUATION)
