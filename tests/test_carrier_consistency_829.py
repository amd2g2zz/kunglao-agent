# -*- coding: utf-8 -*-
"""#829 tests: carrier consistency five rules + decide() downgrade hook."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from carrier_consistency import check  # noqa: E402
from convergence_check import decide  # noqa: E402


def _mk_ws(tmp_path, status="PROVEN"):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    reg = "claims:\n- id: C-1\n  status: " + status + "\n"
    (ws / "claim-register.yaml").write_text(reg, encoding="utf-8")
    return ws


def _fact(ws, fid, status, verified=None, by_run=None, create=True, claims="C-1"):
    d = ws / "facts"
    d.mkdir(exist_ok=True)
    lines = ["---", "id: " + fid, "status: " + status,
             "claim_id: " + claims]
    if verified is not None:
        lines.append("verified: " + ("true" if verified else "false"))
    if by_run:
        r = ws / "runs"
        r.mkdir(exist_ok=True)
        if create:
            (r / by_run).write_text("verdict: CONFIRMED\n", encoding="utf-8")
        lines.append("verified_by_run: runs/" + by_run)
    lines.append("---")
    name = fid + "-x.md"
    (d / name).write_text("\n".join(lines) + "\nbody text\n", encoding="utf-8")


def _index(ws, rows):
    d = ws / "facts"
    d.mkdir(exist_ok=True)
    body = "\n".join(rows) + "\n"
    (d / "_INDEX.md").write_text(body, encoding="utf-8")


def _note(ws, cid, vs):
    d = ws / "notes"
    d.mkdir(exist_ok=True)
    head = "---\nid: n1\nclaim_id: " + cid + "\nverify_status: " + vs + "\n---\n"
    (d / (cid + ".md")).write_text(head + "narrative\n", encoding="utf-8")


def _ledger_actions(ws):
    acts = []
    logdir = ws / "runs" / "logs"
    if logdir.exists():
        for p in sorted(logdir.glob("kunglao-*.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    acts.append(json.loads(line).get("action"))
    return acts


def test_consistent_workspace_ok(tmp_path):
    ws = _mk_ws(tmp_path)
    _fact(ws, "F001", "VERIFIED", verified=True, by_run="r1.md")
    _index(ws, ["F001 | VERIFIED | C-1 | conclusion a"])
    r = check(ws)
    assert r["ok"] is True, r["violations"]
    assert r["checked"] >= 1


def test_a_claim_proven_fact_not_stamped(tmp_path):
    ws = _mk_ws(tmp_path)
    _fact(ws, "A001", "PARTIAL", claims="C-1")
    _index(ws, ["A001 | PARTIAL | C-1 | x"])
    r = check(ws)
    assert r["ok"] is False
    assert any("(a)" in v for v in r["violations"])


def test_a_reverse_fact_stamped_claim_open(tmp_path):
    ws = _mk_ws(tmp_path, status="OPEN")
    _fact(ws, "F001", "VERIFIED", verified=True, claims="C-1")
    _index(ws, ["F001 | VERIFIED | C-1 | x"])
    r = check(ws)
    assert r["ok"] is False
    assert any("(a)" in v for v in r["violations"])


def test_b_index_status_mismatch(tmp_path):
    ws = _mk_ws(tmp_path)
    _fact(ws, "F001", "PARTIAL", claims="C-1")
    _index(ws, ["F001 | VERIFIED | C-1 | x"])
    r = check(ws)
    assert r["ok"] is False
    assert any("(b)" in v for v in r["violations"])


def test_c_note_passes_unverified_fact(tmp_path):
    ws = _mk_ws(tmp_path)
    _fact(ws, "F001", "VERIFIED", verified=False, claims="C-1")
    _index(ws, ["F001 | VERIFIED | C-1 | x"])
    _note(ws, "C-1", "passes")
    r = check(ws)
    assert r["ok"] is False
    assert any("(c)" in v for v in r["violations"])


def test_c_note_pending_not_checked(tmp_path):
    ws = _mk_ws(tmp_path, status="OPEN")
    _fact(ws, "F001", "PARTIAL", claims="C-1")
    _index(ws, ["F001 | PARTIAL | C-1 | x"])
    _note(ws, "C-1", "pending")
    r = check(ws)
    assert r["ok"] is True, r["violations"]


def test_d_verified_by_run_missing(tmp_path):
    ws = _mk_ws(tmp_path, status="OPEN")
    _fact(ws, "F001", "PARTIAL", by_run="missing-record.md", create=False)
    r = check(ws)
    assert r["ok"] is False
    assert any("(d)" in v for v in r["violations"])


def test_e_duplicate_yaml_keys(tmp_path):
    ws = _mk_ws(tmp_path)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: PROVEN\n  status: OPEN\n"
        "  title: x\n  title: y\n", encoding="utf-8")
    r = check(ws)
    assert r["ok"] is False
    assert any("(e)" in v for v in r["violations"])


def test_decide_downgrades_converged_on_drift(tmp_path):
    ws = _mk_ws(tmp_path)
    _fact(ws, "F001", "PARTIAL")
    _index(ws, ["F001 | VERIFIED | C-1 | x"])
    (ws / "task_spec.yaml").unlink(missing_ok=True)
    d = decide(ws)
    assert d["decision"] == "DISPATCH", d["decision"]
    assert "carrier_drift" in d
    assert "carrier_drift" in _ledger_actions(ws)


def test_decide_all_consistent_still_converged(tmp_path):
    ws = _mk_ws(tmp_path)
    _fact(ws, "F001", "VERIFIED", verified=True, by_run="r1.md")
    _index(ws, ["F001 | VERIFIED | C-1 | random conclusion text"])
    (ws / "task_spec.yaml").unlink(missing_ok=True)
    d = decide(ws)
    assert d["decision"] == "CONVERGED", d
    assert "carrier_drift" not in d
