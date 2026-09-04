# -*- coding: utf-8 -*-
"""tests/test_qtable_p3.py — #823-P3 缺口桶排序 + 早停面 + 停滞响应。

蓝图 §7.4/§7.5：
  1. 缺口命中 > tier > VoI（欠账表存在时，answers_question 命中
     未闭合 PQ 的 claim 进领先桶）；无欠账表 → 单桶，结果序与
     旧版 byte-identical。
  2. INFEASIBLE 立案产出的 DEFERRED claim 退出候选与 open 计数（早停面）。
  3. stall 时 decide 附 stall_response（think 引导；#51 起 always-on）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import priority_ratio as pr  # noqa: E402
import mission_ledger as ml  # noqa: E402
from _factories import write_claims_register


def _ws(tmp_path, claims, pqs=None, ledger=True):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    ts = {"primary_questions": pqs or [
        {"id": "q1", "question": "RCE reachability?"}]}
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(ts), encoding="utf-8")
    write_claims_register(ws, claims)
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text("", encoding="utf-8")
    if ledger:
        ml.init(ws)
    return ws


def _claim(cid, **kw):
    c = {"id": cid, "status": "OPEN", "promotion_attempts": 0}
    c.update(kw)
    return c


# ---------- 1. gap bucket ordering ----------

def test_gap_hit_ranks_first(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    claims = [
        _claim("C-gap", answers_question="q1", tier=3),
        _claim("C-junk", tier=1),
    ]
    ws = _ws(tmp_path, claims)
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.mission_active is True
    assert ev.mission_gap.get("q1") == pytest.approx(1.0)
    acts = pr.priority_ratio(claims, {}, ev)
    assert [a.claim_id for a in acts][:1] == ["C-gap"], acts


def test_no_ledger_uniform_buckets_legacy_order(tmp_path, monkeypatch):
    """无欠账表 → 全 0 桶 → 排序还原 legacy key（与有表 workspace 的分数
    一致——prior 同为 uninformative 0.5，cost 通胀同幅）。"""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    claims = [
        _claim("C-b", tier=1),
        _claim("C-a", answers_question="q1", tier=1),
        _claim("C-c", tier=2),
    ]
    ws_with = _ws(tmp_path / "with", claims)
    ws_without = _tmp_no_ledger(tmp_path, claims)
    ev1 = pr.EvidenceView.from_workspace(ws_with)
    ev2 = pr.OthersView = pr.EvidenceView.from_workspace(ws_without)
    a1 = [a.to_dict() for a in pr.priority_ratio(claims, {}, ev1)]
    a2 = [a.to_dict() for a in pr.priority_ratio(claims, {}, ev2)]
    assert a1 == a2
    # 且与 legacy 期望序一致（tier1 并列时按 cost/claim_id）
    assert [d["claim_id"] for d in a1] == ["C-a", "C-b", "C-c"]


def _tmp_no_ledger(tmp_path, claims):
    ws = tmp_path / "without"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(
        {"primary_questions": [{"id": "q1", "question": "x?"}]}),
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": claims}, allow_unicode=True), encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text("", encoding="utf-8")
    return ws


def test_answered_pq_no_bucket(tmp_path, monkeypatch):
    """命中已答 PQ → gap=0 → 不进领先桶。"""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    claims = [
        _claim("C-open", answers_question="q1", tier=1),
        _claim("C-done", status="PROVEN", answers_question="q1"),
        _claim("C-other", tier=1),
    ]
    ws = _ws(tmp_path, claims)
    ml.update(ws)  # C-done PROVEN q1 → q1 answered, gap=0
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.mission_active is False
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    acts = pr.priority_ratio(
        [c for c in reg["claims"] if c["status"] == "OPEN"], {}, ev)
    assert [a.claim_id for a in acts] == ["C-open", "C-other"]


def test_blocked_pq_partial_gap(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    claims = [_claim("C-x", answers_question="q1", tier=1)]
    ws = _ws(tmp_path, claims)
    ml.mark_blocked(ws, "q1", blocker="vm down", wake="vm up")
    ev = pr.EvidenceView.from_workspace(ws)
    assert ev.mission_gap["q1"] == pytest.approx(0.7)  # (1-β)·w = 0.7·1.0


# ---------- 2. early-stop face: DEFERRED exits candidates ----------

def test_deferred_claim_exits_candidates(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    claims = [
        _claim("C-def", status="DEFERRED", answers_question="q1"),
        _claim("C-live", tier=1),
    ]
    ws = _ws(tmp_path, claims)
    ev = pr.EvidenceView.from_workspace(ws)
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8"))
    acts = pr.priority_ratio(reg["claims"], {}, ev)
    ids = [a.claim_id for a in acts]
    assert "C-def" not in ids
    from priority_ratio import is_open
    assert is_open({"id": "C-def", "status": "DEFERRED"}) is False


# ---------- 3. stall_response ----------

def test_stall_response_present(tmp_path, monkeypatch):
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    ws = _mk_decide_ws(tmp_path)
    for _ in range(4):
        ml.value_m(ws)
    import convergence_check as cc
    d = cc.decide(ws, emit_snapshot=False)
    assert d["mission_stall"]["stalled"] is True  # #634 标注仍在
    resp = d.get("stall_response")
    assert isinstance(resp, dict) and "bets_owed" in resp
    assert "file_bet" in resp["guidance"]


# ---------- decide fixture ----------

def _mk_decide_ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(yaml.safe_dump({
        "primary_questions": [{"id": "q1", "question": "RCE reachability?"}],
    }), encoding="utf-8")
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-1", "status": "OPEN"}]}), encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text("F001 | OPEN | C-1 | x\n",
                                            encoding="utf-8")
    ml.init(ws)
    return ws
