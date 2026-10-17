# -*- coding: utf-8 -*-
"""rlvr.invariants — the invariant-pruning operator (entropy reduction).

The search path used to spend attempts on candidates that observed
evidence already ruled out: a captured 16-byte digest coexisted with
32-byte-output hypotheses because nothing checked the candidate AGAINST
the disk before dispatch. This module is that check — feasibility
first, attempt second (the operator missing from the entropy-reduction
toolbox: prune the hypothesis space by observed invariants BEFORE a
step is spent, so every attempt buys information).

Invariant sources (evidence already on disk, never invented):
  - ``output_len``       the captured digest/ciphertext length (exact
                         match — a hash family fixes its width);
  - ``min_loop_bound``   the smallest loop iteration count observed in
                         the trace (a candidate whose core needs FEWER
                         rounds cannot have produced it);
  - ``input_alignment``  the captured input block alignment.

Contract:
  - ``check_candidate(candidate, invariants)`` -> (ok, reason). A
    candidate PREDICTS via ``predicted_<key>`` fields; a key the
    candidate does not predict is INCONCLUSIVE (pass — absence of a
    claim is not a violation; pruning is conservative, it only removes
    impossibilities). Contradiction rule per key: output_len and
    input_alignment are EXACT-match dimensions; min_loop_bound is a
    one-sided lower bound (predicted < observed contradicts — a core
    needing fewer iterations than the smallest loop in the trace could
    not have produced it; predicted > observed stays inconclusive).
    A violation reason NAMES the invariant, the prediction, and the
    observation (the log line is the audit).
  - ``prune(candidates, invariants)`` -> (survivors, rejected_rows).
    Pure; input order preserved; rejected rows carry the reason.

Fail-open+warn posture: malformed candidate rows (non-dict, missing
name) are SURVIVORS with a warn — a broken row must never silently
delete a real candidate (pruning removes IMPOSSIBLE candidates only;
unknown is not impossible).
"""
from __future__ import annotations

from kunglao_log import warn  # canonical warn: ONE implementation

# the closed invariant vocabulary: the observed facts a candidate can
# contradict. Keys outside this set are ignored (forward-compatible —
# an unmodeled observation never crashes the prune).
INVARIANT_KEYS = ("output_len", "min_loop_bound", "input_alignment")

#: contradiction rule per key: "exact" = any difference contradicts
#: (a digest width or an input alignment is a fixed property); "ge"
#: (lower-bound) = the prediction is the candidate's required minimum
#: and only a value BELOW the observation contradicts it (a core whose
#: loop needs FEWER iterations than the smallest loop observed in the
#: trace cannot have produced that trace; needing MORE is compatible —
#: longer inputs legitimately iterate further, so that side stays
#: inconclusive, never a rejection).
_INVARIANT_RULES: dict[str, str] = {
    "output_len": "exact",
    "min_loop_bound": "ge",
    "input_alignment": "exact",
}


def _contradicts(rule: str, observed, predicted) -> bool:
    if rule == "ge":
        return predicted < observed
    return predicted != observed


def _invariant_error(cname: str, key: str, observed, predicted) -> str:
    return (f"{cname}: predicted {key}={predicted!r} contradicts "
            f"observed {key}={observed!r} (invariant from evidence)")


def check_candidate(candidate: dict,
                    invariants: dict) -> tuple[bool, str]:
    """Feasibility of ONE candidate against observed invariants.

    Returns (True, "") when no prediction contradicts an observation,
    else (False, reason) with the FIRST contradiction named (candidate,
    invariant key, prediction, observation — the log line is the
    audit). A candidate that predicts nothing passes (inconclusive !=
    impossible)."""
    if not isinstance(candidate, dict):
        warn("invariants.check", f"non-dict candidate {type(candidate).__name__}")
        return True, ""
    cname = str(candidate.get("name") or "?")
    for key in INVARIANT_KEYS:
        if key not in invariants:
            continue  # unobserved dimension: no constraint
        observed = invariants[key]
        pred = candidate.get(f"predicted_{key}")
        if pred is None:
            continue  # unclaimed dimension: inconclusive, never a violation
        try:
            pred = int(pred)
        except (TypeError, ValueError):
            # malformed prediction: fail-open with one canonical warn —
            # a broken row never rejects a candidate (unknown is not
            # impossible), matching the prune's conservative contract.
            warn("invariants.check",
                 f"{cname}: non-numeric predicted_{key}={pred!r} "
                 f"treated as inconclusive")
            continue
        if _contradicts(_INVARIANT_RULES[key], observed, pred):
            return False, _invariant_error(cname, key, observed, pred)
    return True, ""


def prune(candidates: list[dict],
          invariants: dict) -> tuple[list[dict], list[dict]]:
    """Prune a candidate list BEFORE any attempt is spent.

    Survivors keep input order; rejected rows are the candidate dicts
    themselves (callers log/annotate them). Malformed rows survive with
    one canonical warn each — pruning is conservative by contract."""
    survivors: list[dict] = []
    rejected: list[dict] = []
    for cand in candidates:
        ok, reason = check_candidate(cand, invariants)
        if ok:
            survivors.append(cand)
        else:
            rejected.append(dict(cand, reject_reason=reason))
    return survivors, rejected


def invariants_from_lengths(output_len: int | None = None,
                            min_loop_bound: int | None = None,
                            input_alignment: int | None = None) -> dict:
    """Assemble an invariant set from observations already on disk.

    None observations are OMITTED (an unknown fact constrains nothing —
    the prune stays conservative). Values are coerced to int; a
    non-numeric observation degrades to omission with one warn."""
    out: dict = {}
    for key, value in (("output_len", output_len),
                       ("min_loop_bound", min_loop_bound),
                       ("input_alignment", input_alignment)):
        if value is None:
            continue
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            warn("invariants.assemble",
                 f"{key}: non-numeric observation {value!r} omitted")
    return out
