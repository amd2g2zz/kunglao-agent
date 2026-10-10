#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""approach_demotion.py — D1 (issue 302): approach-class demotion on
failure-signature clusters (satellite of issue 298, validated by the EXP-C
dry-run posted to the issue).

THE RULE: within one approach class, N failures with DISTINCT mechanisms
demote the class; patching within it is forbidden afterwards (must switch
class or invest). Validated counterfactual on the distilled matrix:
N=2 + clause_b cuts the canonical failure series 12 -> 4 attempts, and the
rule's forced-invest carve-out reproduces exactly the shape of the two
real fixes (both were invest outputs after a demotion).

Two demotion clauses over the attempt log (pure replay, no I/O):

  clause_a  |distinct signature clusters(cls)| >= N. Clustering is by
            EXACT signature tuple — the same signature counts once. N
            structurally-different failures means the class fails for
            different reasons: in-class patching is whack-a-mole.
  clause_b  a single post-patch recurrence of one cluster (K_rec=1): the
            patch fixed the symptom, not the class. This is the escape
            hatch for two different bugs with an identical surface
            signature (and for infrastructure re-broken by a rewrite) —
            they cannot be told apart by signature, so recurrence-after-
            patch is counted instead. An invest (infrastructure change)
            NEVER triggers clause_b.

  Recommended rule: N=2 + clause_b(K_rec=1). Sensitivity (pinned in the
  synthetic fixture): N=1 is UNSAFE (it forbids the root-cause discovery
  round), N=3 is too lax, N=4 never fires (max distinct clusters per
  class is 3).

While demoted: in-class patching FORBIDDEN from the demotion round onward
(an attempt whose change since the previous record is "patch" or "none");
an invest ("change_kind": "invest") is allowed and its execution is the
one re-armed attempt. The demoting attempt itself is always allowed — the
demotion is a verdict AFTER the attempt.

GRANULARITY (binding EXP-C constraint): keying on coarse strategy
clusters is VACUOUS on the validated data — every round sits in one
macro-class. The operative taxonomy is the FINE instrumentation approach
classes. In the target_ladder integration (issue 234 artifact) the
demotion unit is therefore the ladder's mechanism FAMILY
(hooking/repackaging/... granularity), never a strategy bucket.

Failure-signature = multi-channel TUPLE lifted from the domain's own
discrimination heuristics (the six channels below). Signature-clusters
feed the demotion COUNTER; mechanism labels are for reporting only.
Single-channel clustering breaks in both directions (masking behind
louder failures; attribution drift across surface variants of one bug).

Record shape (the minimal failure-attempt input; the attempt log is a
list of these, in attempt order):

  {"round": 1,                        # attempt ordinal (label)
   "family": "hooking",               # the approach class (ladder family)
   "signature": {...}|None,           # 6-channel tuple; None on success
   "outcome": "success" | <any failure label>,
   "change_kind": "none"|"patch"|"invest"}   # what changed since the
                                             # previous record
"""
from __future__ import annotations

import json

# The six signature channels (multi-channel tuple; lifted verbatim from the
# validated domain's discrimination heuristics).
SIGNATURE_CHANNELS = ("installed_marker", "rewritten_flag", "did_family",
                      "artifact_size_class", "hit_values_fresh",
                      "process_state")

# What changed since the previous record. "patch" = an in-class patch of
# the failing mechanism (whack-a-mole candidate, triggers clause_b);
# "invest" = an infrastructure change (the forced alternative, never
# triggers clause_b, re-arms a demoted class for exactly one attempt).
CHANGE_KINDS = ("none", "patch", "invest")

ACTIVE = "ACTIVE"
DEMOTED = "DEMOTED"

DEFAULT_N = 2
K_RECURRENCE = 1


def normalize_signature(sig: dict | None) -> tuple[dict | None, str | None]:
    """Validate/normalize a signature tuple at the system boundary.

    Unknown channels are REJECTED (fail-closed — a typo'd channel would
    silently fork clusters); missing channels normalize to explicit nulls
    (the tuple is sparse by design: process-state-only failures leave the
    other five channels null). None is the success-row shape, valid.

    Returns (normalized, None) or (None, error).
    """
    if sig is None:
        return None, None
    if not isinstance(sig, dict):
        return None, ("signature must be a mapping over the channels "
                      f"{','.join(SIGNATURE_CHANNELS)}")
    unknown = sorted(str(k) for k in sig if k not in SIGNATURE_CHANNELS)
    if unknown:
        return None, (f"unknown signature channel(s): {','.join(unknown)} "
                      f"(valid: {','.join(SIGNATURE_CHANNELS)})")
    return {ch: sig.get(ch) for ch in SIGNATURE_CHANNELS}, None


def normalize_attempt(rec: dict) -> tuple[dict | None, str | None]:
    """Validate/normalize one failure-attempt record (the D1 input shape).

    Returns (record, None) or (None, error). The returned record is a NEW
    dict — the input is never mutated.
    """
    if not isinstance(rec, dict):
        return None, "attempt record must be a mapping"
    family = str(rec.get("family") or "").strip()
    if not family:
        return None, "attempt record carries no approach class (family)"
    # outcome CLASSIFIES, it does not reject: the artifact's pre-D1 walk
    # vocabulary (e.g. outcome: blocked) stays valid — a row is a success
    # iff it says so, any other value is a failure attempt. Legacy failures
    # carry no signature, so they can never demote anything.
    outcome = "success" if str(rec.get("outcome") or "").strip().lower() \
        == "success" else "fail"
    change = str(rec.get("change_kind") or "none").strip().lower()
    if change not in CHANGE_KINDS:
        return None, (f"unknown change_kind '{change}' "
                      f"({','.join(CHANGE_KINDS)})")
    sig, err = normalize_signature(rec.get("signature"))
    if err:
        return None, err
    return {"round": rec.get("round"), "family": family, "signature": sig,
            "outcome": outcome, "change_kind": change}, None


def signature_key(sig: dict) -> str:
    """The cluster key: the exact 6-channel tuple, deterministically
    serialized. Identical tuples are ONE cluster ("same signature counts
    once" falls out of key equality)."""
    return json.dumps([sig.get(ch) for ch in SIGNATURE_CHANNELS],
                      ensure_ascii=False, sort_keys=True, default=str)


def _replay(history: list[dict], n: int, k_recurrence: int,
            clause_b: bool) -> dict[str, dict]:
    """Single pass over the attempt log -> per-family demotion state.

    Malformed records fail CLOSED for the computation (they cannot demote
    anyone and they name their defect in the entry's "rejected" list) —
    the caller's ingestion face surfaces them.
    """
    entries: dict[str, dict] = {}
    rejected: list[str] = []
    for rec in history:
        norm, err = normalize_attempt(rec)
        if err:
            rejected.append(f"round {rec.get('round')}: {err}")
            continue
        fam = norm["family"]
        st = entries.setdefault(fam, {
            "state": ACTIVE, "demoted_at": None, "clause": None,
            "forbidden": [], "clusters": [], "recurrences": 0,
            "rejected": []})
        st["rejected"] = rejected  # shared, view of the log so far
        change = norm["change_kind"]
        round_no = norm["round"]
        # while-demoted enforcement: an invest re-arms for exactly one
        # attempt (its own execution row); anything else is forbidden.
        if st["demoted_at"] is not None and change != "invest":
            st["forbidden"].append(round_no)
        if norm["outcome"] == "success" or norm["signature"] is None:
            continue  # successes and signature-less rows add no cluster
        key = signature_key(norm["signature"])
        if key not in st["clusters"]:
            st["clusters"].append(key)  # clause_a: a NEW distinct cluster
            if len(st["clusters"]) >= n and st["demoted_at"] is None:
                st.update({"state": DEMOTED, "demoted_at": round_no,
                           "clause": "clause_a"})
        elif clause_b and change == "patch":
            # clause_b: the SAME cluster recurring after an in-class patch
            st["recurrences"] += 1
            if (st["recurrences"] >= k_recurrence
                    and st["demoted_at"] is None):
                st.update({"state": DEMOTED, "demoted_at": round_no,
                           "clause": "clause_b"})
    return entries


def demotion_state(history: list[dict], n: int = DEFAULT_N,
                   k_recurrence: int = K_RECURRENCE,
                   clause_b: bool = True) -> dict[str, dict]:
    """Pure replay of the attempt log -> per-family state:

    {family: {"state": ACTIVE|DEMOTED, "demoted_at": round|None,
              "clause": "clause_a"|"clause_b"|None,
              "forbidden": [rounds], "clusters": [keys],
              "recurrences": int, "rejected": [defects]}}
    """
    return _replay(history, n, k_recurrence, clause_b)


def demotion_round(history: list[dict], family: str, n: int = DEFAULT_N,
                   k_recurrence: int = K_RECURRENCE,
                   clause_b: bool = True) -> int | None:
    """The round `family` first demotes, or None (never demoted)."""
    entry = _replay(history, n, k_recurrence, clause_b).get(
        str(family).strip())
    return None if entry is None else entry["demoted_at"]


def demote(history: list[dict], family: str, n: int = DEFAULT_N,
           k_recurrence: int = K_RECURRENCE,
           clause_b: bool = True) -> str:
    """ACTIVE | DEMOTED — the demotion verdict for one approach class."""
    entry = _replay(history, n, k_recurrence, clause_b).get(
        str(family).strip())
    return ACTIVE if entry is None else entry["state"]


def forbidden_rounds(history: list[dict], n: int = DEFAULT_N,
                     k_recurrence: int = K_RECURRENCE,
                     clause_b: bool = True) -> list[int]:
    """All rounds the rule FORBIDS across every family, sorted."""
    rounds: list[int] = []
    for entry in _replay(history, n, k_recurrence, clause_b).values():
        rounds.extend(r for r in entry["forbidden"] if r is not None)
    return sorted(rounds)


def patch_forbidden(entry: dict | None, change_kind: str) -> bool:
    """The forward-looking gate face: is a NEXT attempt with `change_kind`
    forbidden for a family in this state? An invest is always allowed (the
    re-arm carve-out); the demoting attempt itself was allowed (enforcement
    starts strictly AFTER the demotion verdict)."""
    if not isinstance(entry, dict):
        return False
    return entry.get("demoted_at") is not None and change_kind != "invest"
