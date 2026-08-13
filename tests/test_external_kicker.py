# -*- coding: utf-8 -*-
"""TDD RED — tests for scripts/external_kicker.py (issue #39, OS-level dead-session recovery).

All I/O is SYNTHETIC: pytest tmp_path only. The real project settings file
(D:/works/samples/2026-07-01/.claude/settings.json) is never read or written;
no claude process is spawned and no schtasks task is registered (command
construction is asserted as strings; the true kill->kick E2E is a documented
manual step in the PR).
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
from external_kicker import (  # noqa: E402
    ACTIVATION_TTL_MINUTES,
    DEFAULT_TICK_INTERVAL_MIN,
    FRESH_WORKER_MINUTES,
    KICKER_LAST_FILE,
    KICKER_PROMPT_FILE,
    acquire_kick_lock,
    build_crontab_line,
    build_kick_command,
    build_schtasks_command,
    ensure_project_hooks,
    has_fresh_workers,
    main,
    release_kick_lock,
    session_is_dead,
    tick,
    validate_interval,
    write_settings_atomic,
)


NOW = datetime.now(timezone.utc)


def ts(minutes_ago: int) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- session_is_dead (D1) ----------

def test_session_is_dead_missing_heartbeat():
    assert session_is_dead(None, NOW, 10) is True


def test_session_is_dead_fresh_last_tick_alive():
    hb = {"last_tick_ts": ts(2), "activity_ts": ts(120)}
    assert session_is_dead(hb, NOW, 10) is False


def test_session_is_dead_fresh_activity_alive():
    hb = {"last_tick_ts": ts(120), "activity_ts": ts(2)}
    assert session_is_dead(hb, NOW, 10) is False


def test_session_is_dead_both_stale():
    hb = {"last_tick_ts": ts(120), "activity_ts": ts(120)}
    assert session_is_dead(hb, NOW, 10) is True


def test_session_is_dead_unparseable_or_absent_fields():
    assert session_is_dead({"last_tick_ts": "not-a-timestamp"}, NOW, 10) is True
    assert session_is_dead({"started_ts": ts(240)}, NOW, 10) is True


# ---------- ensure_project_hooks (D2) ----------

def test_ensure_project_hooks_preserves_env_and_other_keys(tmp_path):
    hook_dir = str(tmp_path / "hooks")
    settings = {
        "env": {"VMR_API_KEY": "SECRET_FAKE"},
        "mcpServers": {"x": {"url": "y"}},
        "permissions": ["Bash(*)"],
    }
    out, added = ensure_project_hooks(settings, hook_dir)
    assert out["env"] == {"VMR_API_KEY": "SECRET_FAKE"}
    assert out["mcpServers"] == {"x": {"url": "y"}}
    assert out["permissions"] == ["Bash(*)"]
    assert added == 5
    assert len(out["hooks"]["PreToolUse"]) == 3
    assert len(out["hooks"]["PostToolUse"]) == 2


def test_ensure_project_hooks_exact_commands(tmp_path):
    hook_dir = str(tmp_path / "hooks")
    out, _ = ensure_project_hooks({}, hook_dir)
    commands = [h["command"] for ev in out["hooks"].values() for e in ev for h in e["hooks"]]
    assert commands == [
        f"python {Path(hook_dir).as_posix()}/worker_budget.py",
        f"python {Path(hook_dir).as_posix()}/dispatch_gate.py",
        f"python {Path(hook_dir).as_posix()}/heartbeat_touch.py",
        f"python {Path(hook_dir).as_posix()}/worker_budget.py",
        f"python {Path(hook_dir).as_posix()}/worker_pulse.py",
    ]


def test_ensure_project_hooks_replaces_legacy_backslash_entry(tmp_path):
    hook_dir = str(tmp_path / "hooks")
    settings = {
        "hooks": {"PreToolUse": [
            {"matcher": "Agent", "hooks": [
                {"type": "command", "command": "python C:\\old\\worker_budget.py"}]}
        ]}
    }
    out, added = ensure_project_hooks(settings, hook_dir)
    agent = [e for e in out["hooks"]["PreToolUse"] if e.get("matcher") == "Agent"]
    wb = [e for e in agent if any("worker_budget.py" in h.get("command", "") for h in e["hooks"])]
    assert len(wb) == 1                      # replaced, not stacked
    assert "\\" not in wb[0]["hooks"][0]["command"]
    assert added == 4                        # legacy entry replaced in place, not appended


def test_ensure_project_hooks_preserves_other_matchers(tmp_path):
    hook_dir = str(tmp_path / "hooks")
    settings = {
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "node .claude/hooks/block_malware_exec.js"}]}
        ]}
    }
    out, _ = ensure_project_hooks(settings, hook_dir)
    bash = [e for e in out["hooks"]["PreToolUse"] if e.get("matcher") == "Bash"]
    assert any("block_malware_exec.js" in h.get("command", "") for e in bash for h in e["hooks"])


def test_ensure_project_hooks_idempotent(tmp_path):
    hook_dir = str(tmp_path / "hooks")
    out1, added1 = ensure_project_hooks({"env": {"K": "V"}}, hook_dir)
    out2, added2 = ensure_project_hooks(out1, hook_dir)
    assert added1 == 5
    assert out2 == out1          # fixed point: re-run is byte-identical
    assert added2 == 0


def test_ensure_project_hooks_does_not_mutate_input(tmp_path):
    hook_dir = str(tmp_path / "hooks")
    settings = {"env": {"K": "V"}}
    snapshot = json.dumps(settings, sort_keys=True)
    ensure_project_hooks(settings, hook_dir)
    assert json.dumps(settings, sort_keys=True) == snapshot


# ---------- lock competition (D3) ----------

def test_acquire_kick_lock_creates_then_release(tmp_path):
    lock = tmp_path / "runs" / ".kicker.lock"
    lock.parent.mkdir()
    assert acquire_kick_lock(lock, DEFAULT_TICK_INTERVAL_MIN) is True
    assert lock.exists()
    release_kick_lock(lock)
    assert not lock.exists()


def test_acquire_kick_lock_fresh_lock_skips(tmp_path):
    lock = tmp_path / "runs" / ".kicker.lock"
    lock.parent.mkdir()
    assert acquire_kick_lock(lock, DEFAULT_TICK_INTERVAL_MIN) is True   # first tick owns
    assert acquire_kick_lock(lock, DEFAULT_TICK_INTERVAL_MIN) is False  # concurrent tick skips


def test_acquire_kick_lock_stale_lock_replaced(tmp_path):
    lock = tmp_path / "runs" / ".kicker.lock"
    lock.parent.mkdir()
    assert acquire_kick_lock(lock, DEFAULT_TICK_INTERVAL_MIN) is True
    old = time.time() - 20 * 60
    os.utime(lock, (old, old))
    assert acquire_kick_lock(lock, DEFAULT_TICK_INTERVAL_MIN) is True   # crashed kicker's lock replaced
    assert time.time() - lock.stat().st_mtime < 5


def test_acquire_kick_lock_precreated_loses(tmp_path):
    lock = tmp_path / "runs" / ".kicker.lock"
    lock.parent.mkdir()
    lock.write_text("other-owner", encoding="utf-8")
    now = time.time()
    os.utime(lock, (now, now))
    assert acquire_kick_lock(lock, DEFAULT_TICK_INTERVAL_MIN) is False


# ---------- fresh-worker suppression (D3) ----------

def _write_status(runs: Path, name: str, status: str, minutes_old: int) -> Path:
    p = runs / name
    p.write_text(f"# worker {name}\nstatus: {status}\n", encoding="utf-8")
    t = time.time() - minutes_old * 60
    os.utime(p, (t, t))
    return p


def test_has_fresh_workers_fresh_inprogress(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_status(runs, "worker-status-1.md", "in-progress", 2)
    assert has_fresh_workers(runs, FRESH_WORKER_MINUTES) is True


def test_has_fresh_workers_stale_inprogress(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_status(runs, "worker-status-1.md", "in-progress", 120)
    assert has_fresh_workers(runs, FRESH_WORKER_MINUTES) is False


def test_has_fresh_workers_done_file(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    _write_status(runs, "worker-status-1.md", "done", 1)
    assert has_fresh_workers(runs, FRESH_WORKER_MINUTES) is False


def test_has_fresh_workers_no_runs_dir(tmp_path):
    assert has_fresh_workers(tmp_path / "runs", FRESH_WORKER_MINUTES) is False


# ---------- command construction (D4/D5) ----------

def test_build_kick_command():
    assert build_kick_command("claude") == ["claude", "-p"]


def test_build_schtasks_command():
    args = build_schtasks_command("kunglao_kicker", 15, "C:/Python/python.exe",
                                  "C:/x/external_kicker.py", "C:/ws")
    assert args[:3] == ["schtasks", "/create", "/tn"]
    assert args[3] == "kunglao_kicker"
    assert args[args.index("/sc") + 1] == "minute"
    assert args[args.index("/mo") + 1] == "15"
    tr = args[args.index("/tr") + 1]
    assert "C:/Python/python.exe" in tr
    assert "C:/ws" in tr
    assert args[-1] == "/f"


def test_build_crontab_line():
    line = build_crontab_line(15, "python", "external_kicker.py", "ws")
    assert line == "*/15 * * * * python external_kicker.py ws"


# ---------- interval gate (D6) ----------

def test_validate_interval_rejects_ttl_boundary():
    with pytest.raises(ValueError):
        validate_interval(ACTIVATION_TTL_MINUTES)
    with pytest.raises(ValueError):
        validate_interval(45)


def test_validate_interval_accepts_default():
    validate_interval(DEFAULT_TICK_INTERVAL_MIN)  # no raise


def test_tick_rejects_interval_at_ttl(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        tick(ws, tick_interval_min=ACTIVATION_TTL_MINUTES, dry_run=True)


def test_main_rejects_30_min_interval_exit_1(tmp_path):
    assert main([str(tmp_path / "ws"), "--tick-interval-min", "30"]) == 1


# ---------- tick orchestration ----------

def _stale_ws(tmp_path, hb_minutes_ago=120):
    ws = tmp_path / "ws"
    runs = ws / "runs"
    runs.mkdir(parents=True)
    (runs / ".heartbeat.json").write_text(
        json.dumps({"started_ts": ts(240), "last_tick_ts": ts(hb_minutes_ago),
                    "activity_ts": ts(hb_minutes_ago)}), encoding="utf-8")
    return ws, runs


def _settings(tmp_path) -> Path:
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({"env": {"VMR_API_KEY": "SECRET_FAKE"}}), encoding="utf-8")
    return p


def test_tick_kill_session_then_kick(tmp_path):
    ws, runs = _stale_ws(tmp_path)
    settings_path = _settings(tmp_path)
    rc = tick(ws, settings_path=settings_path, dry_run=True)
    assert rc == 0
    prompt = (runs / KICKER_PROMPT_FILE).read_text(encoding="utf-8")
    assert prompt.startswith("你正在收敛循环第")   # fired-predicate resume prompt (#45)
    rec = json.loads((runs / KICKER_LAST_FILE).read_text(encoding="utf-8"))
    assert rec["kick_ts"] and rec["pid"] == 0 and rec["prompt_file"]
    s = json.loads(settings_path.read_text(encoding="utf-8"))
    assert s["env"]["VMR_API_KEY"] == "SECRET_FAKE"                # env secret preserved
    assert len(s["hooks"]["PreToolUse"]) == 3
    assert len(s["hooks"]["PostToolUse"]) == 2
    assert not (runs / ".kicker.lock").exists()                    # lock released
    assert not list(tmp_path.glob("*.tmp"))                        # atomic write, no leftovers


def test_tick_kicks_when_heartbeat_never_registered(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    settings_path = _settings(tmp_path)
    rc = tick(ws, settings_path=settings_path, dry_run=True)
    assert rc == 0
    assert (ws / "runs" / KICKER_LAST_FILE).exists()


def test_tick_kicks_on_corrupt_heartbeat(tmp_path):
    ws = tmp_path / "ws"
    runs = ws / "runs"
    runs.mkdir(parents=True)
    (runs / ".heartbeat.json").write_text("not json at all", encoding="utf-8")
    settings_path = _settings(tmp_path)
    rc = tick(ws, settings_path=settings_path, dry_run=True)
    assert rc == 0
    assert (runs / KICKER_LAST_FILE).exists()


def test_tick_skips_when_alive(tmp_path):
    ws, runs = _stale_ws(tmp_path, hb_minutes_ago=2)
    settings_path = _settings(tmp_path)
    rc = tick(ws, settings_path=settings_path, dry_run=True)
    assert rc == 0
    assert not (runs / KICKER_LAST_FILE).exists()
    assert not (runs / KICKER_PROMPT_FILE).exists()
    # settings file untouched — no rewrite of a healthy file
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"env": {"VMR_API_KEY": "SECRET_FAKE"}}


def test_tick_multi_start_exactly_one_winner(tmp_path):
    ws, runs = _stale_ws(tmp_path)
    settings_path = _settings(tmp_path)
    lock = runs / ".kicker.lock"
    assert acquire_kick_lock(lock, DEFAULT_TICK_INTERVAL_MIN)   # first tick owns the lock
    rc = tick(ws, settings_path=settings_path, dry_run=True)    # concurrent second tick
    assert rc == 0
    assert not (runs / KICKER_LAST_FILE).exists()               # skipped — one winner only
    assert not (runs / KICKER_PROMPT_FILE).exists()


def test_tick_skips_when_fresh_workers(tmp_path):
    ws, runs = _stale_ws(tmp_path)
    (runs / "worker-status-1.md").write_text("status: in-progress\n", encoding="utf-8")
    settings_path = _settings(tmp_path)
    rc = tick(ws, settings_path=settings_path, dry_run=True)
    assert rc == 0
    assert not (runs / KICKER_LAST_FILE).exists()


def test_write_settings_atomic_no_tmp_leftover(tmp_path):
    p = tmp_path / "settings.json"
    write_settings_atomic(p, {"env": {"K": "V"}})
    assert json.loads(p.read_text(encoding="utf-8")) == {"env": {"K": "V"}}
    assert not list(tmp_path.glob("*.tmp"))


def test_main_dry_run_returns_0(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    settings_path = _settings(tmp_path)
    assert main([str(ws), "--settings", str(settings_path), "--dry-run"]) == 0
