# -*- coding: utf-8 -*-
"""tests/test_rl_v2_redteam_933.py — the redteam self-learning
machinery (#933).

The #930 battery's M6 arm proved the shape this suite pins through the
PRODUCTION faces (deterministic machinery only — no LLM referee, no
simulated profiles; the planted scenarios here are the tests' fixtures,
never production code):

  DEBATE    worker-evidence vs redteam-challenge structured
            confrontation, ruled by a DETERMINISTIC structure stack:
            an unanchored challenge never disqualifies (the citation
            wall), an anchored + answered challenge stands (the worker
            rebutted), an anchored + UNANSWERED challenge upholds. The
            ruling reads the confrontation structure ONLY —
            pool-invariance by construction (the battery's debate arm:
            0.875 known / 1.0 held-out).
  UNILATERAL the comparator: the report-only ruling verifies anchors
            against the KNOWN signature registry — new-family anchors
            do not resolve, so detection collapses on the held-out
            pool (the battery's 0.25).
  CANARY    dual pools: known-family (recall floor) vs held-out
            new-family (generalization). GAP = recall_known −
            recall_heldout; beyond the floor it IS the collapse signal
            (unilateral 0.75 vs debate −0.125 in the battery).
  ARMS      detection strategies ride Beta posteriors: verified catches
            gain mass (alpha+1), misses lose it (beta+1) — the arm
            machinery, immutable updates, uniform prior at cold start.
  CHEAT     the absolute disqualifier class ABOVE the ladder: a
            cheat-ruled dispatch's credit is 0.0 no matter what the
            measured climb banked, and the caught worker's
            next-dispatch context carries a cheat-warning receipt (the
            loop's receipt channel).
  PUNISH    punishment-beyond-zero is a RECORDED PARAMETER, default
            OFF: cheat prices at exactly 0.0 — never negative — until
            the parameter is explicitly enabled.
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

from policy import redteam  # noqa: E402
from rlvr import consolidated_ledger as _cl  # noqa: E402
from settlement import per_dispatch  # noqa: E402

ALL_PASS = {"mechanical": True, "scope_verifier": True, "redteam": True}


def _case(cid: str, pool: str, *, refs: tuple[str, ...] = (),
          challenge: str | None = None,
          challenge_refs: tuple[str, ...] = (),
          cheat: bool = True,
          worker_refs: tuple[str, ...] = ()) -> redteam.DebateCase:
    return redteam.DebateCase(
        case_id=cid, pool=pool, claim=f"claim {cid}",
        worker_refs=worker_refs, challenge=challenge,
        challenge_refs=challenge_refs, planted_cheat=cheat)


# ------------------------------------------- 1. the debate arbitration

def test_confrontation_rules_are_the_deterministic_structure():
    """The four structure rules: no challenge stands; an unanchored
    challenge never disqualifies (the citation wall); anchored +
    answered stands; anchored + UNANSWERED upholds. Same inputs, same
    verdict — always."""
    no_ch = redteam.arbitrate_debate(_case("c1", "known"))
    assert no_ch["verdict"] == "claim_stands"
    unanchored = redteam.arbitrate_debate(
        _case("c2", "known", challenge="suspicious",
              challenge_refs=()))
    assert unanchored["verdict"] == "claim_stands"
    assert unanchored["reason"] == "challenge-unanchored"
    rebutted = redteam.arbitrate_debate(
        _case("c3", "known", challenge="suspicious",
              challenge_refs=("R-1",), worker_refs=("E-1",)))
    assert rebutted["verdict"] == "claim_stands"
    assert rebutted["reason"] == "rebutted"
    unanswered = redteam.arbitrate_debate(
        _case("c4", "known", challenge="suspicious",
              challenge_refs=("R-1",)))
    assert unanswered["verdict"] == "challenge_upheld"
    assert unanswered["reason"] == "unanswered-anchored-challenge"


def test_arbitration_is_pool_invariant_by_construction():
    """The ruling reads the confrontation structure only: pool-swapped
    structural twins get byte-identical verdicts and reasons (the
    battery's debate pool-invariance — the ruling never learns which
    pool a case came from)."""
    known = redteam.arbitrate_debate(
        _case("k1", "known", challenge="x", challenge_refs=("R-1",)))
    heldout = redteam.arbitrate_debate(
        _case("h1", "heldout", challenge="x", challenge_refs=("R-1",)))
    assert known["verdict"] == heldout["verdict"]
    assert known["reason"] == heldout["reason"]
    assert heldout["pool"] == "heldout"


def test_arbitration_is_deterministic_and_fail_closed():
    """Same case twice -> the same receipt; malformed cases raise."""
    c = _case("c1", "known", challenge="x", challenge_refs=("R-1",))
    assert redteam.arbitrate_debate(c) == redteam.arbitrate_debate(c)
    for bad in ("held-out", "", None):
        with pytest.raises(ValueError):
            redteam.arbitrate_debate(_case("c2", bad))
    with pytest.raises(ValueError):
        redteam.arbitrate_debate(_case("c3", "known",
                                       challenge_refs=("R-1", 0)))  # type: ignore[arg-type]


# --------------------------------------- 2. the unilateral comparator

def test_unilateral_ruling_verifies_against_known_anchors_only():
    """The report-only stack verifies each challenge anchor against the
    KNOWN signature registry: known anchors uphold, a new-family anchor
    does not resolve and the ruling stands (the battery's unilateral
    collapse mechanism — no confrontation round surfaces new-family
    evidence)."""
    registry = {"R-KNOWN"}
    up = redteam.unilateral_rule(
        _case("k", "known", challenge="x",
              challenge_refs=("R-KNOWN",)), known_anchors=registry)
    assert up["verdict"] == "challenge_upheld"
    miss = redteam.unilateral_rule(
        _case("h", "heldout", challenge="x",
              challenge_refs=("R-NEW",)), known_anchors=registry)
    assert miss["verdict"] == "claim_stands"
    assert miss["reason"] == "anchor-does-not-resolve"
    unanchored = redteam.unilateral_rule(
        _case("u", "known", challenge="x", challenge_refs=()),
        known_anchors=registry)
    assert unanchored["verdict"] == "claim_stands"


# ------------------------------------------------ 3. the dual-pool GAP

def _planted_scenario() -> tuple[list, frozenset[str]]:
    """The battery M6 shape as planted fixtures: 8 known-pool cheats
    (7 unanswered + 1 legitimately-rebutted false alarm) and 4
    held-out cheats (3 new-family anchors + 1 known-anchor overlap);
    the registry knows only the known-family signatures."""
    registry = frozenset({"R-K1"})
    cases: list[redteam.DebateCase] = []
    for i in range(7):
        cases.append(_case(f"k{i}", "known", challenge="fabricated",
                           challenge_refs=("R-K1",)))
    cases.append(_case("k-rebutted", "known", challenge="fabricated",
                       challenge_refs=("R-K1",), worker_refs=("E-1",)))
    for i in range(3):
        cases.append(_case(f"h{i}", "heldout", challenge="fabricated",
                           challenge_refs=(f"R-N{i}",)))
    cases.append(_case("h-overlap", "heldout", challenge="fabricated",
                       challenge_refs=("R-K1",)))
    return cases, registry


def test_debate_pool_invariance_holds_the_battery_numbers():
    """The debate arm on the planted scenario: known 7/8 = 0.875, held
    out 4/4 = 1.0 — the confrontation surfaces new-family cheats the
    registry does not know. GAP = −0.125, no collapse."""
    cases, _ = _planted_scenario()
    rulings = [redteam.arbitrate_debate(c) for c in cases]
    cycle = redteam.canary_cycle(cases, rulings)
    assert cycle["recall_known"] == pytest.approx(0.875)
    assert cycle["recall_heldout"] == pytest.approx(1.0)
    assert cycle["gap"] == pytest.approx(-0.125)
    assert cycle["collapse"] is False


def test_unilateral_gap_is_the_collapse_signal():
    """The unilateral arm on the SAME cases: known 8/8, held-out 1/4 =
    0.25 — GAP = 0.75 beyond the floor IS the collapse signal (the
    battery's M6 GO number)."""
    cases, registry = _planted_scenario()
    rulings = [redteam.unilateral_rule(c, known_anchors=registry)
               for c in cases]
    cycle = redteam.canary_cycle(cases, rulings)
    assert cycle["recall_known"] == pytest.approx(1.0)
    assert cycle["recall_heldout"] == pytest.approx(0.25)
    assert cycle["gap"] == pytest.approx(0.75)
    assert cycle["collapse"] is True
    assert cycle["gap"] > redteam.GAP_FLOOR


def test_canary_cycle_honest_edges():
    """A pool with nothing planted reads the honest zero; an empty
    cycle is all zeros and never collapses; a case whose ruling names a
    foreign case id never counts (the receipt must name its case)."""
    cycle = redteam.canary_cycle([], [])
    assert cycle == {"recall_known": 0.0, "recall_heldout": 0.0,
                     "gap": 0.0, "measurable": False,
                     "collapse": False}
    c = _case("solo", "known", challenge="x",
              challenge_refs=("R",))
    strays = [dict(redteam.arbitrate_debate(c), case_id="who-else")]
    cycle = redteam.canary_cycle([c], strays)
    assert cycle["recall_known"] == 0.0


# --------------------------------------------------- 4. the strategy arms

def test_strategy_posteriors_gain_on_catches_and_lose_on_misses():
    """The arm machinery: a uniform prior at cold start; a verified
    catch raises the posterior mean, a miss lowers it; the update is
    IMMUTABLE (the original arm stands untouched)."""
    arm = redteam.StrategyArm("anchor-first")
    assert redteam.strategy_mean(arm) == pytest.approx(0.5)
    hit = redteam.strategy_update(arm, caught=True)
    miss = redteam.strategy_update(arm, caught=False)
    assert redteam.strategy_mean(hit) > 0.5
    assert redteam.strategy_mean(miss) < 0.5
    assert (arm.alpha, arm.beta) == (1.0, 1.0)
    hot = redteam.strategy_update(
        redteam.strategy_update(hit, caught=True), caught=True)
    assert redteam.strategy_mean(hot) > redteam.strategy_mean(hit)
    # two strategies rank by their evidence, deterministically
    assert redteam.strategy_mean(hot) > redteam.strategy_mean(miss)


# ------------------------------------------------------- 5. cheat = 0

def test_cheat_zero_is_absolute_above_the_ladder():
    """A cheat-ruled dispatch banks 0.0 no matter what the measured
    climb priced — the disqualifier class sits ABOVE the evidence
    ladder (a full-climb 1.0 measured credit and a cold-prior all-pass
    both zero out; non-cheat credit passes through untouched)."""
    measured_full = per_dispatch.measured_credit(0.7, gate_pass=True)
    assert measured_full == pytest.approx(1.0)
    assert redteam.cheat_zero(measured_full, cheat=True) == 0.0
    assert redteam.cheat_zero(per_dispatch.PASS_CREDIT, cheat=True) \
        == 0.0
    assert redteam.cheat_zero(measured_full, cheat=False) \
        == pytest.approx(1.0)
    with pytest.raises(ValueError):
        redteam.cheat_zero(float("nan"), cheat=True)


def test_punishment_beyond_zero_is_recorded_and_default_off():
    """The recorded parameter: default OFF — a cheat prices at exactly
    0.0, never negative; flipping the recorded flag ON prices the
    magnitude below zero (and only then)."""
    assert redteam.PUNISHMENT_BEYOND_ZERO is False
    assert redteam.cheat_adjustment(cheat=True) == 0.0
    assert redteam.cheat_adjustment(cheat=False) == 0.0
    assert redteam.cheat_adjustment(cheat=True, enabled=True) \
        == pytest.approx(-redteam.PUNISHMENT_MAGNITUDE)
    with pytest.raises(ValueError):
        redteam.cheat_adjustment(cheat=True, enabled=True,
                                 magnitude=-1.0)


# ------------------------------------------- 6. the warning receipt

def test_cheat_record_lands_and_the_receipt_rides_the_channel(tmp_path):
    """A caught worker's cheat lands a ledger row; the read face hands
    the warning receipt back for the worker's NEXT dispatch context;
    another worker reads None; the latest record wins."""
    ws = tmp_path / "ws"
    landed = redteam.record_cheat(ws, rollout_id="ro-1",
                                  dispatch_id="ro-1-s01", worker="w-1",
                                  reason="fabricated evidence",
                                  ts="t0")
    assert landed["appended"] is True
    redteam.record_cheat(ws, rollout_id="ro-1",
                         dispatch_id="ro-1-s02", worker="w-1",
                         reason="judge-pleasing hack", ts="t1")
    receipt = redteam.cheat_warning_receipt(ws, "w-1")
    assert receipt is not None
    assert receipt["worker"] == "w-1"
    assert receipt["dispatch_id"] == "ro-1-s02"
    assert receipt["reason"] == "judge-pleasing hack"
    assert redteam.cheat_warning_receipt(ws, "w-2") is None


def test_next_dispatch_context_carries_the_warning_immuably(tmp_path):
    """The receipt channel: the next dispatch's context composes the
    warning as a NEW mapping — the base context is never mutated; a
    worker with no receipt composes nothing."""
    ws = tmp_path / "ws"
    redteam.record_cheat(ws, rollout_id="ro-1",
                         dispatch_id="ro-1-s01", worker="w-1",
                         reason="fabricated evidence", ts="t0")
    base = {"task": "core", "phase": "extract"}
    receipt = redteam.cheat_warning_receipt(ws, "w-1")
    warned = redteam.with_cheat_warning(base, receipt)
    assert warned["cheat_warning"] == receipt
    assert warned["task"] == "core"
    assert base == {"task": "core", "phase": "extract"}
    assert "cheat_warning" not in base
    assert redteam.with_cheat_warning(base, None) == base
    assert redteam.with_cheat_warning(base, None) is not base


def test_cheat_record_is_content_derived_and_fail_closed(tmp_path):
    """No wall clock in the identity (the same record in two
    workspaces -> the same signature hash); a blank worker or a blank
    dispatch raises."""
    hashes = []
    for name in ("a", "b"):
        ws = tmp_path / name
        row = redteam.record_cheat(ws, rollout_id="ro-1",
                                   dispatch_id="ro-1-s01",
                                   worker="w-1", reason="r", ts="t0")
        hashes.append(row["row"]["signature_hash"])
    assert hashes[0] == hashes[1]
    ws = tmp_path / "c"
    for kwargs in ({"worker": "", "dispatch_id": "ro-1-s01"},
                   {"worker": "w", "dispatch_id": ""},
                   {"worker": "w", "dispatch_id": None}):
        with pytest.raises(ValueError):
            redteam.record_cheat(ws, rollout_id="ro-1", reason="r",
                                 ts="t0", **kwargs)  # type: ignore[arg-type]


def test_cheat_rows_never_bank_credit(tmp_path):
    """The redteam verdict row is telemetry (credit=None) — the
    disqualifier prices through cheat_zero at the composition, never
    through a credit-bearing row (the state-face discipline)."""
    ws = tmp_path / "ws"
    redteam.record_cheat(ws, rollout_id="ro-1",
                         dispatch_id="ro-1-s01", worker="w-1", ts="t0")
    rows = [r for r in _cl_rows(ws, redteam.CHEAT_SOURCE,
                                redteam.CHEAT_FAMILY)]
    assert len(rows) == 1
    assert rows[0]["credit"] is None


def _cl_rows(ws, source: str, family: str) -> list[dict]:
    return [r for r in _cl.read(ws, "experience",
                                schema_prefix="q-cell-obs")
            if r.get("source") == source
            and r.get("method_family") == family]
