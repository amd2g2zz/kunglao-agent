# -*- coding: utf-8 -*-
"""TDD RED — tests for scripts/completion_gate.py + hooks/completion_gate.py (#55).

The code-owned completion gate makes "done" a CODE verdict. judge(oracle)
returns one of 4 exit codes (0 pass / 1 incomplete / 2 unsigned defer / 3
task_text missing) from a pre-registered task-oracle.yaml. The Stop hook shim
activation-gates + FAIL_OPEN + emits a block decision.

The regression fixture (REGRESSION_ORACLE) is built from issue #55's
2026-08-11 table (G4/G5/G6/#10/#11/#12) — SYNTHETIC test data (a quoted issue
table), not live user data. The gate reads only the oracle YAML (+ optional
declaration text); no workspace state, no network.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
HOOKS = _HERE.parent / "hooks"
sys.path.insert(0, str(SCRIPTS))

import completion_gate as cg  # noqa: E402  (scripts/ on sys.path)


# ---------------------------------------------------------------------------
# Helpers — oracle builders (synthetic; built from issue #55's 2026-08-11 table)
# ---------------------------------------------------------------------------

REGRESSION_TASK_TEXT = (
    "重检测当前分析是否存在矛盾、遗漏和gap。如果存在就需要继续全面分析"
)


def _regression_oracle():
    """The 2026-08-11 session oracle (issue #55 acceptance 2). 6 unsigned
    open_items, zero defers, task_text with the 全面分析 keyword."""
    return {
        "task_text": REGRESSION_TASK_TEXT,
        "acceptance": [
            "every gap G1-G6 closed or explicitly user-deferred",
            "no item re-tiered to a level absent from task_text",
        ],
        "open_items": [
            {"id": "G4", "desc": "SetupFromBytes persistence path @0x1402ef400 unresolved in CF-3",
             "closed_by": "", "closed_at": ""},
            {"id": "G5", "desc": "dead string 'persistence is not enabled on this client' @0x14060e95d unresolved",
             "closed_by": "", "closed_at": ""},
            {"id": "G6", "desc": "3 RCA fixes not filed as issues",
             "closed_by": "", "closed_at": ""},
            {"id": "#10", "desc": "F039 refuted parenthetical not propagated",
             "closed_by": "", "closed_at": ""},
            {"id": "#11", "desc": "26 pre-existing lint errors",
             "closed_by": "", "closed_at": ""},
            {"id": "#12", "desc": "F003 self-deleted string xref not checked",
             "closed_by": "", "closed_at": ""},
        ],
        "deferrals": [],
    }


def _all_closed_oracle():
    o = _regression_oracle()
    for i, item in enumerate(o["open_items"], 1):
        item["closed_by"] = f"commit {i:04d}"
        item["closed_at"] = f"2026-08-11T12:0{i}:00Z"
    return o


def _judge(oracle, declaration_text=None):
    """Convenience: cg.judge returns (exit_code, reason); return both."""
    return cg.judge(oracle, declaration_text=declaration_text)


# ---------------------------------------------------------------------------
# (1) The 4 exit-path tests
# ---------------------------------------------------------------------------

def test_exit0_all_closed():
    code, reason = _judge(_all_closed_oracle())
    assert code == 0, reason
    assert "PASS" in reason.upper(), reason


def test_exit1_regression_2026_08_11():
    """Acceptance 2: the 2026-08-11 replay MUST exit 1 + name all 6 items."""
    code, reason = _judge(_regression_oracle())
    assert code == 1, f"expected exit 1 (6 unsigned items), got {code}: {reason}"
    for item_id in ("G4", "G5", "G6", "#10", "#11", "#12"):
        assert item_id in reason, f"reason must name unclosed item {item_id}: {reason}"


def test_exit2_agent_self_signed_defer():
    """Acceptance 4 negative: agent self-signed defer → exit 2."""
    oracle = {
        "task_text": "do X",
        "open_items": [{"id": "A", "desc": "item A", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "A", "authorized_by": "agent", "reason": "out of scope"}],
    }
    code, reason = _judge(oracle)
    assert code == 2, f"expected exit 2 (agent self-signed defer), got {code}: {reason}"
    assert "A" in reason


def test_exit3_none_oracle():
    code, reason = _judge(None)
    assert code == 3, f"expected exit 3 (None oracle), got {code}: {reason}"


def test_exit3_empty_task_text():
    code, reason = _judge({})
    assert code == 3, f"expected exit 3 (empty oracle), got {code}: {reason}"


def test_exit3_whitespace_task_text():
    code, reason = _judge({"task_text": "   \t  "})
    assert code == 3, f"expected exit 3 (whitespace task_text), got {code}: {reason}"


# ---------------------------------------------------------------------------
# (2) User-vs-agent signature discrimination (mechanical deny-list)
# ---------------------------------------------------------------------------

def test_user_signed_defer_passes():
    """Acceptance 4 positive: authorized_by='用户' resolves the item → exit 0."""
    oracle = {
        "task_text": "do X",
        "open_items": [{"id": "A", "desc": "item A", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "A", "authorized_by": "用户", "reason": "user said A 不用查"}],
    }
    code, reason = _judge(oracle)
    assert code == 0, f"expected exit 0 (user-signed defer), got {code}: {reason}"


def test_exit2_empty_authorized_by():
    oracle = {
        "task_text": "do X",
        "open_items": [{"id": "A", "desc": "item A", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "A", "authorized_by": "", "reason": "skipped"}],
    }
    code, _ = _judge(oracle)
    assert code == 2


def test_source_agent_overrides_user_like_authorized_by():
    """source='agent' rejects even when authorized_by looks user-like ('hr')."""
    oracle = {
        "task_text": "do X",
        "open_items": [{"id": "A", "desc": "item A", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "A", "authorized_by": "hr", "source": "agent", "reason": "skip"}],
    }
    code, _ = _judge(oracle)
    assert code == 2


@pytest.mark.parametrize("agent_id", [
    "agent", "claude", "ai", "self", "assistant", "llm", "kunglao",
    "worker", "verifier", "orchestrator", "auto", "system", "bot", "me",
])
def test_agent_identifiers_all_rejected(agent_id):
    oracle = {
        "task_text": "do X",
        "open_items": [{"id": "A", "desc": "A", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "A", "authorized_by": agent_id, "reason": "skip"}],
    }
    code, _ = _judge(oracle)
    assert code == 2, f"authorized_by={agent_id!r} must be rejected (exit 2)"


# ---------------------------------------------------------------------------
# (3) Precedence: exit 3 > exit 2 > exit 1 > exit 0
# ---------------------------------------------------------------------------

def test_precedence_exit2_wins_over_exit1():
    """Unsigned defer (A) + unresolved item (B) → exit 2 (the diagnostic signal)."""
    oracle = {
        "task_text": "do X",
        "open_items": [
            {"id": "A", "desc": "A", "closed_by": "", "closed_at": ""},
            {"id": "B", "desc": "B", "closed_by": "", "closed_at": ""},
        ],
        "deferrals": [{"item": "A", "authorized_by": "claude", "reason": "skip"}],
    }
    code, reason = _judge(oracle)
    assert code == 2, f"expected exit 2 (precedence over exit 1), got {code}: {reason}"


def test_precedence_exit3_wins_over_exit2():
    """Empty task_text + an unsigned defer → exit 3 (no anchor wins)."""
    oracle = {
        "task_text": "",
        "open_items": [{"id": "A", "desc": "A", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "A", "authorized_by": "agent", "reason": "skip"}],
    }
    code, _ = _judge(oracle)
    assert code == 3


# ---------------------------------------------------------------------------
# (4) "全面/comprehensive" extended check
# ---------------------------------------------------------------------------

def test_comprehensive_keyword_in_reason():
    """2026-08-11 task_text (全面分析) → exit 1 + reason carries 全面/comprehensive."""
    code, reason = _judge(_regression_oracle())
    assert code == 1
    assert ("全面" in reason) or ("comprehensive" in reason.lower()), reason


def test_comprehensive_rejects_tier_language_defer():
    """全面 task_text + defer reason '备注级' → exit 2 (self-invented tier)."""
    oracle = {
        "task_text": "全面分析 the gaps",
        "open_items": [{"id": "G4", "desc": "G4", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "G4", "authorized_by": "用户", "reason": "G4 备注级"}],
    }
    code, _ = _judge(oracle)
    assert code == 2, "备注级 tier term must mark the defer self-invented under 全面"


def test_comprehensive_keeps_genuine_user_defer():
    """全面 task_text + defer reason '不用查' → exit 0 (genuine user decision)."""
    oracle = {
        "task_text": "全面分析 the gaps",
        "open_items": [{"id": "G5", "desc": "G5", "closed_by": "", "closed_at": ""}],
        "deferrals": [{"item": "G5", "authorized_by": "用户", "reason": "G5 不用查"}],
    }
    code, reason = _judge(oracle)
    assert code == 0, f"不用查 is a user decision, not a tier term: {reason}"


# ---------------------------------------------------------------------------
# (5) CLI — exit code == exit_code field; JSON well-formed
# ---------------------------------------------------------------------------

def _write_oracle_yaml(tmp_path, name, oracle_dict):
    import yaml
    p = tmp_path / name
    p.write_text(yaml.safe_dump(oracle_dict, allow_unicode=True), encoding="utf-8")
    return p


def test_cli_all_closed_exits_0(tmp_path):
    p = _write_oracle_yaml(tmp_path, "oracle.yaml", _all_closed_oracle())
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "completion_gate.py"), str(p)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["exit_code"] == 0


def test_cli_regression_exits_1(tmp_path):
    p = _write_oracle_yaml(tmp_path, "oracle.yaml", _regression_oracle())
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "completion_gate.py"), str(p)],
        capture_output=True, text=True,
    )
    assert r.returncode == 1, r.stderr
    out = json.loads(r.stdout)
    assert out["exit_code"] == 1
    for item_id in ("G4", "G5", "G6", "#10", "#11", "#12"):
        assert item_id in out["reason"]


def test_cli_missing_file_exits_3(tmp_path):
    missing = tmp_path / "nope.yaml"
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "completion_gate.py"), str(missing)],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, r.stderr
    # missing oracle → exit 3 (refuse self-anchor); clear message on stderr or stdout
    combined = (r.stdout + r.stderr).lower()
    assert ("oracle" in combined) or ("anchor" in combined) or ("missing" in combined)


# ---------------------------------------------------------------------------
# (6) #54 integration — optional reason-enhancement via declaration_text
# ---------------------------------------------------------------------------

def test_premature_termination_fingerprint_folding():
    """When declaration_text is supplied AND exit 1 fires, the reason folds in
    #54's fingerprint ids (D4 — optional reason-enhancement, not a separate code)."""
    declaration = (
        "Substantive task complete. Stopping here is appropriate. "
        "G4 备注级（记录即可）. Cost ~$52.85 — informational. "
        "Deferred (#10 #11 #12) — queued."
    )
    code, reason = _judge(_regression_oracle(), declaration_text=declaration)
    assert code == 1  # oracle-driven; declaration does NOT change the code
    # the folded fingerprint ids appear in the reason (corroborating color)
    assert ("F1" in reason) or ("F2" in reason) or ("F3" in reason) or ("F4" in reason), reason


# ---------------------------------------------------------------------------
# (7) Module docstring cross-references #43, #44, #54
# ---------------------------------------------------------------------------

def test_module_docstring_cross_references_43_44_54():
    doc = cg.__doc__ or ""
    assert "#43" in doc, "module docstring must name #43 (runtime drift)"
    assert "#44" in doc, "module docstring must name #44 (per-turn anchor)"
    assert "#54" in doc, "module docstring must name #54 (declaration detector)"


# ---------------------------------------------------------------------------
# (8) Stop-hook shim — activation gate, FAIL_OPEN, block decision, anti-loop
# ---------------------------------------------------------------------------

def _load_hook_module():
    """Load hooks/completion_gate.py under a unique name (avoid clash with the
    scripts/ module of the same basename)."""
    name = "completion_gate_hook"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _activated_state(ws: Path):
    """Write a .hook_state.json that strict-activates completion_gate."""
    import datetime as dt
    expires = (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(minutes=30)
               ).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": "2026-08-11T12:00:00Z",
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["completion_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires,
    }), encoding="utf-8")


def _run_hook(ws: Path, stop_hook_active=False):
    """Invoke hooks/completion_gate.py::main with a synthetic Stop payload."""
    mod = _load_hook_module()
    payload = {
        "hook_event_name": "Stop",
        "session_id": "test",
        "cwd": str(ws),
        "stop_hook_active": stop_hook_active,
    }
    import io
    return mod.main(io.StringIO(json.dumps(payload)))


def _hook_stdout(ws: Path, stop_hook_active=False):
    """Run the shim, capturing its stdout (the block-decision JSON or empty)."""
    mod = _load_hook_module()
    payload = {
        "hook_event_name": "Stop",
        "session_id": "test",
        "cwd": str(ws),
        "stop_hook_active": stop_hook_active,
    }
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main(io.StringIO(json.dumps(payload)))
    return rc, buf.getvalue()


def test_stop_not_activated_passthrough(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_oracle_yaml(ws, "task-oracle.yaml", _regression_oracle())
    # no .hook_state.json → not activated → pass-through
    rc, out = _hook_stdout(ws)
    assert rc == 0
    assert out.strip() == ""


def test_stop_activated_blocks_exit1(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_oracle_yaml(ws, "task-oracle.yaml", _regression_oracle())
    _activated_state(ws)
    rc, out = _hook_stdout(ws, stop_hook_active=False)
    assert rc != 0, "activated + unsatisfied oracle must block (non-zero exit)"
    decision = json.loads(out)
    assert decision["decision"] == "block"
    for item_id in ("G4", "G5", "G6", "#10", "#11", "#12"):
        assert item_id in decision["reason"], decision["reason"]


def test_stop_stop_hook_active_passthrough(tmp_path):
    """Anti-loop (#199): stop_hook_active=True passes ONLY when the oracle
    records a sanctioned second stop (adjudication.second_stop + PASS)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    oracle = _regression_oracle()
    oracle["adjudication"] = {"stop_hook_active": {
        "second_stop": True, "last_decision": "PASS"}}
    _write_oracle_yaml(ws, "task-oracle.yaml", oracle)
    _activated_state(ws)
    rc, out = _hook_stdout(ws, stop_hook_active=True)
    assert rc == 0
    assert out.strip() == ""


def test_stop_stop_hook_active_without_sanction_blocks(tmp_path):
    """Anti-loop (#199): stop_hook_active=True WITHOUT a sanctioned PASS on
    record must block (the unconditional pass-through is gone)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_oracle_yaml(ws, "task-oracle.yaml", _regression_oracle())
    _activated_state(ws)
    rc, out = _hook_stdout(ws, stop_hook_active=True)
    assert rc != 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "second stop without oracle sanction" in decision["reason"]


def test_stop_malformed_oracle_blocks_exit3(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task-oracle.yaml").write_text(
        "task_text: ''\nopen_items: []\ndeferrals: []\n", encoding="utf-8")
    _activated_state(ws)
    rc, out = _hook_stdout(ws, stop_hook_active=False)
    assert rc != 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert ("anchor" in decision["reason"].lower()) or ("task_text" in decision["reason"].lower())


def test_stop_activated_no_oracle_blocks(tmp_path):
    """#200: activated + no oracle file → block exit 3 (a kunglao workspace
    must be pre-anchored at Phase 0; the old no-oracle pass-through was the
    replay #4 fail-open half). D9 pass-through now applies only to
    directories with NO workspace markers."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _activated_state(ws)
    rc, out = _hook_stdout(ws, stop_hook_active=False)
    assert rc != 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "task-oracle" in decision["reason"]


# ---------------------------------------------------------------------------
# (9) wire_up_settings Stop section + ALL_HOOKS membership
# ---------------------------------------------------------------------------

def _patch_home(tmp_path, monkeypatch):
    """Mirror tests/test_state_anchor.py — never touch real ~/.claude."""
    import pathlib
    fake_home = tmp_path / "fake-home"
    (fake_home / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pathlib.Path, "home", lambda: fake_home)
    return fake_home


def test_all_hooks_contains_completion_gate():
    import hook_activation as ha
    assert "completion_gate" in ha.ALL_HOOKS


def test_wire_up_registers_stop_completion_gate(tmp_path, monkeypatch):
    fake_home = _patch_home(tmp_path, monkeypatch)
    from wire_up_settings import wire_up_settings
    wire_up_settings()
    settings_path = fake_home / ".claude" / "settings.json"
    assert settings_path.exists(), "wire_up_settings must write settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    stop = settings.get("hooks", {}).get("Stop", [])
    found = False
    for entry in stop:
        for h in entry.get("hooks", []):
            cmd = str(h.get("command", ""))
            if cmd.replace("\\", "/").rsplit("/", 1)[-1] == "completion_gate.py":
                found = True
    assert found, "Stop must register hooks/completion_gate.py"


def test_wire_up_stop_idempotent(tmp_path, monkeypatch):
    fake_home = _patch_home(tmp_path, monkeypatch)
    from wire_up_settings import wire_up_settings
    wire_up_settings()
    wire_up_settings()  # re-run — must be a fixed point
    settings_path = fake_home / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    stop = settings.get("hooks", {}).get("Stop", [])
    n = 0
    for entry in stop:
        for h in entry.get("hooks", []):
            cmd = str(h.get("command", ""))
            if cmd.replace("\\", "/").rsplit("/", 1)[-1] == "completion_gate.py":
                n += 1
    assert n == 1, f"completion_gate must register exactly once under Stop (got {n})"
