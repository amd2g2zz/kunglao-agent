# -*- coding: utf-8 -*-
"""intelligent_scheduling.py — the wake decision as a recorded action.

The heartbeat used to BE the schedule: a fixed cron interval, hand-written
constants, no alternative ever chosen, no propensity ever logged — a
decision surface that could not be evaluated off-policy. This module makes
the wake decision an ACTION like any dispatch:

  vocabulary   the scheduling five live in the action registry
               (scripts/action_space.py, orchestration level, flagged
               ``scheduling``): sleep / wake_on / probe / close_loop /
               none. ``none`` is the null action: do nothing, cost 0,
               value 0.

  width        k = min(free_slots, f(entropy)) — the slot room (the slot
               monitor's own ledger) caps the entropy-derived demand. Both
               inputs and the derived k ride every decision. No trigger
               rule exists: f() is a derived prior, and the prior is
               itself the seat learning fills (the observed cost /
               progress pair — the signal stream this module writes —
               updates it). The math lives in scheduling_selection.

  selection    Gumbel top-k WITHOUT replacement over the candidate logits
               (scheduling_selection.gumbel_topk): the ordered draw is
               exactly a Plackett-Luce sample, so the logged propensity is
               that decision's exact sampling probability — the
               dispatch-receipt discipline applied to the wake face.

  recording    runs/.scheduling-decision.json carries the full decision;
               runs/signals.jsonl gains one kind=scheduling row per
               decision carrying {action, propensity, source, k, selected,
               null_propensity, budgets, entropy_bits, free_slots}.
               ``source`` follows the dispatch-action trichotomy: sampled
               (the sampler chose it) / declared (deterministic, the
               behavior policy itself) / none (the intervention IS
               inaction).

  baseline     EVERY decision also logs the null action's own propensity
               at the same decision point (the record's ``null`` block,
               the row's ``null_propensity`` field): the do-nothing
               baseline any timer action is measured against. A timer
               action's value claim is only meaningful next to it.

  watchdog     the fixed cron path is DEMOTED, never deleted: every record
               carries the cron as an ARMED watchdog — event-first (the
               wake_on predicates the topology already delivers), polling
               as the fallback at the armed interval. Absent any advice
               source the historical default interval stands:
               default-safe by construction.

  budgets      the three-budget price triple {tokens, tool_calls,
               verify_calls} is read from single sources (the tuition
               curve's spend state, the step ledger's tool-call rows, the
               verification stamps on the signal stream) and rides every
               decision, so "how often" has a price.

CLI: intelligent_scheduling.py <workspace> [--json] [--declared ACTION]
Exit codes: 0 ok / 2 usage (unknown declared action) / 3 not a workspace.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import action_space
import signals_stream
from harness_common import utc_now_z  # the canonical Z stamp
from kunglao_log import warn  # canonical warn: ONE implementation
from scheduling_selection import (adapt_k, f_entropy, gumbel_topk,
                                  pl_propensity, pl_terms)

SCHEMA = "scheduling-decision/1"
KIND_SCHEDULING = "scheduling"

SOURCE_SAMPLED = "sampled"
SOURCE_DECLARED = "declared"
SOURCE_NONE = "none"
PROPENSITY_SOURCES = (SOURCE_SAMPLED, SOURCE_DECLARED, SOURCE_NONE)

NULL_ACTION = "none"
DECISION_REL = Path("runs") / ".scheduling-decision.json"

CRON_ROLE = "watchdog"
#: The event-first wake predicates the loop topology already delivers.
WAKE_EVENTS = ("worker_completion", "dispatch_return", "oracle_result",
               "user_signal")

_UNSET = object()

# Registry-derived (the flagged subset, registry order) — never a parallel
# hand-kept list; a vocabulary change lands in the registry and arrives here.
SCHEDULING_ACTIONS: tuple[str, ...] = tuple(
    s.name.split(".", 1)[1]
    for s in action_space.actions_of(action_space.ORCHESTRATION)
    if s.scheduling)

#: Day-one priors: FLAT. The logits are the policy's own quantity; the
#: interval constants the loop used to hard-set become these priors, and
#: the observed (cost, progress) pair is what updates them. A caller may
#: inject its own logits (the learned prior's seat).
DEFAULT_LOGITS: dict[str, float] = {name: 0.0 for name in SCHEDULING_ACTIONS}


def _ts(now: datetime | None = None) -> str:
    """Canonical Z stamp; `now` overrides the clock for replayable tests."""
    if now is None:
        return utc_now_z()
    return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def budget_face(ws) -> dict:
    """The wake decision's price triple:

      tokens       cumulative spend (the tuition curve's cost state — the
                   single source the mission ledger already reads);
      tool_calls   per-tool-call rows on the step ledger (one row IS one
                   call; completion aggregates are excluded);
      verify_calls verification stamps on the signal stream (the penalty
                   input's verify count, full window).

    Every slot is read behind its own guard and an absent source reads zero
    (the sources' own missing-equals-nothing semantics) — a budget face
    never raises and never blocks a decision."""
    tokens = 0.0
    tool_calls = 0
    verify_calls = 0
    ws = Path(ws)
    try:
        from tuition_curve import cost_state
        tokens = float(cost_state(ws)["spent"])
    except Exception as exc:  # noqa: BLE001 — a budget never breaks the decision
        warn("intelligent_scheduling.tokens", f"{type(exc).__name__}: {exc}")
    try:
        from rlvr import step_ledger
        tool_calls = sum(
            1 for row in step_ledger.read_steps(ws)
            if row.get("schema") == step_ledger.STEP_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        warn("intelligent_scheduling.tool_calls", f"{type(exc).__name__}: {exc}")
    try:
        verify_calls = int(signals_stream.penalty_counts(ws)["verify"])
    except Exception as exc:  # noqa: BLE001
        warn("intelligent_scheduling.verify_calls", f"{type(exc).__name__}: {exc}")
    return {"tokens": round(tokens, 4),
            "tool_calls": tool_calls,
            "verify_calls": verify_calls}


def read_state(ws, *, now: datetime | None = None) -> dict:
    """The scheduling inputs, each from its single source, each behind its
    own guard (honest nulls, never an exception):

      entropy_bits  frontier PQ entropy (entropy_face);
      free_slots    slot room from the slot monitor's ledger (cap - active);
      active / cap  the same ledger's raw counts;
      interval_min  the armed cadence interval (cadence advisor; None when
                    no source exists — the watchdog default stands)."""
    ws = Path(ws)
    out: dict = {"entropy_bits": None, "free_slots": None, "active": None,
                 "cap": None, "interval_min": None}
    try:
        import entropy_face
        out["entropy_bits"] = entropy_face.face(ws).get("h_bits")
    except Exception as exc:  # noqa: BLE001 — a face never breaks its caller
        warn("intelligent_scheduling.entropy", f"{type(exc).__name__}: {exc}")
    try:
        import slot_monitor
        scan = slot_monitor.scan(ws, now=now)
        out["free_slots"] = scan.get("free")
        out["active"] = scan.get("active")
        out["cap"] = scan.get("cap")
    except Exception as exc:  # noqa: BLE001
        warn("intelligent_scheduling.slots", f"{type(exc).__name__}: {exc}")
    try:
        import cadence_advisor
        out["interval_min"] = cadence_advisor.current_interval_min(ws)
    except Exception as exc:  # noqa: BLE001
        warn("intelligent_scheduling.cadence", f"{type(exc).__name__}: {exc}")
    return out


def _fallback_interval_min(state: dict) -> int:
    """The watchdog's polling fallback: the armed interval when a source
    exists, else the historical policy default — default-safe means the
    demotion can never silently change the polling cadence."""
    value = state.get("interval_min")
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    try:
        from liveness_policy import TICK_INTERVAL_DEFAULT_MIN
        return int(TICK_INTERVAL_DEFAULT_MIN)
    except Exception:  # noqa: BLE001 — the historical default is the floor
        return 5


def _validate_logits(logits: dict | None) -> dict[str, float]:
    """Candidate logits: the flat priors when none are injected; an injected
    map is restricted to the registered scheduling five (unknown names can
    never enter the sampler) and every value must be a finite number —
    a non-finite weight has no defined sampling probability, so it is
    refused loudly at this boundary, never carried into the math."""
    base = dict(DEFAULT_LOGITS)
    if logits is None:
        return base
    if not isinstance(logits, dict):
        raise ValueError(
            f"logits must be a mapping, got {type(logits).__name__}")
    for name, value in logits.items():
        if name not in base:
            raise ValueError(f"unknown scheduling action in logits: {name!r}")
        try:
            val = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"logit for {name!r} is not a number: {value!r}") from exc
        if not math.isfinite(val):
            raise ValueError(f"logit for {name!r} is not finite: {value!r}")
        base[name] = val
    return base


def decide(ws, *, rng=None, declared_action: str | None = None,
           logits: dict | None = None, entropy_bits=_UNSET,
           free_slots=_UNSET, now: datetime | None = None) -> dict:
    """One wake decision, recorded and logged.

    Selection: Gumbel top-k without replacement over the candidate logits,
    width k = min(free_slots, f(entropy)). A DECLARED action skips the
    sampler (deterministic, propensity 1.0); the forced-null case (k = 0,
    no slot room) is the null action at propensity 1.0 — the only legal
    move under the constraint. Every decision logs the null action's own
    propensity beside the choice (the do-nothing baseline).

    The persisted record (runs/.scheduling-decision.json) and the signal
    row (kind=scheduling) carry the same decision; both writes fail open —
    a recording failure never blocks the caller's wake path."""
    ws = Path(ws)
    rng = rng or random.Random()
    state = read_state(ws, now=now)
    h_bits = state["entropy_bits"] if entropy_bits is _UNSET else entropy_bits
    free = state["free_slots"] if free_slots is _UNSET else free_slots
    candidates = _validate_logits(logits)
    k = min(adapt_k(h_bits, free), len(candidates))
    budgets = budget_face(ws)
    null_p = pl_propensity([NULL_ACTION], candidates)

    terms: list[float]
    if declared_action is not None:
        if declared_action not in candidates:
            raise ValueError(
                f"declared action not in the scheduling vocabulary: "
                f"{declared_action!r}")
        ordered = [declared_action]
        terms = [1.0]
    elif k == 0:
        # no room to act: the null action is the only legal move
        ordered = [NULL_ACTION]
        terms = [1.0]
    else:
        ordered = gumbel_topk(candidates, k, rng)
        terms = pl_terms(ordered, candidates)

    def _entry_source(name: str) -> str:
        """Per-action provenance: the null action's intervention IS
        inaction (source none); any other name is declared (deterministic)
        or sampler-chosen."""
        if name == NULL_ACTION:
            return SOURCE_NONE
        if declared_action is not None:
            return SOURCE_DECLARED
        return SOURCE_SAMPLED

    primary = ordered[0]
    batch_p = 1.0
    for t in terms:
        batch_p *= t
    batch_p = round(batch_p, 12)
    record = {
        "schema": SCHEMA,
        "ts": _ts(now),
        "action": primary,
        "propensity": batch_p,
        "source": _entry_source(primary),
        "k": k,
        "k_inputs": {"entropy_bits": h_bits, "free_slots": free,
                     "demand": f_entropy(h_bits)},
        "selected": [{"action": name,
                      "propensity": round(terms[i], 12),
                      "source": _entry_source(name)}
                     for i, name in enumerate(ordered)],
        "candidates": dict(sorted(candidates.items())),
        "null": {"action": NULL_ACTION, "propensity": null_p,
                 "cost": 0.0, "value": 0.0},
        "budgets": budgets,
        "watchdog": {"role": CRON_ROLE, "armed": True,
                     "interval_min": _fallback_interval_min(state),
                     "mode": ("event_first" if "wake_on" in ordered
                              else "poll_fallback")},
        "wake_events": list(WAKE_EVENTS),
    }
    _persist(ws, record)
    _log(ws, record)
    return record


def _persist(ws: Path, record: dict) -> None:
    """Write the decision record (the read seam for briefs/views)."""
    try:
        p = Path(ws) / DECISION_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    except OSError as exc:
        warn("intelligent_scheduling_write", f"{type(exc).__name__}: {exc}")


def _log(ws, record: dict) -> None:
    """One kind=scheduling row: the off-policy evaluable face of the wake
    decision (the estimators read the signal stream, never this module)."""
    signals_stream.append(
        ws, KIND_SCHEDULING,
        action=record["action"],
        propensity=record["propensity"],
        source=record["source"],
        k=record["k"],
        selected=[s["action"] for s in record["selected"]],
        null_propensity=record["null"]["propensity"],
        budgets=record["budgets"],
        entropy_bits=record["k_inputs"]["entropy_bits"],
        free_slots=record["k_inputs"]["free_slots"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the wake decision as an action")
    ap.add_argument("workspace")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--declared", default=None,
                    help="declare the action (deterministic; source=declared)")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").is_file():
        print(f"intelligent_scheduling: not a kunglao workspace: {ws}",
              file=sys.stderr)
        return 3
    try:
        out = decide(ws, declared_action=args.declared)
    except ValueError as exc:
        print(f"intelligent_scheduling: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"scheduling: action={out['action']} src={out['source']} "
              f"p={out['propensity']} k={out['k']} "
              f"null={out['null']['propensity']} "
              f"watchdog={out['watchdog']['interval_min']}m "
              f"({out['watchdog']['mode']})")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    sys.exit(main())
