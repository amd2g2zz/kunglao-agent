# -*- coding: utf-8 -*-
"""tests/test_heartbeat_off.py — --heartbeat-off teardown guard (issue #237).

双端约束:
  - 清理过早: 未收敛(open claim 仍在)删心跳 → dispatch 被 check_heartbeat_alive
    拒,分析断链。--heartbeat-off 必须拒绝并给出机械收敛依据。
  - 清理过晚: CONVERGED 后心跳仍在 → cron 每 5 分钟空转烧 token($150 实测)。
    只有 CONVERGED(或显式 --force)才允许删 runs/.heartbeat.json。

tick 绑定: 每次 heartbeat tick 必须产生收敛推进动作 — 报告必须带 action_taken
字段,供 orchestrator 填写(派发/验证/解决/重激活),空字段 = 空转故障信号。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK_ACTIVATION = ROOT / "scripts" / "hook_activation.py"

GUIDANCE = "未收敛不可清理:心跳是派发门禁凭证,删除将断分析"


def _make_ws(ws: Path, claims: list[dict] | None = None, heartbeat: bool = True) -> Path:
    """Minimal convergence-check-able workspace (claim-register.yaml + runs/)."""
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    if claims is None:
        claims = []
    body = "claims:\n" + "".join(
        f"- id: {c['id']}\n  status: {c['status']}\n  boundary_type: positive_observation\n"
        for c in claims
    )
    (ws / "claim-register.yaml").write_text(body, encoding="utf-8")
    if heartbeat:
        (ws / "runs" / ".heartbeat.json").write_text(
            json.dumps({"started_ts": "2026-08-13T00:00:00Z", "interval_min": 5}),
            encoding="utf-8",
        )
    return ws


def _run_off(ws: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {"PYTHONIOENCODING": "utf-8", **os.environ}
    return subprocess.run(
        [sys.executable, str(HOOK_ACTIVATION), str(ws), "--heartbeat-off", *extra],
        capture_output=True, text=True, encoding="utf-8", timeout=120, env=env,
    )


def test_unconverged_rejects_and_keeps_heartbeat(tmp_path):
    """OPEN claim → convergence DISPATCH → off 被拒, .heartbeat.json 保留。"""
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    r = _run_off(ws)
    assert r.returncode != 0, f"unconverged must refuse: stdout={r.stdout!r} stderr={r.stderr!r}"
    assert (ws / "runs" / ".heartbeat.json").exists(), "heartbeat must not be deleted on refusal"


def test_unconverged_rejects_with_guidance(tmp_path):
    """拒绝时 stderr 带机械收敛依据引导(双端约束核心)。"""
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    r = _run_off(ws)
    assert GUIDANCE in r.stderr, f"stderr missing guidance text: {r.stderr!r}"


def test_converged_deletes_heartbeat(tmp_path):
    """空 claims(全收敛)→ 允许删心跳 + 打印停机文案。"""
    ws = _make_ws(tmp_path / "ws", claims=[])
    r = _run_off(ws)
    assert r.returncode == 0, f"CONVERGED 应允许 off: stdout={r.stdout!r} stderr={r.stderr!r}"
    assert not (ws / "runs" / ".heartbeat.json").exists(), "heartbeat should be deleted"
    assert "收敛完成,心跳停止" in r.stdout


def test_force_overrides_unconverged(tmp_path):
    """未收敛 + --force → 显式覆盖,删除心跳。"""
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    r = _run_off(ws, "--force")
    assert r.returncode == 0, f"--force 应覆盖: stdout={r.stdout!r} stderr={r.stderr!r}"
    assert not (ws / "runs" / ".heartbeat.json").exists(), "force 应删除心跳"


def test_off_without_registered_heartbeat_is_noop(tmp_path):
    """未注册心跳时 off 是幂等 no-op(不报错)。"""
    ws = _make_ws(tmp_path / "ws", claims=[], heartbeat=False)
    r = _run_off(ws)
    assert r.returncode == 0, f"no heartbeat should no-op: stderr={r.stderr!r}"


def test_heartbeat_off_function_direct(tmp_path):
    """直接调用 heartbeat.heartbeat_off(): 未收敛 → 1 且心跳保留。"""
    from scripts import heartbeat
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    rc = heartbeat.heartbeat_off(ws)
    assert rc != 0, "direct unconverged invocation must also refuse"
    assert (ws / "runs" / ".heartbeat.json").exists()


def test_tick_report_has_action_taken(tmp_path, monkeypatch, capsys):
    """tick 报告必须带 action_taken 字段(默认空, orchestrator 填充)并在输出可见。"""
    import heartbeat_tick
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)

    def fake_run(script: str, ws_: Path, *extra: str) -> dict:
        return {"rc": 0, "stdout": "OK (fake tick)"}

    monkeypatch.setattr(heartbeat_tick, "run", fake_run)
    monkeypatch.setattr(sys, "argv", ["heartbeat_tick.py", str(ws)])
    rc = heartbeat_tick.main()
    assert rc == 0
    report = json.loads((ws / "runs" / ".heartbeat-tick.json").read_text(encoding="utf-8"))
    assert "action_taken" in report, "tick 报告必须含 action_taken 字段"
    assert report["action_taken"] == "", "default empty string, filled by the orchestrator"
    assert "action_taken" in capsys.readouterr().out, "tick stdout 必须输出该字段"


def test_prompt_is_imperative(tmp_path):
    """cron prompt 由'建议'改'命令': 每个决策必须绑定推进动作, 无动作=空转故障。"""
    from scripts.heartbeat_loop_prompt import build_prompt
    p = build_prompt(str(tmp_path / "ws"))
    assert "必须派发 priority.py 第一名" in p, "DISPATCH must dispatch"
    assert "空转故障" in p, "no action = idle fault"
    assert "自恢复" in p, "BLOCKED must self-recover"
    assert "重激活" in p, "DEFERRED must check reactivation"
    assert "--heartbeat-off" in p, "after convergence, --heartbeat-off must stop the heartbeat first"
    assert "handoff-check" in p, "CONVERGED 后先 handoff-check PASS 再 off"
    assert "§6.3" in p


def test_prompt_keeps_sendmessage_ping(tmp_path):
    """回归(issue #88): 心跳 prompt 保留 SendMessage ping 步, 无 agent-team 标记。"""
    from scripts.heartbeat_loop_prompt import build_prompt
    p = build_prompt(str(tmp_path / "ws"))
    assert "SendMessage" in p
    assert "ping" in p
    assert ".ping-log.jsonl" in p
    for marker in ("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "teammate", "team setup"):
        assert marker not in p, f"prompt 不得含 agent-team 标记 ({marker})"
