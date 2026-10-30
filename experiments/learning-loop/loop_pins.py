# -*- coding: utf-8 -*-
"""loop_pins.py — the carried pins as faces (#913).

The unified decision loop's carried pins — the #50①② residuals and
the #898 review duty — pinned here as pure data faces the loop wire
(experiments/learning-loop/loop.py) imports and enforces:

  PHASE ENVELOPE   the closed phase vocabulary (triage / understand /
                   build-env / extract / verify) and the goal-tree
                   inference rule. The rule: the count of the
                   ROLLOUT's own PROVEN subgoals (id prefix
                   ``g-{rollout_id}``) indexes the phase ladder —
                   rung 0 is triage, each proven rung advances one
                   phase, a saturated ladder stays at verify (a
                   recurring task re-proves its rungs). Another
                   rollout's proven rungs never leak into this one's
                   phase. The worker MAY challenge through the mock
                   output's ``phase_challenge`` key; a legal challenge
                   is recorded on the dispatch receipt (the
                   orchestrator's inference stays authoritative for
                   the current dispatch), an off-vocab challenge is a
                   caller bug and refuses.
  INTENT           the closed per-phase intent table: what the
                   dispatch expects to produce (expected_output) and
                   which uncertainty it eliminates
                   (eliminates_uncertainty) — derived from the
                   phase's goal-tree position. ``require_intent`` is
                   the loop's fail-closed gate: a dispatch without a
                   real declaration is structural and lands nothing.
  EVIDENCE WALL    THE LOOP'S PINNED DUTY (#898's review): before
                   ``state/evaluation.apply_proposals`` banks a
                   proposal, every evidence_ref must resolve into the
                   fact base (``<ws>/facts/F*.md``). apply_proposals
                   itself checks the refs' NAME SHAPE only; the
                   byte-anchor EXISTENCE check lives here, so a
                   fabricated ref refuses the WHOLE evaluation before
                   the state ever exists and P never moves.
                   ``bank_evaluation`` is the single banking seam —
                   wall then apply_proposals — unbypassable by
                   construction.

All faces are pure data: no clock, no ledger write, no sampling (the
#251 contract).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parents[1] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import q_cells  # noqa: E402 — the bootstrap lands first
from state import evaluation  # noqa: E402
from state import progress  # noqa: E402
import numpy as np  # noqa: E402

from credit import advantage as credit_advantage  # noqa: E402

#: the closed phase vocabulary (#50①) — the dispatch envelope's tag
PHASES: tuple[str, ...] = ("triage", "understand", "build-env",
                           "extract", "verify")

#: the loop family's shared identity: the policy face the receipts
#: carry and the loop's recurring benchmark task (imported by the
#: wiring and the seam mixin alike)
POLICY_VERSION = "rl-v2-loop/913"
CORE_TASK = "core"

#: the per-phase intent table (#50②): what the dispatch expects to
#: produce and which uncertainty it eliminates — the loop REQUIRES a
#: real declaration per dispatch (fail-closed), and the table is the
#: documented derivation from the phase's goal-tree position
INTENTS: dict[str, dict[str, str]] = {
    "triage": {
        "expected_output":
            "the ground sort: which method family plausibly answers "
            "the task's question",
        "eliminates_uncertainty":
            "the direction uncertainty — whether the tracked "
            "direction applies to this surface at all",
    },
    "understand": {
        "expected_output":
            "one verified premise the later rungs build on",
        "eliminates_uncertainty":
            "the premise uncertainty at the first ladder rung",
    },
    "build-env": {
        "expected_output":
            "a reproducible environment premise (the can-run fact)",
        "eliminates_uncertainty":
            "the can-run uncertainty the extraction rung needs",
    },
    "extract": {
        "expected_output":
            "the extracted artifact the verify rung will check",
        "eliminates_uncertainty":
            "the content uncertainty — what the target actually does",
    },
    "verify": {
        "expected_output":
            "a reproduced, byte-anchored verification of the "
            "extracted artifact",
        "eliminates_uncertainty":
            "the verdict uncertainty — whether the extracted claim "
            "stands",
    },
}


class LoopError(ValueError):
    """The loop family's fail-closed boundary: a structural offense (a
    missing intent, a fabricated evidence ref, an off-vocab phase
    challenge, a bad fault request) refuses loudly, never silently
    degrades."""


def situation_signature(situation: str) -> str:
    """The situation's 12-hex state signature — SAME situation, SAME
    signature: the fold cell the learning banks into is keyed by it."""
    digest = hashlib.sha256(
        f"loop913-situation/{situation}".encode("utf-8"))
    return digest.hexdigest()[:12]


def arm_key(family: str) -> str:
    """The 4-dim fold key the loop banks credit under (the loop_sim_v3
    arm shape)."""
    return q_cells.arm_key(family, "facts_snapshot", "none", 1)


def infer_phase(tree: Sequence[progress.Subgoal],
                rollout_id: str) -> str:
    """The goal-tree position -> phase (the documented inference
    rule): the count of the ROLLOUT's own PROVEN subgoals (id prefix
    ``g-{rollout_id}``) indexes the closed phase ladder — rung 0 is
    triage, each proven rung advances one phase, and a saturated
    ladder stays at verify (a recurring task re-proves its rungs)."""
    if not isinstance(rollout_id, str) or not rollout_id.strip():
        raise LoopError("loop.infer_phase: rollout_id must be a "
                        "non-empty string")
    prefix = f"g-{rollout_id}"
    rung = sum(1 for g in tree
               if g.id.startswith(prefix) and g.status == "PROVEN")
    return PHASES[min(rung, len(PHASES) - 1)]


def declare_intent(phase: str, task_id: str) -> dict[str, str]:
    """The dispatch's intent declaration (#50②) from the closed
    per-phase table. Pure data; a phase off the vocab is a caller
    bug."""
    if phase not in PHASES:
        raise LoopError(f"loop.declare_intent: phase {phase!r} outside "
                        f"the closed vocab {PHASES}")
    if not isinstance(task_id, str) or not task_id.strip():
        raise LoopError("loop.declare_intent: task_id must be a "
                        "non-empty string")
    base = INTENTS[phase]
    return {"expected_output": base["expected_output"],
            "eliminates_uncertainty": base["eliminates_uncertainty"]}


def require_intent(intent: object) -> dict[str, str]:
    """The fail-closed intent gate: a dispatch without a real
    expected_output AND a real eliminates_uncertainty is structural —
    it never assigns, never executes, never lands a row."""
    if not isinstance(intent, Mapping):
        raise LoopError("loop.require_intent: the intent declaration "
                        f"is missing (got {intent!r})")
    out: dict[str, str] = {}
    for field in ("expected_output", "eliminates_uncertainty"):
        value = intent.get(field)
        if not isinstance(value, str) or not value.strip():
            raise LoopError(f"loop.require_intent: intent.{field} must "
                            f"be a non-empty string, got {value!r}")
        out[field] = value
    return out


def fact_base_ids(ws: Path) -> set[str]:
    """The fact base's ids — the stems of ``<ws>/facts/F*.md`` (the
    belief face's own glob). An absent facts dir is the honest empty."""
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return set()
    return {p.stem for p in facts_dir.glob("F*.md")}


def evidence_wall(ws: Path, doc: Mapping) -> None:
    """The evidence-wall existence check: every evidence_ref in the
    document's banking proposals must resolve into the fact base
    BEFORE apply_proposals runs. A fabricated ref refuses the whole
    evaluation here, never banks (see the module docstring)."""
    checked = evaluation.validate_evaluation(doc)
    known = fact_base_ids(ws)
    for i, proposal in enumerate(checked.get("proposals", [])):
        for ref in proposal["evidence_refs"]:
            if ref not in known:
                raise LoopError(
                    "loop.evidence_wall: evidence ref "
                    f"{ref!r} (proposals[{i}]) does not resolve into "
                    f"the fact base {sorted(known)} — refuse before "
                    "apply_proposals banks")


def bank_evaluation(ws: Path, tree: Sequence[progress.Subgoal],
                    doc: Mapping) -> tuple[progress.Subgoal, ...]:
    """The loop's single banking seam: the evidence wall, THEN
    apply_proposals. Everything that moves P through an evaluation
    goes through here — the wall is unbypassable by construction."""
    evidence_wall(ws, doc)
    return evaluation.apply_proposals(tree, doc)


def terminal_advantage(shaped_rewards: Sequence[float],
                       confidences: Sequence[float],
                       p_decisions: Sequence[float]) -> dict[str, Any]:
    """The V-wired advantage over one rollout's shaped returns: the
    decision-time P series feeds credit/advantage through
    progress.values_from — a moving baseline subtracts (A = R − V);
    a FLAT series (or an empty one) is the pinned cold start where
    values_from is None and A == R elementwise. The advantage is
    confidence-modulated (the EMxPG posture)."""
    shaped = np.asarray(shaped_rewards, dtype=float)
    values = progress.values_from(p_decisions)
    adv = credit_advantage.modulate(
        credit_advantage.advantages(shaped, values),
        np.asarray(confidences, dtype=float))
    return {"shaped": shaped,
            "advantage": adv,
            "values": None if values is None
            else [round(float(v), 6) for v in values],
            "source": "values" if values is not None else "cold"}
