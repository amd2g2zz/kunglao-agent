# -*- coding: utf-8 -*-
"""tests/test_init_handoff_593_598.py — #593+#598: init→runtime 机械交接.

RED (adjudicated): init ended with prose-only guidance — the heartbeat prompt
EMITTER existed (heartbeat_loop_prompt.build_prompt) but init never called it,
and the activation commands were prose in a print, not machine-actionable
output. Adjudicated fix (b) 保留红线: loop_registered stays false until the
first real tick; hooks stay dormant until orchestrator Phase-0 — but init now
EMITS the exact /loop prompt body + the exact --verify and --set-active
commands (mechanical handoff, no prose-only dead end).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def _load_bootstrap():
    """Load kunglao-init.py by path (CLI module; heavy top-level kept lazy)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_uut", ROOT / "scripts" / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_handoff_block_prints_loop_prompt_and_verify(tmp_path, capsys):
    mod = _load_bootstrap()
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    rc = mod.emit_activation_handoff(ws)
    out = capsys.readouterr().out
    assert rc == 0
    assert "--verify" in out, "the exact verify command must be printed"
    assert "--heartbeat-on" in out or "/loop" in out, "loop prompt body or command present"
    assert "--set-active" in out or "--tier" in out, "activation command present"


def test_handoff_references_real_prompt_builder(tmp_path, monkeypatch):
    """The handoff must call heartbeat_loop_prompt.build_prompt (the emitter),
    not re-embed a drifting copy of the prompt text."""
    mod = _load_bootstrap()
    import heartbeat_loop_prompt as hlp
    called = {}
    real = hlp.build_prompt
    monkeypatch.setattr(hlp, "build_prompt",
                        lambda ws, interval="5m": called.setdefault("x", True) or real(ws, interval))
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    mod.emit_activation_handoff(ws)
    assert called.get("x") is True, "build_prompt must be invoked"


def test_handoff_preserves_red_lines(tmp_path, capsys):
    """(b) 裁决: init must NOT flip loop_registered nor write .hook_state.json."""
    mod = _load_bootstrap()
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    mod.emit_activation_handoff(ws)
    capsys.readouterr()
    hb_path = ws / "runs" / ".heartbeat.json"
    hb = json.loads(hb_path.read_text(encoding="utf-8")) if hb_path.exists() else {}
    assert hb.get("loop_registered") is not True, "red line: init never fakes registration"
    assert not (ws / ".hook_state.json").exists(), "red line: init never self-activates"
