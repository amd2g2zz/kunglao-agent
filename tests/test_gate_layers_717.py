# -*- coding: utf-8 -*-
"""#717 regression: the sample-incident-01 0.1.2 incident, replayed as fixtures.

The incident (v0.1.2 field run 2026-08-25, 4h): a real workspace ended
cleanly with FIVE open OC items because three independent gate layers
each failed silently:

  L1  is_active_strict('completion_gate') returned False on a state file
      whose active_hooks omitted the gate (["active_intervention"]) — so
      the ALWAYS_ARMED Stop gate never fired, contradicting the
      ALWAYS_ARMED_HOOKS contract next to its definition.
  L2  hooks/completion_gate.py FAIL_OPEN'd on the oracle's L7 ScannerError
      (bare scalar with inner colon) — unparseable YAML passed through.
  L3  judge() silently skipped non-dict open_items/deferrals (isinstance
      guards) — five string items + one string defer produced PASS.

These tests pin all three layers with SYNTHETIC fixtures reproducing the
exact shapes from the incident workspace (quoted in issue #717). They are
deliberately independent of the live workspace, which may not exist on CI.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path


_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
HOOKS = _HERE.parent / "hooks"
sys.path.insert(0, str(SCRIPTS))

import completion_gate as cg  # noqa: E402
import hook_activation as ha  # noqa: E402
from _factories import write_hook_state

# The exact L7 defect: an unquoted scalar value containing "colon+space"
# (结构判定: 本地自损) — yaml.safe_load raises ScannerError "mapping values
# are not allowed here" at line 7 column 47, reproduced verbatim below.
BAD_ORACLE_L7 = """\
# task-oracle.yaml — pre-registered completion anchor (#55, #473).
task_text: "完整分析这个crash点分析产生原理，以及是否可以被利用。"
q1_verdict: PROVEN (C-100/F-100, final redteam QA CONFIRMED)
open_items:
  - "OC-1 本地复现(配置不匹配→崩溃) — 用户已有自然崩溃样本, 需定向复现"
  - "OC-2 对端可控性动态观察 — blocked-until-C015"
  - "OC-3 UAF 窗口测量"
  - "OC-4 远程 DoS — blocked-until-OC2"
  - "OC-5 写原语 — blocked-until-OC3"
deferrals:
  - "C-016 alloc-point enumeration — deferred to dynamic phase"
q2_verdict: PROVEN-layered (C-101/F-101 — 结构判定: 本地自损+对端间接影响+单一未闭合缺口)
registered_ts: 2026-08-25T16:25:36Z
"""


def _load_hook_module():
    name = "completion_gate_hook_717"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _live_state(ws: Path, active_hooks=("active_intervention",)):
    """Live activation omitting completion_gate - the incident shape."""
    write_hook_state(ws, active_hooks=list(active_hooks),
                     ts="2026-08-25T19:31:27Z", tier="advisory",
                     phase="IDLE", user_override={},
                     expires_minutes=30)

def test_l1_gate_fires_when_state_omits_it(tmp_path):
    """ALWAYS_ARMED membership alone activates the gate (init's always_arm
    guarantees the entry; the state file's active_hooks list is advisory)."""
    _live_state(tmp_path)
    assert ha.is_active_strict(tmp_path, "completion_gate") is True


def test_l1_override_off_still_sleeps(tmp_path):
    _live_state(tmp_path)
    state = json.loads((tmp_path / ".hook_state.json").read_text())
    state["user_override"] = {"completion_gate": "off"}
    (tmp_path / ".hook_state.json").write_text(json.dumps(state))
    assert ha.is_active_strict(tmp_path, "completion_gate") is False


def test_l1_pause_still_sleeps(tmp_path):
    _live_state(tmp_path)
    state = json.loads((tmp_path / ".hook_state.json").read_text())
    state["paused_hooks"] = ["completion_gate"]
    (tmp_path / ".hook_state.json").write_text(json.dumps(state))
    assert ha.is_active_strict(tmp_path, "completion_gate") is False


def test_l1_expired_still_sleeps(tmp_path):
    """Expiry is the liveness signal — ALWAYS_ARMED must not outlive it."""
    _live_state(tmp_path)
    state = json.loads((tmp_path / ".hook_state.json").read_text())
    state["expires_at"] = "2026-08-25T20:01:27Z"  # the incident timestamp
    (tmp_path / ".hook_state.json").write_text(json.dumps(state))
    assert ha.is_active_strict(tmp_path, "completion_gate") is False


def test_l1_non_armed_hook_still_requires_active_list(tmp_path):
    """The exemption is membership-scoped: an ordinary hook (worker_pulse)
    omitted from active_hooks must keep sleeping."""
    _live_state(tmp_path)
    assert ha.is_active_strict(tmp_path, "worker_pulse") is False


# ---------------------------------------------------------------------------
# L2 — shim BLOCKs (exit 3) on unparseable oracle YAML
# ---------------------------------------------------------------------------

def test_l2_unparseable_oracle_blocks(capsys, tmp_path):
    (tmp_path / "claim-register.yaml").write_text("# marker\n")
    _live_state(tmp_path)
    (tmp_path / "task-oracle.yaml").write_text(BAD_ORACLE_L7, encoding="utf-8")
    mod = _load_hook_module()
    payload = json.dumps({"hook_event_name": "Stop",
                          "session_id": "t", "cwd": str(tmp_path)})
    rc = mod.main(io.StringIO(payload))
    assert rc == 3, "bad YAML in an activated workspace must BLOCK, not pass"
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"
    assert "unparseable" in out["reason"]


def test_l2_transient_io_failure_still_fail_open(capsys, tmp_path, monkeypatch):
    """OSError (transient IO) stays FAIL_OPEN per the module contract — only
    YAMLError (corrupt content) fails closed."""
    (tmp_path / "claim-register.yaml").write_text("# marker\n")
    _live_state(tmp_path)
    (tmp_path / "task-oracle.yaml").write_text(
        "task_text: 'x'\n", encoding="utf-8")
    import yaml as _y
    real = _y.safe_load

    def _raise_io(*a, **k):
        raise OSError("disk hiccup")
    monkeypatch.setattr(_y, "safe_load", _raise_io)
    try:
        mod = _load_hook_module()
        payload = json.dumps({"hook_event_name": "Stop",
                              "session_id": "t", "cwd": str(tmp_path)})
        rc = mod.main(io.StringIO(payload))
        assert rc == 0
    finally:
        monkeypatch.setattr(_y, "safe_load", real)


# ---------------------------------------------------------------------------
# L3 — judge refuses to bless non-dict ledger entries
# ---------------------------------------------------------------------------

def test_l3_string_open_items_stay_unresolved():
    oracle = {
        "task_text": "task text",
        "open_items": ["OC-1 本地复现", "OC-2 对端动态观察"],
        "deferrals": [],
    }
    code, reason = cg.judge(oracle)
    assert code == 1, "string items are unresolved — must block completion"
    assert "2 unresolved" in reason


def test_l3_string_defer_is_unsigned():
    oracle = {
        "task_text": "task text",
        "open_items": [],
        "deferrals": ["C-016 alloc-point enumeration — deferred"],
    }
    code, _ = cg.judge(oracle)
    assert code == 2, "a string defer has no authorized_by — unsigned"


def test_l3_incident_full_shape_blocks():
    """The exact incident ledger: 5 string items + 1 string defer must NOT
    produce PASS (pre-#717 it returned PASS 0-resolved)."""
    oracle = {
        "task_text": "完整分析这个crash点分析产生原理，以及是否可以被利用。",
        "open_items": [
            "OC-1 本地复现(配置不匹配→崩溃) — 用户已有自然崩溃样本, 需定向复现",
            "OC-2 对端可控性动态观察 — blocked-until-C015",
            "OC-3 UAF 窗口测量",
            "OC-4 远程 DoS — blocked-until-OC2",
            "OC-5 写原语 — blocked-until-OC3",
        ],
        "deferrals": [
            "C-016 alloc-point enumeration — deferred to dynamic phase"],
    }
    code, reason = cg.judge(oracle)
    assert code in (1, 2), "the incident ledger must never PASS"
    assert "PASS" not in reason


def test_l3_wellformed_ledger_still_passes():
    """Guard the other direction: dict items closed + user-signed defers
    keep passing (the #717 change must not over-block)."""
    oracle = {
        "task_text": "task text",
        "open_items": [{"id": "OC-1", "closed_by": "F-100"}],
        "deferrals": [{"item": "OC-2", "authorized_by": "andy",
                       "source": "user", "reason": "not needed"}],
    }
    code, _ = cg.judge(oracle)
    assert code == 0


# ---------------------------------------------------------------------------
# End-to-end: the incident workspace shape must STOP being terminable
# ---------------------------------------------------------------------------

def test_e2e_incident_shape_end_to_end_blocks(capsys, tmp_path):
    """Live activation (gate omitted from active_hooks) + the exact L7
    oracle → the Stop shim must emit a block decision, exit 3."""
    (tmp_path / "claim-register.yaml").write_text("# marker\n")
    _live_state(tmp_path)  # L1 shape: gate omitted
    (tmp_path / "task-oracle.yaml").write_text(BAD_ORACLE_L7, encoding="utf-8")
    mod = _load_hook_module()
    payload = json.dumps({"hook_event_name": "Stop",
                          "session_id": "t", "cwd": str(tmp_path)})
    rc = mod.main(io.StringIO(payload))
    assert rc == 3
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"


# ---------------------------------------------------------------------------
# heartbeat_off dual criterion (#717 criterion 2)
# ---------------------------------------------------------------------------

def test_heartbeat_off_refuses_open_oracle(tmp_path, monkeypatch):
    """Teardown needs BOTH convergence AND a closed oracle. Convergence is
    stubbed to PASS; the oracle still has open items → refuse."""
    import heartbeat as hb
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / ".heartbeat.json").write_text("{}")
    monkeypatch.setattr(hb.subprocess, "run",
                        lambda *a, **k: __import__("types").SimpleNamespace(
                            returncode=0))
    (tmp_path / "task-oracle.yaml").write_text(
        "task_text: 'x'\nopen_items:\n  - 'OC-1 still open'\n",
        encoding="utf-8")
    rc = hb.heartbeat_off(tmp_path)
    assert rc == 1, "open oracle must refuse teardown"
    assert (tmp_path / "runs" / ".heartbeat.json").exists()


def test_heartbeat_off_refuses_missing_oracle(tmp_path, monkeypatch):
    import heartbeat as hb
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / ".heartbeat.json").write_text("{}")
    monkeypatch.setattr(hb.subprocess, "run",
                        lambda *a, **k: __import__("types").SimpleNamespace(
                            returncode=0))
    rc = hb.heartbeat_off(tmp_path)  # no task-oracle.yaml at all
    assert rc == 1
    assert (tmp_path / "runs" / ".heartbeat.json").exists()


def test_heartbeat_off_allows_closed_oracle(tmp_path, monkeypatch):
    import heartbeat as hb
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / ".heartbeat.json").write_text("{}")
    monkeypatch.setattr(hb.subprocess, "run",
                        lambda *a, **k: __import__("types").SimpleNamespace(
                            returncode=0))
    (tmp_path / "task-oracle.yaml").write_text(
        "task_text: 'x'\nopen_items:\n  - id: OC-1\n    closed_by: F-100\n",
        encoding="utf-8")
    rc = hb.heartbeat_off(tmp_path)
    assert rc == 0
    assert not (tmp_path / "runs" / ".heartbeat.json").exists()


def test_heartbeat_off_force_bypasses_oracle(tmp_path, monkeypatch):
    """--force stays the explicit operator override for both criteria."""
    import heartbeat as hb
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / ".heartbeat.json").write_text("{}")
    rc = hb.heartbeat_off(tmp_path, force=True)  # no oracle, not converged
    assert rc == 0
