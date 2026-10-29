# -*- coding: utf-8 -*-
"""policy/prober.py — the probe portfolio, the PROBE face (issue 881).

A portfolio runs one LEADER at full Budget plus exactly TWO PROBES at
a time-boxed fraction: the leader chases the step; the probes exist
only for discriminative evidence about the OTHER candidate families.
The plan is pure — (ws, families, budget) -> receipt; execution
belongs to the loop. Evidence lands through ``record_probe``, the one
write face, and it lands THROUGH the ledger, never a parallel store:
one probe = three rows of the ONE consolidated experience stream —

  1. a ``q-cell-action/1`` row, kind=probe (the decision trace; the
     comparison data rides params),
  2. a ``q-cell-result/1`` row (the evidence trace; the comparison
     rides summary, ``r_t`` stays pending — a probe never fabricates
     an absolute reward),
  3. a ``q-cell-obs/1`` row — the ONLY row shape the fold banks — so
     the next assigner's fold actually SEES the probe (credit_kind
     "step", source "probe", the family's arm key).

The posterior admission is potential-based: the probe reports a RANK
over the portfolio's arms (a comparison, not a score), and the
documented linear map below turns the rank into a bounded credit —
never a full success, never a full failure. A time-boxed side-arm
cannot bank certainty in either direction; it can only re-order the
posterior means the next assignment samples from.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_LOOP = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_SCRIPTS, _LOOP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import method_families  # noqa: E402 — the closed vocabulary owner
from core import Action, ActionKind, Budget, Context  # noqa: E402
from rlvr import q_cells  # noqa: E402 — the store face (library use)

SCHEMA = "portfolio-plan/1"
RECORD_SCHEMA = "probe-record/1"
POLICY_VERSION = "rl-v2-probe/1"

#: portfolio shape: one leader plus exactly two probe arms.
PROBE_ARMS = 2

#: probe Budget = this fraction of the leader's. Policy constant,
#: documented NOT fitted (the method_families constant posture): the
#: probes are evidence arms, never competing budgets.
PROBE_WALL_FRACTION = 0.25

#: the potential map's rails (documented NOT fitted): a probe's rank-1
#: credit and its last-place credit. Bounded away from 0 and 1 — the
#: side-arm's evidence can tilt the posterior, never own it.
PROBE_CREDIT_FLOOR = 0.25
PROBE_CREDIT_CEIL = 0.75

#: the arm-key recipe/verification segments the fold's family-grain
#: read aggregates over (the same defaults the sampler's fixtures use).
_RECIPE_SEGMENT = "facts_snapshot"
_VERIF_SEGMENT = "none"

_SIG_RE = re.compile(r"^[0-9a-f]{12}$")


def _validate_signature(signature_hash: object) -> str:
    if not isinstance(signature_hash, str) \
            or not _SIG_RE.fullmatch(signature_hash):
        raise ValueError(
            f"signature_hash must be a 12-hex signature hash; "
            f"got {signature_hash!r:.80}")
    return signature_hash


def _checked_family(token: object, vocab: frozenset[str],
                    role: str) -> str:
    if not isinstance(token, str) or not token or token.strip() != token:
        raise ValueError(f"{role} must be a bare family token: {token!r:.80}")
    if token not in vocab:
        raise ValueError(
            f"{role} outside the closed method-family vocabulary: "
            f"{token!r}")
    return token


def _checked_probes(probe_candidates: object, vocab: frozenset[str],
                    leader: str) -> list[str]:
    if not isinstance(probe_candidates, (list, tuple)) \
            or len(probe_candidates) != PROBE_ARMS:
        raise ValueError(
            f"a portfolio is one leader plus exactly {PROBE_ARMS} probes; "
            f"got {probe_candidates!r:.80}")
    probes: list[str] = []
    for cand in probe_candidates:
        family = _checked_family(cand, vocab, "probe candidate")
        if family == leader:
            raise ValueError(
                f"a probe arm is another family, not the leader's own: "
                f"{family!r}")
        if family in probes:
            raise ValueError(f"duplicate probe arm: {family!r}")
        probes.append(family)
    return probes


def _budget_doc(budget: Budget) -> dict:
    return {"wall_s": float(budget.wall_s), "max_calls": budget.max_calls}


def _probe_budget(leader: Budget) -> Budget:
    """The fractioned probe Budget (the documented policy constant);
    a fractional call count floors to at least one — a zero-call probe
    is not an arm."""
    calls = None
    if leader.max_calls is not None:
        calls = max(1, int(leader.max_calls * PROBE_WALL_FRACTION))
    return Budget(wall_s=leader.wall_s * PROBE_WALL_FRACTION,
                  max_calls=calls)


def plan_portfolio(ws, leader_family, probe_candidates, *,
                   signature_hash, budget: Budget) -> dict:
    """Plan the leader + two-probe portfolio — pure, no rows written.

    ``budget`` is the LEADER's core Budget (wall seconds + optional
    call cap); each probe arm gets the documented fraction of it.
    Fail-closed: leader and probes must be distinct tokens of the
    closed registry vocabulary, the probe count is exactly
    ``PROBE_ARMS``, and the budget is a real non-negative Budget.

    Receipt (schema ``portfolio-plan/1``): the leader arm and the two
    probe arms, each {family, budget}, plus the fraction constant the
    plan applied — the audit trail never hides its arithmetic.
    """
    sig = _validate_signature(signature_hash)
    if not isinstance(budget, Budget):
        raise ValueError("budget must be a core Budget value object")
    if budget.wall_s < 0.0:
        raise ValueError("budget.wall_s must be >= 0")
    vocab = method_families.registered_tokens(ws)
    leader = _checked_family(leader_family, vocab, "leader_family")
    probes = _checked_probes(probe_candidates, vocab, leader)
    probe_b = _probe_budget(budget)
    return {
        "schema": SCHEMA,
        "signature_hash": sig,
        "leader": {"family": leader, "budget": _budget_doc(budget)},
        "probes": [{"family": family, "budget": _budget_doc(probe_b)}
                   for family in probes],
        "probe_wall_fraction": PROBE_WALL_FRACTION,
    }


def _potential_credit(rank: int, arms: int) -> float:
    """The rank -> credit map, linear on the documented rails: the
    comparison's WINNER banks PROBE_CREDIT_CEIL, the last place
    PROBE_CREDIT_FLOOR, the middle interpolates. Potential-based: the
    credit states the arm's RELATIVE standing inside this portfolio,
    never an absolute quality claim."""
    span = PROBE_CREDIT_CEIL - PROBE_CREDIT_FLOOR
    return PROBE_CREDIT_FLOOR + span * (arms - rank) / (arms - 1)


def _checked_plan(plan: object) -> dict:
    if not isinstance(plan, dict) or plan.get("schema") != SCHEMA:
        raise ValueError(
            f"plan must be a {SCHEMA} receipt; got {plan!r:.80}")
    probes = plan.get("probes")
    if not isinstance(probes, list) or len(probes) != PROBE_ARMS:
        raise ValueError("plan carries a malformed probe arm list")
    return plan


def _checked_rank(rank: object, arms: int) -> int:
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise ValueError(f"rank must be an integer 1..{arms}; got {rank!r}")
    if not 1 <= rank <= arms:
        raise ValueError(f"rank must be an integer 1..{arms}; got {rank!r}")
    return rank


def _checked_arm(plan: dict, probe_family: object) -> tuple[int, dict]:
    """The family must be one of THIS plan's probe arms; returns
    (arms_total, the arm's budget doc)."""
    arm_families = [str(p.get("family")) for p in plan["probes"]]
    if probe_family not in arm_families:
        raise ValueError(
            f"probe_family is not an arm of this portfolio: "
            f"{probe_family!r}")
    budget_doc = next(p["budget"] for p in plan["probes"]
                      if p["family"] == probe_family)
    return 1 + len(arm_families), budget_doc


def _append_probe_rows(ws, plan: dict, probe_family: str, r: int,
                       arms: int, budget_doc: dict, *, rollout_id,
                       step_id, verified: bool, verdict: str,
                       evidence_refs, summary: str,
                       ts: str | None) -> dict:
    """The three-row landing: action trace (kind=probe, the comparison
    in params), result trace (the comparison in summary, r_t pending —
    a probe never prices its own evidence), and the fold-admitted
    observation (source=probe, credit_kind=step)."""
    leader = str(plan["leader"]["family"])
    action = Action(
        kind=ActionKind.PROBE,
        target=probe_family,
        params={"portfolio": SCHEMA, "rank": r, "arms": arms,
                "potential_based": True, "leader": leader},
        budget=Budget(wall_s=float(budget_doc["wall_s"]),
                      max_calls=budget_doc["max_calls"]),
        context=Context(rollout_id=rollout_id, step_id=step_id,
                        policy_version=POLICY_VERSION))
    action_row = q_cells.append_action(
        ws, kind=action.kind.value, rollout_id=rollout_id,
        step_id=step_id, target=probe_family, params=dict(action.params),
        budget=_budget_doc(action.budget), policy_version=POLICY_VERSION,
        ts=ts)
    result_row = q_cells.append_result(
        ws, rollout_id=rollout_id, step_id=step_id,
        r_t=None,  # a probe never prices its own evidence
        verified=verified, verdict=verdict,
        evidence_refs=evidence_refs,
        summary=summary or f"probe rank={r}/{arms} vs leader={leader} "
                           f"(potential-based comparison)",
        ts=ts)
    obs_row = q_cells.append_observation(
        ws, str(plan["signature_hash"]), probe_family,
        _potential_credit(r, arms),
        source="probe",
        arm_key_col=q_cells.arm_key(probe_family, _RECIPE_SEGMENT,
                                    _VERIF_SEGMENT, 0),
        credit_kind="step",
        reason=f"potential-comparison rank={r}/{arms}",
        ts=ts)
    return {"action": action_row, "result": result_row, "obs": obs_row}


def record_probe(ws, plan, probe_family, *, rollout_id, step_id, rank,
                 verified: bool, verdict: str = "", evidence_refs=(),
                 summary: str = "", ts: str | None = None) -> dict:
    """Land ONE probe's evidence in the ledger (the portfolio's one
    write face — three rows, one stream; see the module docstring).

    ``rank`` is the potential-based input: the probe arm's standing
    among the portfolio's arms (1 = strongest evidence of the run).
    The action row's params carry the comparison data, the result
    row's summary names it (``rank=r/arms``), and the observation row
    banks the mapped credit so the next assigner's fold sees the
    probe. IDEMPOTENT on (rollout_id, step_id): a probe probe-identity
    already carrying a kind=probe action row is refused with
    ``already-landed`` — the three-row landing is not atomic, so a
    crash mid-landing followed by a blind retry must never double-bank
    the posterior credit (a re-run after a FULL landing converges to
    the refusal, never to a second observation row). Fail-closed: the
    family must be one of THIS plan's probe arms and the rank a valid
    standing — a raise here is a loop bug surfacing, never a silent
    drop."""
    plan = _checked_plan(plan)
    arms, budget_doc = _checked_arm(plan, probe_family)
    r = _checked_rank(rank, arms)
    if not isinstance(verified, bool):
        raise ValueError("verified must be a bool")
    rid = rollout_id if isinstance(rollout_id, str) \
        and rollout_id.strip() else None
    sid = step_id if isinstance(step_id, str) and step_id.strip() else None
    if not rid or not sid:
        raise ValueError("policy.prober.record_probe: rollout_id and "
                         "step_id must be non-empty strings")
    for row in q_cells.trajectory_rows(ws):
        if row.get("schema") == q_cells.SCHEMA_ACTION_V2 \
                and row.get("kind") == "probe" \
                and str(row.get("rollout_id") or "") == rid \
                and str(row.get("step_id") or "") == sid:
            return {"schema": RECORD_SCHEMA, "portfolio": SCHEMA,
                    "family": probe_family, "rank": r,
                    "appended": {"action": False, "result": False,
                                 "observation": False},
                    "reason": "already-landed",
                    "rollout_id": rid, "step_id": sid}
    rows = _append_probe_rows(
        ws, plan, probe_family, r, arms, budget_doc,
        rollout_id=rollout_id, step_id=step_id, verified=verified,
        verdict=verdict, evidence_refs=evidence_refs, summary=summary,
        ts=ts)
    return {
        "schema": RECORD_SCHEMA,
        "portfolio": SCHEMA,
        "family": probe_family,
        "rank": r,
        "credit": round(_potential_credit(r, arms), 6),
        "appended": {
            "action": rows["action"]["appended"],
            "result": rows["result"]["appended"],
            "observation": rows["obs"]["appended"],
        },
    }
