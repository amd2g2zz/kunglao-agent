# -*- coding: utf-8 -*-
"""tests/test_rl_v2_spend_agg_916.py — the aggregate carries the spend Σ.

RED-first pins for #916: ``rollout_agg.aggregate`` outputs
``total_spend`` (Σ over the drafts' validated spend) alongside
``total_credit`` — from the same draft rows, each dispatch's OWN
figure. The draft wall extends to spend's ≥ 0 bound (per_dispatch
already prices spend finite ≥ 0; the aggregate wall mirrors it so a
tampered or foreign row can never fold a negative/non-finite cost into
the Σ). The terminal adjustment is CREDIT-side only (the TERMINALS
vocabulary carries no spend semantics), so ``total_spend`` is the
drafts' Σ alone — the same number under ``completed`` and
``rolled_back``. A draft without spend is structural garbage at the
wall (per_dispatch semantics: spend is a REQUIRED validated field of
every priced row), never a silent 0.0 contribution. The empty batch
stays fail-closed at the aggregate face (#884, untouched) — the honest
0.0 lives at the committed-view read face, the only legal "empty
batch" shape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from settlement import draft_commit, per_dispatch, rollout_agg  # noqa: E402

ALL_PASS = {"mechanical": True, "scope_verifier": True, "redteam": True}


def _drafts(*spends: float) -> list[dict]:
    return [per_dispatch.price_dispatch("ro-1", f"d-{i}", s, ALL_PASS)
            for i, s in enumerate(spends, start=1)]


# ------------------------------------------------------- the spend Σ

def test_total_spend_is_the_exact_sum_of_each_drafts_own_spend():
    rows = _drafts(0.2, 1.5)
    out = rollout_agg.aggregate(rows, terminal="completed",
                                terminal_bonus=0.0)
    assert out["total_spend"] == pytest.approx(0.2 + 1.5)
    # each row carries its OWN figure, never a cumulative window —
    # the Σ is over the per-dispatch spends, not a running total
    assert [r["spend"] for r in rows] == pytest.approx([0.2, 1.5])


def test_total_spend_ignores_the_terminal_side():
    rows = _drafts(0.2, 1.5)
    done = rollout_agg.aggregate(rows, terminal="completed",
                                 terminal_bonus=2.0)
    back = rollout_agg.aggregate(rows, terminal="rolled_back",
                                 terminal_bonus=2.0)
    # the terminal adjustment is credit-side only — the spend Σ is the
    # drafts' own figure under either outcome
    assert done["total_spend"] == pytest.approx(1.7)
    assert back["total_spend"] == pytest.approx(1.7)
    assert done["total_credit"] != pytest.approx(back["total_credit"])


def test_output_carries_total_credit_and_total_spend_together():
    out = rollout_agg.aggregate(_drafts(0.4), terminal="completed")
    assert "total_credit" in out
    assert "total_spend" in out


def test_spend_key_survives_alongside_the_new_total():
    # the #884 pin reads ``spend`` — the parallel total must not
    # retire it
    out = rollout_agg.aggregate(_drafts(0.4, 0.6), terminal="completed")
    assert out["spend"] == pytest.approx(out["total_spend"])


def test_total_credit_is_unchanged_by_the_spend_column():
    cheap = rollout_agg.aggregate(_drafts(0.1), terminal="completed",
                                  terminal_bonus=1.0)
    pricey = rollout_agg.aggregate(_drafts(9.9), terminal="completed",
                                   terminal_bonus=1.0)
    assert cheap["total_credit"] == pytest.approx(pricey["total_credit"])
    assert cheap["total_spend"] != pytest.approx(pricey["total_spend"])


# ------------------------------------------------------- the spend wall

def test_missing_or_none_spend_is_refused_not_silently_zero():
    # per_dispatch semantics: spend is a REQUIRED validated field of
    # every priced row — a draft without one is structural garbage at
    # the wall, never a silent 0.0 contribution
    for row in ({"schema": "settlement-draft/1", "credit": 1.0},
                {"schema": "settlement-draft/1", "credit": 1.0,
                 "spend": None}):
        with pytest.raises(ValueError, match=r"rows\[0\]\.spend"):
            rollout_agg.aggregate([row], terminal="completed")


def test_negative_spend_is_refused_by_the_wall():
    with pytest.raises(ValueError, match=r"rows\[0\]\.spend"):
        rollout_agg.aggregate(
            [{"schema": "settlement-draft/1", "credit": 1.0,
              "spend": -0.1}], terminal="completed")


def test_non_finite_spend_is_refused_by_the_wall():
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match=r"rows\[0\]\.spend"):
            rollout_agg.aggregate(
                [{"schema": "settlement-draft/1", "credit": 1.0,
                  "spend": bad}], terminal="completed")


def test_bool_spend_is_refused_by_the_wall():
    with pytest.raises(ValueError, match=r"rows\[0\]\.spend"):
        rollout_agg.aggregate(
            [{"schema": "settlement-draft/1", "credit": 1.0,
              "spend": True}], terminal="completed")


# ---------------------------------------------------------- empty batch

def test_empty_batch_stays_fail_closed_at_the_aggregate():
    # the #884 posture is untouched — a batch with no drafts settles
    # nothing; the aggregate refuses rather than fabricate
    with pytest.raises(ValueError):
        rollout_agg.aggregate([], terminal="completed")


def test_empty_batch_reads_total_spend_zero_at_the_view(tmp_path):
    # the honest empty — the committed-view read face is the only
    # legal "empty batch" shape and carries the zero total
    view = draft_commit.committed_rollout(tmp_path / "ws", "ro-1")
    assert view["committed"] is False
    assert view["total_spend"] == pytest.approx(0.0)
