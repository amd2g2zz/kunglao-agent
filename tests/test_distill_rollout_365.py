# -*- coding: utf-8 -*-
"""tests/test_distill_rollout_365.py — the distill_rollout settlement
(issue 365, ruling 3: distillation IS a rollout).

Schema distill-rollout/1 rows ride the consolidated settlement family;
the `distill_rollout` word is EMIT_ACTIONS-registered; the graded bands
are consumed+helped 0.5-1.0 / neutral 0.1-0.5 / never 0.01 / adverse 0;
adverse is evidence-gated; reward history folds into strategy priors.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import distill_rollout as dr  # noqa: E402


class TestEmitRegistration:
    def test_word_registered_sorted_unique(self):
        import event_taxonomy as et
        assert "distill_rollout" in et.EMIT_ACTIONS
        assert et.EMIT_ACTIONS == sorted(set(et.EMIT_ACTIONS))

    def test_row_schema_constant(self):
        assert dr.ROW_SCHEMA == "distill-rollout/1"


class TestAttemptRows:
    def test_admitted_attempt_row(self, tmp_path):
        row = dr.record_attempt(
            tmp_path, item_id="D-x", strategy="self", score=0.8,
            product="runs/episodes/episode-D-x.md")
        assert row["reward"] == 1.0  # an admitted product is the act's +1
        rows = [r for r in cl.read(tmp_path, "settlement")
                if r.get("schema") == dr.ROW_SCHEMA]
        assert len(rows) == 1
        assert rows[0]["item"] == "D-x"
        assert rows[0]["strategy"] == "self"
        assert rows[0]["score"] == pytest.approx(0.8)
        assert rows[0]["ts"]

    def test_abandoned_attempt_row_keeps_reason(self, tmp_path):
        row = dr.record_attempt(
            tmp_path, item_id="D-y", strategy="hybrid", score=0.3,
            product=None, reason="below-threshold 0.3 < 0.6")
        assert row["reward"] == dr.ABANDON_REWARD
        assert row["product"] == "abandoned"
        assert "below-threshold" in row["reason"]
        assert row["reward"] == pytest.approx(0.01)

    def test_row_refuses_scoreless_attempt(self, tmp_path):
        with pytest.raises(ValueError):
            dr.record_attempt(tmp_path, item_id="D-z", strategy="self",
                              score=None, product=None)


class TestRewardBands:
    def test_consumed_helped_band(self):
        lo = dr.settle_band(consumed=True, helped=True, adverse=False,
                            strength=0.0)
        hi = dr.settle_band(consumed=True, helped=True, adverse=False,
                            strength=1.0)
        assert lo["band"] == "consumed+helped"
        assert 0.5 <= lo["reward"] <= 1.0
        assert 0.5 <= hi["reward"] <= 1.0
        assert hi["reward"] == pytest.approx(1.0)

    def test_consumed_neutral_band(self):
        lo = dr.settle_band(consumed=True, helped=False, adverse=False,
                            strength=0.0)
        hi = dr.settle_band(consumed=True, helped=False, adverse=False,
                            strength=1.0)
        assert lo["band"] == "consumed-neutral"
        assert lo["reward"] == pytest.approx(0.1)
        assert hi["reward"] == pytest.approx(0.5)

    def test_never_consumed_band_is_flat(self):
        out = dr.settle_band(consumed=False, helped=False, adverse=False,
                             strength=0.0)
        assert out["band"] == "never-consumed"
        assert out["reward"] == pytest.approx(0.01)

    def test_adverse_is_zero_and_evidence_gated(self):
        out = dr.settle_band(consumed=True, helped=False, adverse=True,
                             strength=0.0,
                             detour_evidence="runs/detour-D-x.md")
        assert out["band"] == "adverse"
        assert out["reward"] == 0.0
        with pytest.raises(dr.SettlementRefused):
            dr.settle_band(consumed=True, helped=False, adverse=True,
                           strength=0.0, detour_evidence="")

    def test_strength_out_of_range_refused(self):
        with pytest.raises(dr.SettlementRefused):
            dr.settle_band(consumed=True, helped=True, adverse=False,
                           strength=1.5)

    def test_settlement_row_lands_in_ledger(self, tmp_path):
        out = dr.record_settlement(
            tmp_path, item_id="D-x", consumed=True, helped=True,
            adverse=False, strength=1.0,
            detour_evidence=None)
        assert out["reward"] == pytest.approx(1.0)
        rows = [r for r in cl.read(tmp_path, "settlement")
                if r.get("schema") == dr.ROW_SCHEMA]
        assert rows[-1]["kind"] == "settlement"
        assert rows[-1]["band"] == "consumed+helped"


class TestStrategyPriors:
    def test_reward_history_folds_by_strategy(self, tmp_path):
        dr.record_attempt(tmp_path, item_id="D-a", strategy="self",
                          score=0.9, product="runs/episodes/e1.md")
        dr.record_attempt(tmp_path, item_id="D-b", strategy="self",
                          score=0.2, product=None, reason="low")
        dr.record_attempt(tmp_path, item_id="D-c", strategy="hybrid",
                          score=0.7, product="runs/episodes/e2.md")
        priors = dr.strategy_priors(tmp_path)
        assert priors["self"]["n"] == 2
        assert priors["self"]["mean_reward"] == pytest.approx(
            (1.0 + 0.01) / 2)
        assert priors["hybrid"]["n"] == 1
        assert priors["hybrid"]["mean_reward"] == pytest.approx(1.0)
