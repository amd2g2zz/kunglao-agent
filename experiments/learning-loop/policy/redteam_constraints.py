# -*- coding: utf-8 -*-
"""policy/redteam_constraints.py — the redteam autonomous-planning
constraint face (card 939).

The owner directive: redteam's autonomous planning needs explicit
action constraints (what redteam may do) and planning constraints (how
it plans). This face is DECLARATIVE — the constraint table is one
frozen record, the plan is a STRUCTURE with declared fields, and
``validate_plan`` is the wall: a violating plan is REFUSED fail-closed
NAMING the violated constraint (the #924 param-wall pattern); a
conforming plan passes with a receipt, so the #933 machinery (the
debate/canary/arm faces in policy/redteam.py) consumes constrained
plans with ZERO behavior change — the wall sits at the planning
boundary and the ruling machinery never learns it exists.

Action constraints (what redteam may do):
    read_only_worker_outputs    the blind-check discipline declared on
        the planning surface: a plan that reads the target's fact
        conclusions or the worker's narratives is refused — raw
        evidence stays readable.
    mutates_settlement=False    redteam rules, the deterministic stack
        prices: a plan step touching the settlement faces is refused.
    challenge_requires_anchors  the citation wall extended to
        PLANNING: a planned challenge without anchorable refs is
        refused.
    strategy_weights_self_granted=False    a weight for a strategy
        outside the posterior's guidance is refused unless it enters
        AT THE PRIOR (FIRST_ENTRY_WEIGHT — the #933 uniform prior's
        first-entry mean); novel arms never self-grant mass.

Planning constraints (how redteam plans):
    canary_floor                a detection schedule that reduces
        canary-pool coverage below its current level is refused — the
        GAP collapse signal is the mechanical rejection criterion.
    posterior_guided            plans run within the strategy
        posterior's guidance; a deviation REQUIRES a declared reason —
        recorded in the receipt, never refused and never silent (the
        orchestrator dispatch-deviation discipline).
    motives_constraints_declared    the R3 identification discipline
        applied to redteam's own planning: a plan missing its motives
        or constraints annotation is refused.
    budget_bounded              plan cycles consume the budget scale.

Distillation linkage (the ONE declarative check):
    when redteam is the independent executor of a DISTILL act that
    does not involve the worker (``is_distill_executor``), the SAME
    constraint face applies — no relaxation path exists.

Mock discipline: the planner itself lives in the agent — this module
consumes and validates plan STRUCTURES only. No LLM machinery, no
I/O, no wall clock; pure functions, immutable records.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Any, Sequence

#: the first-entry weight a NOVEL strategy may enter at: the #933
#: uniform prior's mean (alpha=1, beta=1) — the only mass a new arm
#: can grant itself, any other weight is self-granted.
FIRST_ENTRY_WEIGHT = 0.5

#: the closed act vocabulary (detection vs the distill-executor role).
ACTS: tuple[str, ...] = ("detect", "distill")

#: the forbidden read vocabulary (the blind-check discipline): the
#: target's fact conclusions and the worker's narratives are NEVER
#: plan-readable; raw evidence and step artifacts are. Matching is
#: case-folded and normalized (the #709 lesson: deny must not be
#: defeated by case).
FORBIDDEN_READS: frozenset[str] = frozenset(
    {"fact_conclusions", "worker_narratives", "verdict_conclusions"})

#: the settlement deny is a SUBSTRING deny on the normalized surface
#: name — "settlement", "settlement_faces", "settlement_ledger" all
#: refuse (broad on deny, exact on allow).
SETTLEMENT_TOKEN = "settlement"


class PlanRefused(ValueError):
    """A plan violates a declared constraint. Fail-closed; the
    ``constraint`` attribute always names the violated constraint."""

    def __init__(self, constraint: str, why: str) -> None:
        super().__init__(
            f"policy.redteam_constraints.{constraint}: {why}")
        self.constraint = constraint


def _err(field_name: str, why: str) -> ValueError:
    return ValueError(f"policy.redteam_constraints.{field_name}: {why}")


def _non_empty_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _err(field_name, "must be a non-empty string")
    return value


def _str_seq(value: Any, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise _err(field_name, "must be a sequence of strings")
    return tuple(_non_empty_str(v, field_name) for v in value)


def _norm_surface(name: str) -> str:
    return name.strip().casefold().replace("-", "_")


def _finite_unit(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(float(value)) \
            or not 0.0 <= float(value) <= 1.0:
        raise _err(field_name, "must be a finite number in [0, 1]")
    return float(value)


def _count(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _err(field_name, "must be a non-negative int")
    return int(value)


@dataclass(frozen=True)
class PlannedChallenge:
    """One PLANNED challenge: a kind and the anchors it will cite.
    The refs must be non-empty strings when present at all — the
    citation wall extended to planning."""

    kind: str
    refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind",
                           _non_empty_str(self.kind, "challenge.kind"))
        object.__setattr__(self, "refs",
                           _str_seq(self.refs, "challenge.refs"))


@dataclass(frozen=True)
class StrategyWeight:
    """A weight a plan grants a detection strategy. The GRANT is
    checked against the constraint face at validation — never here
    (the structure records, the face rules)."""

    strategy: str
    weight: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "strategy",
                           _non_empty_str(self.strategy,
                                          "strategy_weight.strategy"))
        object.__setattr__(self, "weight",
                           _finite_unit(self.weight,
                                        "strategy_weight.weight"))


@dataclass(frozen=True)
class RedteamPlanConstraints:
    """THE declarative face: the eight card constraints at their
    declared values. One frozen record — validation reads only this;
    the wall is not caller-tunable."""

    read_only_worker_outputs: bool = True
    mutates_settlement: bool = False
    challenge_requires_anchors: bool = True
    strategy_weights_self_granted: bool = False
    canary_floor: bool = True
    posterior_guided: bool = True
    motives_constraints_declared: bool = True
    budget_bounded: bool = True

    def __post_init__(self) -> None:
        for f in fields(self):
            if not isinstance(getattr(self, f.name), bool):
                raise _err(f.name, "constraint flags must be bools")


#: the face itself (a single frozen instance — the declaration IS the
#: data; every validation reads exactly this).
REDTEAM_PLAN_CONSTRAINTS = RedteamPlanConstraints()

_CONSTRAINT_NAMES: tuple[str, ...] = tuple(
    f.name for f in fields(REDTEAM_PLAN_CONSTRAINTS))


@dataclass(frozen=True)
class RedteamPlan:
    """A redteam PLAN as a structure with declared fields — the
    planner lives in the agent; this is only its record. Validation
    (structural) happens here; constraint ruling happens in
    validate_plan."""

    plan_id: str
    cycles: int
    strategy: str
    reads: tuple[str, ...] = ()
    mutations: tuple[str, ...] = ()
    challenges: tuple[PlannedChallenge, ...] = ()
    strategy_weights: tuple[StrategyWeight, ...] = ()
    canary_coverage: float | None = None
    deviation_reason: str | None = None
    motives: str | None = None
    constraints_note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "plan_id",
                           _non_empty_str(self.plan_id, "plan_id"))
        object.__setattr__(self, "cycles",
                           _count(self.cycles, "cycles"))
        object.__setattr__(self, "strategy",
                           _non_empty_str(self.strategy, "strategy"))
        object.__setattr__(self, "reads",
                           _str_seq(self.reads, "reads"))
        object.__setattr__(self, "mutations",
                           _str_seq(self.mutations, "mutations"))
        item_types = {"challenges": PlannedChallenge,
                      "strategy_weights": StrategyWeight}
        for name, item_type in item_types.items():
            seq = getattr(self, name)
            if isinstance(seq, (str, bytes)) \
                    or not isinstance(seq, Sequence):
                raise _err(name, "must be a sequence")
            for item in seq:
                if not isinstance(item, item_type):
                    raise _err(name,
                               f"each item must be a "
                               f"{item_type.__name__}")
        if self.canary_coverage is not None:
            object.__setattr__(self, "canary_coverage",
                               _finite_unit(self.canary_coverage,
                                            "canary_coverage"))
        for name in ("deviation_reason", "motives", "constraints_note"):
            v = getattr(self, name)
            if v is not None and not isinstance(v, str):
                raise _err(name, "must be None or a string")
            if name == "deviation_reason" and isinstance(v, str) \
                    and not v.strip():
                raise _err(name,
                           "a declared reason must be non-empty")


@dataclass(frozen=True)
class RedteamPlanContext:
    """The planning context the plan is validated AGAINST: the
    posterior's guidance set, the held canary coverage, the remaining
    budget, and the act scope (the distillation linkage rides
    act/involves_worker)."""

    posterior_strategies: tuple[str, ...] = ()
    current_canary_coverage: float = 0.0
    budget_remaining: int = 0
    act: str = "detect"
    involves_worker: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "posterior_strategies",
                           _str_seq(self.posterior_strategies,
                                    "posterior_strategies"))
        object.__setattr__(self, "current_canary_coverage",
                           _finite_unit(self.current_canary_coverage,
                                        "current_canary_coverage"))
        object.__setattr__(self, "budget_remaining",
                           _count(self.budget_remaining,
                                  "budget_remaining"))
        if self.act not in ACTS:
            raise _err("act", f"must be one of {ACTS}, "
                              f"got {self.act!r}")
        if not isinstance(self.involves_worker, bool):
            raise _err("involves_worker", "must be a bool")


def is_distill_executor(context: Any) -> bool:
    """The ONE declarative check of the distillation linkage: redteam
    acting as the independent executor of a distill act that does not
    involve the worker (the anti double-collapse design)."""
    if not isinstance(context, RedteamPlanContext):
        raise _err("context", "must be a RedteamPlanContext")
    return context.act == "distill" and context.involves_worker is False


def _refuse(constraint: str, plan: RedteamPlan, why: str) -> None:
    raise PlanRefused(constraint,
                      f"plan {plan.plan_id!r} {why}")


def _check_action_constraints(plan: RedteamPlan,
                              ctx: RedteamPlanContext) -> None:
    """The action face in declaration order: reads, mutations,
    challenge anchors, strategy-weight grants."""
    for surface in plan.reads:
        if _norm_surface(surface) in FORBIDDEN_READS:
            _refuse("read_only_worker_outputs", plan,
                    f"reads forbidden surface {surface!r} — the "
                    f"target's conclusions/narratives are never "
                    f"plan-readable (raw evidence only)")
    for surface in plan.mutations:
        if SETTLEMENT_TOKEN in _norm_surface(surface):
            _refuse("mutates_settlement", plan,
                    f"mutates settlement surface {surface!r} — "
                    f"redteam rules, the deterministic stack prices")
    for ch in plan.challenges:
        if not ch.refs:
            _refuse("challenge_requires_anchors", plan,
                    f"planned challenge {ch.kind!r} carries no "
                    f"anchorable refs (the citation wall)")
    for sw in plan.strategy_weights:
        if sw.strategy in ctx.posterior_strategies:
            continue
        if sw.weight == FIRST_ENTRY_WEIGHT:
            continue
        _refuse("strategy_weights_self_granted", plan,
                f"grants weight {sw.weight} to non-posterior strategy "
                f"{sw.strategy!r} — novel arms enter only at the "
                f"prior ({FIRST_ENTRY_WEIGHT})")


def _check_planning_constraints(
        plan: RedteamPlan, ctx: RedteamPlanContext) -> list[dict]:
    """The planning face in declaration order: canary floor,
    posterior guidance (deviations recorded), annotation, budget.
    Returns the recorded deviations (a fresh list every call)."""
    if plan.canary_coverage is None:
        _refuse("canary_floor", plan,
                "declares no canary-pool coverage (fail-closed: the "
                "detection schedule must declare its coverage)")
    if plan.canary_coverage < ctx.current_canary_coverage:
        _refuse("canary_floor", plan,
                f"reduces canary-pool coverage "
                f"{ctx.current_canary_coverage} -> "
                f"{plan.canary_coverage} (the GAP collapse signal is "
                f"the mechanical rejection criterion)")
    deviations: list[dict] = []
    if plan.strategy not in ctx.posterior_strategies:
        reason = plan.deviation_reason
        if reason is None or not reason.strip():
            _refuse("posterior_guided", plan,
                    f"deviates from the posterior's guidance to "
                    f"{plan.strategy!r} without a declared reason")
        deviations.append({"kind": "posterior_guided",
                           "strategy": plan.strategy,
                           "reason": reason})
    if plan.motives is None or not plan.motives.strip() \
            or plan.constraints_note is None \
            or not plan.constraints_note.strip():
        _refuse("motives_constraints_declared", plan,
                "missing its motives/constraints annotation (the R3 "
                "identification discipline)")
    if plan.cycles > ctx.budget_remaining:
        _refuse("budget_bounded", plan,
                f"cycles {plan.cycles} exceed the remaining budget "
                f"{ctx.budget_remaining}")
    return deviations


def validate_plan(plan: Any, context: Any) -> dict:
    """THE wall: validate a plan against THE declarative face
    (REDTEAM_PLAN_CONSTRAINTS — not caller-tunable). A conforming
    plan passes with a receipt (the same face, the same receipt,
    deterministic); a violating plan raises PlanRefused naming the
    FIRST violated constraint in the declared order (action face,
    then planning face). The distillation linkage is the same face:
    a distill-executor context changes the receipt's scope label and
    nothing else."""
    if not isinstance(plan, RedteamPlan):
        raise _err("plan", "must be a RedteamPlan")
    if not isinstance(context, RedteamPlanContext):
        raise _err("context", "must be a RedteamPlanContext")
    _check_action_constraints(plan, context)
    deviations = _check_planning_constraints(plan, context)
    return {"plan_id": plan.plan_id,
            "accepted": True,
            "constraint_scope":
                "distill-executor" if is_distill_executor(context)
                else "standard",
            "deviations": deviations,
            "budget": {"cycles": plan.cycles,
                       "remaining_after":
                           context.budget_remaining - plan.cycles},
            "constraints": _CONSTRAINT_NAMES}
