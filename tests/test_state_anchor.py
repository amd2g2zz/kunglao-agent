# -*- coding: utf-8 -*-
"""TDD RED — tests for hooks/state_anchor.py (issue #44, L1 PREVENT layer).

state_anchor is a PostToolUse(Agent) hook that injects a compact mechanical-
state signature (<=500 chars) into additionalContext on every worker
completion, plus a `WARNING: STATE FLAT` drift warning when drift_detected (#43).
FAIL_OPEN: any exception -> empty string, never raises.

All I/O is SYNTHETIC: pytest tmp_path workspaces only. The live workspace
(`<WORKSPACE_ROOT>/samples/<YYYY-MM-DD>/malware-analysis-workspace/`) is the
FORMAT reference only — never read or written.
"""
import importlib.util
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest
from _factories import write_hook_state

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"

# Load scripts/lib_kunglao.py by explicit path under the unique name — SAME
# loader as external_kicker.should_kick and tests/test_drift_detection.py.
# Under pytest, `import lib_kunglao` is ambiguous (hooks first in pythonpath);
# the explicit-path load is unambiguous in both prod and pytest. state_anchor
# reuses this exact loader so the hook and these tests share one instance.
_LIB_NAME = "lib_kunglao_scripts"


def load_scripts_lib() -> ModuleType:
    lib = sys.modules.get(_LIB_NAME)
    if lib is None:
        spec = importlib.util.spec_from_file_location(_LIB_NAME, SCRIPTS / "lib_kunglao.py")
        lib = importlib.util.module_from_spec(spec)
        sys.modules[_LIB_NAME] = lib
        spec.loader.exec_module(lib)
    return lib


_lib = load_scripts_lib()
ROTATION_WINDOW = _lib.ROTATION_WINDOW

def ts(minutes_ago: int = 0) -> str:
    # #375: compute AT CALL TIME — ledger `ts` is excluded from rotation
    # signatures, and expires_at / worker mtimes are compared against the
    # real clock by hook_activation.is_active_strict and
    # lib_kunglao.workers_progressing.
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def future_iso(minutes: int = 30) -> str:
    # #375: same per-call rule as ts() — expires_at is checked against
    # datetime.now() at hook-run time, not at test-module import.
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def snap(decision="DISPATCH", open_ids=None, *, open_count=None,
         partial_count=0, active_workers=0, blockers=None, facts_total=0,
         ts_str=None, **extra):
    """One synthetic SNAPSHOT ledger row (no `type` field -> defaults to SNAPSHOT)."""
    open_ids = list(open_ids or [])
    row = {"ts": ts_str or ts(), "decision": decision,
           "open_count": open_count if open_count is not None else len(open_ids),
           "open_ids": open_ids, "partial_count": partial_count,
           "active_workers": active_workers, "blockers": blockers or [],
           "facts_total": facts_total}
    row.update(extra)
    return row


def write_ledger(ws: Path, rows: list) -> Path:
    p = ws / ".convergence_ledger.jsonl"
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                 encoding="utf-8")
    return p


def write_register(ws: Path, claims: list) -> Path:
    lines = ["claims:"]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        lines.append(f"  status: {c.get('status', 'OPEN')}")
    return (ws / "claim-register.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_worker(ws: Path, minutes_ago: int, name="w1", status="in-progress") -> Path:
    # #375: stamp + mtime AT CALL TIME (workers_progressing compares mtimes
    # against its own real clock).
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    p = runs / f"worker-status-{name}.md"
    p.write_text(f"[{ts()}] step: x | status: {status}\n", encoding="utf-8")
    t = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(p, (t, t))
    return p


def activate(ws: Path, hook="state_anchor") -> Path:
    """Write .hook_state.json that is_active_strict accepts for `hook`."""
    write_hook_state(ws, active_hooks=[hook], ts=ts(), tier="none",
                     phase="IDLE", user_override={},
                     expires_at=future_iso(30))
    return ws


@pytest.fixture
def ws(tmp_path) -> Path:
    w = tmp_path / "ws"
    w.mkdir()
    return w


def _hook():
    """Import hooks/state_anchor.py fresh (RED: ImportError until it exists).

    hooks/ is on sys.path under pytest (pytest.ini pythonpath), so a bare
    `import state_anchor` resolves once the file exists.
    """
    sys.modules.pop("state_anchor", None)
    import state_anchor  # noqa: E402
    return state_anchor


# ===== (a) Agent completion -> anchor has last-row decision + open_count =====

def test_anchor_contains_ledger_decision_and_open_count(ws):
    write_ledger(ws, [
        snap("DISPATCH", ["C-001"], facts_total=10),
        snap("DISPATCH_VERIFIER", ["C-201", "C-003"], facts_total=12),
    ])
    mod = _hook()
    anchor = mod.build_anchor(ws)
    assert "DISPATCH_VERIFIER" in anchor          # last-row decision
    assert "open_count=2" in anchor or ("C-201" in anchor and "C-003" in anchor)


# ===== (b) rotation=4, no worker -> drift warning =====

def test_anchor_warns_on_drift_rotation_4_no_worker(ws):
    write_ledger(ws, [snap("DISPATCH", ["C-777"], active_workers=0, facts_total=12)
                      for _ in range(4)])
    mod = _hook()
    anchor = mod.build_anchor(ws)
    assert "WARNING: STATE FLAT" in anchor
    assert "STATE FLAT: 4 identical" in anchor    # rotation count N=4 in the warning


# ===== (c) FAIL_OPEN: missing + corrupt ledger -> "", never raises =====

def test_anchor_fail_open_missing_ledger(ws):
    mod = _hook()
    assert mod.build_anchor(ws) == ""              # no ledger at all


def test_anchor_fail_open_corrupt_ledger(ws):
    (ws / ".convergence_ledger.jsonl").write_text("not-json{\n", encoding="utf-8")
    mod = _hook()
    assert mod.build_anchor(ws) == ""


def test_anchor_fail_open_never_raises(ws):
    (ws / ".convergence_ledger.jsonl").write_text("not-json{\n", encoding="utf-8")
    mod = _hook()
    try:
        out = mod.build_anchor(ws)
    except Exception as exc:  # noqa: BLE001 — the point of the test
        pytest.fail(f"build_anchor raised on corrupt ledger: {exc!r}")
    assert out == ""


# ===== (d) non-agent tool -> skip (empty output, rc 0) =====

def test_hook_skips_non_agent_tools(ws, capsys):
    for tool in ("Bash", "Read"):
        write_ledger(ws, [snap("DISPATCH", ["C-001"])])
        activate(ws)
        mod = _hook()
        rc = mod.process_event({"tool_name": tool, "cwd": str(ws)})
        assert rc == 0
        assert capsys.readouterr().out == ""


# ===== Agent-tool completion injects additionalContext (worker_pulse shape) =====

def test_hook_emits_on_agent_tool(ws, capsys):
    write_ledger(ws, [snap("DISPATCH", ["C-201"], active_workers=1, facts_total=12)])
    activate(ws)
    mod = _hook()
    rc = mod.process_event({"tool_name": "Agent", "cwd": str(ws)})
    assert rc == 0
    out = capsys.readouterr().out
    assert out, "expected JSON emission for Agent tool"
    obj = json.loads(out)
    assert "hookSpecificOutput" in obj
    hso = obj["hookSpecificOutput"]
    assert hso.get("hookEventName") == "PostToolUse"
    assert "additionalContext" in hso
    ctx = hso["additionalContext"]
    assert "DISPATCH" in ctx


def test_hook_emits_on_agent_tool_case_insensitive(ws, capsys):
    write_ledger(ws, [snap("DISPATCH", ["C-201"])])
    activate(ws)
    mod = _hook()
    rc = mod.process_event({"tool_name": "AGENT", "cwd": str(ws)})
    assert rc == 0
    assert capsys.readouterr().out  # emitted despite uppercase


def test_hook_skips_when_not_activated(ws, capsys):
    write_ledger(ws, [snap("DISPATCH", ["C-201"])])
    # NO .hook_state.json -> is_active_strict False -> default-inactive
    mod = _hook()
    rc = mod.process_event({"tool_name": "Agent", "cwd": str(ws)})
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hook_skips_when_workspace_unresolvable(capsys, tmp_path):
    mod = _hook()
    rc = mod.process_event({"tool_name": "Agent",
                            "cwd": str(tmp_path / "nonexistent" / "path-xyz")})
    assert rc == 0
    assert capsys.readouterr().out == ""


def test_hook_fail_open_unparseable_stdin(capsys):
    mod = _hook()
    rc = mod.main(io.StringIO("not json{"))
    assert rc == 0
    assert capsys.readouterr().out == ""


# ===== truncation + narrative exclusion + worker-exemption =====

def test_anchor_truncates_at_500_chars(ws):
    rows = [snap("DISPATCH", [f"C-{i:03d}" for i in range(200)], facts_total=200)]
    write_ledger(ws, rows)
    write_register(ws, [{"id": f"C-{i:03d}", "status": "OPEN"} for i in range(200)])
    mod = _hook()
    anchor = mod.build_anchor(ws)
    assert len(anchor) <= 500


def test_anchor_excludes_progress_narrative(ws):
    write_ledger(ws, [snap("DISPATCH", ["C-007"], facts_total=12)])
    (ws / "progress.txt").write_text(
        "我正在分析 C-007，接下来准备做 VM detonation", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        "当前任务: 我正在分析 C-007 的反调试逻辑", encoding="utf-8")
    mod = _hook()
    anchor = mod.build_anchor(ws)
    assert "我正在分析 C-007" not in anchor
    assert "反调试" not in anchor


def test_fresh_worker_suppresses_drift_warning(ws):
    # 4 frozen rows BUT a fresh in-progress worker -> legitimate SATURATED
    write_ledger(ws, [snap("SATURATED", ["C-777"], active_workers=1, facts_total=12)
                      for _ in range(4)])
    write_worker(ws, minutes_ago=5)                # fresh in-progress worker
    mod = _hook()
    anchor = mod.build_anchor(ws)
    assert "STATE FLAT" not in anchor


def test_rotation_below_window_does_not_warn(ws):
    write_ledger(ws, [snap("DISPATCH", ["C-777"], facts_total=12),
                      snap("DISPATCH", ["C-777"], facts_total=12)])
    mod = _hook()
    anchor = mod.build_anchor(ws)
    assert "STATE FLAT" not in anchor


# ===== wire-up: PostToolUse(Agent) registration + ALL_HOOKS membership =====
#
# Since #258 the wire-up target is PROJECT-level: register_hooks(workspace=ws)
# writes <ws>/.claude/settings.json. Path.home() is still monkeypatched to a temp
# dir (env-var redirect is unreliable for Path.home() on Windows) as the regression
# probe that the user-global settings.json is NEVER written — the #258 hard
# constraint.

def _patch_home(tmp_path, monkeypatch):
    import pathlib
    fake_home = tmp_path / "fake-home"
    (fake_home / ".claude").mkdir(parents=True, exist_ok=True)
    # Path.home is a classmethod; patch the bound classmethod directly.
    monkeypatch.setattr(pathlib.Path, "home", lambda: fake_home)
    return fake_home


def test_all_hooks_contains_state_anchor():
    sys.path.insert(0, str(SCRIPTS))
    import hook_activation as ha
    assert "state_anchor" in ha.ALL_HOOKS


def test_wire_up_registers_state_anchor_postuse_agent(tmp_path, monkeypatch):
    fake_home = _patch_home(tmp_path, monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from hook_activation import register_hooks
    register_hooks(workspace=ws)
    settings_path = ws / ".claude" / "settings.json"
    assert settings_path.exists(), "wire_up_settings must write the PROJECT settings.json"
    assert not (fake_home / ".claude" / "settings.json").exists(), \
        "wire_up_settings must NOT write the user-global settings (#258)"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    post = settings.get("hooks", {}).get("PostToolUse", [])
    found = False
    for entry in post:
        if entry.get("matcher") != "Agent":
            continue
        for h in entry.get("hooks", []):
            cmd = str(h.get("command", ""))
            if cmd.replace("\\", "/").rsplit("/", 1)[-1] == "state_anchor.py":
                found = True
    assert found, "PostToolUse(Agent) must register state_anchor.py"


def test_wire_up_state_anchor_idempotent(tmp_path, monkeypatch):
    fake_home = _patch_home(tmp_path, monkeypatch)
    ws = tmp_path / "ws"
    ws.mkdir()
    sys.path.insert(0, str(SCRIPTS))
    from hook_activation import register_hooks
    register_hooks(workspace=ws)
    register_hooks(workspace=ws)  # re-run — must be a fixed point
    settings_path = ws / ".claude" / "settings.json"
    assert not (fake_home / ".claude" / "settings.json").exists()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    post = settings.get("hooks", {}).get("PostToolUse", [])
    n = 0
    for entry in post:
        if entry.get("matcher") != "Agent":
            continue
        for h in entry.get("hooks", []):
            cmd = str(h.get("command", ""))
            if cmd.replace("\\", "/").rsplit("/", 1)[-1] == "state_anchor.py":
                n += 1
    assert n == 1, f"state_anchor must register exactly once (got {n})"
