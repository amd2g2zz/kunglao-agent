# -*- coding: utf-8 -*-
"""#873 座舱/性能指标持久化——三缺口闭环 suite。

缺口0：cost_events.jsonl 的 PostToolUse writer（仓库内原本不存在——
cost_gate 只读不写，docstring 声明的写入方是纸面）。
缺口1：cockpit_sample 每 checkpoint 落账（V/D/ETA/cost/burn 字段齐）。
缺口2：rho_pair 行 cost 字段（cost_events 最新 amount，会话累计口径）。
缺口3：burn 逐 tick 序列（cockpit_sample 行携带 spent/remaining，离线可重放）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tuition_curve as tc  # noqa: E402
import rho_verifier as rv  # noqa: E402


# ---------- 缺口0：cost writer ----------

def _load_capture():
    name = "cost_input_capture_873"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "hooks" / "cost_input_capture.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _ws_with_runs(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _payload(ws, response, tool="Agent"):
    return {"tool_name": tool, "tool_response": response, "cwd": str(ws)}


def test_cost_warning_appends_event(tmp_path):
    cap = _load_capture()
    ws = _ws_with_runs(tmp_path)
    rc = cap.process_event(_payload(
        ws, "... COST WARNING: session total ~$12.34 ..."))
    assert rc == 0
    p = ws / "cost_events.jsonl"
    assert p.exists()
    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["amount"] == 12.34
    assert row["source"] == "Agent"
    assert row["ts"].endswith("Z")


def test_cost_critical_also_matched(tmp_path):
    cap = _load_capture()
    ws = _ws_with_runs(tmp_path)
    cap.process_event(_payload(
        ws, "COST CRITICAL: session total ~$666.58 (over $50)"))
    row = json.loads((ws / "cost_events.jsonl")
                     .read_text(encoding="utf-8").splitlines()[0])
    assert row["amount"] == 666.58


def test_no_match_no_write(tmp_path):
    cap = _load_capture()
    ws = _ws_with_runs(tmp_path)
    rc = cap.process_event(_payload(ws, "normal tool output, no cost here"))
    assert rc == 0
    assert not (ws / "cost_events.jsonl").exists()


def test_bad_amount_fail_open(tmp_path):
    cap = _load_capture()
    ws = _ws_with_runs(tmp_path)
    rc = cap.process_event(_payload(ws, "COST WARNING: session total ~$abc"))
    assert rc == 0
    assert not (ws / "cost_events.jsonl").exists()


def test_accumulate_appends(tmp_path):
    cap = _load_capture()
    ws = _ws_with_runs(tmp_path)
    cap.process_event(_payload(ws, "COST WARNING: session total ~$10.00"))
    cap.process_event(_payload(ws, "COST CRITICAL: session total ~$20.00"))
    lines = (ws / "cost_events.jsonl").read_text(
        encoding="utf-8").splitlines()
    assert len(lines) == 2


# ---------- 缺口1/3：cockpit_summary cost/burn + tick 落账 ----------

def _mk_mission_ws(tmp_path, with_cost=True, with_mission=True):
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    if with_mission:
        (ws / "runs" / "mission_ledger.yaml").write_text(yaml.safe_dump({
            "mission": {
                "pqs": [{"id": "PQ-1", "state": "answered", "weight": 1.0}],
                "history": [{"v_m": 0.5}, {"v_m": 0.75}],
            }}), encoding="utf-8")
    if with_cost:
        (ws / "cost_events.jsonl").write_text(
            json.dumps({"ts": "2026-09-01T00:00:00Z", "amount": 12.5,
                        "source": "Agent"}) + "\n", encoding="utf-8")
    return ws


def test_cockpit_summary_carries_cost_burn(tmp_path):
    ws = _mk_mission_ws(tmp_path)
    cs = tc.cockpit_summary(ws)
    assert cs["cost"] == 12.5
    assert cs["burn"] == {"spent": 12.5, "remaining": 37.5}


def test_cockpit_summary_no_cost_events(tmp_path):
    ws = _mk_mission_ws(tmp_path, with_cost=False)
    cs = tc.cockpit_summary(ws)
    assert cs["cost"] is None
    assert cs["burn"] == {"spent": 0.0, "remaining": 50.0}


def test_tick_emits_cockpit_sample_row(tmp_path):
    ws = _mk_mission_ws(tmp_path)
    r = __import__("subprocess").run(
        [sys.executable, str(ROOT / "scripts" / "heartbeat_tick.py"),
         str(ws)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)
    rows = [json.loads(line)
            for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
            for line in p.read_text(encoding="utf-8",
                                    errors="replace").splitlines() if line]
    samples = [r for r in rows if r.get("action") == "cockpit_sample"]
    assert samples, "cockpit_sample row must land in ledger"
    d = samples[-1]["detail"]
    if isinstance(d, str):
        d = json.loads(d)
    assert d["v"] == 0.75
    assert d["cost"] == 12.5
    assert d["burn"] == {"spent": 12.5, "remaining": 37.5}
    assert "eta_checkpoints" in d and "d_slope" in d


def test_tick_skips_without_mission_ledger(tmp_path):
    ws = _mk_mission_ws(tmp_path, with_mission=False)
    (ws / "runs" / "logs").mkdir(parents=True, exist_ok=True)
    __import__("subprocess").run(
        [sys.executable, str(ROOT / "scripts" / "heartbeat_tick.py"),
         str(ws)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)
    rows = [json.loads(line)
            for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
            for line in p.read_text(encoding="utf-8",
                                    errors="replace").splitlines() if line]
    assert not [r for r in rows if r.get("action") == "cockpit_sample"]


# ---------- 缺口2：rho_pair cost + 学费真实 cost ----------

def _rho_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": ["find the packer family"]}),
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "facts").mkdir(exist_ok=True)
    (ws / "facts" / "F001.md").write_text(
        "handler 0x14002abcd allocates 0x150 size gate", encoding="utf-8")
    (ws / "cost_events.jsonl").write_text(
        json.dumps({"ts": "2026-09-01T00:00:00Z", "amount": 7.25,
                    "source": "Agent"}) + "\n", encoding="utf-8")
    return ws


def test_rho_pair_carries_cost(tmp_path):
    ws = _rho_ws(tmp_path)
    rv.sample_and_pair(ws)
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("action") == "rho_pair":
                    rows.append(r)
    assert rows, "rho_pair must land"
    d = rows[-1]["detail"]
    if isinstance(d, str):
        d = json.loads(d)
    assert d["cost"] == 7.25


def test_missions_prefer_real_cost_over_duration(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    row = {"ts": "2026-09-01T00:00:00Z", "actor": "rho_verifier",
           "action": "rho_pair", "duration_ms": 9999,
           "detail": json.dumps({"rho": 0.8, "z": 1.0, "cost": 3.5})}
    (ws / "runs" / "logs" / "kunglao-t.jsonl").write_text(
        json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    recs = tc.missions_from_ledger(ws)
    assert recs and recs[0]["cost"] == 3.5
