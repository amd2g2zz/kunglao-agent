# -*- coding: utf-8 -*-
"""tests/test_heartbeat_off.py — --heartbeat-off teardown guard (issue #237).

Two-sided constraint:
  - Teardown too early: deleting the heartbeat while unconverged (open claim
    still present) → dispatch is rejected by check_heartbeat_alive, analysis
    breaks. --heartbeat-off must refuse and give the mechanical convergence
    evidence.
  - Teardown too late: heartbeat still on after CONVERGED → the cron burns
    tokens idling every 5 minutes ($150 measured). Only CONVERGED (or an
    explicit --force) may delete runs/.heartbeat.json.

tick binding: every heartbeat tick must produce a convergence-advancing action
— the report must carry the action_taken field, filled by the orchestrator
(dispatch / verify / resolve / reactivate); an empty field = idle-fault signal.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from _factories import write_claims_register

ROOT = Path(__file__).resolve().parents[1]
HOOK_ACTIVATION = ROOT / "scripts" / "hook_activation.py"

GUIDANCE = "Not converged — teardown forbidden: the heartbeat is the dispatch gate credential"


def _make_ws(ws: Path, claims: list[dict] | None = None,
             heartbeat: bool = True) -> Path:
    """Minimal workspace via the 863-h claims factory."""
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    claims = [dict(c, boundary_type=c.get("boundary_type", "positive_observation"))
              for c in (claims or [])]
    write_claims_register(ws, claims)
    if heartbeat:
        (ws / "runs" / ".heartbeat.json").write_text(
            json.dumps({"started_ts": "2026-08-13T00:00:00Z", "interval_min": 5}),
            encoding="utf-8",
        )
    return ws


def _closed_oracle(ws: Path) -> Path:
    """#717 dual-criterion fixture: a CLOSED task-oracle.yaml (the teardown
    guard requires convergence AND a judge-clean oracle)."""
    (ws / "task-oracle.yaml").write_text(
        'task_text: "synthetic task"\n'
        "open_items:\n"
        "  - id: OC-1\n"
        "    closed_by: F-001\n",
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
    """OPEN claim → convergence DISPATCH → off refused, .heartbeat.json kept."""
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    r = _run_off(ws)
    assert r.returncode != 0, f"unconverged must refuse: stdout={r.stdout!r} stderr={r.stderr!r}"
    assert (ws / "runs" / ".heartbeat.json").exists(), "heartbeat must not be deleted on refusal"


def test_unconverged_rejects_with_guidance(tmp_path):
    """Refusal puts the mechanical convergence-evidence guidance on stderr
    (core of the two-sided constraint)."""
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    r = _run_off(ws)
    assert GUIDANCE in r.stderr, f"stderr missing guidance text: {r.stderr!r}"


def test_converged_deletes_heartbeat(tmp_path):
    """Empty claims (all converged) + closed oracle (#717 criterion 2) →
    heartbeat deletion allowed + shutdown line printed."""
    ws = _closed_oracle(_make_ws(tmp_path / "ws", claims=[]))
    r = _run_off(ws)
    assert r.returncode == 0, f"CONVERGED should allow off: stdout={r.stdout!r} stderr={r.stderr!r}"
    assert not (ws / "runs" / ".heartbeat.json").exists(), "heartbeat should be deleted"
    assert "Convergence complete, heartbeat stopped" in r.stdout


def test_force_overrides_unconverged(tmp_path):
    """Unconverged + --force → explicit override, heartbeat deleted."""
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    r = _run_off(ws, "--force")
    assert r.returncode == 0, f"--force should override: stdout={r.stdout!r} stderr={r.stderr!r}"
    assert not (ws / "runs" / ".heartbeat.json").exists(), "force should delete the heartbeat"


def test_off_without_registered_heartbeat_is_noop(tmp_path):
    """off without a registered heartbeat is an idempotent no-op (no error).
    #717: teardown still needs a closed oracle even with no heartbeat file."""
    ws = _closed_oracle(_make_ws(tmp_path / "ws", claims=[], heartbeat=False))
    r = _run_off(ws)
    assert r.returncode == 0, f"no heartbeat should no-op: stderr={r.stderr!r}"


def test_heartbeat_off_function_direct(tmp_path):
    """Direct heartbeat.heartbeat_off() call: unconverged → 1 and heartbeat kept."""
    from scripts import heartbeat
    ws = _make_ws(tmp_path / "ws", claims=[{"id": "C-001", "status": "OPEN"}])
    rc = heartbeat.heartbeat_off(ws)
    assert rc != 0, "direct unconverged invocation must also refuse"
    assert (ws / "runs" / ".heartbeat.json").exists()


def test_tick_report_has_action_taken(tmp_path, monkeypatch, capsys):
    """Tick report must carry the action_taken field (default empty, filled
    by the orchestrator) and show it in stdout."""
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
    assert "action_taken" in report, "tick report must include the action_taken field"
    assert report["action_taken"] == "", "default empty string, filled by the orchestrator"
    assert "action_taken" in capsys.readouterr().out, "tick stdout must output that field"


def test_prompt_is_imperative(tmp_path):
    """Cron prompt turned from 'suggestion' to 'command': every decision must
    bind a convergence-advancing action; no action = idle fault."""
    from scripts.heartbeat_loop_prompt import build_prompt
    p = build_prompt(str(tmp_path / "ws"))
    assert "MUST dispatch priority_ratio.py #1" in p, "DISPATCH must dispatch"
    assert "idle fault" in p, "no action = idle fault"
    assert "self-recover" in p, "BLOCKED must self-recover"
    assert "reactivat" in p, "DEFERRED must check reactivation"
    assert "--heartbeat-off" in p, "after convergence, --heartbeat-off must stop the heartbeat first"
    assert "handoff-check" in p, "CONVERGED must handoff-check PASS before off"
    assert "§6.3" in p


def test_prompt_keeps_sendmessage_ping(tmp_path):
    """Regression (issue #88): the heartbeat prompt keeps the SendMessage ping
    step and carries no agent-team markers."""
    from scripts.heartbeat_loop_prompt import build_prompt
    p = build_prompt(str(tmp_path / "ws"))
    assert "SendMessage" in p
    assert "ping" in p
    assert ".ping-log.jsonl" in p
    for marker in ("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "teammate", "team setup"):
        assert marker not in p, f"prompt must not carry agent-team markers ({marker})"
