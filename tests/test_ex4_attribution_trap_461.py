# -*- coding: utf-8 -*-
"""tests/test_ex4_attribution_trap_461.py — EX-4 trap trajectory
determinism pin (issue 461 Phase 1: attribution-in-state data
production for the Phase-2 termination estimator).

EX-4 replays the declared-synthetic five-step trap trajectory
(frida-detected -> unidbg-env-error -> static-tool-limit ->
encrypted-layer -> breakthrough-at-decryptor) through the REAL
obstacle record + state signature faces. Pins:
  - exactly one obstacle row per failing step, over REGISTERED
    method-family tokens (the production Q-key vocabulary);
  - no obstacle row on the breakthrough step;
  - the ob= signature segment moves at every failing step (the
    cause-bearing state the Phase-2 estimator conditions on);
  - byte-identical result document across replays (fixed ts values).

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
FIXTURES = ROOT / "tests" / "fixtures" / "experiments"
sys.path.insert(0, str(FIXTURES))

import state_signature as ssig  # noqa: E402
_ex4 = pytest.importorskip(  # noqa: E402
    "ex4_attribution_trap",
    reason="the ex4 experiment module is not shipped in this repo state "
           "(owner review 2026-10-10, issue #629)")
TRAJECTORY = _ex4.TRAJECTORY
replay = _ex4.replay

EXPECTED_SEQUENCE = [
    ("detection_trigger", "dynamic-trace"),
    ("missing_env_entry", "replay-harness-verification"),
    ("tool_limit", "static-decompile"),
    ("encryption_layer", "obfuscation-peeling"),
]


def test_trajectory_declares_five_steps():
    assert len(TRAJECTORY) == 5
    assert [s["family"] for s in TRAJECTORY] == [
        "dynamic-trace", "replay-harness-verification",
        "static-decompile", "obfuscation-peeling",
        "crypto-core-identification"]


def test_expected_obstacle_sequence(tmp_path):
    doc = replay(tmp_path)
    got = [(r["kind"], r["method_family"])
           for r in doc["obstacles"]]
    assert got == EXPECTED_SEQUENCE


def test_breakthrough_records_no_obstacle(tmp_path):
    doc = replay(tmp_path)
    assert len(doc["obstacles"]) == 4
    assert doc["steps"][-1]["family"] == "crypto-core-identification"
    assert doc["steps"][-1]["outcome"] == "success"


def test_signature_moves_at_every_failing_step(tmp_path):
    doc = replay(tmp_path)
    sigs = [s["signature"] for s in doc["steps"]]
    assert len(set(sigs)) == 5  # every step distinct

    def ob(sig: str) -> str:
        # the ob segment is delimited by the reserved sd tail (the
        # kind-count pattern carries internal pipes)
        return sig.split("|ob=")[1].split("|sd=")[0]

    # the breakthrough step adds NO obstacle: its ob segment equals
    # the post-encrypted step's (the registry did not grow) — the
    # breakthrough moves the state by landing evidence, not by
    # attribution
    assert ob(sigs[4]) == ob(sigs[3])


def test_signature_evolution_cause_bearing(tmp_path):
    """Each failure's ob segment accumulates the attributed kind —
    the state never loses a dead-end attribution (snapshots are taken
    AFTER each step's action; the segment is delimited by the pf dim
    and the sd tail because the kind-count pattern carries internal
    pipes)."""
    doc = replay(tmp_path)

    def ob(sig: str) -> str:
        tail = sig.split("|ob=")[1]
        return tail.split("|pf=")[0].split("|sd=")[0]

    obs = [ob(s["signature"]) for s in doc["steps"]]
    assert obs[0] == "detection_trigger=1"
    assert obs[1] == "detection_trigger=1|missing_env_entry=1"
    assert obs[2] == ("detection_trigger=1|missing_env_entry=1"
                      "|tool_limit=1")
    assert obs[3] == ("detection_trigger=1|encryption_layer=1"
                      "|missing_env_entry=1|tool_limit=1")
    # the breakthrough adds no attribution — the inventory freezes
    assert obs[4] == obs[3]


def test_replay_matches_live_signature_face(tmp_path):
    """The recorded signatures are the REAL face's output, not
    synthesized strings: re-deriving after the final step matches."""
    doc = replay(tmp_path)
    ws = Path(doc["workspace"])
    assert ssig.signature_str(ssig.snapshot(ws)) == doc["steps"][-1][
        "signature"]


def test_determinism(tmp_path):
    import json
    a = replay(tmp_path / "a")
    b = replay(tmp_path / "b")
    # the workspace path is the only machine-local field; everything
    # content-bearing must be byte-identical (fixed ts, sorted order)
    for doc in (a, b):
        doc.pop("workspace", None)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
