#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_commit_semantics_pins_818.py — #818 climb segment 4J.

Behavior pins for scripts/rlvr/commit_semantics.py — the #825 tune/switch/
dead-path semantics live only in fast-tier tests today, so the MEASURED leg
(-m 'not fast') records the module at import-time-only coverage. These pins
run in the measured leg and cover the module's own faces on REAL synthetic
episode pools:

  the switch/tune commit validators (every RED refusal word-for-word
  face), the dead-path reading (run accumulation, evidenced-pivot reset,
  the 9x cap), the surprise loop (verified outcome vs the value table's
  leave-self-out cell expectation, both contradiction kinds), the forced
  re-examination commit, the additive envelope enrichment (dead_path,
  reexamination, tune contract, switch attribution with the ablation and
  no-episode faces), and the four-component ablation pricing table.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import commit_semantics as cs  # noqa: E402
from rlvr import episode_pool as pool  # noqa: E402


# ------------------------------------------------------------ fixtures

def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    status: OPEN\n", encoding="utf-8")
    return ws


def _pass_verification(ws: Path, claim: str) -> None:
    p = ws / "runs" / f"verification-{claim}.md"
    p.write_text(f"# verification {claim}\n\nverdict: verified\n",
                 encoding="utf-8")


_OK = {"status": "completed", "verified": True, "evidence_ref": ""}


def _episode(claim: str, features: list[str], *, outcome: dict | None = None,
             commits: list[dict] | None = None,
             r: float | None = 1.0) -> dict:
    doc = {
        "schema": "episode/1", "id": f"E-{claim}", "claim": claim,
        "created": "2026-10-25T00:00:00Z",
        "updated": "2026-10-25T00:00:00Z",
        "context_features": list(features),
        "commits": commits or [
            {"seq": 1, "action": "persist", "class": "frida-gadget",
             "summary": "ran the class"}],
        "outcome": outcome or _OK,
        "cost": {"tokens": 0.0, "seconds": 0.0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.5},
        "reusable_fragments": [], "milestones": [],
        "attribution": "", "surprise": False,
    }
    if r is not None:
        doc["reward"] = {"completion": 1.0, "milestone_progress": 0.0,
                         "cost_term": 0.0, "r": r}
    return doc


def _seed(ws: Path, doc: dict) -> None:
    _pass_verification(ws, str(doc["claim"]))
    pool.write_episode(ws, doc)


# ------------------------------------------------------ commit validators

class TestCommitValidators:
    def test_switch_requires_the_class_and_the_attribution(self) -> None:
        ok = cs.validate_switch_commit({
            "action": "switch", "to_class": "static-arm",
            "attribution_ref": "attr-E-1"})
        assert ok["to_class"] == "static-arm"
        with pytest.raises(cs.CommitError, match="not 'switch'"):
            cs.validate_switch_commit({"action": "tune"})
        with pytest.raises(cs.CommitError, match="to_class"):
            cs.validate_switch_commit({"action": "switch",
                                       "attribution_ref": "r"})
        with pytest.raises(cs.CommitError, match="attribution_ref"):
            cs.validate_switch_commit({"action": "switch",
                                       "to_class": "static-arm"})

    def test_tune_requires_the_class_and_a_real_delta(self) -> None:
        ok = cs.validate_tune_commit({
            "action": "tune", "class": "frida-gadget",
            "param_changes": {"timeout": 30}})
        assert ok["param_changes"] == {"timeout": 30}
        ok2 = cs.validate_tune_commit({
            "action": "tune", "class": "frida-gadget",
            "tool_changes": ["rev-frida"]})
        assert ok2["tool_changes"] == ["rev-frida"]
        with pytest.raises(cs.CommitError, match="not 'tune'"):
            cs.validate_tune_commit({"action": "switch"})
        with pytest.raises(cs.CommitError, match="tune.class"):
            cs.validate_tune_commit({"action": "tune",
                                     "param_changes": {"a": 1}})
        with pytest.raises(cs.CommitError, match="bare retry"):
            cs.validate_tune_commit({"action": "tune", "class": "frida"})


# ---------------------------------------------------------- dead-path gate

class TestDeadPath:
    def test_runs_accumulate_and_pivots_reset(self) -> None:
        doc = {"commits": [
            {"action": "persist", "class": "frida"},
            {"action": "persist", "class": "frida"},
            {"action": "persist", "class": "frida"},
            {"action": "tune", "class": "frida",
             "param_changes": {"t": 1}},
            {"action": "persist", "class": "frida"},
        ]}
        reading = cs.dead_path_reading(doc)
        assert reading == {"class": "frida", "attempts": 3,
                           "cap": cs.DEAD_PATH_CAP, "over_cap": False}

    def test_switch_resets_and_classes_track_separately(self) -> None:
        doc = {"commits": [
            {"action": "persist", "class": "frida"},
            {"action": "persist", "class": "xposed"},
            {"action": "switch", "to_class": "xposed",
             "attribution_ref": "r"},
            {"action": "persist", "class": "xposed"},
        ]}
        reading = cs.dead_path_reading(doc)
        # both the class change and the evidenced switch reset the run
        assert reading["attempts"] == 1

    def test_classless_and_empty_histories_read_zero(self) -> None:
        assert cs.dead_path_reading({"commits": []})["attempts"] == 0
        assert cs.dead_path_reading({"commits": [
            {"action": "persist"}, {"action": "tune",
                                    "param_changes": {"a": 1}}]
        })["class"] is None

    def test_at_cap_is_red(self) -> None:
        doc = {"commits": [{"action": "persist", "class": "frida"}
                           for _ in range(cs.DEAD_PATH_CAP)]}
        reading = cs.dead_path_reading(doc)
        assert reading["over_cap"] is True
        with pytest.raises(cs.CommitError, match="blind re-probing is RED"):
            cs.validate_commit_history(doc)

    def test_under_cap_passes_with_the_reading(self) -> None:
        doc = {"commits": [{"action": "persist", "class": "frida"}
                           for _ in range(cs.DEAD_PATH_CAP - 1)]}
        out = cs.validate_commit_history(doc)
        assert out["over_cap"] is False
        assert out["max_run"]["attempts"] == cs.DEAD_PATH_CAP - 1


# ------------------------------------------------------------ surprise loop

class TestSurpriseLoop:
    def test_unverified_or_uncovered_cells_read_no_surprise(
            self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        doc = _episode("C-1", ["android"], outcome={**_OK})
        doc["outcome"]["verified"] = False
        assert cs.surprise_check(ws, doc) == {
            "surprise": False, "kind": None, "n": 0,
            "expected_mean_reward": None}
        verified = _episode("C-2", ["android"])
        assert cs.surprise_check(ws, verified)["surprise"] is False

    def test_completed_against_negative_expectation_surprises(
            self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["android", "packed"], r=-1.0))
        doc = _episode("C-1", ["android", "packed"])
        reading = cs.surprise_check(ws, doc)
        assert reading["surprise"] is True
        assert reading["kind"] == "completed_against_negative"
        assert reading["expected_mean_reward"] == pytest.approx(-1.0)
        assert reading["n"] == 1

    def test_failed_against_positive_expectation_surprises(
            self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["android"], r=1.0))
        doc = _episode("C-1", ["android"],
                       outcome={"status": "failed", "verified": True,
                                "evidence_ref": ""})
        reading = cs.surprise_check(ws, doc)
        assert reading["kind"] == "failed_against_positive"

    def test_the_episode_never_surprises_itself(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-1", ["android"], r=-5.0))
        doc = _episode("C-1", ["android"])
        assert cs.surprise_check(ws, doc)["surprise"] is False

    def test_non_numeric_rewards_are_skipped(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        bad = _episode("C-9", ["android"], r=None)
        bad["reward"] = {"r": "not-a-number"}
        _seed(ws, bad)
        assert cs.surprise_check(ws, _episode("C-1", ["android"]))[
            "surprise"] is False

    def test_forced_reexamination_commit(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["android"], r=-1.0))
        quiet = cs.reexamination_block(ws, _episode("C-2", ["x86"]))
        assert quiet["commit"] is None and quiet["summary"] == ""
        block = cs.reexamination_block(ws, _episode("C-1", ["android"]))
        assert block["commit"] == "verify"
        assert block["reason"] == "surprise"
        assert "forced re-examination" in block["summary"]


# ------------------------------------------------------ envelope enrichment

class TestEnrichBlock:
    def test_non_commit_phases_return_untouched(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        block = {"schema": cs.ENVELOPE_SCHEMA, "phase": "episode_start",
                 "commit": {}, "features": []}
        out = cs.enrich_block(ws, "C-1", block)
        assert out == block

    def test_commit_boundary_gains_the_dead_path_reading(
            self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-1", ["android"], commits=[
            {"seq": 1, "action": "persist", "class": "frida",
             "summary": "s"},
            {"seq": 2, "action": "persist", "class": "frida",
             "summary": "s"}]))
        block = {"schema": cs.ENVELOPE_SCHEMA, "phase": "commit_boundary",
                 "commit": {"action": "persist", "scores": {},
                            "source": "test"}, "features": []}
        out = cs.enrich_block(ws, "C-1", block)
        assert out["commit"]["dead_path"]["attempts"] == 2
        # enrichment is additive: the original block is not mutated
        assert "dead_path" not in block["commit"]

    def test_tune_gains_the_same_class_contract(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-1", ["android"], commits=[
            {"seq": 1, "action": "persist", "class": "frida-gadget",
             "summary": "s"}]))
        block = {"schema": cs.ENVELOPE_SCHEMA, "phase": "commit_boundary",
                 "commit": {"action": "tune"}, "features": []}
        out = cs.enrich_block(ws, "C-1", block)
        tune = out["commit"]["tune"]
        assert tune == {"same_class": True, "class": "frida-gadget",
                        "requires": ["param_changes|tool_changes"]}

    def test_switch_attribution_ablation_face(self, tmp_path,
                                              monkeypatch) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-1", ["android"]))
        block = {"schema": cs.ENVELOPE_SCHEMA, "phase": "commit_boundary",
                 "commit": {"action": "switch"}, "features": ["android"]}
        monkeypatch.setenv("KUNGLAO_META_ATTRIBUTION", "0")
        out = cs.enrich_block(ws, "C-1", block)
        att = out["commit"]["attribution"]
        assert att["available"] is False
        assert "KUNGLAO_META_ATTRIBUTION=0" in att["reason"]

    def test_enrichment_fail_open_on_a_broken_pool(self, tmp_path) -> None:
        ws = tmp_path / "broken"
        ws.mkdir()
        (ws / "runs").mkdir()
        block = {"schema": cs.ENVELOPE_SCHEMA, "phase": "commit_boundary",
                 "commit": {"action": "persist"}, "features": []}
        out = cs.enrich_block(ws, "C-1", block)
        assert out["commit"] == {"action": "persist"}  # untouched


# --------------------------------------------------------- ablation pricing

class TestAblationPricing:
    def test_price_table_covers_the_four_components(self, tmp_path,
                                                    monkeypatch) -> None:
        for name in ("KUNGLAO_META_ATTRIBUTION", "KUNGLAO_META_PLAYBOOK",
                     "KUNGLAO_META_VALUE_TABLE", "KUNGLAO_META_RETRIEVAL"):
            monkeypatch.delenv(name, raising=False)
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["android", "packed"], r=-1.0))
        rows = cs.price_ablations(ws, features=["android", "packed"],
                                  phase="commit_boundary", claim="C-1")
        assert set(rows) == {"playbook", "retrieval", "value_table",
                             "attribution"}
        assert "playbook" in rows["playbook"]["price"]
        assert "case(s) leave the context"
        assert rows["value_table"]["on"]["source"]
        assert "manual attribution_ref" in rows["attribution"]["price"]

    def test_playbook_price_off_reads_zero(self, tmp_path) -> None:
        ws = _mk_ws(tmp_path)
        assert cs._playbook_price(ws, ["android"], on=False) == {
            "groups": 0}

    def test_retrieval_price_respects_the_knob_floor(self, tmp_path,
                                                     monkeypatch) -> None:
        ws = _mk_ws(tmp_path)
        _seed(ws, _episode("C-9", ["android"],
                           r=1.0))  # utility 0.5 in the fixture
        monkeypatch.setenv("KUNGLAO_META_MIN_UTILITY", "0.99")
        assert cs._retrieval_price(ws, ["android"], "commit_boundary",
                                   on=True)["cases"] == []
        monkeypatch.setenv("KUNGLAO_META_MIN_UTILITY", "0.1")
        cases = cs._retrieval_price(ws, ["android"], "commit_boundary",
                                    on=True)["cases"]
        assert cases == ["C-9"]
