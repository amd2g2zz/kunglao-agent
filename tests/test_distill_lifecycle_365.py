# -*- coding: utf-8 -*-
"""tests/test_distill_lifecycle_365.py — the 3-strike optimize-then-remove
ladder (issue 365, ruling 5): the P1 update policy's utility decay,
instanced in the distillation domain.

Up to MAX_OPTIMIZATION_ROUNDS re-scored rounds; a passing round re-admits;
exhaustion removes the item from the LIBRARY surfaces (the scored playbook
view skips it) while the document stays on disk and the rollout history
stays in the ledger.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rlvr.episode_pool as pool  # noqa: E402
from rlvr import distill_lifecycle as lc  # noqa: E402
from rlvr import distill_score as sc  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    return ws


def _pass(ws: Path, claim: str) -> None:
    p = ws / "runs" / f"verification-{claim}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# verification {claim}\n\nverdict: verified\n",
                 encoding="utf-8")


def _distill_block(total: float = 0.9) -> dict:
    return {
        "schema": "distill-item/1",
        "source_strategy": "self",
        "source_refs": ["notes/n1.md"],
        "collection_ts": "2026-10-27T00:00:00Z",
        "content": {"branch_table": ["repack then verify by replay"],
                    "verdict_algebra": ["pass := replay clean"],
                    "pseudocode_groups": ["step()"]},
        "scoring": {"generality": total, "self_inspiring": total,
                    "methodology": total, "novelty": total,
                    "total": total, "assessor": "assessor-dispatch/1"},
        "epistemic_class": "evidence-derived",
        "lineage": {"supersedes": "", "superseded_by": ""},
        "optimization_rounds": 0,
    }


def _land_item(ws: Path, claim: str, fragments: list[str],
               total: float = 0.9) -> dict:
    _pass(ws, claim)
    doc = {
        "schema": "episode/1",
        "id": f"E-{claim}",
        "claim": claim,
        "created": "2026-10-27T00:00:00Z",
        "updated": "2026-10-27T00:00:00Z",
        "context_features": ["android"],
        "commits": [{"seq": 1, "action": "deliver",
                     "summary": "item landed"}],
        "outcome": {"status": "completed", "verified": True,
                    "evidence_ref": f"runs/verification-{claim}.md"},
        "cost": {"tokens": 0.0, "seconds": 0.0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
        "reusable_fragments": fragments,
        "milestones": [],
        "distill": _distill_block(total),
    }
    pool.write_episode(ws, doc)
    return doc


def _low_item(ws: Path, claim: str, fragments: list[str]) -> dict:
    return _land_item(ws, claim, fragments, total=0.2)


class TestOptimizationRounds:
    def test_low_round_records_strike(self, tmp_path):
        ws = _ws(tmp_path)
        _low_item(ws, "D-low", ["trace some low guidance fragment"])
        out = lc.record_round(ws, "D-low", admitted=False,
                              reason="below-threshold 0.25")
        assert out["strikes"] == 1
        doc, _body = pool.read_episode_file(pool.episode_path(ws, "D-low"))
        assert doc["distill"]["optimization_rounds"] == 1
        assert doc["distill"]["rounds"][-1]["reason"] == \
            "below-threshold 0.25"

    def test_passing_round_readmits_and_resets(self, tmp_path):
        ws = _ws(tmp_path)
        _low_item(ws, "D-wobble", ["trace wobbling guidance fragment"])
        lc.record_round(ws, "D-wobble", admitted=False, reason="r1")
        out = lc.record_round(ws, "D-wobble", admitted=True,
                              reason="recontent passed")
        assert out["strikes"] == 0
        assert out["removed"] is False
        doc, _ = pool.read_episode_file(
            pool.episode_path(ws, "D-wobble"))
        # both rounds are on record; the strike counter is the reset face
        assert doc["distill"]["optimization_rounds"] == 2
        assert doc["distill"]["rounds"][-1]["admitted"] is True
        assert "removed" not in doc["distill"]

    def test_three_strikes_remove_from_library_surfaces(self, tmp_path):
        ws = _ws(tmp_path)
        _low_item(ws, "D-doomed", ["trace the doomed methodology note"])
        _land_item(ws, "D-keeper", ["verify the keeper methodology note"])
        for i in range(lc.MAX_OPTIMIZATION_ROUNDS):
            out = lc.record_round(ws, "D-doomed", admitted=False,
                                  reason=f"strike {i + 1}")
        assert out["removed"] is True
        doc, _ = pool.read_episode_file(pool.episode_path(ws, "D-doomed"))
        assert doc["distill"]["removed"]["strikes"] == \
            lc.MAX_OPTIMIZATION_ROUNDS
        # the file STAYS (history lives in accounts)
        assert pool.episode_path(ws, "D-doomed").is_file()
        # the library surface drops it, keeps the keeper
        view = sc.scored_playbook_view(ws)
        frags = [f for g in view for f in g["fragments"]]
        assert frags == ["verify the keeper methodology note"]

    def test_fourth_strike_refuses_item_already_removed(self, tmp_path):
        ws = _ws(tmp_path)
        _low_item(ws, "D-gone", ["trace the gone methodology note"])
        for i in range(lc.MAX_OPTIMIZATION_ROUNDS):
            lc.record_round(ws, "D-gone", admitted=False,
                            reason=f"strike {i + 1}")
        with pytest.raises(lc.LifecycleError):
            lc.record_round(ws, "D-gone", admitted=False, reason="late")

    def test_unknown_item_refused(self, tmp_path):
        ws = _ws(tmp_path)
        with pytest.raises(lc.LifecycleError):
            lc.record_round(ws, "D-absent", admitted=False, reason="x")


class TestScoredPlaybookView:
    def test_score_orders_fragments(self, tmp_path):
        ws = _ws(tmp_path)
        _land_item(ws, "D-high", ["replay the high scored guidance"], 0.9)
        _land_item(ws, "D-low2", ["trace the low scored guidance"], 0.2)
        view = sc.scored_playbook_view(ws)
        group = next(g for g in view if g["fragments"])
        assert group["fragments"][0] == "replay the high scored guidance"
        assert group["fragment_scores"]["replay the high scored guidance"] \
            == pytest.approx(0.9)

    def test_plain_episodes_still_admitted(self, tmp_path):
        ws = _ws(tmp_path)
        _pass(ws, "C-plain")
        pool.write_episode(ws, {
            "schema": "episode/1", "id": "E-C-plain", "claim": "C-plain",
            "created": "2026-10-27T00:00:00Z",
            "updated": "2026-10-27T00:00:00Z",
            "context_features": ["ios"],
            "commits": [{"seq": 1, "action": "deliver", "summary": "s"}],
            "outcome": {"status": "completed", "verified": True,
                        "evidence_ref": "runs/verification-C-plain.md"},
            "cost": {"tokens": 0.0, "seconds": 0.0},
            "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
            "reusable_fragments": ["replay the plain guidance note"],
            "milestones": [],
        })
        view = sc.scored_playbook_view(ws)
        frags = [f for g in view for f in g["fragments"]]
        assert "replay the plain guidance note" in frags

    def test_view_writes_nothing_and_is_deterministic(self, tmp_path):
        ws = _ws(tmp_path)
        _land_item(ws, "D-det", ["dump the determinism probe fragment"])
        before = {p: p.read_bytes() for p in pool.list_episodes(ws)}
        v1 = sc.scored_playbook_view(ws)
        v2 = sc.scored_playbook_view(ws)
        assert v1 == v2
        assert {p: p.read_bytes() for p in pool.list_episodes(ws)} == before
