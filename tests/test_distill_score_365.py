# -*- coding: utf-8 -*-
"""tests/test_distill_score_365.py — the 0-1 scoring face (issue 365).

Four weighted dimensions (generality 0.3 / self-inspiring 0.25 /
methodology-shape 0.25 / novelty 0.2): mechanical parts computed, the
model-judged part rides an injected assessor, and EVERY dimension is
recorded with its assessor identity — never a bare total. Below threshold
= abandon.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import distill_schema as ds  # noqa: E402,F401 — re-exported for the rubric
from rlvr import distill_score as sc  # noqa: E402


def _content(rules=1, algebra=1, pseudo=1, case_specific=False):
    """A methodology skeleton. case_specific=True stuffs every rule with
    case tokens (claim ids / hex digests / artifact paths)."""
    def rule(i):
        if case_specific:
            return f"on claim C-{i} dump sha256 into runs/dump-{i}.json"
        return "repack the gadget before attach, then verify by replay"
    return {
        "branch_table": [rule(i) for i in range(rules)],
        "verdict_algebra": [f"pass := rule {i} replays clean"
                            for i in range(algebra)],
        "pseudocode_groups": [f"step_{i}()" for i in range(pseudo)],
    }


def _block(content=None, **over) -> dict:
    blk = {
        "schema": "distill-item/1",
        "source_strategy": "self",
        "source_refs": ["notes/n1.md"],
        "collection_ts": "2026-10-27T00:00:00Z",
        "content": content if content is not None else _content(),
        "scoring": {"generality": 0.0, "self_inspiring": 0.0,
                    "methodology": 0.0, "novelty": 0.0, "total": 0.0,
                    "assessor": "pending"},
        "epistemic_class": "evidence-derived",
        "lineage": {"supersedes": "", "superseded_by": ""},
        "optimization_rounds": 0,
    }
    blk.update(over)
    return blk


def _assessor(general: float = 1.0, inspiring: float = 1.0):
    """A stub dispatch assessor: returns the model-judged dims."""
    def judge(item_block, rubric):
        assert rubric, "the assessor receives the rubric"
        return {"generality": general, "self_inspiring": inspiring}
    return judge


class TestWeights:
    def test_weights_match_the_issue(self):
        assert sc.W_GENERALITY == 0.3
        assert sc.W_SELF_INSPIRING == 0.25
        assert sc.W_METHODOLOGY == 0.25
        assert sc.W_NOVELTY == 0.2
        assert sc.W_GENERALITY + sc.W_SELF_INSPIRING \
            + sc.W_METHODOLOGY + sc.W_NOVELTY == pytest.approx(1.0)


class TestDimensionExtremes:
    def test_all_max_scores_one_with_assessor(self):
        item = _block(_content(rules=4, algebra=4, pseudo=2))
        result = sc.score_item(item, known_corpus=[], assessor=_assessor())
        assert result["generality"] == pytest.approx(1.0)
        assert result["self_inspiring"] == pytest.approx(1.0)
        assert result["methodology"] == pytest.approx(1.0)
        assert result["novelty"] == pytest.approx(1.0)
        assert result["total"] == pytest.approx(1.0)
        assert result["admitted"] is True

    def test_case_specific_and_empty_scores_floor(self):
        item = _block(_content(rules=3, case_specific=True,
                               algebra=0, pseudo=0))
        result = sc.score_item(item, known_corpus=[],
                               assessor=_assessor(general=0.0,
                                                  inspiring=0.0))
        assert result["generality"] == 0.0
        assert result["self_inspiring"] == 0.0
        assert result["methodology"] == pytest.approx(0.5)
        assert result["novelty"] == pytest.approx(1.0)
        assert result["total"] == pytest.approx(0.325)
        assert result["admitted"] is False

    def test_per_dimension_always_recorded(self):
        result = sc.score_item(_block(), known_corpus=[])
        for dim in ("generality", "self_inspiring", "methodology",
                    "novelty", "total"):
            assert dim in result
        assert result["assessor"]  # an identity, never blank


class TestNoveltyRecallDelta:
    def test_duplicate_of_known_ref_scores_zero(self):
        frag = "repack the gadget before attach, then verify by replay"
        corpus = [{"reusable_fragments": [frag],
                   "context_features": ["android"]}]
        result = sc.score_item(_block(_content()), known_corpus=corpus)
        assert result["novelty"] == 0.0

    def test_partial_overlap_lands_between(self):
        corpus = [
            {"reusable_fragments": [
                "repack the gadget before attach, then verify by replay"],
             "context_features": []},
            {"reusable_fragments": [
                "wholly unrelated guidance about ios kernels"],
             "context_features": []}]
        result = sc.score_item(_block(_content()), known_corpus=corpus)
        assert 0.0 < result["novelty"] < 1.0


class TestAssessorContract:
    def test_assessor_receives_rubric_and_sets_dims(self):
        seen = {}
        def judge(block, rubric):
            seen["rubric"] = rubric
            return {"generality": 0.5, "self_inspiring": 0.4}
        result = sc.score_item(_block(), known_corpus=[], assessor=judge)
        assert "generality" in seen["rubric"]
        assert "self_inspiring" in seen["rubric"]
        assert result["self_inspiring"] == pytest.approx(0.4)
        assert result["assessor"] == "assessor-injected"

    def test_mechanical_proxy_fallback_is_labeled(self):
        result = sc.score_item(_block(), known_corpus=[],
                               assessor=None)
        assert result["assessor"] == "mechanical-proxy"

    def test_assessor_malformed_judgment_is_refused(self):
        def judge(block, rubric):
            return {"generality": 2.0}  # out of range
        with pytest.raises(sc.ScoreError):
            sc.score_item(_block(), known_corpus=[], assessor=judge)


class TestThresholdGate:
    def test_below_threshold_abandons(self):
        item = _block(_content(rules=1, algebra=0, pseudo=0,
                               case_specific=True))
        result = sc.score_item(item, known_corpus=[],
                               assessor=_assessor(0.0, 0.0))
        assert result["admitted"] is False
        assert result["reason"]
        assert result["reason"].startswith("below-threshold")

    def test_threshold_constant_is_documented(self):
        assert 0.0 < sc.SCORE_THRESHOLD < 1.0
