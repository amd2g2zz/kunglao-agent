# -*- coding: utf-8 -*-
"""tests/test_infeasible_proposal_815.py — #815 早停接线。

蓝图 §7.3：INFEASIBLE 是需要证据要件的 claim，不是 V 曲线的属性。
恢复阶梯 L1/L2/L3 走完 + 尝试清单非空 + wake_condition 非空 + 信号已运行
→ 才准立案 DEFERRED（带复活条件）；任一缺失 → REJECT 且寄存器零变更。
DEFERRED 在 status_defs.TERMINAL → 全消费方自动退出派发。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import priority_ratio  # noqa: E402
import infeasible_proposal as ip  # noqa: E402


def _mk_ws(tmp_path, claims):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text("F001 | OPEN | C-1 | x\n",
                                            encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    return ws


def _signal(ws):
    (ws / "runs" / "infeasible-state.json").write_text(
        json.dumps({"terminal_count": 3}), encoding="utf-8")


def _ladder(ws, claim="C-1", levels=("L1", "L2", "L3"), inventory=2):
    data = {
        "claim": claim,
        "attempts": [{"level": lv,
                      "action": f"switch mode at {lv}",
                      "outcome": f"{lv} exhausted"} for lv in levels],
        "inventory": [{"tried": f"approach {i}",
                       "failed_because": "closed-source cipher, no key exit"}
                      for i in range(inventory)],
    }
    p = ws / "runs" / f"infeasible-ladder-{claim}.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def _reg_claim(ws, cid="C-1"):
    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    return next(c for c in reg["claims"] if c.get("id") == cid)


def _rows(ws):
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows.extend(json.loads(x) for x in
                    p.read_text(encoding="utf-8").splitlines())
    return rows


def test_missing_ladder_rejected_no_state_change(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    _signal(ws)
    r = ip.file_proposal(ws, "C-1", wake_condition="vm_reachable")
    assert r["filed"] is False
    assert "ladder" in r["reason"]
    assert _reg_claim(ws)["status"] == "OPEN"


def test_partial_ladder_rejected_names_missing(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    _signal(ws)
    _ladder(ws, levels=("L1",))
    r = ip.file_proposal(ws, "C-1", wake_condition="vm_reachable")
    assert r["filed"] is False
    assert "L2" in r["reason"] and "L3" in r["reason"]
    assert _reg_claim(ws)["status"] == "OPEN"


def test_complete_ladder_empty_inventory_rejected(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    _signal(ws)
    _ladder(ws, inventory=0)
    r = ip.file_proposal(ws, "C-1", wake_condition="vm_reachable")
    assert r["filed"] is False
    assert "inventory" in r["reason"]
    assert _reg_claim(ws)["status"] == "OPEN"


def test_missing_wake_condition_rejected(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    _signal(ws)
    _ladder(ws)
    r = ip.file_proposal(ws, "C-1", wake_condition="")
    assert r["filed"] is False
    assert "wake_condition" in r["reason"]


def test_missing_signal_precondition_rejected(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    _ladder(ws)
    r = ip.file_proposal(ws, "C-1", wake_condition="vm_reachable")
    assert r["filed"] is False
    assert "signal" in r["reason"]
    assert _reg_claim(ws)["status"] == "OPEN"


def test_full_requirements_filed_deferred(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    _signal(ws)
    _ladder(ws)
    r = ip.file_proposal(ws, "C-1", wake_condition="new_unpack_tool")
    assert r["filed"] is True, r["reason"]
    c = _reg_claim(ws)
    assert c["status"] == "DEFERRED"
    assert c["deferred_reason"] == "infeasible"
    assert c["wake_condition"] == "new_unpack_tool"
    assert (ws / "runs" / "infeasible-proposal-C-1.md").exists()
    rows = _rows(ws)
    assert any(x.get("action") == "infeasible_filed" for x in rows)
    # 派发面：DEFERRED 自动退出派发（status_defs 单源）
    assert priority_ratio.is_open(c) is False


def test_terminal_claim_cannot_be_filed(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    _signal(ws)
    _ladder(ws)
    r = ip.file_proposal(ws, "C-1", wake_condition="new_unpack_tool")
    assert r["filed"] is False
    assert "terminal" in r["reason"]
    assert _reg_claim(ws)["status"] == "PROVEN"


def test_wake_revives_infeasible_deferred(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
    _signal(ws)
    _ladder(ws)
    ip.file_proposal(ws, "C-1", wake_condition="new_unpack_tool")
    r = ip.wake(ws, "C-1", reason="new tool landed: unipacker-2.0")
    assert r["woken"] is True, r["reason"]
    c = _reg_claim(ws)
    assert c["status"] == "OPEN"
    assert c["woken_at"]
    assert c["wake_reason"] == "new tool landed: unipacker-2.0"
    rows = _rows(ws)
    assert any(x.get("action") == "infeasible_woken" for x in rows)


def test_wake_rejects_plain_deferred(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "DEFERRED"}])
    r = ip.wake(ws, "C-1", reason="retry")
    assert r["woken"] is False
    assert _reg_claim(ws)["status"] == "DEFERRED"


def test_wake_rejects_terminal(tmp_path):
    ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    r = ip.wake(ws, "C-1", reason="retry")
    assert r["woken"] is False
    assert _reg_claim(ws)["status"] == "PROVEN"
