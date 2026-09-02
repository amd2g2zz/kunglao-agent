# -*- coding: utf-8 -*-
"""WAIT/UNWAIT — signal write, pulse skip and idle-breaker exemption.

Three consumers make the wait state operationally real:

  - hooks/dispatch_gate.py: on the dispatch-ALLOW path, when the target
    agent id matches an existing ``runs/worker-status-<agent>.md`` whose
    LAST status is ``waiting``, the gate writes the wake signal
    ``runs/wait-signal-<agent>.json`` ({"claim", "ts"}) BEFORE allowing the
    dispatch. Fire-and-forget: a failed signal write must never block the
    dispatch (hook fail-open discipline), so the face is assert-on-file,
    rc stays 0.
  - hooks/worker_pulse.py: a worker whose LAST status is ``waiting`` is
    delivered-but-alive — it re-arms on the next dispatch and is NOT a
    zombie, so the TASKSTOP delivery reminder must skip it (other final
    states keep the reminder).
  - scripts/heartbeat_tick.py noop_breaker: a stable state fingerprint is
    HEALTHY when zero workers are active and at least one is waiting —
    idle spin-down, not a stuck loop; the breaker must report
    ``{"tripped": False, "reason": "all-workers-waiting"}`` instead of
    tripping. Waiting files must never age into the stuck list either
    (covered by the scan exemption in test_scan_waiting_902.py).

The gate and the pulse run as wired subprocesses (JSON payload on stdin);
the breaker is imported (scripts/ is a pytest import root).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from _factories import write_hook_state

ROOT = Path(__file__).resolve().parents[1]


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _mk_ws(root: Path) -> Path:
    """Minimal activated workspace whose single claim C-1 IS the top-1, so a
    plain dispatch reaches the ALLOW path unchanged."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    _write(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": "OPEN",
         "statement": "background work"}]})
    _write(ws / "claim_deps.yaml",
           {"depends_on": {}, "competitor_groups": {}})
    _write(ws / "task_spec.yaml", {"primary_questions": []})
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    (ws / "runs").mkdir()
    return ws


def _waiting_ledger(ws: Path, agent: str = "kunglao-worker",
                    last: str = "waiting") -> Path:
    p = ws / "runs" / f"worker-status-{agent}.md"
    p.write_text(
        "[12:00] step: started task | status: in-progress\n"
        "[12:30] step: delivered | status: done\n"
        f"[12:31] wait: awaiting signal | status: {last}\n",
        encoding="utf-8")
    return p


_GATE_PROMPT = "[T1 tools=Read,Write] claim C-1 background sweep"


def _run_gate(root: Path, ws: Path, agent: str = "kunglao-worker") -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "tool_input": {"prompt": _GATE_PROMPT, "subagent_type": agent},
    })
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=90,
        cwd=str(ROOT), errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
    )


# ---------- dispatch gate: the wake signal ----------

class TestDispatchWaitSignal:
    def test_allow_path_writes_signal_for_waiting_worker(self, tmp_path):
        root = tmp_path / "r1"
        ws = _mk_ws(root)
        _waiting_ledger(ws)
        r = _run_gate(root, ws)
        assert r.returncode == 0, (
            f"plain top-1 dispatch must be allowed; stderr={r.stderr!r}")
        sig = ws / "runs" / "wait-signal-kunglao-worker.json"
        assert sig.exists(), (
            "a dispatch targeting a waiting worker must write the wake "
            f"signal; stderr={r.stderr!r}")
        data = json.loads(sig.read_text(encoding="utf-8"))
        assert data.get("claim") == "C-1"
        assert data.get("ts"), "signal must carry a ts field"

    def test_no_waiting_worker_no_signal(self, tmp_path):
        root = tmp_path / "r2"
        ws = _mk_ws(root)
        r = _run_gate(root, ws)
        assert r.returncode == 0
        assert not (ws / "runs" / "wait-signal-kunglao-worker.json").exists()

    def test_in_progress_ledger_no_signal(self, tmp_path):
        root = tmp_path / "r3"
        ws = _mk_ws(root)
        _waiting_ledger(ws, last="in-progress")
        r = _run_gate(root, ws)
        assert r.returncode == 0
        assert not (ws / "runs" / "wait-signal-kunglao-worker.json").exists()

    def test_other_agent_target_no_signal(self, tmp_path):
        root = tmp_path / "r4"
        ws = _mk_ws(root)
        _waiting_ledger(ws)  # waiting, but for kunglao-worker
        r = _run_gate(root, ws, agent="ghidra-light")
        assert r.returncode == 0
        assert not (ws / "runs" / "wait-signal-ghidra-light.json").exists()

    def test_plugin_qualified_agent_id_matches_bare_ledger(self, tmp_path):
        root = tmp_path / "r5"
        ws = _mk_ws(root)
        _waiting_ledger(ws)  # ledger keyed on the bare agent name
        r = _run_gate(root, ws, agent="kunglao-agent:kunglao-worker")
        assert r.returncode == 0
        sig = ws / "runs" / "wait-signal-kunglao-worker.json"
        assert sig.exists(), (
            "a plugin-qualified dispatch id must match the bare-id waiting "
            f"ledger; stderr={r.stderr!r}")


# ---------- worker pulse: waiting is not a zombie ----------

def _pulse_ws(path: Path, body: str) -> Path:
    path.mkdir(parents=True)
    (path / "runs").mkdir()
    (path / "claim-register.yaml").write_text(
        "claims:\n- id: C-203\n  status: OPEN\n", encoding="utf-8")
    (path / "runs" / "worker-status-W-1.md").write_text(body, encoding="utf-8")
    write_hook_state(path, active_hooks=["worker_pulse"],
                     phase="test", tier="none", user_override={},
                     expires_at=None)
    return path


def _run_pulse(ws: Path) -> str:
    payload = json.dumps({
        "hookEventName": "PostToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": "[T1 tools=basic] claim C-203: grep chemistry strings"},
    })
    r = subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "worker_pulse.py")],
        input=payload, capture_output=True, encoding="utf-8",
        errors="replace", env={"PYTHONIOENCODING": "utf-8", **os.environ},
        cwd=str(ROOT), timeout=120,
    )
    return (r.stdout or "") + (r.stderr or "")


class TestPulseSkipsWaiting:
    def test_done_then_waiting_gets_no_taskstop(self, tmp_path):
        ws = _pulse_ws(tmp_path / "wait",
                       "[12:00] step: work done | status: done\n"
                       "[12:31] wait: awaiting signal | status: waiting\n")
        out = _run_pulse(ws)
        assert "TASKSTOP" not in out, (
            "a waiting worker re-arms on the next dispatch — it is not a "
            f"zombie and must not be reminded for TaskStop. Got:\n{out}")

    def test_done_control_still_reminds(self, tmp_path):
        ws = _pulse_ws(tmp_path / "done",
                       "[12:00] step: work done | status: done\n")
        out = _run_pulse(ws)
        assert "TASKSTOP:" in out, (
            f"the #88 D1 delivery reminder must keep firing on done. Got:\n{out}")


# ---------- heartbeat noop breaker: all-waiting is healthy idle ----------

from heartbeat_tick import noop_breaker  # noqa: E402  (scripts import root)


class TestNoopBreakerWaitingExemption:
    def test_fingerprint_stable_all_waiting_no_trip(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "worker-status-kunglao-worker.md").write_text(
            "[12:00] step: delivered | status: done\n"
            "[12:31] wait: awaiting signal | status: waiting\n",
            encoding="utf-8")
        h = "a" * 64
        r1 = noop_breaker(ws, h, threshold=2)
        assert r1["tripped"] is False
        r2 = noop_breaker(ws, h, threshold=2)
        assert r2["tripped"] is False, (
            "stable fingerprint + zero active + waiting workers = idle "
            f"spin-down; the breaker must not trip. Got {r2}")
        assert r2.get("reason") == "all-workers-waiting"

    def test_no_workers_control_still_trips(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        h = "a" * 64
        for _ in range(2):
            r = noop_breaker(ws, h, threshold=2)
        assert r["tripped"] is True

    def test_active_worker_control_still_trips(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "worker-status-w-live.md").write_text(
            "[12:00] step: grinding | status: in-progress\n",
            encoding="utf-8")
        h = "a" * 64
        for _ in range(2):
            r = noop_breaker(ws, h, threshold=2)
        assert r["tripped"] is True
