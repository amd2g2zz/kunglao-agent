# -*- coding: utf-8 -*-
"""tests/test_think_bets_711.py — #711 强制下注席位 TDD。

契约（蓝图 §7.3）：
  1. 失败事件后必有下注——近 K ledger 失败（death_verdict_rejected /
     top1_reject）近窗口失败 claim 无 think-bet 覆盖 → bet_required=True +
     artifact ## bets 区点名
  两个失败用例: file_bet 立案（空预测拒绝）→ settle_bet 双向结算
  （confirmed 需 confirming 证据，refuted 遇 None 证据即 InvalidTransition）
  3. 失败触发先例检索——bets_owed>0 时 suggested_searches 立即出现（不等
     stall 计数；盘古先例案例"不搜=确定性损失"的机制化）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import think_seat  # noqa: E402


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        "F001 | OPEN | C-1 | x\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n- id: C-2\n  status: OPEN\n",
        encoding="utf-8")
    (ws / "hypotheses").mkdir()
    return ws


def _seat_only(monkeypatch) -> None:
    """隔离：席位逻辑与 priority 机制解耦（无 dispatchable 动作才等待）。"""
    monkeypatch.setattr(think_seat, "dispatchable_count", lambda ws: 0)


def _mk_failure_ledger(ws: Path, rows: list[tuple[str, str]]) -> None:
    log = ws / "runs" / "logs" / "kunglao-2026-09-01.jsonl"
    with log.open("a", encoding="utf-8") as f:
        for action, claim in rows:
            f.write(json.dumps({
                "ts": "2026-09-01T00:00:00Z", "actor": "orchestrator",
                "action": action, "claim": claim,
            }, ensure_ascii=False) + "\n")


def _ledger_rows(ws: Path) -> list[dict]:
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for ln in p.read_text(encoding="utf-8",
                              errors="replace").splitlines():
            if ln.strip():
                rows.append(json.loads(ln))
    return rows


def test_failure_events_demand_bets(tmp_path, monkeypatch):
    _seat_only(monkeypatch)
    ws = _mk_ws(tmp_path)
    _mk_failure_ledger(ws, [("death_verdict_rejected", "C-1"),
                            ("top1_reject", "C-2")])
    res = think_seat.maybe_think(ws)
    assert res["waiting"] is True
    bet_required = res.get("bet_required")
    assert bet_required is True
    assert set(res["bets_owed"]) == {"C-1", "C-2"}
    art = (ws / res["artifact"]).read_text(encoding="utf-8")
    assert "## bets" in art
    assert "C-1" in art and "C-2" in art


def test_no_failure_no_bet_required(tmp_path, monkeypatch):
    _seat_only(monkeypatch)
    ws = _mk_ws(tmp_path)
    res = think_seat.maybe_think(ws)
    assert res.get("bet_required") is False
    assert res.get("bets_owed") == []


def test_file_bet_persists_predicted_observation(tmp_path):
    ws = _mk_ws(tmp_path)
    h = think_seat.file_bet(ws, "C-1", "crash 是预写越界",
                            "探针 W 读 0x150 处的 size-gate 常量命中")
    store = think_seat.HypothesisStore(ws / "hypotheses")
    got = store.get(h.id)
    assert got.predicted_observation == "探针 W 读 0x150 处的 size-gate 常量命中"
    assert got.competitor_group == "think-bet"
    assert got.status == "open"
    rows = _ledger_rows(ws)
    bet_filed = [r for r in rows if r.get("action") == "bet_filed"]
    assert any(r.get("claim") == "C-1" for r in bet_filed)


def test_file_bet_requires_prediction(tmp_path):
    ws = _mk_ws(tmp_path)
    with pytest.raises(ValueError):
        think_seat.file_bet(ws, "C-1", "crash 是预写越界", "  ")
    assert not list((ws / "hypotheses").glob("*.md"))


def test_settle_bet_confirmed(tmp_path):
    ws = _mk_ws(tmp_path)
    h = think_seat.file_bet(ws, "C-1", "s", "obs before settle")
    think_seat.settle_bet(ws, h.id, "confirmed", evidence_id="F001")
    got = think_seat.HypothesisStore(ws / "hypotheses").get(h.id)
    assert got.status == "confirmed"
    assert got.confirming_fact_id == "F001"
    rows = _ledger_rows(ws)
    settled = [r for r in rows if r.get("action") == "bet_settled"]
    assert any(r.get("claim") == "C-1" for r in settled)


def test_settle_bet_refuted_requires_evidence(tmp_path):
    ws = _mk_ws(tmp_path)
    h = think_seat.file_bet(ws, "C-1", "s", "obs")
    from hypothesis_store import InvalidTransition
    with pytest.raises(InvalidTransition):
        think_seat.settle_bet(ws, h.id, "refuted", evidence_id=None)
    think_seat.settle_bet(ws, h.id, "refuted", evidence_id="F002")
    got = think_seat.HypothesisStore(ws / "hypotheses").get(h.id)
    assert got.status == "refuted"
    assert got.refuting_fact_id == "F002"


def test_settle_unknown_bet_raises(tmp_path):
    ws = _mk_ws(tmp_path)
    with pytest.raises(KeyError):
        think_seat.settle_bet(ws, "H-999", "confirmed", evidence_id="F001")


def test_failure_triggers_precedent_retrieval(tmp_path, monkeypatch):
    _seat_only(monkeypatch)
    ws = _mk_ws(tmp_path)
    _mk_failure_ledger(ws, [("death_verdict_rejected", "C-1")])
    res = think_seat.maybe_think(ws)
    art = (ws / res["artifact"]).read_text(encoding="utf-8")
    assert "## suggested_searches" in art


def test_no_failure_stall_gated_searches(tmp_path, monkeypatch):
    """无失败时 suggested_searches 仍由 stall 计数门控（#759 语义保持）。"""
    _seat_only(monkeypatch)
    ws = _mk_ws(tmp_path)
    res = None
    for _ in range(think_seat.STALL_TICKS_FOR_SEARCH + 1):
        res = think_seat.maybe_think(ws)
    art = (ws / res["artifact"]).read_text(encoding="utf-8")
    assert "## suggested_searches" in art
