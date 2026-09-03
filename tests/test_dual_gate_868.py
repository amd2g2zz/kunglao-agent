# -*- coding: utf-8 -*-
"""tests/test_dual_gate_868.py — #868 双门验证引擎。

覆盖：异票强制（#825）、反例切分 disclosed/held-out、搜索边界声明强制、
诚实失败=CEGAR 全披露、Goodhart 签名=最小信号、held-out 复检炸=升级、
N=3 replan 超限升级、座舱数据面。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dual_gate as dg  # noqa: E402


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def _load(ws, cid):
    return json.loads((ws / "runs" / "dual-gate" /
                       f"{cid}.json").read_text(encoding="utf-8"))


def _open(tmp_path, cid="case-1"):
    ws = _mk_ws(tmp_path)
    dg.open_case(ws, cid, "sub_xxx 是注入函数", source="user")
    return ws, cid


def test_open_case_creates_open_state(tmp_path):
    ws, cid = _open(tmp_path)
    c = _load(ws, cid)
    assert c["status"] == "open" and c["redteam"] is None


def test_same_identity_vote_rejected(tmp_path):
    ws, cid = _open(tmp_path)
    dg.file_redteam(ws, cid, identity="sess-a", counterexamples=[
        {"kind": "ontological", "detail": "x"}], search_boundary="查了 3 层")
    dg.file_verifier(ws, cid, identity="sess-a", evidence_refs=["e1"])
    c = dg.resolve(ws, cid)          # 异票检查在 resolve 单一卡点
    assert c["status"] == "invalid", "同身份双票必须被 #825 异票规则拒绝"


def test_redteam_reject_splits_disclosed_held_out(tmp_path):
    ws, cid = _open(tmp_path)
    dg.file_redteam(ws, cid, identity="rt-1", counterexamples=[
        {"kind": "ontological", "detail": "无法完成注入"},
        {"kind": "attribution", "detail": "存在更优注入点 sub_yyy"},
        {"kind": "attribution", "detail": "第三处注入"}],
        search_boundary="3 层调用图全查")
    c = _load(ws, cid)
    assert len(c["redteam"]["disclosed"]) == 2
    assert len(c["redteam"]["held_out"]) == 1


def test_unanimity_requires_search_boundary(tmp_path):
    ws, cid = _open(tmp_path)
    dg.file_redteam(ws, cid, identity="rt-1", counterexamples=[],
                    search_boundary="")
    dg.file_verifier(ws, cid, identity="vf-1", evidence_refs=["e1"])
    c = dg.resolve(ws, cid)
    assert c["status"] == "rejected"
    assert "boundary" in json.dumps(c["history"][-1])


def test_unanimous_pass_carries_search_boundary(tmp_path):
    ws, cid = _open(tmp_path)
    dg.file_redteam(ws, cid, identity="rt-1", counterexamples=[],
                    search_boundary="反例搜索：调用图 3 层 + 交叉引用")
    dg.file_verifier(ws, cid, identity="vf-1", evidence_refs=["e1", "e2"])
    c = dg.resolve(ws, cid)
    assert c["status"] == "passed"
    assert c["search_boundary"] == "反例搜索：调用图 3 层 + 交叉引用"


def test_honest_failure_runs_cegar_full_disclosure(tmp_path):
    ws, cid = _open(tmp_path)
    dg.file_redteam(ws, cid, identity="rt-1", counterexamples=[
        {"kind": "ontological", "detail": "无法完成注入"}],
        search_boundary="查过")
    dg.file_verifier(ws, cid, identity="vf-1", evidence_refs=["e1"])
    c = dg.resolve(ws, cid)
    assert c["status"] == "rejected"
    assert c["disclosure_mode"] == "cegar_full"
    assert c["redteam"]["disclosed"], "CEGAR 模式必须全披露给精炼方"


def test_goodhart_held_out_refire_escalates(tmp_path):
    ws, cid = _open(tmp_path)
    dg.file_redteam(ws, cid, identity="rt-1", counterexamples=[
        {"kind": "ontological", "detail": "A"},
        {"kind": "attribution", "detail": "B"}],
        search_boundary="查过")
    dg.resolve(ws, cid)
    dg.replan(ws, cid)                       # 换路径（强制 replan）
    # held-out 复检：仍是当初扣留的那个反例在炸
    dg.refire_held_out(ws, cid, still_failing=True)
    c = _load(ws, cid)
    assert c["goodhart"] is True
    assert c["disclosure_mode"] == "minimal"
    assert c["escalated"] is True            # held-out 复炸 = 实锤升级


def test_replan_n3_escalates(tmp_path):
    ws, cid = _open(tmp_path)
    dg.file_redteam(ws, cid, identity="rt-1", counterexamples=[
        {"detail": "c1"}], search_boundary="b")
    dg.resolve(ws, cid)
    for _ in range(dg.MAX_REPLANS):
        dg.replan(ws, cid)
    c = _load(ws, cid)
    assert c["escalated"] is True            # N=3 超限 → 升级 PARK 建议


def test_cockpit_face_reports_pending_and_settlement(tmp_path):
    ws, cid = _open(tmp_path, "case-a")
    dg.file_redteam(ws, "case-a", identity="rt", counterexamples=[
        {"detail": "x"}], search_boundary="b")
    face = dg.cockpit_face(ws)
    assert face["pending_signals"] >= 1
    assert any(entry["case_id"] == "case-a" for entry in face["recent"])
