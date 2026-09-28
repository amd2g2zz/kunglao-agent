# -*- coding: utf-8 -*-
"""Tests for #412 — component activation truth: self-check + statusline.

RED-first contract (TDD):

1. scripts/hooks_selfcheck.py exposes component ACTIVATION checks (the
   `components` section of runs/.hooks-selfcheck.json):
   - hooks: wired AND armed (.hook_state.json — the v1.9.7 dormant-by-design
     state: missing/expired/empty-active = dormant, never armed);
   - scheduler: last-tick freshness (threshold = SCHEDULER_STALE_TICKS ticks
     x interval_min, derived from the heartbeat file);
   - mcp: registered per the #408 face + workspace approval state;
   - oracle / ledger presence (unified existing faces).
   Every failed check carries a remediation: auto-repair where allowed
   (hook rebuild, .mcp.json scaffold, approval flag), else a structured
   blocker naming the exact command/file.
2. scripts/statusline_snapshot.py extends the health set (hooks/mcp/
   scheduler) and reads THE SAME state file the self-check writes (single
   source of component truth). Dormant renders yellow (suspect), stale
   source renders STALE HARD — never green.
3. Exit contract: default rc is unchanged (hooks face); --strict exits 1 on
   any blocker (the init/upgrade closure face, #412).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hooks_selfcheck  # noqa: E402
import liveness_policy  # noqa: E402


# ---------- fixtures ----------

KONG = hooks_selfcheck.KONG_HOOK_FILES


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _wired_settings(ws: Path) -> None:
    settings = ws / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    hooks = []
    for hf in KONG:
        hooks.append({"matcher": "Bash", "hooks": [
            {"type": "command",
             "command": f"uv run --project /skill scripts/{hf}"}]})
    settings.write_text(json.dumps({"hooks": {"PreToolUse": hooks}}),
                        encoding="utf-8")


def _armed_state(ws: Path, minutes: int = 30, active: list[str] | None = None) -> None:
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": _iso(datetime.now(timezone.utc)),
        "active_hooks": KONG if active is None else active,
        "expires_at": _iso(datetime.now(timezone.utc)
                           + timedelta(minutes=minutes)),
    }), encoding="utf-8")


def _heartbeat(ws: Path, tick_age_s: int = 0, interval_min: int = 5) -> None:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    hb = ws / "runs" / ".heartbeat.json"
    hb.write_text(json.dumps({
        "started_ts": _iso(datetime.now(timezone.utc)),
        "last_tick_ts": _iso(datetime.now(timezone.utc)
                             - timedelta(seconds=tick_age_s)),
        "interval_min": interval_min,
    }), encoding="utf-8")
    old = time.time() - tick_age_s
    os.utime(hb, (old, old))


def _oracle(ws: Path, registered: bool = True) -> None:
    if not registered:
        return
    (ws / "task-oracle.yaml").write_text(
        "goal_verbatim: find the flag\n", encoding="utf-8")


def _ledger(ws: Path, present: bool = True) -> None:
    if not present:
        return
    (ws / "runs" / "logs").mkdir(parents=True, exist_ok=True)
    (ws / "runs" / "logs" / "kunglao-20260927.jsonl").write_text(
        '{"ts": "2026-09-27T00:00:00Z"}\n', encoding="utf-8")


@pytest.fixture
def healthy_ws(tmp_path: Path) -> Path:
    """Every component genuinely green — the post-#408 sanctioned shape:
    desktop HARD items registered in workspace scope + approval on."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    _wired_settings(ws)
    _armed_state(ws)
    _heartbeat(ws)
    _oracle(ws)
    _ledger(ws)
    (ws / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=windows\n", encoding="utf-8")
    (ws / ".mcp.json").write_text(json.dumps({"mcpServers": {
        "ghidra": {"command": "bridge"},
        "sequential-thinking": {"command": "npx"},
        "x64dbg": {"command": "x64dbg-automate-mcp"},
    }}), encoding="utf-8")
    settings = ws / ".claude" / "settings.json"
    merged = json.loads(settings.read_text(encoding="utf-8"))
    merged["enableAllProjectMcpServers"] = True
    settings.write_text(json.dumps(merged), encoding="utf-8")
    return ws


@pytest.fixture
def no_rebuild(monkeypatch):
    """Keep the self-check hermetic: the hook rebuild is a subprocess —
    monkeypatched out; tests that need it stub their own."""
    calls: list[Path] = []

    def fake_rebuild(ws: Path) -> dict:
        calls.append(ws)
        return {"rebuilt": True, "rc": 0}

    monkeypatch.setattr(hooks_selfcheck, "rebuild_project_level", fake_rebuild)
    return calls


# ---------- hooks component ----------

def test_hooks_armed_when_wired_and_active(healthy_ws):
    row = hooks_selfcheck.check_component_hooks(healthy_ws)
    assert row["ok"] is True and row["state"] == "armed"


def test_hooks_dormant_when_state_expired(healthy_ws):
    _armed_state(healthy_ws, minutes=-5)  # expired TTL
    row = hooks_selfcheck.check_component_hooks(healthy_ws)
    assert row["ok"] is False and row["state"] == "dormant"
    assert row["remediation"]["command"], "dormant names the renew command"


def test_hooks_dormant_when_state_file_missing(healthy_ws):
    (healthy_ws / ".hook_state.json").unlink()
    row = hooks_selfcheck.check_component_hooks(healthy_ws)
    assert row["ok"] is False and row["state"] == "dormant"


def test_hooks_dormant_when_active_set_empty(healthy_ws):
    _armed_state(healthy_ws, active=[])
    row = hooks_selfcheck.check_component_hooks(healthy_ws)
    assert row["ok"] is False and row["state"] == "dormant"


def test_hooks_partial_wiring_is_a_blocker(healthy_ws, no_rebuild):
    _wired_settings(healthy_ws)
    s = json.loads((healthy_ws / ".claude" / "settings.json")
                   .read_text(encoding="utf-8"))
    del s["hooks"]["PreToolUse"][0]  # drop one KONG hook
    (healthy_ws / ".claude" / "settings.json").write_text(
        json.dumps(s), encoding="utf-8")
    row = hooks_selfcheck.check_component_hooks(healthy_ws)
    assert row["ok"] is False and row["state"] == "partial"
    assert row["remediation"]["kind"] == "blocker"


# ---------- scheduler component ----------

def test_scheduler_fresh(healthy_ws):
    row = hooks_selfcheck.check_component_scheduler(healthy_ws)
    assert row["ok"] is True and row["state"] == "fresh"


def test_scheduler_threshold_derivation(healthy_ws):
    _heartbeat(healthy_ws, tick_age_s=0, interval_min=15)
    row = hooks_selfcheck.check_component_scheduler(healthy_ws)
    assert row["threshold_min"] == 2 * 15, (
        "threshold = SCHEDULER_STALE_TICKS x interval_min")


def test_scheduler_stale_beyond_two_ticks(healthy_ws):
    _heartbeat(healthy_ws, tick_age_s=(2 * 5 + 3) * 60)
    row = hooks_selfcheck.check_component_scheduler(healthy_ws)
    assert row["ok"] is False and row["state"] == "stale"
    assert row["remediation"]["command"], "stale names the tick command"


def test_scheduler_never_ticked(healthy_ws):
    (healthy_ws / "runs" / ".heartbeat.json").unlink()
    row = hooks_selfcheck.check_component_scheduler(healthy_ws)
    assert row["ok"] is False and row["state"] == "never"


def test_scheduler_stale_tick_constant_single_sourced():
    assert liveness_policy.SCHEDULER_STALE_TICKS == 2


# ---------- mcp component ----------

def test_mcp_ok_for_web_via_plugin_carriage(healthy_ws):
    healthy_ws / ".mcp.json"  # absent on purpose
    row = hooks_selfcheck.check_component_mcp(healthy_ws, "web")
    assert row["ok"] is True and row["state"] == "ok"


def test_mcp_pending_approval_auto_repairs(healthy_ws):
    (healthy_ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"camoufox-reverse": {"command": "python"}}}),
        encoding="utf-8")
    s = json.loads((healthy_ws / ".claude" / "settings.json")
                   .read_text(encoding="utf-8"))
    s["enableAllProjectMcpServers"] = False
    (healthy_ws / ".claude" / "settings.json").write_text(
        json.dumps(s), encoding="utf-8")
    row = hooks_selfcheck.check_component_mcp(healthy_ws, "web")
    assert row["state"] == "pending_approval" and row["ok"] is False
    assert "enableAllProjectMcpServers" in row["remediation"]["detail"]
    repair = hooks_selfcheck.apply_mcp_repairs(healthy_ws)
    assert repair["approval"]["changed"] is True
    row2 = hooks_selfcheck.check_component_mcp(healthy_ws, "web")
    assert row2["ok"] is True, "auto-repair must clear the blocker"


def test_mcp_missing_hard_items_is_blocker(healthy_ws):
    (healthy_ws / ".mcp.json").unlink()
    row = hooks_selfcheck.check_component_mcp(healthy_ws, "windows")
    assert row["ok"] is False and row["state"] == "missing"
    assert row["remediation"]["kind"] == "blocker"
    assert row["remediation"]["command"], "names the register/probe command"


# ---------- oracle / ledger components ----------

def test_oracle_unregistered_is_blocker(healthy_ws):
    (healthy_ws / "task-oracle.yaml").unlink()
    row = hooks_selfcheck.check_component_oracle(healthy_ws)
    assert row["ok"] is False and row["state"] == "unregistered"
    assert row["remediation"]["kind"] == "blocker"
    assert "task-oracle.yaml" in (row["remediation"]["file"] or "")


def test_ledger_absent_is_advisory(healthy_ws):
    (healthy_ws / "runs" / "logs" / "kunglao-20260927.jsonl").unlink()
    row = hooks_selfcheck.check_component_ledger(healthy_ws)
    assert row["state"] == "absent"
    assert row["remediation"]["kind"] == "advisory"


# ---------- component table + report wiring ----------

def test_component_table_green_ws_has_no_blockers(healthy_ws, no_rebuild):
    comps, blockers = hooks_selfcheck.component_table(healthy_ws)
    assert set(comps) == {"hooks", "scheduler", "mcp", "oracle", "ledger"}
    assert blockers == []
    assert all(c["ok"] for c in comps.values())


def test_selfcheck_writes_components_and_repairs(healthy_ws, no_rebuild,
                                                 monkeypatch, capsys):
    # simulate the #408 pending-forever trap: approval flag off
    s = json.loads((healthy_ws / ".claude" / "settings.json")
                   .read_text(encoding="utf-8"))
    s["enableAllProjectMcpServers"] = False
    (healthy_ws / ".claude" / "settings.json").write_text(
        json.dumps(s), encoding="utf-8")
    rc = hooks_selfcheck.main_with_ws(healthy_ws)
    report = json.loads((healthy_ws / "runs" / ".hooks-selfcheck.json")
                        .read_text(encoding="utf-8"))
    assert "components" in report
    assert report["components"]["mcp"]["ok"] is True, (
        "the approval auto-repair must land before the table is written")
    assert report["mcp_repairs"]["approval"]["changed"] is True
    assert rc == 0
    assert "components" in capsys.readouterr().out


def test_default_exit_unchanged_by_components(healthy_ws, no_rebuild):
    """Default rc stays the hooks face (zero tick-cadence behavior change):
    a scheduler stall must NOT flip the default exit."""
    _heartbeat(healthy_ws, tick_age_s=10_000)
    assert hooks_selfcheck.main_with_ws(healthy_ws) == 0


def test_strict_exit_fails_on_blocker(healthy_ws, no_rebuild):
    (healthy_ws / "task-oracle.yaml").unlink()
    assert hooks_selfcheck.main_with_ws(healthy_ws, strict=True) == 1


def test_strict_exit_zero_when_green(healthy_ws, no_rebuild):
    assert hooks_selfcheck.main_with_ws(healthy_ws, strict=True) == 0


def test_blocker_shape_names_command_or_file(healthy_ws, no_rebuild):
    (healthy_ws / "task-oracle.yaml").unlink()
    _heartbeat(healthy_ws, tick_age_s=10_000)
    comps, blockers = hooks_selfcheck.component_table(healthy_ws)
    assert blockers, "stale scheduler + unregistered oracle must surface"
    for b in blockers:
        assert {"component", "check", "detail"} <= set(b)
        assert b.get("fix_command") or b.get("fix_file"), (
            f"blocker must name the exact command/file: {b}")


# ---------- statusline: same state file, never green when broken ----------

def _write_selfcheck_state(ws: Path, components: dict, age_s: int = 0) -> None:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    p = ws / "runs" / ".hooks-selfcheck.json"
    p.write_text(json.dumps({"ts": _iso(datetime.now(timezone.utc)),
                             "components": components}), encoding="utf-8")
    old = time.time() - age_s
    os.utime(p, (old, old))


def test_statusline_registers_component_probes():
    import statusline_snapshot as sls
    ids = {p["id"] for p in sls.PROBES}
    assert {"component_hooks", "component_mcp",
            "component_scheduler"} <= ids


def test_statusline_probe_reads_selfcheck_state(healthy_ws):
    import statusline_snapshot as sls
    _write_selfcheck_state(healthy_ws, {
        "hooks": {"ok": True, "state": "armed"},
        "mcp": {"ok": True, "state": "ok"},
        "scheduler": {"ok": True, "state": "fresh"},
    })
    for pid, fn in (("component_hooks", sls.probe_component_hooks),
                    ("component_mcp", sls.probe_component_mcp),
                    ("component_scheduler", sls.probe_component_scheduler)):
        entry = next(p for p in sls.PROBES if p["id"] == pid)
        d = fn(healthy_ws, entry)
        assert d["ok"] is True, f"{pid} must be green on a green source"


def test_statusline_probe_missing_state_never_green(healthy_ws):
    import statusline_snapshot as sls
    entry = next(p for p in sls.PROBES if p["id"] == "component_hooks")
    d = sls.probe_component_hooks(healthy_ws, entry)
    assert d["ok"] is False, "no self-check state = never green (#412)"


def test_statusline_probe_dormant_not_ok(healthy_ws):
    import statusline_snapshot as sls
    _write_selfcheck_state(healthy_ws, {
        "hooks": {"ok": False, "state": "dormant"},
        "mcp": {"ok": True, "state": "ok"},
        "scheduler": {"ok": True, "state": "fresh"},
    })
    entry = next(p for p in sls.PROBES if p["id"] == "component_hooks")
    d = sls.probe_component_hooks(healthy_ws, entry)
    assert d["ok"] is False


def test_statusline_probe_stale_source_renders_stale_hard(healthy_ws):
    """Staleness contract: component truth older than N ticks renders STALE
    (HARD/red), never green."""
    import statusline_snapshot as sls
    _write_selfcheck_state(healthy_ws, {
        "hooks": {"ok": True, "state": "armed"},
        "mcp": {"ok": True, "state": "ok"},
        "scheduler": {"ok": True, "state": "fresh"},
    }, age_s=(liveness_policy.SCHEDULER_STALE_TICKS * 5 + 2) * 60)
    for pid in ("component_hooks", "component_mcp", "component_scheduler"):
        entry = next(p for p in sls.PROBES if p["id"] == pid)
        fn = getattr(sls, entry["probe"])
        d = fn(healthy_ws, entry)
        assert d["ok"] is False, f"{pid} must not be green from stale data"
        assert "STALE" in d["detail"]
        assert d["severity"] == "HARD"


def test_statusline_health_extends_and_never_greens_broken(healthy_ws):
    import statusline_snapshot as sls
    _write_selfcheck_state(healthy_ws, {
        "hooks": {"ok": False, "state": "dormant"},
        "mcp": {"ok": True, "state": "ok"},
        "scheduler": {"ok": True, "state": "fresh"},
    })
    health = sls._health(healthy_ws)
    assert {"hooks", "mcp", "scheduler"} <= set(health)
    assert health["hooks"] is False, "dormant is never green"
    assert health["mcp"] is True and health["scheduler"] is True


def test_statusline_snapshot_carries_component_truth(healthy_ws):
    import statusline_snapshot as sls
    _write_selfcheck_state(healthy_ws, {
        "hooks": {"ok": False, "state": "dormant"},
        "mcp": {"ok": True, "state": "ok"},
        "scheduler": {"ok": True, "state": "fresh"},
    })
    snap = sls.build_snapshot(healthy_ws)
    assert snap["stale_after_ticks"] == liveness_policy.SCHEDULER_STALE_TICKS
    specs = {s["key"]: s for s in snap["health_specs"]}
    assert specs["hooks"]["ok"] is False
    assert specs["hooks"]["suspect"] is True, "dormant = yellow at best"
    assert specs["mcp"]["ok"] is True and specs["scheduler"]["ok"] is True
    assert snap["components"]["hooks"]["state"] == "dormant"


def test_statusline_component_source_is_the_selfcheck_file(healthy_ws):
    """Single source: the snapshot's component truth must come from
    runs/.hooks-selfcheck.json (the file the self-check writes) — deleting
    it degrades the components section instead of reading elsewhere."""
    import statusline_snapshot as sls
    _write_selfcheck_state(healthy_ws, {
        "hooks": {"ok": True, "state": "armed"},
        "mcp": {"ok": True, "state": "ok"},
        "scheduler": {"ok": True, "state": "fresh"},
    })
    p = healthy_ws / "runs" / ".hooks-selfcheck.json"
    p.unlink()
    snap = sls.build_snapshot(healthy_ws)
    assert snap["components"]["source_missing"] is True
    hooks_row = snap["components"]["hooks"]
    assert hooks_row["ok"] is False, "absent source is never green"


def test_health_specs_trio_derives_from_real_health(healthy_ws):
    """Review round-3 pin: the legacy trio (oracle/retro/dormant) in
    health_specs must carry the REAL computed health values — a hardcoded
    ok would re-create the 3-green-lights-while-broken bug (#412)."""
    import statusline_snapshot as sls
    (healthy_ws / "task-oracle.yaml").unlink()  # oracle unregistered
    snap = sls.build_snapshot(healthy_ws)
    specs = {s["key"]: s for s in snap["health_specs"]}
    assert specs["oracle"]["ok"] is False, (
        "unregistered oracle must NOT render a green dot")
    assert snap["health"]["oracle"] is False


def test_naive_expires_at_does_not_crash_the_table(healthy_ws):
    """Review round-3 pin: an offset-less expires_at normalizes to UTC —
    the component table degrades to dormant instead of crashing."""
    (healthy_ws / ".hook_state.json").write_text(json.dumps({
        "active_hooks": ["dispatch_gate"],
        "expires_at": "2099-01-01T00:00:00",  # naive (no offset)
    }), encoding="utf-8")
    row = hooks_selfcheck.check_component_hooks(healthy_ws)
    assert row["state"] == "armed", "naive future expiry = armed (UTC)"


def test_surviving_pending_approval_is_a_blocker(healthy_ws):
    """Review round-3 pin: the table is collected AFTER the auto-repair, so
    a surviving pending_approval row means the repair failed — it must
    strict-gate (kind=blocker), not silently pass."""
    (healthy_ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"camoufox-reverse": {"command": "python"}}}),
        encoding="utf-8")
    s = json.loads((healthy_ws / ".claude" / "settings.json")
                   .read_text(encoding="utf-8"))
    s["enableAllProjectMcpServers"] = False
    (healthy_ws / ".claude" / "settings.json").write_text(
        json.dumps(s), encoding="utf-8")
    row = hooks_selfcheck.check_component_mcp(healthy_ws, "web")
    assert row["state"] == "pending_approval"
    assert row["remediation"]["kind"] == "blocker"
