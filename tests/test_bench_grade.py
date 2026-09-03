# -*- coding: utf-8 -*-
"""B5 (#823): bench_grade — L1 mechanical scoring + z_self + arm blinding.

success = every scoring PQ matched; partial_score kept for the timeout
diagnostic view (two lenses reported separately); timeout runs fail
CLOSED (experiment semantics, both arms equal); z_self reuses the A1
four-channel scan; arm identity lives only in the sealed map.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_grade as bg


def _key(pqs):
    return {"stratum": "S1", "family": "vidar", "c2": [], "mutex": [],
            "persistence": [], "injection": [], "crypto": [], "attck": [],
            "config_format": "json", "pqs": pqs}


def _pq(pid, expected, matcher="exact"):
    return {"pq_id": pid, "question": f"{pid}?", "expected": expected,
            "matcher": matcher}


def test_success_all_matched():
    key = _key([_pq("PQ1", "vidar"), _pq("PQ2", "T1071", "attck-id")])
    out = bg.grade({"PQ1": "vidar", "PQ2": "t1071"}, key)
    assert out["success"] is True
    assert out["partial_score"] == 1.0
    assert out["per_pq"] == {"PQ1": True, "PQ2": True}


def test_partial_fraction():
    key = _key([_pq("PQ1", "vidar"), _pq("PQ2", "wingo")])
    out = bg.grade({"PQ1": "vidar", "PQ2": "something-else"}, key)
    assert out["success"] is False
    assert out["partial_score"] == pytest.approx(0.5)


def test_missing_answer_counts_fail():
    key = _key([_pq("PQ1", "vidar"), _pq("PQ2", "wingo")])
    out = bg.grade({"PQ1": "vidar"}, key)
    assert out["success"] is False
    assert out["per_pq"]["PQ2"] is False


def test_timeout_fail_closed_but_partial_kept():
    key = _key([_pq("PQ1", "vidar"), _pq("PQ2", "wingo")])
    out = bg.grade({"PQ1": "vidar"}, key, outcome="timeout")
    assert out["success"] is False          # fail-closed, both arms equal
    assert out["partial_score"] == 0.5      # diagnostic lens retained
    assert out["outcome"] == "timeout"


def _mk_ws(tmp: Path, actions=(), verifies=(), extra=None):
    ws = tmp / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "facts" / "_INDEX.md").write_text(
        "F001 | PROVEN | C-001 | x\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: PROVEN\n", encoding="utf-8")
    with (ws / "runs" / "logs" / "kunglao-2026-08-28.jsonl").open(
            "w", encoding="utf-8") as f:
        for a in actions:
            f.write(json.dumps({"actor": "hook", "action": a}) + "\n")
    for i, v in enumerate(verifies):
        (ws / "runs" / f"verify-F001-{i}.json").write_text(
            json.dumps({"fact_id": "F001", "overall": v}), encoding="utf-8")
    return ws


def test_z_self_channels_trigger_independently(tmp_path):
    # extra carries BAD-EVENT counts (interventions beyond the opening
    # prompt), so 0 = clean on that channel
    clean = bg.z_self_of(_mk_ws(tmp_path / "a"), extra={"notes_due": 0, "human_turns": 0})
    assert clean == 1
    reopen = bg.z_self_of(_mk_ws(tmp_path / "b", verifies=["REJECTED", "VERIFIED"]),
                          extra={"notes_due": 0, "human_turns": 0})
    assert reopen == 0
    gate = bg.z_self_of(_mk_ws(tmp_path / "c", actions=["top1_reject"]),
                        extra={"notes_due": 0, "human_turns": 0})
    assert gate == 0
    human = bg.z_self_of(_mk_ws(tmp_path / "d"),
                         extra={"notes_due": 0, "human_turns": 2})
    assert human == 0
    notes = bg.z_self_of(_mk_ws(tmp_path / "e"),
                         extra={"notes_due": 2, "human_turns": 0})
    assert notes == 0


def test_opaque_seal_roundtrip(tmp_path):
    sealed = bg.seal({"s1": "O", "s2": "N"})
    assert len(sealed) == 2
    assert all(oid.startswith("run-") and len(oid) == 16 for oid in sealed)
    # unseal recovers the mapping
    assert bg.unseal(sealed) == {"s1": "O", "s2": "N"}


def test_grade_selfcheck_golden():
    report = bg.grade_selfcheck()
    assert report["cases"] >= 10
    assert report["failures"] == []
