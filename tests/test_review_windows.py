# -*- coding: utf-8 -*-
"""tests/test_review_windows.py — the three-window review + attribution
bridge (issue 861, P3 of the learning-loop live-wire program).

Every pin asserts observable behavior (the plan's testing strategy —
no mock-shape pins):

  - the three windows over a five-step fixture (one confirmed anchor,
    one deviation): index window lists the tried actions (anti-
    repetition), segment window marks the last confirmed anchor and the
    deviation, tree window replays the alive-hypothesis chain and
    reports the delta against a prior episode's belief state;
  - attribute_step: verdict, anchors (step-index + hypothesis refs) and
    a stated falsifier; a contraction-quiet step is neutral and not
    falsifiable; an unanchored conclusion refuses loudly (the P1
    validator's own rule, single-source);
  - attribute_mission: the METHOD face carries step rewards, the
    STRATEGY face carries the mission reward; the strategy attribution
    lands on the suspect segment (anchor..deviation), never on the
    preparation step; a trajectory with no citable anchor refuses;
    a trajectory with nothing falsifiable refuses;
  - land_attributions: writes two SEPARATE ledger rows (a mission gain
    never appears in the method ledger and vice versa); a failed
    mission still lands its step gains (method memory eats step
    rewards); an already-mastered family writes NOTHING (zero-write);
    re-landing is idempotent (no duplicate rows); a non-falsifiable
    attribution refuses before any write.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from rlvr import ledger  # noqa: E402
from rlvr import review_windows as rw  # noqa: E402

# ------------------------------------------------------------- fixtures

H1 = {"id": "H1", "claim": "the K-array is the standard MD5 constant set",
      "kill_test": "diff the dumped K-array against the reference table"}
H2 = {"id": "H2", "claim": "the XOR assembly order reproduces the capture",
      "kill_test": "reorder the assembly until the capture reproduces"}
H3 = {"id": "H3", "claim": "the trainer reads the key from a config file",
      "kill_test": "trace the file reads until the key buffer appears"}


def _step(**over):
    doc = {
        "task": "recover the licensing key from the tf-snake binary",
        "environment": {"type": "protected-binary", "auth_state": "local"},
        "observation": "the entry stub decrypts a constant table at 0x4010",
        "hypotheses": [dict(H1), dict(H2)],
        "action": "dump the decrypted constant table",
        "result": "the dump shows a 64-word table, first word 0x67452301",
        "conclusion": "Preparation checkpoint declared: H1 and H2 are "
                      "asserted and the probes are staged.",
        "confidence": 0.8,
        "reusable_when": ["sample carries an obfuscated constant table"],
        "used_recalled": False,
        "reward": {"value": 0.0, "source": "evidence"},
    }
    doc.update(over)
    return doc


def _trajectory():
    """Five steps: s0 quiet, s1 CONFIRMED anchor, s2/s3 quiet (the
    planted wrong-tool path), s4 the deviation that refutes H2."""
    return [
        _step(),  # s0 — preparation, decides nothing
        _step(  # s1 — the confirmed anchor
            action="run the known-answer test on the primitive head",
            result="the diff against the reference table is clean",
            conclusion="The diff is clean, so H1 survives; H2 stays "
                       "asserted for the assembly probe.",
            reward={"value": 0.4, "source": "evidence"}),
        _step(  # s2 — quiet, wrong-tool path begins
            action="reorder the assembly big-endian",
            result="the capture still mismatches",
            conclusion="H2 remains the working guess; the mismatch is "
                       "queued for the next probe.",
            reward={"value": 0.0, "source": "evidence"}),
        _step(  # s3 — quiet, the same wrong-tool attempt again
            action="reorder the assembly big-endian",
            result="the capture mismatches again",
            conclusion="H2 keeps its standing; the probe list is "
                       "extended.",
            reward={"value": 0.0, "source": "evidence"}),
        _step(  # s4 — the deviation
            hypotheses=[dict(H1), dict(H2), dict(H3)],
            action="trace the file reads around the mismatch",
            result="the key buffer appears in a config read, not the "
                   "assembly",
            conclusion="The assembly is refuted by this trace; H1 keeps "
                       "its standing, and H3 survives as the new lead.",
            reward={"value": 1.0, "source": "phi_gain"}),
    ]


def _episode(**over):
    doc = {
        "schema": "episode/1",
        "id": "mission-C-001",
        "claim": "C-001",
        "outcome": {"status": "failed", "verified": True,
                    "evidence_ref": ""},
        "reward": 0.25,
        "reward_block": {"r": 0.25},
    }
    doc.update(over)
    return doc


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    claims = {"claims": [{"id": "C-001", "status": "PROVEN",
                          "title": "packaging"}]}
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(claims), encoding="utf-8")
    return ws


# ------------------------------------------------------------- windows

class TestThreeWindows:
    def test_index_window_lists_tried_actions(self):
        w = rw.index_window(_trajectory())
        assert [r["i"] for r in w["rows"]] == [0, 1, 2, 3, 4]
        assert w["tried_actions"][0] == "dump the decrypted constant table"
        assert w["repeated"] == ["reorder the assembly big-endian"]

    def test_segment_window_marks_anchor_and_deviation(self):
        w = rw.segment_window(_trajectory())
        assert w["anchor"] == 1
        assert w["deviation"] == 4
        assert [r["i"] for r in w["rows"]] == [1, 2, 3, 4]
        assert w["rows"][0]["conclusion"].startswith("The diff is clean")

    def test_segment_window_none_without_anchor(self):
        assert rw.segment_window([_step()]) is None

    def test_tree_window_replays_alive_chain(self):
        w = rw.tree_window(_trajectory())
        assert w["chain"][0]["alive"] == ["H1", "H2"]
        assert w["chain"][4]["alive"] == ["H1", "H3"]
        assert w["alive"] == ["H1", "H3"]

    def test_tree_window_delta_against_prior(self):
        prior = ["H1", "H2"]
        w = rw.tree_window(_trajectory(), prior_alive=prior)
        assert w["delta"]["new"] == ["H3"]
        assert w["delta"]["died"] == ["H2"]
        assert w["delta"]["carried"] == ["H1"]


# ------------------------------------------------------- attribute_step

class TestAttributeStep:
    def test_gain_step_cites_anchors_and_falsifier(self):
        steps = _trajectory()
        a = rw.attribute_step(steps[1], index=1)
        assert a["verdict"] == "gain"
        assert "step-1" in a["anchors"]
        assert "H1" in a["anchors"]
        assert a["falsifiable"] is True
        assert "kill" in a["falsifier"]
        assert "H1" in a["falsifier"]

    def test_refutation_step_cites_killed_hypothesis(self):
        steps = _trajectory()
        a = rw.attribute_step(steps[4], index=4)
        assert a["verdict"] == "refutation"
        assert "H2" in a["anchors"]
        assert "step-4" in a["anchors"]
        assert a["falsifiable"] is True

    def test_quiet_step_is_neutral_and_not_falsifiable(self):
        a = rw.attribute_step(_trajectory()[0], index=0)
        assert a["verdict"] == "neutral"
        assert a["falsifiable"] is False
        assert a["falsifier"] is None

    def test_unanchored_conclusion_refuses(self):
        bad = _step(conclusion="The weather is pleasant today.")
        with pytest.raises(rw.AttributionRefused) as err:
            rw.attribute_step(bad, index=0)
        assert "references none" in str(err.value)


# ---------------------------------------------------- attribute_mission

class TestAttributeMission:
    def test_method_and_strategy_stay_separate(self):
        out = rw.attribute_mission(_trajectory(), _episode())
        m = out["method_attribution"]
        s = out["strategy_attribution"]
        assert [e["i"] for e in m] == [1, 4]
        assert m[0]["reward"] == 0.4
        assert m[1]["reward"] == 1.0
        assert m[1]["verdict"] == "refutation"
        assert all(e["falsifiable"] for e in m)
        assert s["reward"] == 0.25
        assert s["verdict"] == "refutation"
        assert s["falsifiable"] is True

    def test_strategy_lands_on_segment_not_preparation(self):
        out = rw.attribute_mission(_trajectory(), _episode())
        anchors = out["strategy_attribution"]["anchors"]
        assert "step-1" in anchors
        assert "step-4" in anchors
        assert "step-0" not in anchors

    def test_completed_mission_strategy_is_gain(self):
        out = rw.attribute_mission(
            _trajectory(), _episode(outcome={"status": "completed",
                                             "verified": True,
                                             "evidence_ref": "r"}))
        assert out["strategy_attribution"]["verdict"] == "gain"

    def test_refuses_without_citable_anchor(self):
        steps = [_step(), _step(
            action="another dump",
            conclusion="H1 remains the working guess; the probes "
                       "continue.")]
        with pytest.raises(rw.AttributionRefused) as err:
            rw.attribute_mission(steps, _episode())
        assert "anchor" in str(err.value)

    def test_refuses_when_nothing_falsifiable(self):
        quiet = [_step(), _step(
            action="another dump",
            conclusion="H1 and H2 are asserted again for the record.")]
        with pytest.raises(rw.AttributionRefused):
            rw.attribute_mission(quiet, _episode())

    def test_refuses_episode_without_reward(self):
        episode = _episode()
        del episode["reward"]
        del episode["reward_block"]
        with pytest.raises(rw.AttributionRefused) as err:
            rw.attribute_mission(_trajectory(), episode)
        assert "reward" in str(err.value)


# ----------------------------------------------------- land_attributions

class TestLandAttributions:
    def _land(self, ws, **over):
        att = rw.attribute_mission(_trajectory(), _episode())
        return rw.land_attributions(ws, att, family="tf-snake", **over)

    def test_writes_two_separate_rows(self, tmp_path):
        ws = _mk_ws(tmp_path)
        out = self._land(ws, ts="2026-10-29T00:00:00Z")
        assert out["written"] == 2
        method = ledger.fold(ws, "method/mission-C-001")
        strategy = ledger.fold(ws, "strategy/mission-C-001")
        assert method["kind"] == rw.KIND_METHOD
        assert strategy["kind"] == rw.KIND_STRATEGY
        assert [s["type"] for s in method["signals"]] == \
            ["step_gain", "step_refutation"]
        assert [s["value"] for s in method["signals"]] == [0.4, 1.0]
        # the mission reward never appears in the method ledger
        assert 0.25 not in [s["value"] for s in method["signals"]]
        assert [s["type"] for s in strategy["signals"]] == \
            ["mission_attribution"]
        assert strategy["signals"][0]["value"] == 0.25
        # no step reward rides the strategy row
        assert 0.4 not in [s["value"] for s in strategy["signals"]]
        assert 1.0 not in [s["value"] for s in strategy["signals"]]

    def test_failed_mission_still_lands_step_gains(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._land(ws, ts="2026-10-29T00:00:00Z")
        method = ledger.fold(ws, "method/mission-C-001")
        gains = [s for s in method["signals"] if s["type"] == "step_gain"]
        assert gains and gains[0]["value"] == 0.4

    def test_already_mastered_writes_nothing(self, tmp_path):
        ws = _mk_ws(tmp_path)
        pool_state = {"memory": {"tf-snake": {"mastered": True}}}
        out = self._land(ws, pool_state=pool_state,
                         ts="2026-10-29T00:00:00Z")
        assert out["written"] == 0
        assert out["reason"] == "already-mastered"
        assert ledger.read(ws) == []

    def test_relanding_is_idempotent(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._land(ws, ts="2026-10-29T00:00:00Z")
        out = self._land(ws, ts="2026-10-29T00:00:00Z")
        assert out["written"] == 0
        rows = ledger.read(ws)
        assert len([r for r in rows
                    if r["rollout_id"] == "method/mission-C-001"]) == 1
        assert len([r for r in rows
                    if r["rollout_id"] == "strategy/mission-C-001"]) == 1

    def test_non_falsifiable_refuses_before_write(self, tmp_path):
        ws = _mk_ws(tmp_path)
        att = rw.attribute_mission(_trajectory(), _episode())
        att["method_attribution"][0]["falsifiable"] = False
        with pytest.raises(rw.AttributionRefused):
            rw.land_attributions(ws, att, family="tf-snake")
        assert ledger.read(ws) == []
