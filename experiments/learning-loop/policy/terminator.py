# -*- coding: utf-8 -*-
"""policy/terminator.py — β(s_t), the dynamic step-count face (#882).

The fixed-N rollout length is replaced by an adaptive termination
policy: after every step result the loop asks this face whether the
rollout continues, and the answer rides three rules —

  rule 1  question-covered  the scope-verifier's coverage input says
          the claim's question is answered by verified results. The
          rollout terminates and the receipt carries the
          efficiency-credit flag: finishing early is a POSITIVE
          signal, never a failure (the efficiency credit must never
          train as loss mass).
  rule 2  loss-cut          N consecutive steps of this rollout
          produced no new verified fact. The rollout terminates to
          stop wasting the per-dispatch budget on a dead arm.
  watchdog                  one-shot per-rollout deadline = family
          prior × per-dispatch budget × slack, where the prior is the
          family's expected dispatch count learned from the ledger's
          own history (obs dispatch rows grouped per claim, v2
          assign_step rows grouped per rollout — real fields only). A
          cold family takes the documented default prior, never zero.
          A rollout completing before the deadline early-cancels it.
          The prior is STABILITY-FIRST (#906): it recomputes only at
          batch boundaries (every PRIOR_BATCH-th family rollout),
          commits a boundary candidate only outside the relative
          hysteresis deadband, and the candidate is the just-completed
          batch's rollout-order mean (recency — new short rollouts are
          not averaged away by old long ones). An optional normalized
          progress P_norm damps the frozen prior by (1 − κ·P_norm),
          floored at one dispatch. Within the FIRST (sub-batch)
          batch the read faces project the live all-history mean (the
          #882 posture, byte-identical) — the warmup holder itself
          carries no materialized prior, so incremental threading
          composes exactly with one-shot replay.

The deployed fixed-N surface under scripts/ and hooks/ is removed by
the separate removal card; THIS face is the policy that supersedes it
and pins the new semantics — the two must not be wired side by side.

Pure decision faces: (state inputs, ledger rows, rng) -> receipt
dicts, no polling, no wall clock in any decision (durations appear
only as Budget arithmetic). The rng is the uniform policy-face
contract slot (samples never argmax); the current rules are
deterministic draws, so a rule that later needs stochastic
hysteresis threads this rng without a signature change. Live callers
derive the seed with ``terminator_seed`` (ledger state + round —
never the clock, the #251 contract) and thread it as
``random.Random(seed)``.

Fail-closed at the boundary (the episode_schema validator posture):
structural garbage in THIS rollout's rows raises ValueError, because
a silently tolerated malformed row would fabricate a termination
decision. The row wall accepts ONLY the three q-cell trajectory
schemas — the face never half-reads its evidence base; rows of OTHER
rollouts are skipped before the per-row validation (their integrity
is their own rollout's concern, never silently folded in here). Honest gaps INSIDE valid rows
(a dispatch row without a claim, an action row without a family)
are skipped, never bucketed (the usage_family_map tolerance).
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_HERE = Path(__file__).resolve().parent.parent          # learning-loop/
_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget  # noqa: E402 — the path bootstrap needs to land first
from rlvr import q_cells  # noqa: E402

#: the receipt stamps — every decision names its schema (the audit face)
CHECK_SCHEMA = "terminator-check/1"
WATCHDOG_SCHEMA = "watchdog-deadline/1"
WATCHDOG_CHECK_SCHEMA = "watchdog-check/1"

#: rule 2's default empty-step cut. A documented policy constant (NOT
#: fitted), the same governance class as q_cells.SHRINK_CAP: changing
#: it follows the replay-evidence-plus-pins procedure.
LOSS_CUT_N = 3

#: the cold-family prior: a family with no ledger history still gets a
#: real deadline. Deliberately generous — the watchdog exists to cut
#: wasteful rollouts, not to starve unexplored arms (never zero).
COLD_FAMILY_PRIOR = 4.0

#: the deadline's slack multiplier over prior × per-dispatch budget.
WATCHDOG_SLACK = 2.0

#: #906 batch cadence: the family prior recomputes ONLY at batch
#: boundaries — every PRIOR_BATCH-th rollout observation of that
#: family. Within a batch the deadline is FROZEN: a step length that
#: churns per rollout adds noise, not signal.
PRIOR_BATCH = 5

#: #906 hysteresis deadband (relative): a boundary candidate replaces
#: the standing prior only when |candidate − prior| > this fraction of
#: the prior. Sub-deadband micro-fluctuations never move the deadline.
PRIOR_DEADBAND = 0.20

#: #906 state-conditioning damping: with normalized progress P_norm
#: supplied, the effective prior is prior × (1 − κ·P_norm) — knowledge
#: growth shortens the expected path, damped so the deadline never
#: collapses on a rich state. Documented, not fitted.
WATCHDOG_KAPPA = 0.5

#: #906 floor for the P-damped effective prior, in dispatches: the
#: watchdog never tightens below one dispatch regardless of progress.
PRIOR_FLOOR = 1.0

#: rule → closed action kind. The decision acts only through the
#: #878 action space; both fire rules end the ROLLOUT (the loss-cut
#: judges the arm, not one step of it).
RULE_ACTION_KINDS: Mapping[str, str] = {
    "question_covered": "terminate_rollout",
    "loss_cut": "terminate_rollout",
}

_ROW_SCHEMAS = frozenset({q_cells.OBS_SCHEMA, q_cells.SCHEMA_ACTION_V2,
                          q_cells.SCHEMA_RESULT_V2})


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"terminator.{field}: {why}")


def _non_empty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(field, "must be a non-empty string")
    return value


def _count(value: Any, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or value < minimum:
        raise _fail(field, f"must be an integer >= {minimum}")
    return value


def _real(value: Any, field: str, *, minimum: float,
          exclusive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) \
            or (value <= minimum if exclusive else value < minimum):
        bound = f"> {minimum}" if exclusive else f">= {minimum}"
        raise _fail(field, f"must be a finite number {bound}")
    return float(value)


def _rows_wall(rows: Any) -> list[dict]:
    """The fail-closed row boundary: a sequence of mappings whose
    schema is one of the three q-cell trajectory kinds. Anything else
    is structural garbage — the face refuses to decide on it."""
    if not isinstance(rows, (list, tuple)):
        raise _fail("rows", "must be a list of ledger rows")
    for row in rows:
        if not isinstance(row, Mapping):
            raise _fail("rows", "every row must be a mapping")
        schema = row.get("schema")
        if schema not in _ROW_SCHEMAS:
            raise _fail("rows",
                        f"{schema!r} outside the q-cell trajectory "
                        f"schemas {sorted(_ROW_SCHEMAS)}")
    return list(rows)


def _coverage_doc(coverage: Any) -> dict:
    """The scope-verifier's coverage input. ``covered`` is the ONE
    load-bearing field and must be a real bool; the audit fields
    (question, verified_step_ids) are recorded, never re-litigated —
    re-deciding another face's verdict would be a second authority."""
    if not isinstance(coverage, Mapping):
        raise _fail("coverage", "must be the scope-verifier's mapping")
    covered = coverage.get("covered")
    if not isinstance(covered, bool):
        raise _fail("coverage.covered", "must be a bool")
    doc: dict[str, Any] = {"covered": covered}
    question = coverage.get("question")
    if question is not None:
        doc["question"] = _non_empty(question, "coverage.question")
    steps = coverage.get("verified_step_ids")
    if steps is not None:
        if not isinstance(steps, (list, tuple)):
            raise _fail("coverage.verified_step_ids",
                        "must be a list of step ids")
        doc["verified_step_ids"] = [
            _non_empty(s, "coverage.verified_step_ids") for s in steps]
    return doc


def terminator_seed(rows: Sequence[Mapping], subject: str,
                    round_no: int = 0) -> int:
    """The decision seed: sha256 over the trajectory's content
    identities (canonical json per row, append order) + the subject +
    the round. Same ledger, same seed; the evidence moved or the
    round advanced → the seed moves. Never the wall clock (the #251
    contract) — ``ts`` enters only as row data, never as a clock
    read."""
    safe = _rows_wall(rows)
    key = _non_empty(subject, "subject")
    rnd = _count(round_no, "round_no", minimum=0)
    digest = hashlib.sha256()
    digest.update(f"terminator/{key}/{rnd}".encode("utf-8"))
    for row in safe:
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                 default=str).encode("utf-8"))
    return int.from_bytes(digest.digest()[:8], "big")


def _unverified_streak(rows: list[dict], rollout_id: str) -> int:
    """The rollout's trailing run of unverified result rows — the
    loss-cut's counter. Rows of other rollouts never leak in; the
    first verified result breaks the streak."""
    streak = 0
    for row in reversed(rows):
        if row.get("schema") != q_cells.SCHEMA_RESULT_V2:
            continue
        if str(row.get("rollout_id") or "") != rollout_id:
            continue
        verified = row.get("verified")
        if not isinstance(verified, bool):
            raise _fail("verified",
                        f"result row of {rollout_id} carries a non-bool")
        if verified:
            break
        streak += 1
    return streak


def check_termination(rollout_id: str, coverage: Mapping[str, Any],
                      rows: Sequence[Mapping], *,
                      loss_cut_n: int = LOSS_CUT_N,
                      rng: random.Random | None = None) -> dict:
    """β(s_t) — the per-step termination check (#882). Pure:
    (rollout id, coverage input, trajectory rows) -> receipt. Rule 1
    (question-covered) outranks rule 2 (loss-cut); neither firing
    means the rollout continues. The rng is the protocol slot (see
    module docstring); the rules themselves are deterministic."""
    del rng  # the deterministic rules make no draw; the slot stays
    rid = _non_empty(rollout_id, "rollout_id")
    cut = _count(loss_cut_n, "loss_cut_n", minimum=1)
    cov = _coverage_doc(coverage)
    safe = _rows_wall(rows)
    streak = _unverified_streak(safe, rid)
    if cov["covered"]:
        rule = "question_covered"
        why = ("rule 1 question_covered: the scope verifier reports the "
               "claim's question answered by verified results")
    elif streak >= cut:
        rule = "loss_cut"
        why = (f"rule 2 loss_cut: {streak} consecutive steps produced no "
               f"new verified fact (cut at {cut})")
    else:
        rule = None
        why = (f"continue: coverage open and the empty-step streak is "
               f"{streak}/{cut}")
    kind = RULE_ACTION_KINDS.get(rule) if rule is not None else None
    return {
        "schema": CHECK_SCHEMA,
        "rollout_id": rid,
        "terminate": rule is not None,
        "rule": rule,
        "action_kind": kind,
        "efficiency_credit": rule == "question_covered",
        "consecutive_unverified": streak,
        "loss_cut_n": cut,
        "question": cov.get("question"),
        "verified_step_ids": list(cov.get("verified_step_ids") or ()),
        "why": why,
    }


def _family_rollout_counts(rows: list[dict]) -> dict[str, list[int]]:
    """Per-family rollout observations in ROLLOUT ORDER (append order —
    never wall clock), learned from the ledger's own history. Two
    sample sources over REAL fields, pooled as independent rollout
    observations: obs dispatch rows (source=dispatch) grouped per
    ``claim`` with the claim's LAST declared ``method_family``
    winning, and v2 ``assign_step`` action rows grouped per
    ``rollout_id`` keyed by ``params.method_family``. Each sample is
    one rollout's dispatch count. Family-less rows are the honest
    gap — counted nowhere, never a bucket."""
    claim_family: dict[str, str] = {}
    claim_counts: dict[str, int] = {}
    ro_family: dict[str, str] = {}
    ro_counts: dict[str, int] = {}
    for row in rows:
        schema = row["schema"]
        if schema == q_cells.OBS_SCHEMA:
            if str(row.get("source") or "") != "dispatch":
                continue
            claim = str(row.get("claim") or "").strip()
            if not claim:
                continue
            claim_counts[claim] = claim_counts.get(claim, 0) + 1
            family = str(row.get("method_family") or "").strip()
            if family:
                claim_family[claim] = family
        elif schema == q_cells.SCHEMA_ACTION_V2:
            if row.get("kind") != "assign_step":
                continue
            rid = str(row.get("rollout_id") or "").strip()
            if not rid:
                continue
            ro_counts[rid] = ro_counts.get(rid, 0) + 1
            params = row.get("params")
            family = params.get("method_family") \
                if isinstance(params, Mapping) else None
            family = family.strip() if isinstance(family, str) else ""
            if family:
                ro_family[rid] = family
    samples: dict[str, list[int]] = {}
    for claim, family in claim_family.items():
        samples.setdefault(family, []).append(claim_counts[claim])
    for rid, family in ro_family.items():
        samples.setdefault(family, []).append(ro_counts[rid])
    return samples


def _fold_family_prior(
        samples: Sequence[int],
        state: tuple[float | None, int, tuple[int, ...]] | None = None,
) -> tuple[float | None, int, tuple[int, ...]]:
    """The #906 prior fold over one family's rollout-order samples.
    Carries the prior-state holder ``(current_prior,
    rollouts_since_update, batch_accumulator)``: every sample joins the
    batch accumulator; at each PRIOR_BATCH-th sample (a batch boundary)
    the accumulator's mean is the recency candidate, which replaces the
    standing prior only outside PRIOR_DEADBAND. Until the FIRST
    boundary commits, ``current_prior`` stays None — the warmup prior
    is a READ-FACE PROJECTION (see ``_holder_prior``), never a
    materialized state field, so threading a mid-batch state composes
    EXACTLY with the one-shot fold (the first boundary commits
    unconditionally in both). The fold is pure: new tuples in, no
    globals; the state re-derives from replay, it is never stored."""
    prior, since, acc = state if state is not None else (None, 0, ())
    for count in samples:
        acc = acc + (count,)
        since += 1
        if since >= PRIOR_BATCH:
            candidate = sum(acc) / len(acc)
            if prior is None \
                    or abs(candidate - prior) > PRIOR_DEADBAND * prior:
                prior = candidate
            acc, since = (), 0
    return (prior, since, acc)


def _holder_prior(
        state: tuple[float | None, int, tuple[int, ...]]) -> float | None:
    """The effective prior a holder projects for the read faces: the
    committed batch prior, or — before the first boundary — the live
    all-history mean of the partial accumulator (the #882 warmup
    posture, byte-identical for sub-batch histories). None = no
    samples."""
    prior, _since, acc = state
    if prior is not None:
        return prior
    return sum(acc) / len(acc) if acc else None


def _prior_state_and_census(
        rows: list[dict],
        prior_state: Mapping[str, tuple[float | None, int,
                                         tuple[int, ...]]] | None = None,
) -> tuple[dict[str, tuple[float | None, int, tuple[int, ...]]],
           dict[str, list[int]]]:
    """ONE scan over the rows returning both the #906 prior holder and
    the raw rollout census, so the deadline face never rescans the
    ledger it just folded."""
    counts = _family_rollout_counts(rows)
    state = dict(prior_state) if prior_state is not None else {}
    holder = {family: _fold_family_prior(samples, state.get(family))
              for family, samples in sorted(counts.items())}
    return holder, counts


def _family_samples(
        rows: list[dict],
        prior_state: Mapping[str, tuple[float | None, int,
                                         tuple[int, ...]]] | None = None,
) -> dict[str, tuple[float | None, int, tuple[int, ...]]]:
    """Per-family #906 prior state: {family: (current_prior,
    rollouts_since_update, batch_accumulator)}. The prior state is
    DERIVABLE from the ledger replay — the batch counter and
    accumulator recompute from the row order and are never stored.
    Streaming contract: ``prior_state`` must summarize STRICTLY
    PRECEDING rows and ``rows`` carries only the not-yet-condensed
    tail — the composition then equals the one-shot fold over the
    concatenation for ANY partition, mid-batch ones included (pinned)."""
    return _prior_state_and_census(rows, prior_state)[0]


def family_dispatch_priors(rows: Sequence[Mapping]) -> dict[str, float]:
    """The prior read face: {family: the #906 batch-frozen prior} — the
    standing prior each rollout of that family sees at this ledger
    state. A family absent from the map is COLD — consumers take
    ``COLD_FAMILY_PRIOR``, never zero."""
    holder, _counts = _prior_state_and_census(_rows_wall(rows))
    priors: dict[str, float] = {}
    for family, state in holder.items():
        prior = _holder_prior(state)
        if prior is not None:
            priors[family] = round(prior, 6)
    return priors


def _checked_p_norm(value: Any) -> float | None:
    """None or a finite number in [0, 1] — the #898 P face's normalized
    progress, damped by WATCHDOG_KAPPA at the deadline boundary."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise _fail("p_norm", "must be None or a finite number in [0, 1]")
    return float(value)


def watchdog_deadline(family: str, rows: Sequence[Mapping],
                      budget: Budget, *,
                      slack: float = WATCHDOG_SLACK,
                      round_no: int = 0,
                      p_norm: float | None = None) -> dict:
    """Arm the ONE-SHOT per-rollout watchdog:
    deadline = effective prior × per-dispatch budget × slack. The
    prior is the #906 batch-frozen recency prior (batch cadence +
    hysteresis, see the module docstring); a cold family takes the
    documented default. With ``p_norm`` supplied (#898's normalized
    progress in [0,1]) the EFFECTIVE prior is the frozen prior damped
    by (1 − κ·p_norm), floored at PRIOR_FLOOR; without it the receipt
    is byte-identical to the pre-#906 legacy receipt (same keys, same
    values). The receipt's ``prior`` stays the learned frozen prior;
    ``effective_prior`` is what the deadline spends. Pure arithmetic on
    Budget fields — no clock is read here; the runtime that spends the
    deadline compares elapsed wall time against ``deadline_s`` through
    ``watchdog_check``."""
    fam = _non_empty(family, "family")
    rnd = _count(round_no, "round_no", minimum=0)
    norm = _checked_p_norm(p_norm)
    if not isinstance(budget, Budget):
        raise _fail("budget", "must be a core.Budget value object")
    wall = _real(budget.wall_s, "budget.wall_s", minimum=0.0,
                 exclusive=True)
    slack_f = _real(slack, "slack", minimum=0.0, exclusive=True)
    safe = _rows_wall(rows)
    holder, counts = _prior_state_and_census(safe)
    projected = _holder_prior(holder[fam]) if fam in holder else None
    if projected is not None:
        prior, cold = projected, False
        rollouts = len(counts.get(fam, ()))
    else:
        prior, cold, rollouts = COLD_FAMILY_PRIOR, True, 0
    rec: dict[str, Any] = {
        "schema": WATCHDOG_SCHEMA,
        "family": fam,
        "prior": round(prior, 6),
        "cold": cold,
        "per_dispatch_budget_s": round(wall, 6),
        "slack": slack_f,
        "deadline_s": round(prior * wall * slack_f, 6),
        "one_shot": True,
        "early_cancel_on_complete": True,
        "history_rollouts": rollouts,
        "seed": terminator_seed(safe, fam, rnd),
    }
    if norm is not None:
        effective = max(PRIOR_FLOOR, prior * (1.0 - WATCHDOG_KAPPA * norm))
        rec["p_norm"] = norm
        rec["kappa"] = WATCHDOG_KAPPA
        rec["effective_prior"] = round(effective, 6)
        rec["deadline_s"] = round(effective * wall * slack_f, 6)
    return rec


def watchdog_check(deadline: Mapping[str, Any], *, elapsed_s: float,
                   rollout_completed: bool) -> dict:
    """Spend the watchdog: has the rollout outlived its deadline? A
    rollout that completed BEFORE the deadline early-cancels the
    one-shot (it never fires on a finished rollout) and earns the
    efficiency credit — done under the family-informed line is the
    same POSITIVE signal as rule 1's early answer. A LATE completion
    still early-cancels (the watchdog has nothing left to guard) but
    earns NOTHING: crediting slow would train "slow is fine". The
    deadline boundary is inclusive: at exactly ``deadline_s`` it
    fires."""
    if not isinstance(deadline, Mapping) \
            or deadline.get("schema") != WATCHDOG_SCHEMA:
        raise _fail("deadline",
                    f"must be a {WATCHDOG_SCHEMA!r} receipt")
    limit = _real(deadline.get("deadline_s"), "deadline.deadline_s",
                  minimum=0.0)
    spent = _real(elapsed_s, "elapsed_s", minimum=0.0)
    if not isinstance(rollout_completed, bool):
        raise _fail("rollout_completed", "must be a bool")
    if rollout_completed:
        early = spent < limit
        return {"schema": WATCHDOG_CHECK_SCHEMA,
                "fired": False, "early_cancel": True,
                "efficiency_credit": early,
                "reason": ("rollout_completed_early" if early
                           else "rollout_completed_late"),
                "elapsed_s": spent, "deadline_s": limit,
                "family": deadline.get("family")}
    fired = spent >= limit
    return {"schema": WATCHDOG_CHECK_SCHEMA,
            "fired": fired, "early_cancel": False,
            "efficiency_credit": False,
            "reason": "deadline_reached" if fired else "within_deadline",
            "elapsed_s": spent, "deadline_s": limit,
            "family": deadline.get("family")}
