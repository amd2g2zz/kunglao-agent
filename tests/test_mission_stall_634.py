# -*- coding: utf-8 -*-
"""tests/test_mission_stall_634.py — #634 主线停滞指纹 + PARK 合法化。

覆盖：flat-K 触发 / 有进展不触发 / 无欠账表安全 / 合法 PARK（wake 齐备 →
无违规且退出派发队列）/ 无 wake 违规（判别器 + 载体规则 f）/ revive 翻回
OPEN 落账 / decide PARK 降级 / mission_stall 决策标注 / 心跳空转熔断。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mission_ledger  # noqa: E402
import mission_stall  # noqa: E402


def _mk_ws(tmp_path, claims=None):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(yaml.safe_dump({
        "primary_questions": [
            {"id": "q1", "question": "RCE reachability?"}],
    }), encoding="utf-8")
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": claims or [{"id": "C-1", "status": "OPEN"}]}),
        encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        "F001 | OPEN | C-1 | x\n", encoding="utf-8")
    mission_ledger.init(ws)
    return ws


# ---------- stall fingerprint ----------

def test_flat_k_triggers_stall(tmp_path):
    ws = _mk_ws(tmp_path)
    for _ in range(4):
        mission_ledger.value_m(ws)
    r = mission_stall.stall_mission(ws, k=3)
    assert r["stalled"] is True
    assert r["consecutive_flat"] >= 3
    assert r["open_claims"] >= 1


def test_fresh_progress_not_stalled(tmp_path):
    ws = _mk_ws(tmp_path, claims=[{"id": "C-1", "status": "PROVEN",
                                   "answers_question": "q1"}])
    mission_ledger.update(ws)
    mission_ledger.value_m(ws)
    mission_ledger.value_m(ws)
    r = mission_stall.stall_mission(ws, k=3)
    assert r["stalled"] is False
    assert r["consecutive_flat"] < 3


def test_no_mission_ledger_ok(tmp_path):
    ws = tmp_path / "ws2"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "OPEN"}]}),
        encoding="utf-8")
    r = mission_stall.stall_mission(ws, k=3)
    assert r["stalled"] is False  # 无欠账表 = 特征不可用，不判停滞


# ---------- PARK legality ----------

def test_park_with_wake_legal(tmp_path):
    ws = _mk_ws(tmp_path, claims=[{"id": "C-1", "status": "PARK",
                                   "wake_condition": "vm reachable"}])
    assert mission_stall.park_violations(ws) == []
    from priority_ratio import is_open
    assert is_open({"status": "PARK"}) is False


def test_park_without_wake_violation(tmp_path):
    ws = _mk_ws(tmp_path, claims=[{"id": "C-1", "status": "PARK"}])
    v = mission_stall.park_violations(ws)
    assert v and "C-1" in v[0]
    import carrier_consistency as cc
    r = cc.check(ws)
    assert r["ok"] is False
    assert any("(f)" in x for x in r["violations"])


def test_revive_flips_to_open(tmp_path):
    ws = _mk_ws(tmp_path, claims=[{"id": "C-1", "status": "PARK",
                                   "wake_condition": "vm reachable"}])
    mission_stall.revive(ws, "C-1", "vm came back")
    reg = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    assert reg["claims"][0]["status"] == "OPEN"
    ledgers = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    assert ledgers, "revive must leave a ledger event"
    rows = []
    for p in ledgers:
        for line in p.read_text(encoding="utf-8").splitlines():
            rows.append(json.loads(line))
    assert any(r.get("action") == "claim_revive" for r in rows)


# ---------- decide integration ----------

def test_decide_mission_stall_annotation(tmp_path):
    ws = _mk_ws(tmp_path)
    for _ in range(4):
        mission_ledger.value_m(ws)
    import convergence_check as cc
    d = cc.decide(ws, emit_snapshot=False)
    assert d["mission_stall"]["stalled"] is True
    assert d["mission_stall"]["consecutive_flat"] >= 3


def test_decide_park_downgrade(tmp_path):
    """全 open claims external-blocked + 零 worker + 零 partial → PARK。"""
    ws = _mk_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN",
                                   "blocked": True,
                                   "blocker": "waiting for VM",
                                   "external": True}])
    import convergence_check as cc
    d = cc.decide(ws, emit_snapshot=False)
    assert d["decision"] == "PARK"
    assert d["wake_condition"]
    assert d["reason"]
    assert d["exit_code"] == 5


def test_decide_blocked_unchanged_when_not_all_external(tmp_path):
    ws = _mk_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN",
                                   "blocked": True,
                                   "blocker": "lint violation",
                                   "external": False}])
    import convergence_check as cc
    d = cc.decide(ws, emit_snapshot=False)
    assert d["decision"] == "BLOCKED"


def test_heartbeat_noop_breaker(tmp_path):
    from heartbeat_tick import noop_breaker
    ws = _mk_ws(tmp_path)
    h = "a" * 64
    for i in range(5):
        r = noop_breaker(ws, h)
        assert r["tripped"] is False
        assert r["consecutive_noop"] == i + 1
    r = noop_breaker(ws, h)
    assert r["tripped"] is True
    r2 = noop_breaker(ws, "b" * 64)
    assert r2["tripped"] is False
    assert r2["consecutive_noop"] == 1
