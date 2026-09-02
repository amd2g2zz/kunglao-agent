# -*- coding: utf-8 -*-
"""tests/test_issue454_wiring_transparency.py — wiring != activation (#454).

Both wiring surfaces print an "OK ... wired" line that previously read as
armed — but wired hooks are DORMANT by design (v1.9.7 default-inactive:
hooks/dispatch_gate.py _kunglao_active — no .hook_state.json -> hooks sleep;
the orchestrator activates at Phase 0 and renews the 30-min TTL via --renew).
Each surface must STATE that in its output (#454 acceptance: "init 输出含
hook 激活语义说明 (wired ≠ active)").

Boundary: #445 owns the post-registration self-CHECK; #454 owns ONLY the
dormant-semantics copy at the two wiring surfaces.

#455 target-alignment: init refuses to proceed without an explicit
--type / --resolve (sniff is NOT a default by design) — the test passes
--type windows for the canonical PE sample.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


def _assert_dormant_semantics(out: str) -> None:
    """#454: wired-but-dormant (TTL activation) semantics, surface-agnostic."""
    low = out.lower()
    assert "wired" in low, f"wiring line missing: {out}"
    assert "dormant" in low, f"wired-but-DORMANT state not stated: {out}"
    # activation is orchestrator-owned (Phase 0), never implied by wiring
    assert "phase 0" in low, f"activation owner (orchestrator Phase 0) not named: {out}"
    # TTL window + the renewal command that keeps it alive
    assert "ttl" in low or "30" in out, f"TTL window not named: {out}"
    assert "--renew" in out, f"renewal command (--renew) not named: {out}"


def _run_hook_activation(ws: Path, extra: list[str],
                         fake_home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(fake_home), "USERPROFILE": str(fake_home),
           "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "hook_activation.py"), str(ws), *extra],
        capture_output=True, text=True, timeout=120, env=env, errors="replace")


def test_wire_up_output_says_wired_but_dormant(tmp_path):
    """hook_activation.py --wire-up stdout: the OK/wired line must be
    followed by the dormant semantics — wiring registers hooks, activation
    is a separate orchestrator act (Phase 0 + TTL renewal)."""
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    r = _run_hook_activation(ws, ["--wire-up"], fake_home)
    assert r.returncode == 0, f"--wire-up failed: {r.stdout}{r.stderr}"
    assert "wired into" in r.stdout, f"wired OK line missing: {r.stdout}"
    _assert_dormant_semantics(r.stdout + r.stderr)


def test_init_hooks_output_says_wired_but_dormant(tmp_path):
    """kunglao-init hooks-deployed output carries the same dormant semantics
    (deploy_hooks path exercised via --hooks-json). #455 target-alignment:
    --type windows is required (sniff is never a default by design)."""
    ws = tmp_path / "ws"
    seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
    hooks_json = ws / "seeded-settings.json"
    hooks_json.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            "--skip-toolchain", "--type", "windows",
            "--hooks-json", str(hooks_json),
            "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                       env=env, errors="replace")
    assert r.returncode == 0, f"init failed: {r.stdout}{r.stderr}"
    out = r.stdout + r.stderr
    assert "hooks ->" in out, \
        f"hooks-deployed line missing (deploy path not taken?): {out}"
    _assert_dormant_semantics(out)
