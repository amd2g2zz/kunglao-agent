# -*- coding: utf-8 -*-
"""tests/test_ex6_option_death_461.py — EX-6: the option-death MC
replay A/B on the owner's five-step trap trajectory (issue 461 Phase 2
acceptance: attribution-in-state + learned termination vs decay-only
vs the cause-free control).

Pins:
  - determinism: the replay document is byte-identical across reruns;
  - expectations: arm B (attribution + termination) reaches the
    breakthrough family at least as often as arm A (decay-only) with
    no more wasted acts; the four trap families' cells cross the
    threshold under B; arm C (cause-free: termination consulted,
    attribution skipped) holds ZERO dead cells and tracks A exactly
    (the negative control — cause-free failures never terminate);
    crypto-core-identification is never dead in any arm; the learning
    halves show the posteriors crossing during the run.

The experiment itself is DECLARED SYNTHETIC (the EX-4 truth table).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load_ex6():
    spec = importlib.util.spec_from_file_location(
        "ex6_option_death", ROOT / "tests" / "fixtures" / "experiments"
        / "ex6_option_death.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TRAP_CELLS = {
    ("detection_trigger", "dynamic-trace"),
    ("missing_env_entry", "replay-harness-verification"),
    ("tool_limit", "static-decompile"),
    ("encryption_layer", "obfuscation-peeling"),
}
BREAKTHROUGH = "crypto-core-identification"


def _run():
    ex6 = _load_ex6()
    return ex6.replay()


class TestEx6Determinism:
    def test_replay_document_byte_identical_across_reruns(self):
        d1 = _run()
        d2 = _run()
        assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)

    def test_no_machine_local_paths_in_document(self):
        doc = _run()
        text = json.dumps(doc)
        assert "/tmp" not in text and "var/folders" not in text


class TestEx6Expectations:
    def test_arm_b_terminates_the_four_trap_families(self):
        doc = _run()
        dead = {(c["kind"], c["family"]) for c in doc["arms"]["B"]["report"]["cells"] if c["dead"]}
        assert dead == TRAP_CELLS, f"arm B dead cells {dead} != the four trap pairs"

    def test_arm_c_cause_free_control_zero_deaths(self):
        doc = _run()
        rep_c = doc["arms"]["C"]["report"]
        assert rep_c["cells"] == [], "cause-free failures must never produce death cells"
        assert all(not v["dead"] for v in doc["arms"]["C"]["verdicts_sample"].values())

    def test_arm_c_tracks_arm_a_exactly(self):
        """Zero-registry verdicts = no kwarg at all: C's episodes are
        byte-identical to A's (the strongest negative control)."""
        doc = _run()
        assert doc["arms"]["C"]["episodes"] == doc["arms"]["A"]["episodes"]
        assert doc["arms"]["C"]["aggregate"] == doc["arms"]["A"]["aggregate"]

    def test_breakthrough_family_never_dead_any_arm(self):
        doc = _run()
        for arm in ("A", "B", "C"):
            for v in doc["arms"][arm]["verdicts_sample"].values():
                if v["family"] == BREAKTHROUGH:
                    assert v["dead"] is False, f"the breakthrough family died in arm {arm}"

    def test_arm_b_reaches_breakthrough_at_least_as_often(self):
        doc = _run()
        agg_a = doc["arms"]["A"]["aggregate"]
        agg_b = doc["arms"]["B"]["aggregate"]
        assert agg_b["breakthrough_rate"] >= agg_a["breakthrough_rate"]
        assert agg_b["mean_wasted_acts"] <= agg_a["mean_wasted_acts"]

    def test_learning_halves_show_the_crossing(self):
        doc = _run()
        halves = doc["arms"]["B"]["halves"]
        assert halves["second"]["breakthrough_rate"] >= halves["first"]["breakthrough_rate"]
