#!/usr/bin/env python3
"""hooks/completion_gate.py — Stop-hook shim for the code-owned completion gate (#55).

Thin wrapper around scripts/completion_gate.py::judge. Reads the Claude Code
Stop payload, resolves the workspace, strict-activates (mirrors
hooks/state_anchor.py #44), finds task-oracle.yaml, calls judge, and emits a
Stop-hook `{"decision": "block", "reason": "..."}` when judge returns non-zero.

Activation gating + FAIL_OPEN (design.md D8/D9):
  - not activated (no .hook_state.json / completion_gate not active / expired)
    → pass-through (exit 0, empty stdout)
  - activated + no task-oracle.yaml in the workspace
    → pass-through (D9: the gate is opt-in via oracle presence; the orchestrator
      registers the oracle at Phase 0 for any non-trivial task)
  - activated + oracle present + empty task_text → block with exit 3 (D6:
      malformed oracle is the genuine self-anchor fingerprint)
  - activated + oracle present + unsatisfied → block with exit 1/2
  - stop_hook_active=true in the payload → pass-through (anti-loop: after one
      block the agent gets a second stop attempt to fix the items / register a
      proper oracle; blocking forever would deadlock the session)
  - any exception → pass-through (FAIL_OPEN: a completion-gate failure must
      never deadlock the session)

Emits Claude Code Stop-hook JSON to block; empty stdout + exit 0 to pass. The
pure judge() function does NOT fail open (it returns exit 3 on bad input) —
only THIS shim does. Mirrors state_anchor's _resolve_workspace +
_kunglao_active + FAIL_OPEN structure (#44).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # kunglao-agent/
ORACLE_FILE = "task-oracle.yaml"


# ---------- workspace + activation (mirror hooks/state_anchor.py #44) ----------

def _resolve_workspace(payload: dict) -> Path | None:
    """First candidate with a task-oracle.yaml wins. The oracle is the gate's
    primary input, so its presence is the correct workspace marker."""
    cwd = Path(payload.get("cwd") or payload.get("workspace") or ".")
    for base in [cwd / "malware-analysis-workspace", cwd]:
        if (base / ORACLE_FILE).exists():
            return base
    return None


def _kunglao_active(ws: Path) -> bool:
    """Strict activation (default-inactive): the gate fires only if explicitly
    activated AND not expired. Mirrors worker_pulse / state_anchor (#44)."""
    if not (ws / ".hook_state.json").exists():
        return False
    try:
        sys.path.insert(0, str(SKILL_DIR / "scripts"))
        import hook_activation as ha
        return ha.is_active_strict(ws, "completion_gate")
    except Exception:  # noqa: BLE001 — never block on an activation-check error
        return False


def _load_judge():
    """Load scripts/completion_gate.py under a unique module name (avoid clash
    with this shim's basename). Cached in sys.modules for prod+test sharing."""
    name = "completion_gate_scripts"
    mod = sys.modules.get(name)
    if mod is not None:
        return mod
    spec = importlib.util.spec_from_file_location(
        name, SKILL_DIR / "scripts" / "completion_gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- the Stop-event core ----------

def process_event(payload: dict) -> int:
    """Testable core: anti-loop → workspace resolve → strict activation →
    load oracle → judge → emit block decision or pass through. Returns rc."""
    # anti-loop: stop_hook_active means the gate already blocked once; let the
    # agent's second stop attempt through so the session is not trapped.
    if payload.get("stop_hook_active"):
        return 0
    ws = _resolve_workspace(payload)
    if ws is None:
        return 0  # no oracle file → pass-through (D9)
    if not _kunglao_active(ws):
        return 0  # not activated → pass-through
    try:
        import yaml
        oracle = yaml.safe_load((ws / ORACLE_FILE).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — FAIL_OPEN on oracle read
        return 0
    try:
        cg = _load_judge()
        code, reason = cg.judge(oracle)
    except Exception:  # noqa: BLE001 — FAIL_OPEN on judge
        return 0
    if code == 0:
        return 0  # PASS — let the session end
    # non-zero → block termination with the unclosed-items reason
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return code


def main(stdin_stream=None) -> int:
    """Stop entry. Reads JSON payload from stdin (or stdin_stream for tests).
    FAIL_OPEN: unparseable stdin or any processing error → exit 0, empty
    stdout (never deadlock the session)."""
    try:
        stream = stdin_stream if stdin_stream is not None else sys.stdin
        data = stream.read()
        payload = json.loads(data) if data else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return 0
    try:
        return process_event(payload)
    except Exception:  # noqa: BLE001 — FAIL_OPEN at the body level
        return 0


if __name__ == "__main__":
    sys.exit(main())
