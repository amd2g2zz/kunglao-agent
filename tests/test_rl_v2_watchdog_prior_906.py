# -*- coding: utf-8 -*-
"""tests/test_rl_v2_watchdog_prior_906.py — the watchdog prior refinement.

RED-first pins for issue #906 (STABILITY-FIRST over the #882 all-history
mean prior):

  1. batch cadence: the prior recomputes ONLY at batch boundaries —
     every PRIOR_BATCH-th rollout of that family; within a batch the
     deadline is FROZEN (every rollout sees the identical expectation);
  2. recency: the boundary candidate is the just-completed batch's
     rollout-order mean — new short rollouts are NOT averaged away by
     old long ones (append order, never wall clock);
  3. hysteresis: at a boundary the candidate replaces the old prior
     only when |new − old| exceeds the relative deadband; sub-deadband
     drift keeps the old prior — pinned with wide binary-exact margins
     from both sides (the equality edge itself is
     IEEE-rounding-direction dependent and deliberately unpinned);
  4. P-conditioning: p_norm ∈ [0,1] damps the frozen prior by
     (1 − κ·P_norm) floored at 1 dispatch; monotone in P_norm; the
     no-P path is byte-identical to the legacy #882 receipt;
  5. cold families unchanged; warmup (sub-batch) families keep the
     live all-history mean so no #882 pin moves without cause;
  6. determinism: the prior state re-derives from ledger replay —
     threading the holder equals the one-shot fold across ANY
     partition, mid-batch ones included (warmup states carry no
     materialized prior).
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget  # noqa: E402
from policy import terminator  # noqa: E402
from rlvr import q_cells  # noqa: E402

LEGACY_DEADLINE_KEYS = frozenset({
    "schema", "family", "prior", "cold", "per_dispatch_budget_s",
    "slack", "deadline_s", "one_shot", "early_cancel_on_complete",
    "history_rollouts", "seed",
})


def _sig() -> str:
    return "a" * 12


_CLAIM_UID = itertools.count()          # per-call unique claim ids


def _rollouts(ws, family, counts, *, claim_prefix="C"):
    """One dispatch-claim group per rollout observation: claim i carries
    counts[i] dispatch rows, appended in rollout order. Claim ids are
    unique across calls — a repeated id would merge two rollouts into
    one observation."""
    base = f"{claim_prefix}-{next(_CLAIM_UID)}"
    for i, n in enumerate(counts):
        for j in range(n):
            q_cells.append_observation(
                ws, _sig(), family, None, source="dispatch",
                claim=f"{base}-{i}",
                dispatch_id=f"d-{base}-{i}-{j}")


def _priors(ws, family):
    rows = q_cells.trajectory_rows(ws)
    return terminator.family_dispatch_priors(rows).get(family)


def _deadline(ws, family, *, wall=600.0, slack=2.0, **kw):
    rows = q_cells.trajectory_rows(ws)
    return terminator.watchdog_deadline(family, rows, Budget(wall_s=wall),
                                        slack=slack, **kw)


# --------------------------------------------------- documented constants

def test_constants_are_documented_not_fitted():
    assert terminator.PRIOR_BATCH == 5
    assert terminator.PRIOR_DEADBAND == pytest.approx(0.20)
    assert terminator.WATCHDOG_KAPPA == pytest.approx(0.5)
    assert terminator.PRIOR_FLOOR == pytest.approx(1.0)


# ------------------------------------------------------- batch cadence / freeze

def test_batch_freeze_deadline_identical_within_batch(tmp_path):
    """Batch 1 is EXEMPT from the freeze: until the first boundary
    commits, the warmup prior is the live all-history mean (the #882
    posture — legacy byte-identity where batch semantics have not yet
    bitten). The freeze contract bites from the first boundary on:
    within batch 2 the deadline never moves even as the accumulator
    fills (a rollout-wise recompute would drag it to the drifting
    all-history mean)."""
    ws = tmp_path / "ws"
    _rollouts(ws, "fz", [5, 5, 5, 5, 5])       # boundary 1: commits 5.0
    seen = [_priors(ws, "fz")]
    deadlines = [_deadline(ws, "fz")["deadline_s"]]
    for _ in range(4):                          # rollouts 6..9: batch 2 body
        _rollouts(ws, "fz", [1])
        seen.append(_priors(ws, "fz"))
        deadlines.append(_deadline(ws, "fz")["deadline_s"])
    assert seen[1:] == [5.0, 5.0, 5.0, 5.0]     # the prior never moves
    assert len(set(deadlines)) == 1             # the deadline is FROZEN
    # the frozen value is the batch-1 commit, not the drifting all-history
    # mean ((25 + 4) / 9 ≈ 3.22) a rollout-wise recompute would produce
    assert deadlines[-1] == pytest.approx(5.0 * 600.0 * 2.0)
    assert deadlines[-1] != pytest.approx((29.0 / 9.0) * 600.0 * 2.0)


def test_batch_cadence_prior_moves_at_most_once_per_k(tmp_path):
    ws = tmp_path / "ws"
    counts = [5, 5, 5, 5, 5, 1, 1, 1, 1, 1, 5, 5, 5, 5, 5]
    sweep = []
    for n, c in enumerate(counts, start=1):
        _rollouts(ws, "cd", [c])
        sweep.append(_priors(ws, "cd"))
    change_points = [n for n in range(2, len(sweep) + 1)
                     if sweep[n - 1] != sweep[n - 2]]
    assert change_points == [10, 15]            # only at boundaries
    assert all(n % terminator.PRIOR_BATCH == 0 for n in change_points)
    assert sweep[:9] == [5.0] * 9               # n=1..9: warmup + batch-1
    assert sweep[9:14] == [1.0] * 5             # n=10..14: the fresh batch
    assert sweep[14] == pytest.approx(5.0)


def test_recency_candidate_is_not_the_all_history_mean(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "rc", [5, 5, 5, 5, 5, 1, 1, 1, 1, 1])
    assert _priors(ws, "rc") == pytest.approx(1.0)      # the fresh batch
    all_history = (5 * 5 + 1 * 5) / 10
    assert _priors(ws, "rc") != pytest.approx(all_history)  # ≈ 3.0: the lag


# ---------------------------------------------------------------- hysteresis

@pytest.mark.parametrize("batch2, moved", [
    ([2, 2, 2, 2, 1], False),   # candidate 1.8: |Δ| = 0.2, inside deadband
    ([1, 1, 1, 1, 1], True),    # candidate 1.0: |Δ| = 1.0, strictly outside
])
def test_hysteresis_deadband_gates_the_boundary_move(tmp_path, batch2, moved):
    ws = tmp_path / "ws"
    _rollouts(ws, "hy", [2, 2, 2, 2, 2])        # batch 1 commits prior 2.0
    assert _priors(ws, "hy") == pytest.approx(2.0)
    _rollouts(ws, "hy", batch2)
    assert _priors(ws, "hy") == pytest.approx(1.0 if moved else 2.0)


def test_hysteresis_edge_pins_are_binary_exact_not_ieee_riding():
    """The equality edge itself (candidate exactly deadband×prior away)
    is IEEE-rounding-direction dependent and deliberately NOT pinned;
    the strict-inequality contract is pinned from both sides with
    binary-exact values instead (prior 2.0: candidate 1.5 → 0.5 is
    decisively outside; candidate 1.8 → 0.2 decisively inside)."""
    outside = terminator._fold_family_prior(
        (1.5, 1.5, 1.5, 1.5, 1.5), (2.0, 0, ()))
    assert outside == (1.5, 0, ())              # 0.5 > deadband 0.4: moves
    inside = terminator._fold_family_prior(
        (1.8, 1.8, 1.8, 1.8, 1.8), (2.0, 0, ()))
    assert inside == (2.0, 0, ())               # 0.2 ≤ deadband 0.4: keeps


# ------------------------------------------------------------ P-conditioning

def test_p_norm_damps_monotonically_at_a_fixed_batch_position(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "pz", [2, 2, 2, 2, 2, 1, 1])  # within batch 2: frozen 2.0
    effective = []
    for p in (0.0, 0.25, 0.5, 0.75, 1.0):
        rec = _deadline(ws, "pz", p_norm=p)
        effective.append(rec["effective_prior"])
        assert rec["deadline_s"] == pytest.approx(
            rec["effective_prior"] * 600.0 * 2.0)
        assert rec["p_norm"] == pytest.approx(p)
        assert rec["kappa"] == pytest.approx(terminator.WATCHDOG_KAPPA)
    assert effective == [2.0, 1.75, 1.5, 1.25, 1.0]  # monotone in P_norm
    assert all(a >= b for a, b in zip(effective, effective[1:]))


def test_p_norm_floors_at_one_dispatch(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "fl", [1, 1, 1, 1, 1])        # learned prior 1.0
    rec = _deadline(ws, "fl", p_norm=1.0)
    assert rec["effective_prior"] == pytest.approx(1.0)   # 1 × (1 − κ) → floor
    assert rec["deadline_s"] == pytest.approx(1.0 * 600.0 * 2.0)
    cold = _deadline(ws, "fam-never-seen", p_norm=1.0)    # 4 × (1 − κ) → 2.0
    assert cold["effective_prior"] == pytest.approx(2.0)


def test_p_norm_validation_reject_pins(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "v", [1, 1, 1, 1, 1])
    for bad in (-0.1, 1.1, 2, True, "0.5", float("nan"), float("inf")):
        with pytest.raises(ValueError):
            _deadline(ws, "v", p_norm=bad)
    for good in (0, 1, 0.5):
        assert _deadline(ws, "v", p_norm=good)["p_norm"] == pytest.approx(good)


# ----------------------------------------------- legacy byte-identity / cold

def test_no_p_norm_path_is_byte_identical_to_the_legacy_receipt(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "fam-a", [2, 4])              # sub-batch history
    rec = _deadline(ws, "fam-a")
    assert frozenset(rec) == LEGACY_DEADLINE_KEYS   # no #906 fields appear
    assert rec["prior"] == pytest.approx(3.0)       # the #882 all-history mean
    assert rec["deadline_s"] == pytest.approx(3.0 * 600.0 * 2.0)
    assert rec["cold"] is False and rec["history_rollouts"] == 2


def test_cold_family_posture_unchanged(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="select_task", rollout_id="ro-1",
                          target="C-1")
    rows = q_cells.trajectory_rows(ws)
    rec = terminator.watchdog_deadline("fam-cold", rows,
                                       Budget(wall_s=100.0), slack=1.5)
    assert frozenset(rec) == LEGACY_DEADLINE_KEYS
    assert rec["cold"] is True
    assert rec["prior"] == pytest.approx(terminator.COLD_FAMILY_PRIOR)
    assert rec["deadline_s"] == pytest.approx(
        terminator.COLD_FAMILY_PRIOR * 100.0 * 1.5)
    assert rec["history_rollouts"] == 0


def test_warmup_live_mean_matches_the_legacy_all_history_mean(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "wm", [4])
    assert _priors(ws, "wm") == pytest.approx(4.0)
    _rollouts(ws, "wm", [2])
    assert _priors(ws, "wm") == pytest.approx(3.0)
    _rollouts(ws, "wm", [2])
    assert _priors(ws, "wm") == pytest.approx(8.0 / 3.0)


def test_history_rollouts_still_counts_every_family_rollout(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "hc", [2, 2, 2, 2, 2, 1, 1, 1, 1, 1])
    rec = _deadline(ws, "hc")
    assert rec["history_rollouts"] == 10        # the census, not the window
    assert rec["prior"] == pytest.approx(1.0)   # while the prior is the window


# ---------------------------------------------------------------- determinism

def test_determinism_same_rows_same_p_norm_same_receipt(tmp_path):
    ws = tmp_path / "ws"
    _rollouts(ws, "dt", [5, 5, 5, 5, 5, 1, 1, 1, 1])
    rows = q_cells.trajectory_rows(ws)
    kw = {"p_norm": 0.4}
    assert (terminator.watchdog_deadline("dt", rows, Budget(wall_s=600.0),
                                         **kw)
            == terminator.watchdog_deadline("dt", rows, Budget(wall_s=600.0),
                                            **kw))


def test_rollout_order_not_wall_clock_drives_the_recency(tmp_path):
    fresh_first = tmp_path / "fresh"
    stale_first = tmp_path / "stale"
    _rollouts(fresh_first, "ro", [5, 5, 5, 5, 5, 1, 1, 1, 1, 1])
    _rollouts(stale_first, "ro", [1, 1, 1, 1, 1, 5, 5, 5, 5, 5])
    assert _priors(fresh_first, "ro") == pytest.approx(1.0)
    assert _priors(stale_first, "ro") == pytest.approx(5.0)


def test_prior_state_threads_batch_by_batch_and_rederives_from_replay(
        tmp_path):
    first = tmp_path / "first"
    rest = tmp_path / "rest"
    both = tmp_path / "both"
    _rollouts(first, "th", [5, 5, 5, 5, 5])     # batch 1: commits (5.0, 0, ())
    _rollouts(rest, "th", [1, 1, 1, 1, 1])      # batch 2: the condensed tail
    _rollouts(both, "th", [5, 5, 5, 5, 5, 1, 1, 1, 1, 1])
    rows_first = q_cells.trajectory_rows(first)
    rows_rest = q_cells.trajectory_rows(rest)
    rows_both = q_cells.trajectory_rows(both)
    state = terminator._family_samples(rows_first)
    threaded = terminator._family_samples(rows_rest, prior_state=state)
    assert threaded == terminator._family_samples(rows_both)
    assert threaded["th"] == (1.0, 0, ())       # hysteresis: 5.0 → 1.0


def test_fold_composition_law_holds_for_sub_batch_states():
    """The reviewer's exact repro: a mid-batch state must carry NO
    materialized prior, or the first boundary would hysteresis-gate the
    commit against the warmup live mean instead of committing it
    unconditionally — silently diverging from one-shot replay (the
    determinism wall). Warmup states hold current_prior=None; the live
    mean is a read-face projection only."""
    one_shot = terminator._fold_family_prior([1, 2, 3, 4, 5])
    assert one_shot == (3.0, 0, ())
    mid = terminator._fold_family_prior([1, 2, 3, 4])
    assert mid[0] is None                       # warmup: nothing committed
    assert terminator._fold_family_prior([5], mid) == one_shot


def test_sub_batch_threading_equals_one_shot_through_the_public_face(
        tmp_path):
    """Streaming composition across a MID-BATCH partition: the state
    from the first four rollouts threads over the remaining six and
    equals the one-shot fold over all ten (the state summarizes
    strictly preceding rows; the fold input is the tail only)."""
    first = tmp_path / "first"
    rest = tmp_path / "rest"
    both = tmp_path / "both"
    _rollouts(first, "sb", [5, 5, 5, 5])        # MID-batch cut (4 of 5)
    _rollouts(rest, "sb", [2, 1, 1, 1, 1, 1])   # the un-condensed tail
    _rollouts(both, "sb", [5, 5, 5, 5, 2, 1, 1, 1, 1, 1])
    rows_first = q_cells.trajectory_rows(first)
    rows_rest = q_cells.trajectory_rows(rest)
    rows_both = q_cells.trajectory_rows(both)
    state = terminator._family_samples(rows_first)
    assert state["sb"] == (None, 4, (5, 5, 5, 5))   # no materialized prior
    threaded = terminator._family_samples(rows_rest, prior_state=state)
    assert threaded == terminator._family_samples(rows_both)
    assert threaded["sb"] == (1.0, 0, ())
    assert terminator.family_dispatch_priors(rows_both)["sb"] \
        == pytest.approx(1.0)
