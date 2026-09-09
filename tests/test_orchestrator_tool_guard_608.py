# -*- coding: utf-8 -*-
"""tests/test_orchestrator_tool_guard_608.py — #608: the orchestrator running
analysis tools via Bash gets a signal, not silence.

RED (adjudicated): the Bash matcher carried only heartbeat_touch (exit 0
forever) — the orchestrator ran jadx directly in production (~7 min of
maker-checker violation, zero signal). Adjudicated fix (target-based + WARN,
#532-style arming): NEW hooks/orchestrator_tool_guard.py on PreToolUse/Bash —
command matches an analysis-binary pattern AND cwd is NOT inside a .wt-*
worker worktree → signal + kunglao_log event.
Workers (cwd inside .wt-*) pass silently. Registration: WIRE_UP_HOOK_FILES +
external_kicker._KICKER_SKIP_FILES (else the kicker import breaks).

POSTURE UPDATE (#57 gate 2, 2026-09): the owner ruling makes orchestrator
overreach framework-layer — violations REJECT with no opt-out — and the #601
precision fix removed the false-positive classes that motivated the WARN, so
the Bash face upgraded WARN → REJECT (rc 2 + repair path). Wrapper bypasses
(`sh -c 'jadx ...'`, nohup/timeout/env/xargs) are unwrapped; covered in
tests/test_framework_rigidity_57.py.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_guard():
    spec = importlib.util.spec_from_file_location(
        "orchestrator_tool_guard_uut", ROOT / "hooks" / "orchestrator_tool_guard.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_orchestrator_bash_jadx_gets_rejected(tmp_path):
    mod = _load_guard()
    ws = tmp_path / "ws"; ws.mkdir()
    rc, err, ctx = mod.evaluate({"cwd": str(ws), "tool_name": "Bash",
                                 "tool_input": {"command": "jadx -d out app.apk"}})
    assert rc == 2, "REJECT posture — orchestrator overreach is framework-layer (#57)"
    assert "REJECT orchestrator_tool_guard" in err, "stderr carries the verdict"
    assert ctx and "ispatch" in ctx, "repair path says: dispatch a worker"


def test_worker_in_worktree_passes_silently(tmp_path):
    mod = _load_guard()
    wt = tmp_path / ".wt-C100"; wt.mkdir()
    rc, err, ctx = mod.evaluate({"cwd": str(wt), "tool_name": "Bash",
                                 "tool_input": {"command": "jadx -d out app.apk"}})
    assert (rc, err, ctx) == (0, "", None), "workers dispatch analysis tools freely"


def test_unrelated_bash_untouched(tmp_path):
    mod = _load_guard()
    ws = tmp_path / "ws"; ws.mkdir()
    rc, err, ctx = mod.evaluate({"cwd": str(ws), "tool_name": "Bash",
                                 "tool_input": {"command": "ls -la"}})
    assert (rc, err, ctx) == (0, "", None)


def test_warn_leaves_event(tmp_path):
    mod = _load_guard()
    ws = tmp_path / "ws"; ws.mkdir()
    mod.evaluate({"cwd": str(ws), "tool_name": "Bash",
                  "tool_input": {"command": "apktool d app.apk"}})
    rows = []
    log = ws / "runs" / "logs"
    if log.exists():
        for f in sorted(log.glob("kunglao-*.jsonl")):
            rows += [json.loads(ln) for ln in f.read_text().splitlines() if ln.strip()]
    assert any(r["action"] == "orchestrator_tool_violation" for r in rows), \
        "the REJECT must also be durable"
    hits = [r for r in rows if r["action"] == "orchestrator_tool_violation"]
    assert hits[0].get("exit") == 2, "the durable row carries the rc"


def test_registered_in_wire_up_and_kicker_skip():
    wu = (ROOT / "scripts" / "wire_up_settings.py").read_text(encoding="utf-8")
    assert "orchestrator_tool_guard.py" in wu, "must be wired (PreToolUse/Bash)"
    ek = (ROOT / "scripts" / "external_kicker.py").read_text(encoding="utf-8")
    assert "orchestrator_tool_guard.py" in ek, \
        "must join _KICKER_SKIP_FILES — else kicker import-time registry check breaks"
