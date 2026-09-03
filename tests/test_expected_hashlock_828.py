# -*- coding: utf-8 -*-
"""tests/test_expected_hashlock_828.py - #828: verify expected hash lock.

Incident: maker runs verify -> L1 FAIL -> rewrites fact frontmatter `expected`
to the observed output -> re-runs -> PASS (F008: 8s after FAIL; F017: 7
REJECTED iterations then hand-aligned). F3 covers tautology only. Fix: verify
JSON history records expected_hash; last run L1=FAIL AND hash changed AND no
expected_correction -> EXPECTED_TAMPERED (fail-closed REJECTED).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import kunglao_verify as kv  # noqa: E402

H_RIGHT = hashlib.sha256(b"hello").hexdigest()
H_WRONG = hashlib.sha256(b"wrong").hexdigest()
H_OTHER = hashlib.sha256(b"bye").hexdigest()


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "runs" / "logs").mkdir()
    return ws


def _write_fact(ws, expected, extra=""):
    (ws / "facts" / "F001.md").write_text(
        "---\nid: F001\nclaim_id: C-001\n"
        "reproduce: print('hello')\nexpected: " + expected + "\n"
        + extra + "---\n\nbody\n", encoding="utf-8")


def _last_json(ws):
    p = sorted((ws / "runs").glob("verify-F001-*.json"),
               key=lambda p: p.stat().st_mtime)[-1]
    return json.loads(p.read_text(encoding="utf-8"))


def test_first_run_anchors_expected_hash(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_fact(ws, H_RIGHT)
    out = kv.verify(ws, "F001")
    j = _last_json(ws)
    assert j["expected_hash"] == H_RIGHT
    assert out["overall"] == "VERIFIED"


def test_fail_then_rewrite_rejected_expected_tampered(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_fact(ws, H_WRONG)
    v1 = kv.verify(ws, "F001")              # L1 FAIL -> REJECTED
    assert v1["overall"] == "REJECTED"
    _write_fact(ws, H_RIGHT)                # rewrite after FAIL = forgery
    v2 = kv.verify(ws, "F001")
    assert v2["overall"] == "REJECTED"
    assert "EXPECTED_TAMPERED" in v2["lint"]["reason"]
    recs = kv.prior_expected_history(ws, "F001")
    assert len(recs) == 2 and recs[-1]["expected_hash"] == H_RIGHT


def test_fail_then_rewrite_with_correction_passes(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_fact(ws, H_WRONG)
    kv.verify(ws, "F001")                   # FAIL run
    _write_fact(ws, H_RIGHT,
                extra="expected_correction: observed value is the contract\n")
    v2 = kv.verify(ws, "F001")
    assert v2["overall"] == "VERIFIED"
    assert "EXPECTED_TAMPERED" not in v2["lint"]["reason"]


def test_same_expected_fail_not_tamper(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_fact(ws, H_WRONG)
    kv.verify(ws, "F001")
    v2 = kv.verify(ws, "F001")
    assert "EXPECTED_TAMPERED" not in v2["lint"]["reason"]
    assert v2["overall"] == "REJECTED"      # still L1-failed, not this gate


def test_change_after_pass_allowed(tmp_path):
    ws = _mk_ws(tmp_path)
    _write_fact(ws, H_RIGHT)
    kv.verify(ws, "F001")
    (ws / "facts" / "F001.md").write_text(
        "---\nid: F001\nclaim_id: C-001\n"
        "reproduce: print('bye')\nexpected: " + H_OTHER + "\n"
        "---\n\nbody\n", encoding="utf-8")
    v2 = kv.verify(ws, "F001")
    assert v2["overall"] == "VERIFIED"
    assert "EXPECTED_TAMPERED" not in v2["lint"]["reason"]
    assert _last_json(ws)["expected_hash"] == H_OTHER
