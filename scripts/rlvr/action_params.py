# -*- coding: utf-8 -*-
"""action_params.py — the per-kind parameter spec of the rl-v2 action
space (issue 924).

The closed action vocabulary (experiments/learning-loop/core/actions.py
``ActionKind``) gains its parameter CONTRACT: one declarative spec per
kind — required params (fail-closed, named on refusal), optional
params (each with an explicit default + validator), and nothing else
(unknown params refuse — typo-proof, the CODES-registry pattern).

WHY a scripts-side module: the spec's enforcement must live at BOTH
walls — the ``action/1`` boundary (core.actions.parse_action) and the
ledger's action-row landing face (rlvr.q_cells.append_action). The
deployed scripts tree cannot import experiments/ (the deploy manifest
closure is scripts-only), while experiments→scripts is the learning
loop's existing dependency direction — so the single source lives
HERE, stdlib-only, and core.actions consumes it like every other
learning-loop face consumes rlvr.

Auditability ruling (issue 924): an optional param ABSENT at write time is
recorded AT ITS DEFAULT in the row — the row shows the effective
values, never a silent absence. ``normalize_params`` returns a NEW
dict (the input mapping is never mutated); the spec table and every
entry are frozen (MappingProxyType over frozen dataclasses).

The spawn dispatch width: ``slots`` is the orchestrator's EXPLICIT
per-dispatch choice (owner directive 2026-10-31 — the old
always-fill-slots policy is revoked); it has NO default and refuses
anything but an int in [SLOTS_MIN, SLOTS_MAX].
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

#: the explicit dispatch width's rails (issue 924: min 1, max 5)
SLOTS_MIN = 1
SLOTS_MAX = 5


class ActionParamError(ValueError):
    """A params mapping violates the kind's spec. Fail-closed; the
    message always names the offending param (or the kind)."""


#: validator signature: (value, field) -> normalized value, raising
#: ActionParamError naming the field. Pure — no I/O, no mutation.
Validator = Callable[[Any, str], Any]

#: an optional param's immutable (default, validator) pair.
ParamDefault = tuple[Any, Validator]


def _v_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise ActionParamError(
            f"action.params.{field_name}: must be a string")
    return value


def _v_nonempty_str(value: Any, field_name: str) -> str:
    _v_str(value, field_name)
    if not value.strip():
        raise ActionParamError(
            f"action.params.{field_name}: must be a non-empty string")
    return value


def _v_str_or_none(value: Any, field_name: str) -> str | None:
    return None if value is None else _v_str(value, field_name)


def _v_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ActionParamError(
            f"action.params.{field_name}: must be an integer")
    return value


def _v_int_ge1(value: Any, field_name: str) -> int:
    _v_int(value, field_name)
    if value < 1:
        raise ActionParamError(
            f"action.params.{field_name}: must be an integer >= 1")
    return value


def _v_bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ActionParamError(
            f"action.params.{field_name}: must be a bool")
    return value


def _v_mapping_or_none(value: Any, field_name: str) -> Mapping | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ActionParamError(
            f"action.params.{field_name}: must be a mapping")
    return value


def _v_seq_or_none(value: Any, field_name: str) -> list | tuple | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise ActionParamError(
            f"action.params.{field_name}: must be a sequence")
    return value


def _v_jsonable_or_none(value: Any, field_name: str) -> Any:
    """The loosest honest wall — the row payload boundary's own
    serializability posture (q_cells._v2_jsonable), admitted at the
    spec so a structured excerpt can ride without a narrower shape."""
    if value is None:
        return None
    try:
        json.dumps(value)
    except (TypeError, ValueError) as exc:
        raise ActionParamError(
            f"action.params.{field_name}: must be JSON-serializable "
            f"({type(exc).__name__})") from None
    return value


def _v_num_or_none(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        raise ActionParamError(
            f"action.params.{field_name}: must be a finite number")
    return float(value)


def _v_slots(value: Any, field_name: str) -> int:
    """The orchestrator's explicit dispatch width — no default, no
    coercion (a bool/str/float 'slots' is a decision that was never
    consciously made, exactly what the ruling refuses)."""
    _v_int(value, field_name)
    if not SLOTS_MIN <= value <= SLOTS_MAX:
        raise ActionParamError(
            f"action.params.{field_name}: must be an integer in "
            f"[{SLOTS_MIN}, {SLOTS_MAX}] (the orchestrator's explicit "
            f"dispatch width), got {value!r}")
    return value


@dataclass(frozen=True)
class ActionParamSpec:
    """One kind's parameter contract. ``required`` maps name ->
    validator; ``optional`` maps name -> (default, validator). A
    params mapping may carry EXACTLY these names — nothing more
    (unknown refuses), nothing less on the required side (missing
    refuses)."""

    required: Mapping[str, Validator]
    optional: Mapping[str, ParamDefault]


#: the issue-925 select contract. The distribution is the #925 ranking
#: persistence (experiments/learning-loop/loop_seams.py:128 — the full
#: per-candidate posterior map recorded at decision time); optional at
#: default None so the pre-925 rows stay read-tolerant.
_SELECT_SPEC = ActionParamSpec(
    required=MappingProxyType({}),
    optional=MappingProxyType({"distribution": (None,
                                                _v_jsonable_or_none)}))

EMPTY_SPEC = ActionParamSpec(required=MappingProxyType({}),
                             optional=MappingProxyType({}))

#: the issue-924 assign contract. method_family REQUIRED — the terminator's
#: family-rollout prior reads it back from v2 assign_step rows
#: (experiments/learning-loop/policy/terminator.py:315, keyed by
#: ``params.method_family``). tier/phase/intent are the loop's audit
#: enrichment on the same rows (loop.py:292-296 writes all three;
#: sim/loop_sim_v3.py:264 and tests/chain_test_harness.py:288 write tier
#: only) — optional at their defaults so the row always shows the
#: effective assignment.
_ASSIGN_SPEC = ActionParamSpec(
    required=MappingProxyType({"method_family": _v_nonempty_str}),
    optional=MappingProxyType({"tier": (1, _v_int_ge1),
                               "phase": ("", _v_str),
                               "intent": (None, _v_mapping_or_none),
                               "distribution": (None,
                                                _v_jsonable_or_none)}))

#: the issue-924 spawn contract. slots REQUIRED — the orchestrator's
#: explicit dispatch width (owner directive 2026-10-31; the row must
#: record the conscious choice, never a policy default).
#: spawn_id/goal/snapshot_excerpt/cards ride the spawn receipt's audit
#: (workers/spawner.py:163-167 record_spawn); phase rides the loop's
#: construction seam (experiments/learning-loop/loop.py:240-241).
_SPAWN_SPEC = ActionParamSpec(
    required=MappingProxyType({"slots": _v_slots}),
    optional=MappingProxyType({"spawn_id": (None, _v_str_or_none),
                               "goal": ("", _v_str),
                               "snapshot_excerpt": (None,
                                                    _v_jsonable_or_none),
                               "cards": (None, _v_seq_or_none),
                               "phase": ("", _v_str)}))

#: the terminal rows' audit: the β rule + the arbiter's ΔP (loop.py:503
#: writes both; sim/loop_sim_v3.py:407 and tests/chain_test_harness.py:457
#: write rule only; sim/loop_sim_v3.py:679-681 writes neither). No read face
#: consumes them yet (sim/counterfactual_analysis.py:240 and
#: state/telemetry.py:258 read the KIND) — optional at explicit
#: not-applicable defaults, so the row shows the terminal's inputs.
_TERMINAL_SPEC = ActionParamSpec(
    required=MappingProxyType({}),
    optional=MappingProxyType({"rule": (None, _v_str_or_none),
                               "delta_p": (None, _v_num_or_none)}))

#: the probe contract: the potential-based comparison rides params
#: EVERY time (policy/prober.py:212-213 — the only writer; the result
#: row's summary re-prints it, prober.py:223-230), so the comparison
#: data is REQUIRED — a probe row without it is hollow.
_PROBE_SPEC = ActionParamSpec(
    required=MappingProxyType({"portfolio": _v_nonempty_str,
                               "rank": _v_int_ge1,
                               "arms": _v_int_ge1,
                               "potential_based": _v_bool,
                               "leader": _v_nonempty_str}),
    optional=MappingProxyType({}))


def _build_specs() -> Mapping:
    """The frozen kind -> spec table, keyed by the closed vocabulary's
    canonical STRINGS (the ten ``ActionKind.value`` spellings — the
    enum in experiments/learning-loop/core/actions.py stays the
    membership authority). WHY strings, not the enum: a scripts face
    cannot import experiments (the dep-surface gate refuses the
    undeclared 'core' dist; the deploy closure imports rlvr WITHOUT
    the learning-loop tree on sys.path) — so the keys are the
    canonical literals and DRIFT IS A TEST FAILURE (the issue-924 pin
    asserts table keys == enum values, both directions fail-closed: a
    kind added to the enum without a spec refuses at the wall with
    'no param spec'; a spec key outside the enum refuses through
    ActionKind at the boundary).

    select_task rides its TARGET (the task id) — the posterior join
    and the belief face read target, never params (policy/selector.py:
    92, state/belief.py:86); record_selection passes params through
    unset (policy/selector.py:163-166). The vocabulary-only kinds
    (decompose / switch_method / terminate_step / materialize —
    core/actions.py:32,35,36,40) have no write face in the repo yet:
    their specs admit params-free rows only, so the day a writer
    appears it must DECLARE its contract here first."""
    table: dict[str, ActionParamSpec] = {
        "select_task": _SELECT_SPEC,
        "decompose": EMPTY_SPEC,
        "assign_step": _ASSIGN_SPEC,
        "probe": _PROBE_SPEC,
        "switch_method": EMPTY_SPEC,
        "terminate_step": EMPTY_SPEC,
        "terminate_rollout": _TERMINAL_SPEC,
        "rollback": _TERMINAL_SPEC,
        "spawn_candidate": _SPAWN_SPEC,
        "materialize": EMPTY_SPEC,
    }
    return MappingProxyType(table)


#: the kind -> spec table — the single source both walls consult.
ACTION_PARAM_SPECS: Mapping = _build_specs()


def normalize_params(kind: str, params: Mapping | None) -> dict:
    """The ONE param wall: validate ``params`` against ``kind``'s spec
    and return the EFFECTIVE params — required present (validated),
    optional absent filled at their explicit defaults, unknown
    refused. Pure: a new dict every call; the input is never mutated.

    Fail-closed with the offending name in every message: a missing
    required param, an unknown param, a validator refusal, or a kind
    outside the closed action space (no spec) all raise
    ActionParamError."""
    kind = getattr(kind, "value", kind)
    if not isinstance(kind, str) or not kind.strip():
        raise ActionParamError("action.params.kind: must be a non-empty "
                               "string")
    spec = ACTION_PARAM_SPECS.get(kind)
    if spec is None:
        raise ActionParamError(
            f"action.params.kind: {kind!r} outside the closed action "
            f"space (no param spec)")
    if params is None:
        params = {}
    if not isinstance(params, Mapping):
        raise ActionParamError(
            f"action.params.{kind}.params: must be a mapping")
    known = frozenset(spec.required) | frozenset(spec.optional)
    unknown = sorted(str(n) for n in set(params) - known)
    if unknown:
        raise ActionParamError(
            f"action.params.{kind}: unknown param(s) "
            f"{unknown} — not in the {kind!r} param spec")
    missing = sorted(n for n in spec.required if n not in params)
    if missing:
        raise ActionParamError(
            f"action.params.{kind}: missing required "
            f"param(s) {missing}")
    out: dict[str, Any] = {}
    for name, validator in spec.required.items():
        out[name] = validator(params[name], name)
    for name, (default, validator) in spec.optional.items():
        out[name] = (validator(params[name], name) if name in params
                     else default)
    return out
