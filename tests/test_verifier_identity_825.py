# -*- coding: utf-8 -*-
"""#825 identity-binding tests (I1-I4 register gate, W1-W5 write_gate)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import yaml  # noqa: E402

import register_proven_gate as rpg  # noqa: E402
import verifier_identity as vi  # noqa: E402
import write_gate as wg  # noqa: E402


def _mk_ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _verify_note(ws, claim, verdict="passes", identity=None):
    name = f"2026-08-31-verify-{claim}.md"
    ident = f"\nverifier-identity: {identity}" if identity else ""
    (ws / "runs" / name).write_text(
        "---\nclaim_id: " + claim + "\n---\n\n"
        "## Overall verdict\n" + verdict + ident, encoding="utf-8")
    return name


def _redteam(ws, claim, verdict="CONFIRMED", identity=None):
    name = "verify-redteam-" + claim + ".md"
    ident = "verifier-identity: " + identity + "\n" if identity else ""
    (ws / "runs" / name).write_text(
        "---\ntarget: " + claim + "\n---\n\n"
        "RED-TEAM VERDICT: " + verdict + "\nclaim: " + claim + "\n" + ident,
        encoding="utf-8")
    return name


def _reg_with(claim, status):
    return yaml.safe_dump({"claims": [{"id": claim, "status": status,
                                       "statement": "x"}]}, sort_keys=False)


def _transition(ws, claim="C-001"):
    return rpg.check_register_transitions(
        ws, _reg_with(claim, "PROVEN"), old_text=_reg_with(claim, "OPEN"))


def _anchors(ws):
    p = ws / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in
            p.read_text(encoding="utf-8").splitlines() if x.strip()
            and json.loads(x).get("type") == "verdict_anchor"]


# ---------------------------------------------------------------- register

def test_i1_no_identity_rejected(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify_note(ws, "C-001", "passes")
    _redteam(ws, "C-001", "CONFIRMED", identity=None)
    r = _transition(ws)
    assert not r["ok"], r
    assert any("verifier-identity header" in v for v in r["violations"]), r


def test_i2_same_identity_is_collapse(tmp_path):
    ws = _mk_ws(tmp_path)
    _verify_note(ws, "C-001", "passes", identity="sess-A")
    _redteam(ws, "C-001", "CONFIRMED", identity="sess-A")
    r = _transition(ws)
    assert not r["ok"], r
    assert any("collapse" in v for v in r["violations"]), r


def test_i3_redteam_predates_verify_note(tmp_path):
    ws = _mk_ws(tmp_path)
    vn = _verify_note(ws, "C-001", "passes", identity="sess-A")
    rt = _redteam(ws, "C-001", "CONFIRMED", identity="sess-B")
    os.utime(ws / "runs" / vn, (2000000000.0, 2000000000.0))
    os.utime(ws / "runs" / rt, (1999999000.0, 1999999000.0))
    r = _transition(ws)
    assert not r["ok"], r
    assert any("predates" in v for v in r["violations"]), r


def test_i4_accept_and_anchor_idempotent(tmp_path):
    ws = _mk_ws(tmp_path)
    vn = _verify_note(ws, "C-001", "passes", identity="sess-A")
    rt = _redteam(ws, "C-001", "CONFIRMED", identity="sess-B")
    os.utime(ws / "runs" / vn, (2000000000.0, 2000000000.0))
    os.utime(ws / "runs" / rt, (2000000100.0, 2000000100.0))
    r = _transition(ws)
    assert r["ok"], r
    rows = _anchors(ws)
    assert len(rows) == 1, rows
    assert rows[0]["claim_id"] == "C-001"
    assert rows[0]["verifier_identity"] == "sess-B"
    assert len(rows[0]["record_sha256"]) == 64
    _transition(ws)
    assert len(_anchors(ws)) == 1, "anchor must be idempotent"


# ---------------------------------------------------------------- write_gate

def _wjson(ws, fid, overall, l2_verdict, identity):
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    ident = {"verifier_identity": identity} if identity else {}
    (runs / ("verify-" + fid + "-20260811T000000Z.json")).write_text(
        json.dumps({"fact_id": fid, "claim_id": "C-1", "overall": overall,
                    "l2": dict({"verdict": l2_verdict, "gaps": []}, **ident),
                    "l1": {"verdict": "PASS" if overall == "VERIFIED" else "FAIL",
                           "actual_sha256": "a" * 64, "cmd": "x"}}),
        encoding="utf-8")


def _wfact(ws, fid):
    facts = ws / "facts"
    facts.mkdir(parents=True, exist_ok=True)
    (facts / (fid + ".md")).write_text(
        "---\nid: " + fid + "\nclaim_id: C-1\nstatus: PROVEN\n---\nbody",
        encoding="utf-8")


def test_w1_l1_only_json_rejected(tmp_path):
    ws = tmp_path / "ws"
    _wfact(ws, "F-1")
    _wjson(ws, "F-1", "VERIFIED", "NOT-RUN", None)
    ok, reason = wg._fact_runs_records("F-1", ws)
    assert ok is False and "l2" in reason.lower(), (ok, reason)


def test_w2_l2_without_identity_rejected(tmp_path):
    ws = tmp_path / "ws"
    _wfact(ws, "F-2")
    _wjson(ws, "F-2", "VERIFIED", "CONFIRMED", None)
    ok, reason = wg._fact_runs_records("F-2", ws)
    assert ok is False and "verifier_identity" in reason, (ok, reason)


def test_w3_l2_with_identity_clean(tmp_path):
    ws = tmp_path / "ws"
    _wfact(ws, "F-3")
    _wjson(ws, "F-3", "VERIFIED", "CONFIRMED", "rt-x")
    ok, reason = wg._fact_runs_records("F-3", ws)
    assert ok is True, reason


def test_w4_md_without_identity_rejected(tmp_path):
    ws = tmp_path / "ws"
    runs = ws / "runs"
    runs.mkdir(parents=True)
    (runs / "verify-redteam-20260812.md").write_text(
        "## redteam F-4\nverdict: CONFIRMED\n", encoding="utf-8")
    ok, reason = wg._fact_runs_records("F-4", ws)
    assert ok is False and "verifier-identity" in reason, (ok, reason)


def test_w5_md_with_identity_clean(tmp_path):
    ws = tmp_path / "ws"
    runs = ws / "runs"
    runs.mkdir(parents=True)
    (runs / "verify-redteam-20260812.md").write_text(
        "## redteam F-5\nverdict: CONFIRMED\nverifier-identity: rt-9\n",
        encoding="utf-8")
    ok, reason = wg._fact_runs_records("F-5", ws)
    assert ok is True, reason
