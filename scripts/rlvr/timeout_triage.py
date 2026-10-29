# -*- coding: utf-8 -*-
"""rlvr/timeout_triage.py — the timeout's three-verdict triage
(P2 of the learning-loop live-wire program).

A TIMEOUT is not one failure. Three verdicts with three DIFFERENT
memory landings (the card's separation demand — one wrong landing
poisons exactly one memory):

  granularity_fault  the window produced nothing (the P6 granularity
                     face's own zero-output rule: no artifacts in the
                     window) — the claim was SIZED wrong. Lands a
                     sizing record; NEVER method memory.
  envelope_too_tight progress was happening (checkpoints closed) when
                     the envelope killed the window — the claim costs
                     more than its envelope priced. Lands a pricing
                     update only.
  method_fail        core-work attempts happened (artifacts exist) but
                     closed zero checkpoints — the method produced
                     nothing. The ONLY verdict feeding method memory a
                     negative.

Decision ladder (mechanical, first match):
  closed checkpoints >= 1          -> envelope_too_tight
  closed == 0 and artifacts        -> method_fail
  closed == 0 and no artifacts     -> granularity_fault

The envelope_event shape is the P6 guard's own terminal row
(``action: "envelope_timeout"``, hooks/worker_budget_gates.py); any
event carrying a timeout marker in action/kind/type/event (or a truthy
``timeout`` key) classifies. A non-timeout event is a caller error and
refuses loudly (ValueError) — this face classifies timeouts, nothing
else.

Zero telemetry points (Standard 11): the CALLER lands the memories
(this face returns the verdict + its landing); nothing emits. No
fitted parameters.
"""
from __future__ import annotations

#: verdict vocabulary
GRANULARITY_FAULT = "granularity_fault"
ENVELOPE_TOO_TIGHT = "envelope_too_tight"
METHOD_FAIL = "method_fail"

#: verdict -> the ONLY memory face the verdict may land (the card's
#: memory-landing rule, encoded as data so the separation is total)
MEMORY_LANDINGS = {
    GRANULARITY_FAULT: "sizing_record",
    ENVELOPE_TOO_TIGHT: "pricing_update",
    METHOD_FAIL: "method_memory",
}

#: checkpoint statuses that count as closed (case-folded); a plain
#: string claim (no status field) is an OPEN claim, as is a backward_plan
#: row with a truthy ``gap``
_CLOSED_STATUSES = frozenset({
    "closed", "done", "proven", "verified", "pass", "passed",
    "complete", "completed",
})

_TIMEOUT_WORDS = frozenset({"timeout", "envelope_timeout", "timed_out"})


def _is_timeout(event: dict) -> bool:
    for key in ("action", "kind", "type", "event"):
        if str(event.get(key) or "").strip().casefold() in _TIMEOUT_WORDS:
            return True
    return event.get("timeout") is True


def _closed_count(checkpoint_claims) -> int:
    """How many declared checkpoints reached a closed state. Plain
    strings are OPEN claims; a dict counts closed only on a closed
    status (a truthy ``gap`` is the backward_plan open marker)."""
    closed = 0
    for claim in (checkpoint_claims or []):
        if not isinstance(claim, dict):
            continue
        if claim.get("gap"):
            continue
        status = str(claim.get("status") or "").strip().casefold()
        if status in _CLOSED_STATUSES:
            closed += 1
    return closed


def classify_timeout(checkpoint_claims, envelope_event, artifacts) -> dict:
    """Classify one TIMEOUT into the three-verdict triage and name its
    memory landing. Returns {"verdict", "memory_landing",
    "method_memory_negative", "closed_checkpoints", "artifact_count"} —
    the landing fields are what the caller must obey (granularity
    never touches method memory; only method_fail carries a negative
    there). Pure — no IO, no mutation."""
    if not isinstance(envelope_event, dict) or not _is_timeout(envelope_event):
        raise ValueError(
            "classify_timeout: envelope_event carries no timeout marker — "
            "this face classifies timeouts, nothing else")
    if not isinstance(artifacts, (list, tuple)):
        raise ValueError("classify_timeout: artifacts must be a list")
    closed = _closed_count(checkpoint_claims)
    n_artifacts = len(list(artifacts))
    if closed >= 1:
        verdict = ENVELOPE_TOO_TIGHT
    elif n_artifacts >= 1:
        verdict = METHOD_FAIL
    else:
        verdict = GRANULARITY_FAULT
    return {
        "verdict": verdict,
        "memory_landing": MEMORY_LANDINGS[verdict],
        "method_memory_negative": verdict == METHOD_FAIL,
        "closed_checkpoints": closed,
        "artifact_count": n_artifacts,
    }
