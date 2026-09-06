# -*- coding: utf-8 -*-
"""tests/test_qtable_p3.py — 价值循环排序回归 + 早停面 + 停滞响应。

#107 重钉：缺口桶（bucket 领排）随加权公式一起被 owner 裁决废弃
（"之前的不要了"）。排序改为 Thompson 复合量；本文件现在钉住：
  1. PQ categorical（posteriors 账本）经 dH 项进入排序；mission_ledger
     的欠账数据面不再泄漏进排序（旧 feed 删除的回归钉）。
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


# ---------- 1. PQ categorical -> dH term; mission ledger stays OUT ----------

def test_pq_categorical_lands_dh_feed(tmp_path, monkeypatch):
    """posteriors 账本里的 PQ categorical 经 dH 进入排序面（#106/#107
    接线）：命中该 PQ 的 claim 带非零 dH feed 与加分。"""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    from posteriors import PQCategorical, PosteriorLedger
    claims = [
        _claim("C-gap", answers_question="q1", tier=3),
        _claim("C-junk", tier=1),
    ]
    ws = _ws(tmp_path, claims)
    led = PosteriorLedger()
    led.pqs["q1"] = PQCategorical("q1", {"plain-md5": 1.0, "salted": 1.0})
    led.save(ws)
    ev = pr.EvidenceView.from_workspace(ws)
    acts = pr.priority_ratio(claims, {}, ev)
    gap = next(a for a in acts if a.claim_id == "C-gap")
    junk = next(a for a in acts if a.claim_id == "C-junk")
    assert "dH=0" not in gap.feeds["dh_pq"]
    assert "dH=0" in junk.feeds["dh_pq"]
    assert gap.score > junk.score - pr.LAMBDA_DH  # the dH lift is bounded


def test_with_and_without_empty_ledger_byte_identical(tmp_path, monkeypatch):
    """空账本（或无账本）→ 同一冷启动分布：结果 byte-identical（账本文件
    的存在本身不是信号）。"""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    claims = [
        _claim("C-b", tier=1),
        _claim("C-a", answers_question="q1", tier=1),
        _claim("C-c", tier=2),
    ]
    ws_with = _ws(tmp_path / "with", claims)
    ws_without = _tmp_no_ledger(tmp_path, claims)
    ev1 = pr.EvidenceView.from_workspace(ws_with)
    ev2 = pr.EvidenceView.from_workspace(ws_without)
    a1 = [a.to_dict() for a in pr.priority_ratio(claims, {}, ev1)]
    a2 = [a.to_dict() for a in pr.priority_ratio(claims, {}, ev2)]
    assert a1 == a2


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


def test_mission_ledger_no_longer_leaks_into_ranking(tmp_path, monkeypatch):
    """#107 回归钉：mission_ledger（V_m / 欠账态）不再是任何排序输入——
    有欠账表与无欠账表的同内容 workspace 排序 byte-identical（数据面
    保留在 mission_ledger.py，消费面已死）。"""
    monkeypatch.delenv("KUNGLAO_VALUE_ALGO", raising=False)
    claims = [
        _claim("C-open", answers_question="q1", tier=1),
        _claim("C-done", status="PROVEN", answers_question="q1"),
        _claim("C-other", tier=1),
    ]
    ws_ledger = _ws(tmp_path / "led", claims)
    ml.update(ws_ledger)  # q1 answered, ledger history written
    ws_none = _tmp_no_ledger(tmp_path, claims)
    a1 = [a.to_dict() for a in pr.priority_ratio(claims, {},
                                                 pr.EvidenceView.from_workspace(ws_ledger))]
    a2 = [a.to_dict() for a in pr.priority_ratio(claims, {},
                                                 pr.EvidenceView.from_workspace(ws_none))]
    assert a1 == a2


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
