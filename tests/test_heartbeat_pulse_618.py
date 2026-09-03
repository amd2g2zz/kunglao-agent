# -*- coding: utf-8 -*-
"""tests/test_heartbeat_pulse_618.py — #618/#795 heartbeat 触发面自主化。

机制面四件：
  A. hook pulse 触达 durable 侧车（actor="hook"）——既有 hook 只写缓存
  B. 60s 去重——窗口内二次 pulse 不追加侧车行
  C. Stop 面注册——heartbeat_touch 并排 PreToolUse/Bash + Stop 两条
  D. gap 告警——侧车 newest 超阈 → 事件落账 + decide 标注；无 agent 参与全链可跑
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))

import heartbeat  # noqa: E402


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        "F001 | OPEN | C-001 | x\n", encoding="utf-8")
    return ws


def _load_hook():
    name = "heartbeat_touch_hook_618"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "heartbeat_touch.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _sidecar_lines(ws: Path) -> list[dict]:
    log = ws / "runs" / ".heartbeat.log"
    if not log.exists():
        return []
    return [json.loads(line) for line in
            log.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_hook_pulse_lands_durable_sidecar(tmp_path, monkeypatch):
    """A: hook（无 agent 参与，假 payload 直接调 hook 模块）→ 侧车落 actor=hook 行。"""
    ws = _mk_ws(tmp_path)
    (ws / "runs" / ".heartbeat.json").write_text("{}", encoding="utf-8")
    hook = _load_hook()
    monkeypatch.chdir(ws)
    rc = hook.main()
    assert rc == 0
    lines = _sidecar_lines(ws)
    assert len(lines) == 1
    assert lines[0]["actor"] == "hook"
    assert "ts" in lines[0]


def test_hook_pulse_dedup_60s(tmp_path, monkeypatch):
    """B: 60s 窗口内二次 pulse 不追加侧车行（缓存照常刷新）。"""
    ws = _mk_ws(tmp_path)
    (ws / "runs" / ".heartbeat.json").write_text("{}", encoding="utf-8")
    hook = _load_hook()
    monkeypatch.chdir(ws)
    assert hook.main() == 0
    assert hook.main() == 0
    lines = _sidecar_lines(ws)
    assert len(lines) == 1, lines
    # 缓存仍被刷新（activity_ts 变化）
    cache = json.loads((ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))
    assert "activity_ts" in cache


def test_stop_face_registered(tmp_path):
    """C: register_hooks_deployed 产物里 heartbeat_touch 同时有 Bash 面
    （legacy 键 = PreToolUse/Bash）与 Stop 两条注册——会话每轮结束必跳。"""
    import hook_activation
    ws = _mk_ws(tmp_path)
    hook_activation.register_hooks_deployed(ws)
    settings_path = ws / ".claude" / "settings.json"
    assert settings_path.exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})
    faces = {event for event, entries in hooks.items()
             for grp in (entries or [])
             if "heartbeat_touch" in json.dumps(grp)}
    assert "PreToolUse" in faces, faces   # matcher=Bash under PreToolUse
    assert "Stop" in faces, faces         # #618 second slot, no matcher


def test_gap_alarm_over_threshold(tmp_path):
    """D1: 侧车 newest 超阈 → alarm=True + gap 分钟数。"""
    import datetime as dt
    ws = _mk_ws(tmp_path)
    old = (dt.datetime.now(dt.timezone.utc)
           - dt.timedelta(minutes=60)).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / "runs" / ".heartbeat.log").write_text(
        json.dumps({"ts": old, "actor": "hook"}) + "\n", encoding="utf-8")
    r = heartbeat.gap_alarm(ws)
    assert r["alarm"] is True
    assert r["gap_min"] is not None and r["gap_min"] > 55
    assert r["newest_ts"] == old


def test_gap_alarm_no_sidecar(tmp_path):
    """D2: 无侧车 → alarm=None（不误报：没有心跳面≠死寂，义务面归注册检查）。"""
    ws = _mk_ws(tmp_path)
    r = heartbeat.gap_alarm(ws)
    assert r["alarm"] is None and r["gap_min"] is None


def test_decide_annotates_gap(tmp_path, capsys):
    """D3: decide() 在 gap 超阈时标注 decision["heartbeat_gap"] 并落账事件。"""
    import datetime as dt
    import convergence_check as cc
    ws = _mk_ws(tmp_path)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"depth": "standard", "time_budget_minutes": 60}),
        encoding="utf-8")
    old = (dt.datetime.now(dt.timezone.utc)
           - dt.timedelta(minutes=60)).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / "runs" / ".heartbeat.log").write_text(
        json.dumps({"ts": old, "actor": "hook"}) + "\n", encoding="utf-8")
    decision = cc.decide(ws)
    assert decision.get("heartbeat_gap"), decision
    # 事件落账：TODAY-dated ledger（glob 全 ledger 扫，日期敏感）
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows.extend(json.loads(line) for line in
                    p.read_text(encoding="utf-8").splitlines() if line.strip())
    assert any(r.get("action") == "heartbeat_gap" for r in rows), rows[:3]


def test_no_agent_in_chain(tmp_path, capsys):
    """无 agent 参与全链：Synthetic PostToolUse payload stdin → hook → 侧车 +
    gap 面全部就位（第三用例的假 hook 调用形态）。"""
    ws = _mk_ws(tmp_path)
    (ws / "runs" / ".heartbeat.json").write_text("{}", encoding="utf-8")
    hook = _load_hook()
    monkey_default = ws
    import os
    old_cwd = os.getcwd()
    os.chdir(ws)
    try:
        rc = hook.main()
    finally:
        os.chdir(old_cwd)
    assert rc == 0
    assert len(_sidecar_lines(ws)) == 1
    r = heartbeat.gap_alarm(ws)
    assert r["alarm"] is False  # 刚跳过，无 gap
