# -*- coding: utf-8 -*-
"""tests/test_rl_v2_judge_933.py — the gated judge + cumulative cap
(#933).

The #930 battery proved the three properties this suite pins through
the PRODUCTION faces (the battery itself stays retired out-of-tree per
the mock-code ruling — what lands here is deterministic machinery only,
no simulated-judge profiles):

  GATE      ``is_ambiguous`` fires ONLY on measured progress ~= 0 or a
            signal conflict (the battery's escalation semantics). A
            clean step never escalates: the judge callable is never
            invoked (a raising sentinel proves the call never happens)
            and the step's delta is exactly 0.0.
  SEAM      the judge is a Callable the face owns no profile for — the
            real LLM judge plugs in later (the #922 rubric). Its output
            is HARD-CLAMPED into [-bound, +bound]; a non-finite or
            non-numeric ruling is a fabrication and raises.
  BAND      the calibration posterior: the judge's effective band
            shrinks toward neutral (0) as its modulation-vs-outcome
            agreement drops — monotone in the agreement history
            (battery M5). No history = the designed bound (the judge is
            trusted until evidence accumulates).
  CAP       the judge's cumulative injection per trajectory is capped
            at epsilon of the COMMIT-certified mechanical total (the
            battery M4 lesson: uncapped injection inflates — 9.0 raw —
            while the capped arm stays at epsilon x mechanical). The
            cap binds to the settlement path's certified aggregate via
            ``draft_commit.committed_rollout`` — read-only composition,
            the #884 settlement pins byte-unchanged.
  LEDGER    judge rows land credit=None (telemetry posture, the
            state/progress discipline) with a strict ``delta_j=``
            fingerprint parse — a poisoned row raises, never silently
            prices. Same-state re-derivation is byte-identical.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) in sys.path:
        continue
    sys.path.insert(0, str(_p))

from rlvr import q_cells  # noqa: E402
from settlement import draft_commit, judge_cap  # noqa: E402
from state import judge  # noqa: E402

ALL_PASS = {"mechanical": True, "scope_verifier": True, "redteam": True}
CONFLICT = {"mechanical": True, "scope_verifier": False, "redteam": True}


def _rec(ws, rid: str, did: str, delta: float, ts: str) -> dict:
    return judge.record_judgment(ws, rollout_id=rid, dispatch_id=did,
                                 delta=delta, escalated=True, ts=ts)


# ----------------------------------------------------------- 1. the gate

def test_clean_step_never_escalates_and_the_judge_is_never_called():
    """Progress made + agreeing signals = the mechanical base is
    trusted: the gate stays closed, the judge callable is never
    invoked, the step's delta is exactly 0.0."""

    def _sentinel(payload):
        raise AssertionError("the judge must not be called on a "
                             "non-ambiguous step")

    out = judge.judge_step(_sentinel, progress_delta=0.7,
                           signals=ALL_PASS)
    assert out["escalated"] is False
    assert out["delta"] == pytest.approx(0.0)
    assert out["raw"] is None


def test_gate_fires_on_flat_progress_and_on_signal_conflict():
    """The two escalation triggers (the battery's semantics): measured
    progress at the ambiguity floor, and a verdict conflict — the
    conflict fires even on a full climb (the layers disagree about
    what happened). No measurement (None) is NOT progress-ambiguous:
    the cold-start honestly says 'unknown', never 'flat'."""
    assert judge.is_ambiguous(0.0, ALL_PASS) is True
    assert judge.is_ambiguous(1e-9, ALL_PASS) is True
    assert judge.is_ambiguous(None, ALL_PASS) is False
    assert judge.is_ambiguous(0.7, ALL_PASS) is False
    assert judge.is_ambiguous(0.7, CONFLICT) is True
    assert judge.is_ambiguous(0.35, {"a": True, "b": False}) is True


def test_gate_is_fail_closed_on_malformed_signals_or_delta():
    """Structural garbage raises: non-bool signals, an empty signal
    map, a non-finite delta — a silently tolerated payload would let a
    fabricated escalation (or a fabricated clean bill) price."""
    with pytest.raises(ValueError):
        judge.is_ambiguous(0.7, {"mechanical": 1, "scope": True})
    with pytest.raises(ValueError):
        judge.is_ambiguous(0.7, {})
    with pytest.raises(ValueError):
        judge.is_ambiguous(float("nan"), ALL_PASS)
    with pytest.raises(ValueError):
        judge.is_ambiguous("0.7", ALL_PASS)  # type: ignore[arg-type]


# ----------------------------------------------------------- 2. the seam

def test_judge_output_is_hard_clamped_to_the_bound():
    """A bounded per-step delta: any raw magnitude clamps into
    [-bound, +bound] (the Ask-a-Strong-Judge structure — the judge
    modulates, it never prices)."""
    def _loud(payload):
        return 5.0

    def _sabotage(payload):
        return -0.5

    up = judge.judge_step(_loud, progress_delta=0.0, signals=ALL_PASS)
    assert up["escalated"] is True
    assert up["delta"] == pytest.approx(judge.DELTA_BOUND)
    assert up["raw"] == pytest.approx(5.0)
    down = judge.judge_step(_sabotage, progress_delta=0.0,
                            signals=ALL_PASS)
    assert down["delta"] == pytest.approx(-judge.DELTA_BOUND)


def test_judge_seam_receives_the_structured_payload():
    """The callable gets ONE payload mapping (progress + signals) —
    the seam the real judge plugs into later."""
    seen: list[dict] = []

    def _spy(payload):
        seen.append(payload)
        return 0.05

    judge.judge_step(_spy, progress_delta=0.0, signals=CONFLICT)
    assert len(seen) == 1
    assert seen[0]["progress_delta"] == pytest.approx(0.0)
    assert seen[0]["signals"] == CONFLICT


def test_judge_fabrication_raises():
    """A non-finite or non-numeric ruling is a fabrication — it raises,
    never silently prices."""
    with pytest.raises(ValueError):
        judge.judge_step(lambda p: float("nan"), progress_delta=0.0,
                         signals=ALL_PASS)
    with pytest.raises(ValueError):
        judge.judge_step(lambda p: float("inf"), progress_delta=0.0,
                         signals=ALL_PASS)
    with pytest.raises(ValueError):
        judge.judge_step(lambda p: "0.1", progress_delta=0.0,  # type: ignore[arg-type,return-value]
                         signals=ALL_PASS)


def test_band_parameter_binds_the_clamp_and_validates():
    """A supplied calibration band replaces the designed bound for the
    clamp (it can only SHRINK the judge's reach — a band above the
    designed bound, negative, or non-finite raises)."""
    out = judge.judge_step(lambda p: 5.0, progress_delta=0.0,
                           signals=ALL_PASS, band=0.02)
    assert out["delta"] == pytest.approx(0.02)
    assert out["bound"] == pytest.approx(0.02)
    for bad in (-0.1, judge.DELTA_BOUND * 2, float("nan")):
        with pytest.raises(ValueError):
            judge.judge_step(lambda p: 0.01, progress_delta=0.0,
                             signals=ALL_PASS, band=bad)


# ----------------------------------------------- 3. the calibration band

def test_band_shrinks_monotone_toward_neutral():
    """The calibration posterior (battery M5): the effective band is
    monotone in the agreement history — full agreement keeps (an
    ever-larger share of) the designed bound, a coin-flip judge is
    neutral (band 0), and every added disagreement shrinks it."""
    base = judge.DELTA_BOUND
    trusted = judge.effective_band([True] * 10)
    mid = judge.effective_band([True] * 6 + [False] * 4)
    worse = judge.effective_band([True] * 5 + [False] * 5)
    hostile = judge.effective_band([False] * 10)
    assert trusted > mid > worse
    assert worse == 0.0
    assert hostile == 0.0
    assert judge.effective_band([]) == pytest.approx(base)
    # more agreement monotonically re-grows the band toward the base
    assert (judge.effective_band([True] * 3)
            < judge.effective_band([True] * 30) <= base)


def test_band_validates_its_inputs():
    """Fail-closed: non-bool agreement entries, a bad base."""
    with pytest.raises(ValueError):
        judge.effective_band([True, 1])  # type: ignore[list-item]
    with pytest.raises(ValueError):
        judge.effective_band([True], base=-1.0)
    with pytest.raises(ValueError):
        judge.effective_band([True], base=judge.DELTA_BOUND * 2)


# --------------------------------------------------------- 4. the ledger

def test_judgment_rows_land_credit_free_and_round_trip(tmp_path):
    """The judge rows are telemetry (credit=None, the state-face
    discipline) carrying the delta in a strict fingerprint; the
    trajectory read sums them back exactly."""
    ws = tmp_path / "ws"
    _rec(ws, "ro-1", "ro-1-s01", 0.1, "t0")
    _rec(ws, "ro-1", "ro-1-s02", -0.05, "t1")
    _rec(ws, "ro-2", "ro-2-s01", 0.1, "t2")
    rows = judge.judgment_rows(ws, "ro-1")
    assert len(rows) == 2
    for row in rows:
        assert row["credit"] is None
        assert row["source"] == judge.SOURCE
    assert judge.trajectory_delta(ws, "ro-1") == pytest.approx(0.05)
    assert judge.trajectory_delta(ws, "ro-2") == pytest.approx(0.1)
    assert judge.trajectory_delta(ws, "ro-empty") == 0.0


def test_poisoned_judge_fingerprint_raises(tmp_path):
    """A tampered judge row (a fingerprint off the delta_j= vocabulary)
    must never silently price — the read raises (the fail-closed
    posture)."""
    ws = tmp_path / "ws"
    q_cells.append_observation(
        ws, "sig", judge.METHOD_FAMILY, credit=None,
        source=judge.SOURCE, claim="ro-1", dispatch_id="ro-1-s01",
        fingerprint="delta_j=garbage", reason=judge.REASON)
    with pytest.raises(ValueError):
        judge.trajectory_delta(ws, "ro-1")


def test_out_of_bound_judgment_refuses_to_land(tmp_path):
    """The ledger never carries an out-of-bound judge delta — the
    landing face re-enforces the clamp (the seam already clamps; a
    forged record must not resurrect the magnitude)."""
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        judge.record_judgment(ws, rollout_id="ro-1",
                              dispatch_id="ro-1-s01", delta=9.0,
                              escalated=True, ts="t0")


def test_judgment_record_is_content_derived_and_replay_identical(tmp_path):
    """No wall clock in the identity: two workspaces receiving the same
    judgment land byte-identical signature hashes (the determinism
    pin); the same call re-derivation lands the same row shape."""
    hashes = []
    for name in ("a", "b"):
        ws = tmp_path / name
        row = _rec(ws, "ro-1", "ro-1-s01", 0.1, "t0")
        hashes.append(row["row"]["signature_hash"])
    assert hashes[0] == hashes[1]
    assert hashes[0] == _rec(tmp_path / "a", "ro-1", "ro-1-s01", 0.1,
                             "t9")["row"]["signature_hash"]


# ------------------------------------------------------------- 5. the cap

def test_capped_injection_binds_to_epsilon_of_mechanical():
    """The battery M4 arithmetic as a pure face: raw injection 9.0 over
    mechanical 6.0 stays at epsilon x mechanical (0.6 at the default
    10%, 0.3 at the 5% arm) — the UNcapped arm is the 9.0 inflation the
    battery measured. The cap is load-bearing by construction."""
    assert judge_cap.JUDGE_CAP_EPSILON == pytest.approx(0.10)
    assert judge_cap.capped_injection(9.0, 6.0) == pytest.approx(0.6)
    assert judge_cap.capped_injection(9.0, 6.0, epsilon=0.05) \
        == pytest.approx(0.3)
    assert judge_cap.capped_injection(0.05, 6.0) == pytest.approx(0.05)
    assert judge_cap.capped_injection(-9.0, 6.0) == pytest.approx(-0.6)
    # no mechanical base, nothing to bind to: the judge can never mint
    # from zero
    assert judge_cap.capped_injection(9.0, 0.0) == 0.0


def test_capped_injection_validates():
    with pytest.raises(ValueError):
        judge_cap.capped_injection(float("nan"), 6.0)
    with pytest.raises(ValueError):
        judge_cap.capped_injection(1.0, 6.0, epsilon=1.5)
    with pytest.raises(ValueError):
        judge_cap.capped_injection(1.0, 6.0, epsilon=-0.1)
    with pytest.raises(ValueError):
        judge_cap.capped_injection(True, 6.0)


def _commit_two_climbs(ws) -> None:
    """A certified mechanical terminal of 3.0: two cold-prior all-pass
    dispatches (2.0 in drafts) + the completed bonus (+1.0), drafted +
    committed through the REAL settlement path (the #932 prior mode —
    no transition rows)."""
    verdicts = {"mechanical": True, "scope_verifier": True,
                "redteam": True}
    for i in (1, 2):
        draft_commit.ensure_draft(ws, "ro-1", f"ro-1-s{i:02d}", 0.1,
                                  verdicts, ts=f"t{i}")
    q_cells.append_action(ws, kind="terminate_rollout", rollout_id="ro-1",
                          target="C-1", ts="t3")
    marker = draft_commit.commit_batch(ws, "ro-1", ts="t4")
    assert marker["total_credit"] == pytest.approx(2.0)


def test_trajectory_total_caps_through_the_settlement_path(tmp_path):
    """The integration pin: the cap binds the judge injection to the
    COMMIT marker's certified mechanical terminal (drafts + terminal
    adjustment, 3.0 here), through the real draft/commit path. Raw
    injection 3.0 over mechanical 3.0 lands at the 10% ceiling (total
    3.3) — the uncapped trajectory would have carried 6.0 (the
    battery's inflation lesson)."""
    ws = tmp_path / "ws"
    _commit_two_climbs(ws)
    for i in range(1, 31):
        _rec(ws, "ro-1", f"ro-1-s{i:02d}", 0.1, f"j{i}")
    assert judge.trajectory_delta(ws, "ro-1") == pytest.approx(3.0)
    view = judge_cap.trajectory_total(ws, "ro-1")
    assert view["mechanical"] == pytest.approx(3.0)
    assert view["judge_raw"] == pytest.approx(3.0)
    assert view["judge_capped"] == pytest.approx(0.3)
    assert view["total"] == pytest.approx(3.3)
    # the epsilon arm is a recorded parameter: the 5% arm binds tighter
    assert judge_cap.trajectory_total(ws, "ro-1", epsilon=0.05)["total"] \
        == pytest.approx(3.15)


def test_trajectory_total_is_deterministic_over_the_ledger(tmp_path):
    """Same ledger state, same figures — the cap read is a pure
    function of the committed drafts + judge rows."""
    ws = tmp_path / "ws"
    _commit_two_climbs(ws)
    _rec(ws, "ro-1", "ro-1-s01", 0.1, "t5")
    first = judge_cap.trajectory_total(ws, "ro-1")
    second = judge_cap.trajectory_total(ws, "ro-1")
    assert first == second


def test_trajectory_total_refuses_an_uncommitted_rollout(tmp_path):
    """The cap binds to a CERTIFIED aggregate — a rollout with no
    commit marker has no mechanical reward to bind to, and the read
    raises rather than binding to nothing."""
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        judge_cap.trajectory_total(ws, "ro-none")
