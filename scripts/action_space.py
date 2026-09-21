# -*- coding: utf-8 -*-
"""action_space.py — the action vocabulary + operator metadata (the
minimal slice: vocabulary + operator metadata first; composition can
follow).

The value algorithm carried exactly ONE action label (``evidence_collection``,
the classify_action catch-all) and zero per-action metadata: a ruler with
one mark. The co-spine ruling named the decision vocabulary the capability
bottleneck — "a clean reward with no improvable policy face is a ruler
measuring nothing". This module is the vocabulary:

  - operator level (the worker's hands): observe / trace / hook / emulate /
    derive / verify / search / ask / plan_segment;
  - orchestration level (the loop's teeth): dispatch / verify / deepen /
    replan / osint / expand;
  - strategic level (the route choice): FIGHT (push through: dispatch
    against the obstacle) / BYPASS (defer: DEFERRED + wake_condition, the
    negative-exit machinery — referenced, never rebuilt) / INVEST (build
    capability first: rule-14 tool creation, then return).

Scope ruling (2026-09-20): "vocabulary + operator metadata first;
composition can follow". Every entry carries cost / precondition /
proof-power / consumer and a Delta-value estimator SIGNATURE — a
documented stub interface, deliberately NOT implemented (the estimators
are the v0.2 controller's job; execution semantics land in the v0.1.7
card). The vocabulary provides the switches; the model holds the choice.

Reward semantics (2026-09-04 ruling): outcome signals are primary and
every estimator reads the SIGNAL STREAM (runs/signals.jsonl — see
signals_stream.py), never the orchestrator's memory. The persisted
per-round factor vector (mission_ledger) is the decision surface; the
stream feeds the reward that updates it.

The claim-category table (the labels the CURRENT ranker emits) moves here
VERBATIM from priority_ratio (same tuples, same order, same scoring loop)
so the ``action`` field is registry-sourced while the rank output stays
byte-identical under default weights (the zero-behavior-change baseline is
pinned by tests/test_action_space_12.py's frozen capture).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# NOTE: no module-level priority_ratio import — priority_ratio imports THIS
# module (the claim-category table is registry-owned), so the two constants
# the weights loader needs are resolved lazily inside load_action_weights
# (the repo's standard cycle-break; no import-order trap at module load).


# ---- levels -----------------------------------------------------------------

OPERATOR = "operator"
ORCHESTRATION = "orchestration"
STRATEGIC = "strategic"


# ---- Δ-value estimator stub interface ----------------------------------------

@dataclass(frozen=True)
class DeltaEstimator:
    """Δ-value estimator SIGNATURE (stub — the v0.1.6 slice ships the
    interface, never an implementation).

    Contract (the one signature every estimator implements in v0.2):

        SIGNATURE = "estimate_delta_v(action: ActionSpec,
                                      signals: list[dict],
                                      history: list[dict],
                                      round_no: int) -> float"

    ``signals``  — rows read from runs/signals.jsonl (the append-only
                   outcome-signal stream; scripts/signals_stream.py);
    ``history``  — the persisted per-round factor vectors (mission_ledger
                   mission.history rows carrying the factor-vector shape) — ruling 4:
                   the orchestrator consumes the history, not the raw signal;
    ``round_no`` — the convergence tick the estimate is for.

    ``inputs`` names the stream faces the estimator reads; every estimator
    declares the signal stream (ruling 5) — never orchestrator memory.
    ``implemented`` is False for the whole slice BY DESIGN (the scope
    annotation pins it: composition can follow).
    """

    SIGNATURE = ("estimate_delta_v(action: ActionSpec, signals: list[dict], "
                 "history: list[dict], round_no: int) -> float")

    name: str
    signature: str = SIGNATURE
    inputs: tuple[str, ...] = ("runs/signals.jsonl",)
    implemented: bool = False


def _est(name: str, inputs: tuple[str, ...] = ("runs/signals.jsonl",)) -> DeltaEstimator:
    return DeltaEstimator(name=name, inputs=inputs)


# ---- the spec ----------------------------------------------------------------

@dataclass(frozen=True)
class ActionSpec:
    """One registered action: metadata only in this slice.

    cost          — constant action cost (relative units; the orchestration
                    dispatch inherits the tier cost at rank time — the value
                    here is the registry's planning constant).
    precondition  — what must hold before the action is available.
    proof_power   — what the action can and cannot prove (the proof-power shape:
                    observation vs reproduction vs verification).
    consumer      — who dispatches/holds the action.
    references    — existing machinery the action REUSES (no new semantics).
    """

    name: str
    level: str
    cost: float
    precondition: str
    proof_power: str
    consumer: str
    delta_estimator: DeltaEstimator
    references: tuple[str, ...] = field(default_factory=tuple)


def _spec(name: str, level: str, cost: float, precondition: str,
          proof_power: str, consumer: str,
          references: tuple[str, ...] = ()) -> ActionSpec:
    return ActionSpec(name=f"{level}.{name}", level=level, cost=float(cost),
                      precondition=precondition, proof_power=proof_power,
                      consumer=consumer, delta_estimator=_est(f"delta_v/{level}.{name}"),
                      references=references)


# ---- the registry --------------------------------------------------------------
# Registry keys are level-namespaced ("operator.verify" vs
# "orchestration.verify" — both vocabularies carry a verify).

ACTIONS: dict[str, ActionSpec] = {}


def _register(*specs: ActionSpec) -> None:
    for s in specs:
        ACTIONS[s.name] = s


_register(
    # ---- operator level: the worker's hands (the co-spine vocabulary) ----
    _spec("observe", OPERATOR, 1,
          "artifact in reach (file / binary / log present on the declared channel)",
          "observation — non-terminal: an observation alone never settles a "
          "generation-side claim (settle_by_need evidence classes)",
          "worker (T1/T2)"),
    _spec("trace", OPERATOR, 2,
          "a data flow / call edge to follow from a known anchor",
          "observation chain — anchors the derivation, cannot alone prove intent",
          "worker (T1/T2)"),
    _spec("hook", OPERATOR, 8,
          "runtime reachable (VM channel up / frida server attached); "
          "instrumentation is first-class, never a static-failure fallback",
          "dynamic observation — counter-evidence capable (a hook can refute "
          "a static guess)",
          "worker (T2/T3, VM)"),
    _spec("emulate", OPERATOR, 10,
          "emulation profile exists (qiling / malware-framework) or a VM slot "
          "is free",
          "dynamic reproduction — strongest non-oracle dynamic face",
          "worker (T3, framework)"),
    _spec("derive", OPERATOR, 2,
          "raw artifact + a recompute path (the fact schema's reproduce/"
          "expected pair)",
          "recomputation — machine-checkable: expected/actual byte-exact",
          "worker (T1)"),
    _spec("verify", OPERATOR, 3,
          "a settled claim with stamped evidence awaiting an independent pass",
          "independent verification — maker-checker: the producer never "
          "verifies its own output",
          "verifier (kunglao-redteam / verdict-scorer)"),
    _spec("search", OPERATOR, 1,
          "an indexed corpus / references index present",
          "corroboration only — search hits are never PROVEN alone",
          "worker (T1)"),
    _spec("ask", OPERATOR, 1,
          "a decision-rights gap: a user-owned fork the loop may not decide",
          "authority — an operator ruling settles what evidence cannot",
          "orchestrator (escalation ladder)"),
    _spec("plan_segment", OPERATOR, 1,
          ">=2 open claims on the dispatch frontier sharing a route",
          "none (organizational) — sequencing, never evidence",
          "orchestrator"),
    # ---- orchestration level: the loop's teeth ----
    _spec("dispatch", ORCHESTRATION, 3,
          "claim OPEN + promotion_attempts<3 + every depends_on parent "
          "terminal (the priority_ratio candidate filter, unchanged)",
          "inherits the worker action's proof power",
          "orchestrator"),
    _spec("verify", ORCHESTRATION, 5,
          "a PROVEN-bound claim with gates armed (BLIND / contradiction / "
          "inference / provenance)",
          "independent verification at the loop level (outcome rows land as "
          "OUTCOME records)",
          "orchestrator"),
    _spec("deepen", ORCHESTRATION, 6,
          "an identified obstacle: mint the +3 obstacle claim with a walked "
          "target/attack-surface ladder",
          "capability settlement — a PROVEN obstacle means 'really can't'",
          "orchestrator"),
    _spec("replan", ORCHESTRATION, 4,
          "plan-drift detected (severe drift auto-integrates; warning "
          "saturates) or the frontier is stale",
          "none (organizational) — replanning never manufactures evidence",
          "orchestrator"),
    _spec("osint", ORCHESTRATION, 4,
          "an external-facing surface (web target / public artifact) and a "
          "sanctioned lane",
          "source-derived — external evidence records URL+date, never "
          "directly PROVEN",
          "web-re-worker"),
    _spec("expand", ORCHESTRATION, 3,
          "a claim whose scope splits (mint_split lineage: parent SUPERSEDED "
          "+ sub claims)",
          "inherits the sub-claims' proof power",
          "orchestrator"),
    # ---- strategic level: the route choice (the 2026-09-20 ruling) ----
    _spec("fight", STRATEGIC, 12,
          "obstacle identified + the capability-disproof ladder walkable "
          "(dispatch against the obstacle; a PROVEN obstacle is the honest "
          "'really can't')",
          "capability settlement — push-through either validates the route "
          "or settles the blocker",
          "orchestrator (route choice; execution lands in the v0.1.7 card)",
          references=("target_ladder settlement gate", "infeasible ladder L1/L2/L3")),
    _spec("bypass", STRATEGIC, 4,
          "defer: recovery ladder complete + attempt inventory non-empty + "
          "wake_condition non-empty (the infeasible_proposal.file_proposal "
          "fail-closed gate) -> claim DEFERRED with wake_condition; "
          "infeasible_proposal.wake revives",
          "none (deferral) — a deferred claim is terminal-by-deferral, "
          "revivable only through the wake face",
          "orchestrator (route choice; execution lands in the v0.1.7 card)",
          references=("scripts/infeasible_proposal.py file_proposal/wake "
                      "(DEFERRED + wake_condition machinery — reused, not "
                      "rebuilt)",)),
    _spec("invest", STRATEGIC, 10,
          "missing tool family (tools/_INDEX.yaml gap): build the capability "
          "first (rule-14 tool creation + registration), then return to the "
          "route",
          "capability construction — the registered tool outlives the round",
          "orchestrator (route choice; execution lands in the v0.1.7 card)",
          references=("rule 14 tool creation", "tools/_INDEX.yaml registration")),
)

assert len(ACTIONS) == 18, "the vocabulary is exactly 9 + 6 + 3"


def actions_of(level: str) -> list[ActionSpec]:
    """Registered specs of one level, registry order."""
    return [s for s in ACTIONS.values() if s.level == level]


def get(name: str) -> ActionSpec:
    """Namespaced lookup ("operator.trace"); KeyError on unknown."""
    return ACTIONS[name]


# ---- claim-category table (moved VERBATIM from priority_ratio) ----------------
# The labels the CURRENT ranker emits and the worth-era worker hints consume.
# Verbatim move: same tuples, same order, same scoring loop — the rank output
# stays byte-identical (pinned by the frozen capture test).

DEFAULT_CLAIM_ACTION = "evidence_collection"

CLAIM_ACTION_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("c2", "mpd", "pegasus", "dead-drop", "dead drop", "c2 配置"), "c2_config_extract"),
    (("命令表", "command table", "命令分发"), "command_table"),
    (("协议", "protocol", "runtime 行为", "network io", "网络"), "protocol_restore"),
    (("持久化", "persistence", "autorun", "注册表"), "persistence"),
    (("注入", "injection", "reflective", "createremotethread"), "injection"),
    (("反分析", "anti-analysis", "anti analysis", "garble", "诱饵",
      "decoy", "cff", "混淆"), "anti_analysis"),
    (("家族", "family", "归属", "vidar", "wingo", "gsb"), "family_attribution"),
]

# The producible claim-category labels (registry view of the table).
CLAIM_CATEGORIES: frozenset[str] = frozenset(
    [DEFAULT_CLAIM_ACTION] + [cat for _, cat in CLAIM_ACTION_KEYWORDS])

# Composition metadata (DATA only in this slice): which operator actions a
# claim category plausibly composes. No consumer in v0.1.6 — the scope
# annotation keeps composition out.
CATEGORY_OPERATOR_ACTIONS: dict[str, tuple[str, ...]] = {
    "evidence_collection": ("operator.observe", "operator.derive", "operator.search"),
    "c2_config_extract": ("operator.trace", "operator.derive"),
    "command_table": ("operator.trace", "operator.derive"),
    "protocol_restore": ("operator.trace", "operator.emulate"),
    "persistence": ("operator.observe", "operator.derive"),
    "injection": ("operator.hook", "operator.emulate"),
    "anti_analysis": ("operator.emulate", "operator.hook"),
    "family_attribution": ("operator.search", "operator.derive"),
}


def classify_claim_action(claim: dict) -> str:
    """statement + answers_question keywords → action category; no hit →
    evidence_collection. Scoring: each category accumulates keyword hit
    counts, the highest wins; ties broken by CLAIM_ACTION_KEYWORDS order.
    (Verbatim from priority_ratio.classify_action — the single scoring
    authority; the priority_ratio name is a delegation alias.)"""
    text = " ".join([
        str(claim.get("statement", "")),
        str(claim.get("answers_question", "")),
    ]).lower()
    best, best_score = DEFAULT_CLAIM_ACTION, 0
    for keywords, action in CLAIM_ACTION_KEYWORDS:
        score = sum(text.count(k) for k in keywords)
        if score > best_score:
            best, best_score = action, score
    return best


# ---- value-weights.yaml per-action weights section ----

def load_action_weights(ws: Path) -> dict[str, float]:
    """Per-action weights from runs/value-weights.yaml ``actions:`` section.

    The section is DATA in this slice — no ranker consumer (default weights
    are identity and the rank output must stay byte-equivalent; composition
    is v0.2). Same fail-open discipline as the worth channel: missing
    file/section → {}; unparsable YAML → {}; illegal entries dropped
    individually (strictly-positive numerics only, via the priority_ratio
    _positive_weights single source)."""
    from priority_ratio import VALUE_WEIGHTS_FILE, _positive_weights  # noqa: E402 — lazy (cycle)
    path = Path(ws) / VALUE_WEIGHTS_FILE
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception:  # noqa: BLE001 — corrupt weights never break ranking
        return {}
    if not isinstance(data, dict):
        return {}
    section = data.get("actions")
    return _positive_weights(section if isinstance(section, dict) else None)


DEFAULT_ACTION_WEIGHTS: dict[str, float] = {name: 1.0 for name in ACTIONS}
"""Identity defaults: per-action weight 1.0 for every registered action —
the defaults reproduce current behavior exactly (composition is v0.2)."""


def spec_for_category(category: str) -> tuple[str, ...]:
    """Operator actions a claim category composes (composition metadata,
    unused in this slice). Unknown categories → the evidence_collection
    default row."""
    return CATEGORY_OPERATOR_ACTIONS.get(
        category, CATEGORY_OPERATOR_ACTIONS[DEFAULT_CLAIM_ACTION])
