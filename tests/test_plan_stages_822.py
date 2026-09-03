# -*- coding: utf-8 -*-
"""tests/test_plan_stages_822.py — #822 plan 阶段模型三族测试。

工件：runs/plan-stages.yaml（stages[] + reviews[]）。
规则：结构校验 fail-closed；BIG_BANG_PLAN 检测；盘点裁决 adjust/replan
必带 trigger reason；裁决落 yaml + runs 文档 + ledger 事件。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plan_stages as ps  # noqa: E402


def _mk_ws(tmp_path, stub_plan=True):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
    if stub_plan:
        (ws / "global_plan.txt").write_text(
            "# global_plan — kunglao-init v1 stub\n", encoding="utf-8")
    return ws


def _two_stage(ws):
    ps.write_stages(ws, [
        {"id": "S1", "name": "recon", "goal": "g1",
         "claims": ["C-001"], "expected_evidence": "static json",
         "exit_criteria": "C-001 terminal", "next_candidates": ["S2"],
         "status": "active"},
        {"id": "S2", "name": "dyn", "goal": "g2",
         "claims": ["C-001"], "expected_evidence": "trace log",
         "exit_criteria": "C-001 verified twice",
         "next_candidates": [], "status": "pending"},
    ])
    return ps.load(ws)


def test_validate_ok_two_stage(tmp_path):
    ws = _mk_ws(tmp_path)
    data = _two_stage(ws)
    r = ps.validate(data)
    assert r["ok"] is True, r["violations"]


def test_validate_missing_required_field(tmp_path):
    ws = _mk_ws(tmp_path)
    data = _two_stage(ws)
    del data["stages"][0]["exit_criteria"]
    r = ps.validate(data)
    assert r["ok"] is False
    assert any("exit_criteria" in v for v in r["violations"])


def test_validate_dup_stage_id(tmp_path):
    ws = _mk_ws(tmp_path)
    data = _two_stage(ws)
    data["stages"][1]["id"] = "S1"
    r = ps.validate(data)
    assert r["ok"] is False
    assert any("duplicate" in v for v in r["violations"])


def test_big_bang_single_active_stage(tmp_path):
    ws = _mk_ws(tmp_path)
    ps.write_stages(ws, [
        {"id": "S1", "name": "everything", "goal": "g",
         "claims": ["C-001"], "expected_evidence": "e",
         "exit_criteria": "x", "next_candidates": [],
         "status": "active"},
    ])
    r = ps.check(ws)
    assert r["ok"] is False
    assert any("BIG_BANG_PLAN" in v for v in r["violations"])


def test_big_bang_missing_yaml(tmp_path):
    ws = _mk_ws(tmp_path)
    r = ps.check(ws)
    assert r["ok"] is False
    assert any("BIG_BANG_PLAN" in v for v in r["violations"])


def test_check_ok_multi_stage(tmp_path):
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    r = ps.check(ws)
    assert r["ok"] is True, r["violations"]


def test_review_adjust_requires_reason(tmp_path):
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    r = ps.review(ws, verdict="adjust", stage_id="S1", reason="")
    assert r["ok"] is False
    assert any("reason" in v for v in r["violations"])


def test_review_replan_requires_reason(tmp_path):
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    r = ps.review(ws, verdict="replan", stage_id="S1", reason="")
    assert r["ok"] is False
    assert any("reason" in v for v in r["violations"])


def test_review_replan_requires_new_stages(tmp_path):
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    r = ps.review(ws, verdict="replan", stage_id="S1",
                  reason="evidence contradicted stage goal")
    assert r["ok"] is False
    assert any("stages" in v for v in r["violations"])


def test_review_adjust_ok_and_recorded(tmp_path):
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    r = ps.review(ws, verdict="adjust", stage_id="S1",
                  reason="exit criteria too strict after recon findings")
    assert r["ok"] is True, r["violations"]
    data = ps.load(ws)
    assert data["reviews"][-1]["verdict"] == "adjust"
    assert data["reviews"][-1]["reason"]
    docs = sorted((ws / "runs").glob("plan-review-*.md"))
    assert docs, "review doc must land in runs/"


def test_review_maintain_ok(tmp_path):
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    r = ps.review(ws, verdict="maintain", stage_id="S1", reason="")
    assert r["ok"] is True, r["violations"]


def test_review_emits_ledger_event(tmp_path):
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    ps.review(ws, verdict="adjust", stage_id="S1",
              reason="criteria adjusted after recon")
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows.extend(json.loads(x) for x in
                    p.read_text(encoding="utf-8").splitlines() if x.strip())
    hits = [r for r in rows if r.get("action") == "plan_review"]
    assert hits, "plan_review event must land in ledger"
    assert hits[-1].get("claim") == "S1"
    d = json.loads(hits[-1].get("detail") or "{}")
    assert d.get("verdict") == "adjust"
    assert d.get("reason")


def test_cli_check_fresh_stub_ws_nonzero(tmp_path):
    import subprocess
    ws = _mk_ws(tmp_path)
    cli = ROOT / "scripts" / "plan_stages.py"
    p = subprocess.run([sys.executable, str(cli), "--check", str(ws)],
                       capture_output=True, text=True)
    assert p.returncode != 0, "stub workspace must fail plan validation"
    assert "BIG_BANG_PLAN" in (p.stdout + p.stderr)


def test_cli_check_multi_stage_ws_zero(tmp_path):
    import subprocess
    ws = _mk_ws(tmp_path)
    _two_stage(ws)
    cli = ROOT / "scripts" / "plan_stages.py"
    p = subprocess.run([sys.executable, str(cli), "--check", str(ws)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
