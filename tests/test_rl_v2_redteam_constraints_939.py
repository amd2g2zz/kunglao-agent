# -*- coding: utf-8 -*-
"""tests/test_rl_v2_redteam_constraints_939.py — the redteam
autonomous-planning constraint face (issue 939).

The owner directive: redteam's autonomous planning needs explicit
action constraints (what redteam may do) and planning constraints (how
it plans). The face is DECLARATIVE — a frozen constraint table + a
validation wall — and the plan is a STRUCTURE (declared fields; the
planner itself lives in the agent, never here). validate_plan refuses
violating plans fail-closed NAMING the violated constraint (the #924
param-wall pattern); a conforming plan passes UNCHANGED, so the #933
machinery consumes constrained plans with zero behavior change.

  ACTION    read-only toward worker outputs (fact conclusions and
            worker narratives are never read — the blind-check
            discipline on the planning surface); no settlement-face
            mutation (redteam rules, the deterministic stack prices);
            every planned challenge carries anchorable refs (the
            citation wall extended to PLANNING); strategy weights are
            never self-granted (the posterior's guidance or the
            first-entry prior — nothing else).
  PLANNING  canary-pool coverage never reduces (the GAP collapse
            signal is the mechanical rejection criterion); plans run
            within the strategy posterior's guidance, deviations
            REQUIRE a declared reason (recorded, not refused — the
            orchestrator dispatch-deviation discipline); motives and
            constraints are declared (the R3 identification
            discipline applied to redteam's own planning); plan
            cycles consume the budget scale.
  DISTILL   the ONE declarative check: when redteam is the
            independent executor of a distill act (not involving the
            worker), the SAME constraint face applies — no relaxation
            path exists.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) in sys.path:
        continue
    sys.path.insert(0, str(_p))

from policy import redteam  # noqa: E402
from policy import redteam_constraints as rc  # noqa: E402


# ------------------------------------------------------------- helpers

def _context(**kw) -> rc.RedteamPlanContext:
    """A conforming planning context: two posterior-guided strategies,
    0.8 canary coverage held, 3 cycles of budget."""
    base = {"posterior_strategies": ("anchor-first", "pool-sweep"),
            "current_canary_coverage": 0.8,
            "budget_remaining": 3,
            "act": "detect",
            "involves_worker": True}
    base.update(kw)
    return rc.RedteamPlanContext(**base)


def _conforming_plan(**kw) -> rc.RedteamPlan:
    """A conforming plan: anchored challenges, evidence-only reads,
    posterior strategy, coverage held, annotation present."""
    base = {"plan_id": "p-1",
            "cycles": 2,
            "strategy": "anchor-first",
            "reads": ("raw_evidence", "step_artifacts"),
            "mutations": ("challenge_rows",),
            "challenges": (rc.PlannedChallenge(kind="fabricated-evidence",
                                               refs=("R-K1", "E-7")),),
            "strategy_weights": (rc.StrategyWeight("anchor-first", 0.75),),
            "canary_coverage": 0.8,
            "deviation_reason": None,
            "motives": "attack-test every claim before promotion",
            "constraints_note": "read-only; no settlement mutation",
            }
    base.update(kw)
    return rc.RedteamPlan(**base)


def _refuses(plan: rc.RedteamPlan, ctx: rc.RedteamPlanContext,
             constraint: str) -> None:
    """The wall refuses fail-closed NAMING the violated constraint."""
    with pytest.raises(rc.PlanRefused) as err:
        rc.validate_plan(plan, ctx)
    assert err.value.constraint == constraint
    assert constraint in str(err.value)


# ------------------------------------------ 1. the declarative face

def test_constraint_face_is_declarative_frozen_and_exact():
    """The face is ONE frozen table naming exactly the eight card
    constraints at their declared values — the declaration is data,
    immutable, and complete."""
    with pytest.raises(TypeError):
        rc.REDTEAM_PLAN_CONSTRAINTS["read_only_worker_outputs"] = False  # type: ignore[index]
    face = dataclasses.asdict(rc.REDTEAM_PLAN_CONSTRAINTS)
    assert face == {
        "read_only_worker_outputs": True,
        "mutates_settlement": False,
        "challenge_requires_anchors": True,
        "strategy_weights_self_granted": False,
        "canary_floor": True,
        "posterior_guided": True,
        "motives_constraints_declared": True,
        "budget_bounded": True,
    }


def test_plan_structure_is_declared_and_fail_closed():
    """The plan is a structure with declared fields — junk cycles and
    out-of-range coverage raise naming the field (the structural
    failure is not a constraint verdict); booleans never pass as
    numbers."""
    plan = _conforming_plan()
    assert plan.plan_id == "p-1"
    for kw in ({"cycles": -1}, {"cycles": True}, {"cycles": "2"},
               {"cycles": None}):
        with pytest.raises(ValueError):
            _conforming_plan(**kw)
    with pytest.raises(ValueError):
        _conforming_plan(canary_coverage=1.5)
    with pytest.raises(ValueError):
        _conforming_plan(canary_coverage=float("nan"))


def test_context_is_fail_closed():
    """The context validates at the boundary: a closed act vocabulary,
    bool involves_worker, finite bounded coverage, non-negative
    budget."""
    _context()
    with pytest.raises(ValueError):
        _context(act="freeform")
    with pytest.raises(ValueError):
        _context(involves_worker="yes")
    with pytest.raises(ValueError):
        _context(current_canary_coverage=1.2)
    with pytest.raises(ValueError):
        _context(budget_remaining=-1)


# --------------------------------------- 2. the action constraints

def test_read_only_worker_outputs_refuses_conclusion_reads():
    """A plan that reads the target's fact conclusions or the worker's
    narratives is REFUSED naming read_only_worker_outputs — raw
    evidence stays readable. The deny is case-folded (the #709
    lesson)."""
    ctx = _context()
    _refuses(_conforming_plan(reads=("raw_evidence",
                                     "fact_conclusions")),
             ctx, "read_only_worker_outputs")
    _refuses(_conforming_plan(reads=("worker_narratives",)),
             ctx, "read_only_worker_outputs")
    _refuses(_conforming_plan(reads=("Fact_Conclusions",)),
             ctx, "read_only_worker_outputs")
    rc.validate_plan(_conforming_plan(reads=("raw_evidence",)), ctx)


def test_mutates_settlement_refuses_settlement_mutations():
    """A plan step touching the settlement faces is REFUSED naming
    mutates_settlement — redteam rules, the deterministic stack
    prices; every other mutation surface passes."""
    ctx = _context()
    _refuses(_conforming_plan(mutations=("settlement",)),
             ctx, "mutates_settlement")
    _refuses(_conforming_plan(mutations=("challenge_rows",
                                         "settlement_faces")),
             ctx, "mutates_settlement")
    rc.validate_plan(_conforming_plan(mutations=("challenge_rows",)),
                     ctx)


def test_challenge_requires_anchors_refuses_unanchored_challenges():
    """A planned challenge without anchorable refs is REFUSED naming
    challenge_requires_anchors — the citation wall extended to
    PLANNING; every anchored challenge passes."""
    ctx = _context()
    _refuses(_conforming_plan(
        challenges=(rc.PlannedChallenge(kind="vague", refs=()),)),
        ctx, "challenge_requires_anchors")
    _refuses(_conforming_plan(
        challenges=(rc.PlannedChallenge(kind="a", refs=("R-1",)),
                    rc.PlannedChallenge(kind="b", refs=()),)),
        ctx, "challenge_requires_anchors")
    rc.validate_plan(_conforming_plan(), ctx)


def test_strategy_weights_never_self_granted():
    """A weight for a strategy OUTSIDE the posterior's guidance is
    refused naming strategy_weights_self_granted unless it enters AT
    THE PRIOR (the #933 uniform prior's first-entry weight); posterior
    strategies take any weight in range."""
    ctx = _context()
    _refuses(_conforming_plan(
        strategy_weights=(rc.StrategyWeight("novel-arm", 0.9),)),
        ctx, "strategy_weights_self_granted")
    rc.validate_plan(_conforming_plan(
        strategy_weights=(rc.StrategyWeight("novel-arm",
                                            rc.FIRST_ENTRY_WEIGHT),)),
        ctx)
    rc.validate_plan(_conforming_plan(
        strategy_weights=(rc.StrategyWeight("pool-sweep", 0.9),)),
        ctx)


# ------------------------------------ 3. the planning constraints

def test_canary_floor_refuses_coverage_reducing_plans():
    """The GAP collapse signal is the mechanical rejection criterion: a
    detection schedule that reduces canary-pool coverage below its
    current level is REFUSED naming canary_floor; holding or raising
    passes; an undeclared schedule refuses fail-closed."""
    ctx = _context(current_canary_coverage=0.8)
    _refuses(_conforming_plan(canary_coverage=0.5), ctx, "canary_floor")
    rc.validate_plan(_conforming_plan(canary_coverage=0.8), ctx)
    rc.validate_plan(_conforming_plan(canary_coverage=0.9), ctx)
    _refuses(_conforming_plan(canary_coverage=None), ctx, "canary_floor")


def test_posterior_deviations_recorded_not_refused():
    """The dispatch-deviation discipline: a plan deviating from the
    posterior's guidance WITHOUT a declared reason is refused naming
    posterior_guided; the SAME deviation WITH a reason PASSES and the
    receipt RECORDS it — deviation is a declared decision, never a
    silent one, and never a refusal."""
    ctx = _context(posterior_strategies=("anchor-first",))
    _refuses(_conforming_plan(strategy="pool-sweep"),
             ctx, "posterior_guided")
    receipt = rc.validate_plan(
        _conforming_plan(strategy="pool-sweep",
                         deviation_reason="held-out pool needs sweep"),
        ctx)
    assert receipt["accepted"] is True
    assert receipt["deviations"] == [
        {"kind": "posterior_guided", "strategy": "pool-sweep",
         "reason": "held-out pool needs sweep"}]
    rc.validate_plan(_conforming_plan(strategy="anchor-first"), ctx)


def test_motives_and_constraints_must_be_declared():
    """The R3 identification discipline on redteam's own planning: a
    plan missing its motives or its constraints annotation is REFUSED
    naming motives_constraints_declared; blank whitespace is a
    missing annotation."""
    ctx = _context()
    _refuses(_conforming_plan(motives=None), ctx,
             "motives_constraints_declared")
    _refuses(_conforming_plan(motives="   "), ctx,
             "motives_constraints_declared")
    _refuses(_conforming_plan(constraints_note=None), ctx,
             "motives_constraints_declared")


def test_budget_bounded_cycles():
    """Plan cycles consume the budget scale: a plan whose cycles exceed
    the remaining budget is REFUSED naming budget_bounded; a plan
    within it passes and the receipt shows the budget after the
    spend."""
    ctx = _context(budget_remaining=3)
    _refuses(_conforming_plan(cycles=4), ctx, "budget_bounded")
    receipt = rc.validate_plan(_conforming_plan(cycles=2), ctx)
    assert receipt["budget"] == {"cycles": 2, "remaining_after": 1}


# ----------------------------- 4. the happy path stays the #933 path

def test_conforming_plan_passes_with_full_receipt():
    """The happy path: a conforming plan passes with the standard
    scope, no recorded deviations, the full constraint face in the
    receipt — and the SAME face validates twice deterministically."""
    ctx = _context()
    receipt = rc.validate_plan(_conforming_plan(), ctx)
    assert receipt["accepted"] is True
    assert receipt["constraint_scope"] == "standard"
    assert receipt["deviations"] == []
    assert receipt["constraints"] == tuple(
        dataclasses.asdict(rc.REDTEAM_PLAN_CONSTRAINTS))
    again = rc.validate_plan(_conforming_plan(), ctx)
    assert again == receipt


def test_nine33_machinery_consumes_constrained_plans_unchanged():
    """The #933 behavior pin: a validated plan's challenges arbitrate
    EXACTLY as bare DebateCases — same verdicts, same reasons, same
    canary arithmetic. The wall sits at the planning boundary; the
    ruling machinery never learned it exists."""
    plan = _conforming_plan(
        challenges=(rc.PlannedChallenge(kind="fabricated",
                                        refs=("R-K1",)),
                    rc.PlannedChallenge(kind="unanchored", refs=())))
    ctx = _context()
    # an unanchored PLANNED challenge cannot pass the wall...
    with pytest.raises(rc.PlanRefused):
        rc.validate_plan(plan, ctx)
    # ...but the anchored face of the plan arbitrates identically
    validated = _conforming_plan(
        challenges=(rc.PlannedChallenge(kind="fabricated",
                                        refs=("R-K1",)),))
    rc.validate_plan(validated, ctx)
    case = redteam.DebateCase(case_id="c1", pool="known",
                              claim="claim c1", challenge="fabricated",
                              challenge_refs=("R-K1",),
                              planted_cheat=True)
    from_plan = redteam.arbitrate_debate(case)
    assert from_plan["verdict"] == "challenge_upheld"
    assert from_plan["reason"] == "unanswered-anchored-challenge"
    cycle = redteam.canary_cycle([case], [from_plan])
    assert cycle["recall_known"] == pytest.approx(1.0)


def test_refusals_deterministic_first_violation_wins():
    """Same violating plan, same named constraint — always; a plan
    violating two constraints names the FIRST in the declared order
    (action before planning, card order within each)."""
    ctx = _context()
    plan = _conforming_plan(reads=("fact_conclusions",),
                            cycles=99)
    for _ in range(2):
        _refuses(plan, ctx, "read_only_worker_outputs")
    plan = _conforming_plan(motives=None, cycles=99)
    # the declared order: the annotation precedes the budget inside
    # the planning face
    _refuses(plan, ctx, "motives_constraints_declared")
    _refuses(_conforming_plan(cycles=99), ctx, "budget_bounded")
    plan = _conforming_plan(canary_coverage=0.1, motives=None)
    _refuses(plan, ctx, "canary_floor")


# ------------------------------------- 5. the distillation linkage

def test_distill_executor_gets_the_same_face():
    """The ONE declarative check: redteam as the independent executor
    of a distill act not involving the worker — the receipt names the
    distill-executor scope, and the SAME constraint face applies with
    no relaxation path: every refusal is identical to the standard
    scope."""
    dctx = _context(act="distill", involves_worker=False)
    sctx = _context()
    receipt = rc.validate_plan(_conforming_plan(), dctx)
    assert receipt["accepted"] is True
    assert receipt["constraint_scope"] == "distill-executor"
    assert rc.is_distill_executor(dctx) is True
    assert rc.is_distill_executor(sctx) is False
    for plan, constraint in (
            (_conforming_plan(reads=("fact_conclusions",)),
             "read_only_worker_outputs"),
            (_conforming_plan(mutations=("settlement",)),
             "mutates_settlement"),
            (_conforming_plan(canary_coverage=0.1), "canary_floor")):
        _refuses(plan, dctx, constraint)
        _refuses(plan, sctx, constraint)
