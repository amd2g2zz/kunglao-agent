# -*- coding: utf-8 -*-
"""Issue #461 — heartbeat bootstrap (release-blocker, #498 A-class).

Three behaviors, one spine (see openspec/changes/issue-461-heartbeat-bootstrap):

  A. init self-arm   — a successful init leaves runs/.heartbeat.json fresh
                       AND the full hook registry wired, with ZERO manual
                       hook_activation calls (the SKILL.md Phase-1 manual
                       6-step chain becomes init-owned bootstrap).
  B. dispatch linkage— a PASSING worker_budget pre_check renews the hook
                       activation TTL (auto --renew), completes the active
                       set (dispatch_gate + worker_pulse), flips phase to
                       DISPATCH, refreshes the heartbeat tick, and appends
                       a dispatch event to the unified log
                       (runs/logs/kunglao-<date>.jsonl — #459 target).
  C. cron HARD verify— heartbeat_loop_prompt.py --verify fails non-zero
                       with stderr guidance when the /loop cron is not
                       verifiably registered (loop marker absent/false) —
                       never a silent RC 0.

RED contract (dev baseline 5e185a2 + SDD 85d7688, 2026-08-19): none of
these exist — init exits 0 with no heartbeat file, pre_check approves
without touching .hook_state.json or the event log, and --verify is an
unknown flag that the prompt printer ignores.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import wire_up_settings  # pytest.ini pythonpath = . hooks scripts tools

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# #675: the registry file set IMPORTED from its single source (not a
# hand-mirrored tuple — the #608 anchor-drift class). sorted() keeps
# failure messages deterministic.
REGISTRY_HOOK_FILES = tuple(sorted(wire_up_settings.WIRE_UP_HOOK_FILES))


# ---------- shared helpers ----------

def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _ago(minutes: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))


def _ahead(minutes: float) -> str:
    return _iso(datetime.now(timezone.utc) + timedelta(minutes=minutes))


def _read_hook_state(ws: Path) -> dict:
    return json.loads((ws / ".hook_state.json").read_text(encoding="utf-8"))


def _read_heartbeat(ws: Path) -> dict:
    return json.loads((ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))


def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------- A. init bootstrap helpers (hermetic CLI, mirrors test_init_deploy_env) ----------

def _mk_init_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    """Hermetic CLI run: pinned fake claude.json + empty PATH dir + profile
    root under tmp (mirrors test_init_deploy_env._run_init)."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    argv += ["--type", "windows", "--skip-toolchain",
             "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PATH"] = str(ws.parent / "empty-bin")
    (ws.parent / "empty-bin").mkdir(exist_ok=True)
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "fake-claude.json")
    fake = ws.parent / "fake-claude.json"
    if not fake.exists():
        fake.write_text("{}", encoding="utf-8")
    return subprocess.run(argv, capture_output=True, text=True, timeout=180,
                          env=env, errors="replace")


def _hook_commands(settings_path: Path) -> list[str]:
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    return [str(h.get("command", ""))
            for entries in (data.get("hooks") or {}).values()
            for e in entries for h in e.get("hooks", [])]


def _command_counts(settings_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for cmd in _hook_commands(settings_path):
        base = cmd.replace("\\", "/").rsplit("/", 1)[-1]
        counts[base] = counts.get(base, 0) + 1
    return counts


# ---------- B. dispatch linkage helpers (library surface, mirrors test_worker_budget) ----------

def _write_register(path: Path, claims: list[dict]) -> None:
    lines = ["claims:"]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        lines.append(f"  status: {c.get('status', 'OPEN')}")
        lines.append(f"  promotion_attempts: {c.get('promotion_attempts', 0)}")
        lines.append(f"  evidence_tier_attempted: {c.get('evidence_tier_attempted', 1)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _healthy_ws(path: Path) -> Path:
    """A workspace where every pre_check gate passes (mirror of
    test_worker_budget._healthy_ws — local copy, this file owns #461)."""
    ws = path
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    now = _iso(datetime.now(timezone.utc))
    prev = _ago(5)
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps({"last_tick_ts": now, "activity_ts": now,
                    "started_ts": prev,
                    "tick_history": [prev, now]}), encoding="utf-8")
    (ws / "runs" / "plan-C001-strings.md").write_text(
        "goal: strings\nsteps:\nfallback:\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        f"deadline_ts: {int(time.time()) + 3600}\n", encoding="utf-8")
    _write_register(ws / "claim-register.yaml", [
        {"id": "C-001", "status": "OPEN", "promotion_attempts": 0,
         "evidence_tier_attempted": 1}])
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "constraints:\n  vm_detonation: allowed\n", encoding="utf-8")
    return ws


def _paths_for(ws: Path) -> dict:
    return {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }


def _dispatch_payload(prompt: str = "facts-snapshot: 1 facts",
                      desc: str = "[T1 tools=grep] claim C-001 strings") -> dict:
    return {"tool_input": {"name": "w-test", "description": desc, "prompt": prompt}}


def _write_hook_state(ws: Path, *, phase: str = "IDLE",
                      active: list[str] | None = None,
                      paused: list[str] | None = None,
                      expires_minutes: float = 30,
                      overrides: dict[str, str] | None = None) -> None:
    state = {
        "ts": _ago(1),
        "tier": "none",
        "phase": phase,
        "active_hooks": active if active is not None else ["cost_gate"],
        "paused_hooks": paused or [],
        "user_override": overrides or {},
        "expires_at": (_ahead(expires_minutes) if expires_minutes >= 0 else _ago(-expires_minutes)),
    }
    (ws / ".hook_state.json").write_text(json.dumps(state), encoding="utf-8")


@pytest.fixture
def quiet_subprocess_gates(monkeypatch):
    """Deterministic drift/health/backtrack gates (rc 0) — mirrors the
    monkeypatch in test_worker_budget.test_e2e_every_reject_emits_guidance."""
    import worker_budget as wb
    from types import SimpleNamespace
    monkeypatch.setattr(wb, "_run_py",
                        lambda args, cwd=None: SimpleNamespace(
                            returncode=0, stderr="", stdout=""))


def _dispatch_events(ws: Path) -> list[dict]:
    logs = ws / "runs" / "logs"
    events: list[dict] = []
    if not logs.is_dir():
        return events
    for f in sorted(logs.glob("kunglao-*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(json.loads(line))
    return events


# ===========================================================================
# A. init self-arm — heartbeat + full wire-up on the success path (#461)
# ===========================================================================

def test_init_success_bootstraps_heartbeat_and_hooks(tmp_path):
    """Default init exit 0 -> runs/.heartbeat.json exists and is fresh, the
    FULL #445 registry is wired into <ws>/.claude/settings.json, and the
    test itself never invokes hook_activation (zero manual calls — the
    SKILL.md Phase-1 6-step chain is init-owned now)."""
    ws = _mk_init_ws(tmp_path)
    r = _run_init(ws)
    assert r.returncode == 0, f"init failed: {r.stdout}{r.stderr}"
    hb = ws / "runs" / ".heartbeat.json"
    assert hb.exists(), (
        f"#461: init exited 0 without registering {hb}: {r.stdout}{r.stderr}")
    data = _read_heartbeat(ws)
    last = data.get("last_tick_ts") or data.get("started_ts")
    assert last, f"heartbeat carries no freshness timestamp: {data}"
    age = datetime.now(timezone.utc) - _parse_ts(last)
    assert age < timedelta(minutes=35), f"heartbeat registered STALE: {data}"
    assert "loop_registered" in data, (
        f"#461: the cron loop marker must exist (False until CronCreate "
        f"fires — init alone never fakes loop registration): {data}")
    settings = ws / ".claude" / "settings.json"
    assert settings.exists(), "init did not wire hooks into workspace settings"
    counts = _command_counts(settings)
    for hook_file in REGISTRY_HOOK_FILES:
        assert counts.get(hook_file, 0) >= 1, (
            f"#461 full wire-up missing {hook_file}: {counts}")


def test_init_bootstrap_idempotent_no_hook_stacking(tmp_path):
    """Re-running init (resume path) keeps the bootstrap idempotent: no
    hook entry stacks (exact per-file command counts) and the heartbeat
    stays fresh."""
    ws = _mk_init_ws(tmp_path)
    r1 = _run_init(ws)
    assert r1.returncode == 0, r1.stderr
    settings = ws / ".claude" / "settings.json"
    r2 = _run_init(ws)
    assert r2.returncode == 0, f"second init failed: {r2.stderr}"
    counts = _command_counts(settings)
    expected = dict.fromkeys(REGISTRY_HOOK_FILES, 1)
    # #675: double-registered files command-count 2 (one per event slot) —
    # derived, not hand-named.
    for f in wire_up_settings.DOUBLE_REGISTERED_HOOKS & set(REGISTRY_HOOK_FILES):
        expected[f] = 2
    assert counts == expected, (
        f"bootstrap not idempotent (stacked/dropped entries): {counts}")
    assert (ws / "runs" / ".heartbeat.json").exists()


def test_init_no_hooks_skips_heartbeat_bootstrap(tmp_path):
    """--no-hooks opts out of the engineering layer: no settings.json
    (#478 pin) and no heartbeat bootstrap either."""
    ws = _mk_init_ws(tmp_path)
    r = _run_init(ws, ["--no-hooks"])
    assert r.returncode == 0, r.stderr
    assert not (ws / ".claude" / "settings.json").exists()
    assert not (ws / "runs" / ".heartbeat.json").exists(), (
        "--no-hooks must not bootstrap the heartbeat (engineering layer opt-out)")


def test_init_hooks_json_target_not_extended(tmp_path):
    """--hooks-json names an operator-owned hook target: init must NOT
    wire the full registry into a file the operator did not name (the
    heartbeat — workspace monitoring state, not a hook entry — still
    registers)."""
    ws = _mk_init_ws(tmp_path)
    seeded = ws / "seeded-settings.json"
    seeded.write_text(json.dumps({"hooks": {}}, indent=2), encoding="utf-8")
    r = _run_init(ws, ["--hooks-json", str(seeded)])
    assert r.returncode == 0, f"init failed: {r.stdout}{r.stderr}"
    cmds = _hook_commands(seeded)
    for full_wire_only in ("dispatch_gate.py", "worker_pulse.py"):
        assert not any(c.endswith(full_wire_only) for c in cmds), (
            f"#461 wire-up escaped the operator target ({full_wire_only} in "
            f"--hooks-json file): {cmds}")
    assert (ws / "runs" / ".heartbeat.json").exists(), (
        "heartbeat bootstrap must still run under --hooks-json")


def test_init_resume_path_re_bootstraps_heartbeat(tmp_path):
    """A pre-#461 workspace (heartbeat + settings removed after init) gets
    re-armed by the RESUME exit-0 path — not only the fresh-initialize
    path."""
    ws = _mk_init_ws(tmp_path)
    assert _run_init(ws).returncode == 0
    (ws / "runs" / ".heartbeat.json").unlink()
    (ws / ".claude" / "settings.json").unlink()
    r = _run_init(ws)
    assert r.returncode == 0, f"resume init failed: {r.stderr}"
    assert "resume" in (r.stdout + r.stderr)
    hb = ws / "runs" / ".heartbeat.json"
    assert hb.exists(), "#461: resume exit-0 path did not re-bootstrap the heartbeat"
    settings = ws / ".claude" / "settings.json"
    assert settings.exists(), "#461: resume exit-0 path did not re-wire hooks"


# ===========================================================================
# B. dispatch linkage — the four lifecycle effects on approval (#461)
# ===========================================================================

def test_dispatch_pass_renews_activation_ttl(tmp_path, quiet_subprocess_gates):
    """A passing dispatch renews the activation TTL: an already-EXPIRED
    .hook_state.json (the '30min 过期的 --renew 由派发事件自动触发' ask)
    comes back with a fresh future expiry."""
    import worker_budget as wb
    ws = _healthy_ws(tmp_path / "renew")
    _write_hook_state(ws, expires_minutes=-5)  # expired 5 min ago
    assert _parse_ts(_read_hook_state(ws)["expires_at"]) < datetime.now(timezone.utc)
    rc = wb.pre_check(_dispatch_payload(), _paths_for(ws))
    assert rc == 0, "healthy dispatch unexpectedly rejected"
    expires = _parse_ts(_read_hook_state(ws)["expires_at"])
    assert expires > datetime.now(timezone.utc) + timedelta(minutes=25), (
        f"#461: dispatch did not auto-renew the TTL (expires_at={expires})")


def test_dispatch_flips_phase_and_completes_activation(tmp_path, quiet_subprocess_gates):
    """A passing dispatch flips phase to DISPATCH (the state machine's
    RUNNING) and completes the active set with dispatch_gate +
    worker_pulse (issue: 'phase 翻转(IDLE→RUNNING)' + '激活集完整')."""
    import worker_budget as wb
    ws = _healthy_ws(tmp_path / "phase")
    _write_hook_state(ws, phase="IDLE", active=["cost_gate"],
                      paused=["dispatch_gate", "worker_pulse"])
    rc = wb.pre_check(_dispatch_payload(), _paths_for(ws))
    assert rc == 0
    state = _read_hook_state(ws)
    assert state["phase"] == "DISPATCH", f"phase not flipped: {state['phase']}"
    for hook in ("dispatch_gate", "worker_pulse"):
        assert hook in state["active_hooks"], (
            f"activation set incomplete — {hook} not active: {state}")
        assert hook not in state["paused_hooks"], (
            f"{hook} still paused after dispatch: {state}")


def test_dispatch_respects_user_override_off(tmp_path, quiet_subprocess_gates):
    """user_override off is an explicit operator opt-out — the linkage
    must NOT force-activate the overridden hook."""
    import worker_budget as wb
    ws = _healthy_ws(tmp_path / "override")
    _write_hook_state(ws, phase="MONITOR", active=["cost_gate"],
                      paused=["dispatch_gate", "worker_pulse"],
                      overrides={"dispatch_gate": "off"})
    rc = wb.pre_check(_dispatch_payload(), _paths_for(ws))
    assert rc == 0
    state = _read_hook_state(ws)
    assert state["phase"] == "DISPATCH"
    assert "dispatch_gate" not in state["active_hooks"], (
        f"user_override=off was force-armed by the linkage: {state}")
    assert "worker_pulse" in state["active_hooks"]  # not overridden -> completed


def test_dispatch_cold_state_bootstraps_full_set(tmp_path, quiet_subprocess_gates):
    """No .hook_state.json at all (the 2026-08-18 field state): the
    dispatch itself bootstraps a state file with the full default set and
    phase DISPATCH."""
    import worker_budget as wb
    ws = _healthy_ws(tmp_path / "cold")
    assert not (ws / ".hook_state.json").exists()
    rc = wb.pre_check(_dispatch_payload(), _paths_for(ws))
    assert rc == 0
    state = _read_hook_state(ws)
    assert state["phase"] == "DISPATCH"
    assert {"dispatch_gate", "worker_pulse"} <= set(state["active_hooks"]), (
        f"cold-start activation missing the dispatch pair: {state}")
    assert _parse_ts(state["expires_at"]) > datetime.now(timezone.utc)


def test_dispatch_refreshes_heartbeat_last_tick(tmp_path, quiet_subprocess_gates):
    """A passing dispatch refreshes runs/.heartbeat.json last_tick_ts
    (renew's existing side effect — a dispatching orchestrator IS alive)."""
    import worker_budget as wb
    ws = _healthy_ws(tmp_path / "tick")
    # 20-min-old two-tick seed (#754): enough to pass the continuity GATE
    # at pre_check time; the renewed tick that this test observes lands after.
    before = json.dumps({"last_tick_ts": _ago(20), "activity_ts": _ago(20),
                         "interval_min": 5,
                         "tick_history": [_ago(21), _ago(20)]})
    (ws / "runs" / ".heartbeat.json").write_text(before, encoding="utf-8")
    rc = wb.pre_check(_dispatch_payload(), _paths_for(ws))
    assert rc == 0
    tick = _parse_ts(_read_heartbeat(ws)["last_tick_ts"])
    assert datetime.now(timezone.utc) - tick < timedelta(minutes=2), (
        f"last_tick_ts not refreshed by the dispatch: {tick}")


def test_dispatch_event_logged_to_unified_log(tmp_path, quiet_subprocess_gates):
    """The dispatch event lands in the EXISTING unified log
    (runs/logs/kunglao-<date>.jsonl via kunglao_log.emit) — '零 dispatch
    事件' from the field report is closed; no new log format."""
    import worker_budget as wb
    ws = _healthy_ws(tmp_path / "event")
    rc = wb.pre_check(_dispatch_payload(), _paths_for(ws))
    assert rc == 0
    events = _dispatch_events(ws)
    dispatches = [e for e in events if e.get("action") == "dispatch"]
    assert dispatches, f"#461: no dispatch event in the unified log: {events}"
    e = dispatches[-1]
    assert e.get("claim") == "C-001", e
    assert "worker_budget" in str(e.get("actor", "")), e


def test_stale_heartbeat_dispatch_still_rejected_no_linkage(tmp_path, quiet_subprocess_gates):
    """Regression anchor: a STALE heartbeat (>35 min) still REJECTS the
    dispatch, and a REJECTED dispatch triggers NO linkage (no TTL renew,
    no phase flip, no dispatch event — reject is not a lifecycle event)."""
    import worker_budget as wb
    ws = _healthy_ws(tmp_path / "stale")
    stale = json.dumps({"last_tick_ts": _ago(40), "activity_ts": _ago(40)})
    (ws / "runs" / ".heartbeat.json").write_text(stale, encoding="utf-8")
    _write_hook_state(ws, phase="IDLE", active=["cost_gate"],
                      expires_minutes=-5)  # expired — must stay expired
    rc = wb.pre_check(_dispatch_payload(), _paths_for(ws))
    assert rc == 2, "stale heartbeat must keep REJECTING the dispatch"
    state = _read_hook_state(ws)
    assert state["phase"] == "IDLE", "rejected dispatch must not flip phase"
    assert _parse_ts(state["expires_at"]) < datetime.now(timezone.utc), (
        "rejected dispatch must not renew the TTL")
    assert not _dispatch_events(ws), (
        "rejected dispatch must not emit a dispatch event (that is #459 "
        "reject-observability territory, not a lifecycle event)")


# ===========================================================================
# C. cron registration HARD verify (#461)
# ===========================================================================

def _run_verify(ws: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "heartbeat_loop_prompt.py"),
         str(ws), "--verify"],
        capture_output=True, text=True, timeout=60, errors="replace")


def _write_hb(ws: Path, data: dict) -> None:
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "runs" / ".heartbeat.json").write_text(
        json.dumps(data), encoding="utf-8")


def test_verify_hard_fails_without_heartbeat_file(tmp_path):
    """No .heartbeat.json at all -> --verify exits non-zero with guidance
    naming --heartbeat-on (never a silent prompt print + RC 0)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    r = _run_verify(ws)
    assert r.returncode != 0, f"--verify must HARD-fail on missing heartbeat: {r.stdout}"
    assert "--heartbeat-on" in r.stderr, (
        f"stderr must carry actionable guidance, got: {r.stderr!r}")


def test_verify_hard_fails_when_loop_marker_absent(tmp_path):
    """Heartbeat file exists but no loop marker (init-registered, cron
    never created) -> non-zero + stderr naming CronCreate + the marker."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_hb(ws, {"started_ts": _ago(1), "interval_min": 5,
                   "last_tick_ts": _ago(1)})
    r = _run_verify(ws)
    assert r.returncode != 0, f"unregistered cron must HARD-fail: {r.stdout}"
    assert "CronCreate" in r.stderr and "loop_registered" in r.stderr, (
        f"stderr must name CronCreate + the loop marker (clear guidance, "
        f"not silent): {r.stderr!r}")


def test_verify_hard_fails_when_loop_marker_false(tmp_path):
    """Explicit loop_registered=false -> same HARD failure + guidance."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_hb(ws, {"started_ts": _ago(1), "interval_min": 5,
                   "last_tick_ts": _ago(1), "loop_registered": False})
    r = _run_verify(ws)
    assert r.returncode != 0
    assert "loop 5m" in r.stderr or "CronCreate" in r.stderr, (
        f"guidance must tell the operator HOW to register: {r.stderr!r}")


def test_verify_passes_when_loop_registered(tmp_path):
    """loop_registered=true -> exit 0 with the OK line."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_hb(ws, {"started_ts": _ago(6), "interval_min": 5,
                   "last_tick_ts": _ago(1), "loop_registered": True,
                   "tick_history": [_ago(6), _ago(1)]})
    r = _run_verify(ws)
    assert r.returncode == 0, f"registered loop must verify PASS: {r.stderr}"
    assert "cron loop registered" in r.stdout, (
        f"PASS must be observable on stdout: {r.stdout!r}")


def test_loop_prompt_marks_loop_registration(tmp_path):
    """The /loop prompt's FIRST action registers the heartbeat AND marks
    the cron loop — the prompt body executing is the proof CronCreate
    accepted it."""
    import heartbeat_loop_prompt as hlp
    prompt = hlp.build_prompt(str(tmp_path / "ws"))
    assert "--heartbeat-on --loop-registered" in prompt, (
        "#461: the loop prompt must carry the registration marker flag")


def test_mark_loop_registered_roundtrip(tmp_path):
    """mark_loop_registered flips the marker; a re-register
    (--heartbeat-on) must NOT silently erase a proven registration."""
    import heartbeat
    ws = tmp_path / "ws"
    ws.mkdir()
    assert heartbeat.heartbeat_register(ws) == 0
    assert heartbeat.mark_loop_registered(ws) == 0
    assert _read_heartbeat(ws)["loop_registered"] is True
    assert heartbeat.heartbeat_register(ws) == 0  # re-register preserves
    assert _read_heartbeat(ws)["loop_registered"] is True, (
        "re-register erased the proven loop registration (#461)")
