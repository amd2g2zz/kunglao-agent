# -*- coding: utf-8 -*-
"""tests/test_ws4_expansion_546.py — the discovery-layer operator's
mechanical pins (issue #546, L3): the trigger predicate over sanctioned
faces only, feature-keyed novelty (the anti-renaming wall), the
admission score decomposition, append-only receipts, and the envelope's
new action_type."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import expansion as ex  # noqa: E402


def _lib_kunglao():
    spec = importlib.util.spec_from_file_location(
        "lib_kunglao_546", ROOT / "hooks" / "lib_kunglao.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------- the trigger

def test_trigger_needs_both_obstacles_and_a_dead_arm():
    dead = {"static-decompile": {"dead": True}}
    snap2 = {"obstacles": {"count": 2}}
    assert ex.trigger(snap2, dead) == {
        "obstacle_count": 2, "collapsed_arms": ["static-decompile"],
        "arm": "family-death"}
    # below K: no fire
    assert ex.trigger({"obstacles": {"count": 1}}, dead) is None
    # obstacles present but nothing collapsed: no fire
    assert ex.trigger(snap2, {"static-decompile": {"dead": False}}) is None
    # no obstacles at all: no fire (the empty-registry rule)
    assert ex.trigger({"obstacles": {"count": 0}}, dead) is None
    assert ex.trigger({}, dead) is None
    # malformed inputs degrade to no-fire, never raise
    assert ex.trigger(None, dead) is None
    assert ex.trigger(snap2, None) is None
    assert ex.trigger(snap2, {"weird": 7}) is None


def test_trigger_collapsed_arms_sorted_deterministically():
    death = {"b-fam": {"dead": True}, "a-fam": {"dead": True},
             "c-fam": {"dead": False}}
    doc = ex.trigger({"obstacles": {"count": 9}}, death)
    assert doc["collapsed_arms"] == ["a-fam", "b-fam"]


# ------------------------------------------------- feature-keyed novelty

def test_novelty_of_a_renamed_dead_arm_is_zero():
    """The anti-novelty-hacking wall: identical feature tokens under a
    brand-new family NAME are the same arm — novelty 0, no admission.
    (Tokens are the feature-table/1 vocabulary: lane= / ptype= / the
    nested target_kind lang= and entry=.)"""
    dead_arm = {"lane": "static", "project_type": "linux",
                "target_kind": {"language": "rust",
                                "entry_suffix": ".dll"}}
    renamed = json.loads(json.dumps(dead_arm))  # same tokens, new name
    assert ex.novelty(renamed, [dead_arm]) == 0.0


def test_novelty_scales_with_token_distance():
    dead = {"lane": "static", "project_type": "linux",
            "target_kind": {"language": "rust", "entry_suffix": ".dll"}}
    near = {"lane": "static", "project_type": "windows",
            "target_kind": {"language": "rust", "entry_suffix": ".dll"}}
    far = {"lane": "dynamic", "project_type": "wasm",
           "target_kind": {"language": "js", "entry_suffix": ".bin"}}
    n_near = ex.novelty(near, [dead])
    n_far = ex.novelty(far, [dead])
    assert 0.0 < n_near < 1.0  # shares lane= + lang= + entry=
    assert n_far == 1.0  # zero shared tokens
    # novelty is the MAX over every existing arm (nearest neighbor)
    assert ex.novelty(near, [far, dead]) == n_near
    # no existing arms: nothing shared with nothing
    assert ex.novelty(dead, []) == 1.0


# ------------------------------------------------------ admission score

def test_score_decomposition_is_attributable():
    s = ex.score(0.5, 0.25, 0.5)
    assert s["log_p_llm"] == round(-0.693147, 6)
    assert s["policy"] == 0.25
    assert s["novelty"] == 0.5
    assert s["total"] == round(s["log_p_llm"] + ex.NOVELTY_WEIGHT * 0.5
                               + 0.25, 6)
    # a zero P_LLM floors, never crashes
    assert ex.score(0.0, 0.0, 1.0)["log_p_llm"] < -27.0


def test_admit_excludes_zero_novelty_before_ranking():
    dead = {"lane": "static", "project_type": "linux",
            "target_kind": {"language": "rust", "entry_suffix": ".dll"}}
    hyps = [
        {"id": "h1", "family": "fresh-emu", "p_llm": 0.1, "policy": 0.0,
         "features": {"lane": "dynamic", "project_type": "linux",
                      "target_kind": {"language": "py",
                                      "entry_suffix": ".py"}}},
        # a renamed retry — same tokens as the dead arm, new name
        {"id": "h2", "family": "static-decompile-2", "p_llm": 0.9,
         "policy": 0.5,
         "features": json.loads(json.dumps(dead))},
        {"id": "h3", "family": "fuzz-unpack", "p_llm": 0.2, "policy": 0.1,
         "features": {"lane": "dynamic", "project_type": "windows"}},
    ]
    ranked = ex.admit(hyps, [dead])
    ids = [r["id"] for r in ranked]
    assert "h2" not in ids, "a renamed dead arm never spends the move"
    # h3 (novelty 1.0) outscores h1 (novelty ~0.857) despite the lower
    # P_LLM: log(0.2)+1.0+0.1 > log(0.1)+0.857+0.0
    assert ids == ["h3", "h1"]
    assert all(r["verdict"] == "pending" for r in ranked)
    # deterministic ties
    same = [{"id": f"h{i}", "family": f"f{i}", "p_llm": 0.5,
             "policy": 0.0,
             "features": {"project_type": f"p{i}"}} for i in range(5)]
    assert [r["id"] for r in ex.admit(same, [])] == ["h0", "h1", "h2"]


# ------------------------------------------------------------- receipts

def test_receipt_append_only_and_readable(tmp_path):
    t1 = {"obstacle_count": 3, "collapsed_arms": ["static-decompile"]}
    ranked = ex.admit([{"id": "h1", "family": "fresh-emu", "p_llm": 0.3,
                        "policy": 0.0,
                        "features": {"project_type": "wasm"}}], [])
    d1 = ex.record_receipt(tmp_path, t1, ranked,
                           [r["id"] for r in ranked])
    d2 = ex.record_receipt(tmp_path, t1, [], [])
    files = sorted((tmp_path / "runs" / "expansion").glob("E-*.json"))
    assert [f.name for f in files] == ["E-1.json", "E-2.json"]
    assert d1["schema"] == "expansion/1"
    assert d1["admitted"] == ["h1"]
    # the provenance chain: trigger -> hypotheses -> admitted
    assert d1["trigger"] == t1
    assert d1["hypotheses"][0]["id"] == "h1"
    back = ex.read_receipts(tmp_path)
    assert [doc["admitted"] for doc in back] == [["h1"], []]
    # a corrupt receipt is skipped, history stays readable
    files[0].write_text("{broken", encoding="utf-8")
    assert len(ex.read_receipts(tmp_path)) == 1


def test_no_receipts_dir_reads_empty(tmp_path):
    assert ex.read_receipts(tmp_path) == []


# ------------------------------------------------- the envelope action

def test_envelope_action_types_carry_expand():
    lib = _lib_kunglao()
    assert "expand" in lib.ACTION_TYPES
    # the v2 defaults face tolerates the new action (schema-additive)
    payload = {"dispatch_protocol_version": 2,
               "action": {"action_type": "expand",
                          "method_family": "fresh-emu",
                          "context_recipe": "minimal",
                          "verification_mode": "red_team"}}
    defaults = lib.envelope_v2_defaults(payload)
    assert defaults is not None
