# -*- coding: utf-8 -*-
"""Template contracts + Stop-hook second-stop adjudication.

- Templates (issue #201): the delivery gate (#204) needs task_spec to
  declare calibration, and the second-stop persistent adjudication
  (#199/#200) needs a standard task-oracle shape. These tests pin the
  TEMPLATES so the contract cannot drift from the enforcing code.
- Second stop (issue #199): the Stop shim must not pass through just
  because the payload carries stop_hook_active=true — the decision is
  delegated to the oracle's persistent adjudication.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_hook():
    """Load hooks/completion_gate.py under a unique name (avoid the
    sys.modules clash with scripts/completion_gate.py — same pattern as
    tests/test_completion_gate.py::_load_hook_module)."""
    name = "completion_gate_hook"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "hooks" / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def test_task_spec_template_declares_calibration_requirement():
    """Batch 1 acceptance: task_spec template must declare calibration
    (confidence + falsifier) so the delivery gate can enforce it."""
    import yaml

    text = (ROOT / "templates/state/task_spec.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    cal = data.get("calibration", {})
    assert cal.get("require_confidence", False) is True
    assert cal.get("require_falsifier", False) is True


def test_task_oracle_template_has_persistent_adjudication():
    """Task oracle template must carry the persistent adjudication fields
    (second-stop anti-loop lives here, not in the shim)."""
    import yaml

    data = yaml.safe_load((ROOT / "templates/state/task-oracle.yaml").read_text(encoding="utf-8"))
    adj = data.get("adjudication", {})
    assert "stop_hook_active" in adj
    assert "second_stop" in adj.get("stop_hook_active", {})


# =====================================================================
# Second-stop oracle adjudication (issue #199)
# =====================================================================

def _activated_state(ws: Path) -> None:
    """Write .hook_state.json that is_active_strict accepts for completion_gate
    (real schema: ts/tier/phase/active_hooks/paused_hooks/user_override/expires_at)."""
    import datetime as dt
    import json

    expires = (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(minutes=30)
               ).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": "2026-08-13T00:00:00Z",
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["completion_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires,
    }, indent=2), encoding="utf-8")


def test_second_stop_pass_requires_oracle_second_stop_marker(tmp_path):
    """Second stop may pass ONLY when the oracle's persistent adjudication
    says second_stop: true AND last_decision == PASS (user-level override
    recorded in the oracle file)."""
    import yaml

    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    oracle = {
        "task_text": "analyze the payload",
        "open_items": [],
        "adjudication": {"stop_hook_active": {"second_stop": True,
                                               "last_decision": "PASS"}},
    }
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False), encoding="utf-8"
    )
    payload = {"cwd": str(ws), "workspace": str(ws), "stop_hook_active": True}
    rc = _load_hook().process_event(payload)
    assert rc == 0, f"oracle-sanctioned second stop must pass, got {rc}"


def test_second_stop_without_oracle_sanction_blocks(tmp_path):
    """No oracle sanction (second_stop: false) → second stop must block."""
    import yaml

    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    oracle = {
        "task_text": "analyze the payload",
        "open_items": [],
        "adjudication": {"stop_hook_active": {"second_stop": False,
                                               "last_decision": "BLOCK"}},
    }
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False), encoding="utf-8"
    )
    payload = {"cwd": str(ws), "workspace": str(ws), "stop_hook_active": True}
    rc = _load_hook().process_event(payload)
    assert rc != 0, "unsanctioned second stop must block"


# =====================================================================
# No-oracle tightening (issue #200)
# =====================================================================

def test_activated_workspace_without_oracle_blocks(tmp_path):
    """An ACTIVATED workspace (claim-register marker + hook_state) without a
    task oracle must NOT silently pass — no-oracle is not a pass signal."""
    import yaml

    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": []}, sort_keys=False), encoding="utf-8"
    )
    payload = {"cwd": str(ws), "workspace": str(ws)}
    rc = _load_hook().process_event(payload)
    assert rc != 0, "activated workspace without oracle must block"


def test_unactivated_dir_without_oracle_still_passes(tmp_path):
    """A directory with NO workspace markers at all must still pass (D9:
    non-kunglao sessions get zero noise from the gate)."""
    plain = tmp_path / "plain"
    plain.mkdir()
    rc = _load_hook().process_event({"cwd": str(plain)})
    assert rc == 0, "no markers -> D9 pass-through must hold"
