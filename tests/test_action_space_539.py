# -*- coding: utf-8 -*-
"""Issue #539 WS1 — the v2 action envelope + the 4-dim arm key.

The external-SMDP action tuple rides the dispatch envelope: action_type
(incl. the distill/recall meta-actions), context_recipe,
verification_mode. v1 envelopes stay first-class (back-fill defaults,
never reject). The q-cell rows dual-write the derived arm key
(family|recipe|verif|tier) — recording-only this PR; the keyed
consumption switch lands with the cross-task store (WS2).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import lib_kunglao  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402


# ---- the envelope face -----------------------------------------------------

def test_v2_envelope_parses_and_v1_backfills():
    v2 = ('{"kunglao_dispatch": {"version": 2, "claim": "C-007", '
          '"tier": 1, "tools": ["grep"], "action_type": "verify", '
          '"context_recipe": "full_recall", '
          '"verification_mode": "oracle_case"}}')
    rc, tools, claim, meta = lib_kunglao.parse_dispatch_json(v2)
    assert rc == 1 and claim == "C-007" and tools == ["grep"]
    v2f = lib_kunglao.envelope_v2_defaults(meta)
    assert v2f["action_type"] == "verify"
    assert v2f["context_recipe"] == "full_recall"
    assert v2f["verification_mode"] == "oracle_case"

    v1 = ('{"kunglao_dispatch": {"version": 1, "claim": "C-003", '
          '"tier": 2, "tools": ["strings"]}}')
    rc1, _, claim1, meta1 = lib_kunglao.parse_dispatch_json(v1)
    assert rc1 == 2 and claim1 == "C-003"
    back = lib_kunglao.envelope_v2_defaults(meta1)
    assert back["action_type"] == "dispatch"       # the back-fill defaults
    assert back["context_recipe"] == "facts_snapshot"
    assert back["verification_mode"] == "none"


def test_action_type_vocabulary_is_the_smdp_set():
    assert "distill-online" in lib_kunglao.ACTION_TYPES
    assert "recall-history" in lib_kunglao.ACTION_TYPES
    assert "stop" in lib_kunglao.ACTION_TYPES


# ---- the arm key -----------------------------------------------------------

def test_arm_key_is_4dim_and_tier_buckets():
    assert qc.arm_key("strings-first", "facts_snapshot", "none", 1) == \
        "strings-first|facts_snapshot|none|1"
    assert qc.arm_key("strings-first", "facts_snapshot", "none", "2") == \
        "strings-first|facts_snapshot|none|2"
    assert qc.arm_key("strings-first", "facts_snapshot", "none", None) == \
        "strings-first|facts_snapshot|none|0"


def test_dispatch_observation_dual_writes(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    prompt = ('{"kunglao_dispatch": {"version": 2, "claim": "C-004", '
              '"tier": 1, "tools": ["grep"], "method_family": '
              '"structural-anchoring", "action_type": "dispatch", '
              '"context_recipe": "facts_anti_hints", '
              '"verification_mode": "none"}}')
    out = qc.record_dispatch_observation(
        ws, prompt, envelope_meta={"method_family": "structural-anchoring",
                                   "action_type": "dispatch",
                                   "context_recipe": "facts_anti_hints",
                                   "verification_mode": "none",
                                   "tier": 1}, claim="C-004")
    assert out["appended"], out
    row = qc.JSONLQStore(str(ws)).observations()[-1]
    assert row["arm_key"] == \
        "structural-anchoring|facts_anti_hints|none|1"
    assert row["action_type"] == "dispatch"
    assert row["method_family"] == "structural-anchoring"  # legacy intact
