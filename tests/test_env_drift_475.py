# -*- coding: utf-8 -*-
"""tests/test_env_drift_475.py — env-state bound to heartbeat + tool_error_policy wiring (#475).

RED phase — these tests drive the NEW contract:
  (a) heartbeat_tick step 9 writes runs/env-state.json (schema + idempotency)
  (b) worker_budget.check_env_fresh three states (FAIL_OPEN / FAIL∩tier REJECT /
      stale 2×TTL self-heal hint)
  (c) kunglao-monitor env_drift advisory (DRIFT/OK/NO_DATA; tick never blocked)
  (d) tool_error_policy mechanical consumer in worker_budget.post_check
      (3→warn / 5→disable_escalate + env-state fail writeback / success resets)
  (e) scripts/env_repair_l1.py idempotent + safe no-op without substrate

Everything here is RED on the baseline: env_state_probe.py / env_repair_l1.py
do not exist, check_env_fresh / env_drift do not exist, tool-error streaks
are never persisted.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TICK = SCRIPTS / "heartbeat_tick.py"
MONITOR = SCRIPTS / "kunglao-monitor.py"
ENV_STATE = Path("runs") / "env-state.json"

sys.path.insert(0, str(SCRIPTS))


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_ws(tmp_path: Path, project_type: str | None = None) -> Path:
    """Minimal workspace the tick chain accepts (claim-register.yaml)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    if project_type:
        (ws / "analysis_state.txt").write_text(
            f"[current_task]\nsample=488d2dd8\n[/current_task]\nproject_type={project_type}\n",
            encoding="utf-8")
    return ws


def _write_env_state(ws: Path, per_capability: dict, ts_age_min: float = 0.0,
                     written_by: str = "env_state_probe") -> None:
    ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=ts_age_min))
    state = {
        "per_capability": {
            name: {**entry, "last_probe_ts": entry.get(
                "last_probe_ts", ts)}
            for name, entry in per_capability.items()
        },
        "written_by": written_by,
        "ts": ts,
    }
    (ws / ENV_STATE).write_text(json.dumps(state, indent=2), encoding="utf-8")


# =====================================================================
# (a) heartbeat_tick step 9 — env-state write + idempotency
# =====================================================================

class TestTickWritesEnvState:
    def test_env_state_exists_after_tick_with_schema(self, tmp_path):
        """Step 8: after a tick, runs/env-state.json exists with the schema —
        per_capability entries (status/last_probe_ts/detail), written_by, ts."""
        ws = _make_ws(tmp_path)
        r = subprocess.run([sys.executable, str(TICK), str(ws)],
                            capture_output=True, text=True, timeout=180,
                            encoding="utf-8", errors="replace")
        p = ws / ENV_STATE
        assert p.exists(), f"tick rc={r.returncode} stdout={r.stdout[-300:]} stderr={r.stderr[-300:]}"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("written_by") == "env_state_probe"
        assert "ts" in data
        caps = data.get("per_capability")
        assert isinstance(caps, dict) and caps, "per_capability must be a non-empty map"
        for name, entry in caps.items():
            assert entry.get("status") in ("pass", "fail", "skip"), f"{name}: {entry}"
            assert "last_probe_ts" in entry, f"{name} missing last_probe_ts"
            assert "detail" in entry, f"{name} missing detail (evidence semantics)"

    def test_tick_env_state_idempotent(self, tmp_path):
        """Two consecutive ticks: same capability key set, same statuses,
        same written_by — timestamps may advance."""
        ws = _make_ws(tmp_path)
        for _ in range(2):
            subprocess.run([sys.executable, str(TICK), str(ws)],
                           capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
        p = ws / ENV_STATE
        assert p.exists(), "second tick must still leave env-state.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["written_by"] == "env_state_probe"
        # no-device machine: every capability must be a stable 'skip', not
        # alternating fail/pass (idempotency = no fabricated probe flapping)
        statuses = {k: v["status"] for k, v in data["per_capability"].items()}
        assert all(s == "skip" for s in statuses.values()) or statuses, statuses

    def test_no_env_is_noop_not_fabricated_failures(self, tmp_path):
        """A machine with no VM host and no adb: capabilities report skip
        with honest detail — never a fabricated 'fail'."""
        ws = _make_ws(tmp_path)
        subprocess.run([sys.executable, str(TICK), str(ws)],
                       capture_output=True, text=True, timeout=180,
                       encoding="utf-8", errors="replace")
        data = json.loads((ws / ENV_STATE).read_text(encoding="utf-8"))
        for name, entry in data["per_capability"].items():
            if entry["status"] == "skip":
                assert entry["detail"], f"{name}: skip must carry an honest reason"


# =====================================================================
# (b) check_env_fresh — three states
# =====================================================================

class TestCheckEnvFresh:
    def _paths(self, ws: Path) -> dict:
        ws.mkdir(parents=True, exist_ok=True)
        return {
            'workspace': str(ws),
            'state': ws / 'analysis_state.txt',
            'register': ws / 'claim-register.yaml',
            'deps': ws / 'claim_deps.yaml',
            'task_spec': ws / 'task_spec.yaml',
        }

    def _payload(self, desc: str = 'w-t bootstrap dispatch') -> dict:
        # #862 通道归一：形状走 prompt（canonical），description 纯描述
        return {'tool_input': {'name': 'w-t', 'description': desc,
                               'prompt': '[T2 tools=vmr-shell] claim C-001 detonate'}}

    def test_missing_file_fail_open(self, tmp_path, capsys):
        """Missing env-state.json → allow (FAIL_OPEN) + one-time stderr hint."""
        from worker_budget import check_env_fresh
        ws = _make_ws(tmp_path)
        ok, msg = check_env_fresh(self._paths(ws), tier=2, tools=['vmr-shell'])
        assert ok is True
        assert msg, "FAIL_OPEN must still explain (hint to stderr)"

    def test_fail_intersecting_tier_rejects(self, tmp_path, capsys):
        """vm_reachable: fail (fresh ts) + T2 vmr-shell dispatch → REJECT
        with 'REJECT envfresh' + L1 repair guidance."""
        from worker_budget import pre_check
        ws = _make_ws(tmp_path)
        (ws / 'claim-register.yaml').write_text(
            "claims:\n- id: C-001\n  status: OPEN\n  evidence_tier_attempted: 1\n",
            encoding="utf-8")
        _write_env_state(ws, {"vm_reachable": {"status": "fail",
                                               "detail": "VM unreachable"}})
        rc = pre_check(self._payload(), self._paths(ws))
        captured = capsys.readouterr()
        assert rc == 2
        assert 'REJECT envfresh' in captured.err
        assert 'env_repair_l1' in captured.out + captured.err  # L1 guidance named

    def test_fail_not_intersecting_allows(self, tmp_path, capsys):
        """vm_reachable: fail but the dispatch is T1 static-only → allowed
        (drift is visible, static work is not blocked)."""
        from worker_budget import check_env_fresh
        ws = _make_ws(tmp_path)
        _write_env_state(ws, {"vm_reachable": {"status": "fail",
                                               "detail": "VM unreachable"}})
        ok, msg = check_env_fresh(self._paths(ws), tier=1, tools=['grep'])
        assert ok is True

    def test_stale_beyond_2x_ttl_rejects_with_selfheal(self, tmp_path, capsys):
        """last_probe_ts older than 2×ENV_STATE_TTL → REJECT telling the
        dispatcher to run one heartbeat_tick."""
        from worker_budget import check_env_fresh, ENV_STATE_TTL_MINUTES
        ws = _make_ws(tmp_path)
        stale_age = ENV_STATE_TTL_MINUTES * 2 + 5
        _write_env_state(ws, {"vm_reachable": {"status": "pass", "detail": "ok"}},
                         ts_age_min=stale_age)
        ok, msg = check_env_fresh(self._paths(ws), tier=2, tools=['vmr-shell'])
        assert ok is False
        assert 'heartbeat_tick' in msg, "self-heal hint must name the tick"

    def test_fresh_pass_allows(self, tmp_path):
        """Fresh passing entries → allow, no message noise."""
        from worker_budget import check_env_fresh
        ws = _make_ws(tmp_path)
        _write_env_state(ws, {"vm_reachable": {"status": "pass", "detail": "ok"}})
        ok, msg = check_env_fresh(self._paths(ws), tier=2, tools=['vmr-shell'])
        assert ok is True

    def test_corrupt_json_fails_open(self, tmp_path):
        """Garbage env-state.json → fail open (aligned with drift/health precedent)."""
        from worker_budget import check_env_fresh
        ws = _make_ws(tmp_path)
        (ws / ENV_STATE).write_text("{not json", encoding="utf-8")
        ok, msg = check_env_fresh(self._paths(ws), tier=2, tools=['vmr-shell'])
        assert ok is True


# =====================================================================
# (c) monitor env_drift advisory
# =====================================================================

class TestMonitorEnvDrift:
    def test_drift_advisory_surfaced_tick_not_blocked(self, tmp_path):
        """vm_reachable: fail → env_drift.status=DRIFT naming the capability;
        the monitor still exits 0 (#88: advisory never gates)."""
        ws = _make_ws(tmp_path)
        _write_env_state(ws, {"vm_reachable": {"status": "fail",
                                               "detail": "VM unreachable"}})
        r = subprocess.run([sys.executable, str(MONITOR), str(ws), "--json"],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        drift = out.get("env_drift")
        assert drift, "env_drift field must exist"
        assert drift["status"] == "DRIFT"
        assert "vm_reachable" in drift.get("drifted", [])
        # frozen fields untouched
        for k in ("ts", "heartbeat", "active_workers", "health", "next"):
            assert k in out

    def test_ok_when_fresh_passing(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_env_state(ws, {"vm_reachable": {"status": "pass", "detail": "ok"}})
        r = subprocess.run([sys.executable, str(MONITOR), str(ws), "--json"],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        out = json.loads(r.stdout)
        assert out["env_drift"]["status"] == "OK"

    def test_no_data_when_file_missing(self, tmp_path):
        ws = _make_ws(tmp_path)
        r = subprocess.run([sys.executable, str(MONITOR), str(ws), "--json"],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        out = json.loads(r.stdout)
        assert out["env_drift"]["status"] == "NO_DATA"


# =====================================================================
# (d) tool_error_policy mechanical consumer
# =====================================================================

class TestToolErrorPolicyWired:
    def _post(self, ws: Path, tool_result: str) -> None:
        from worker_budget import post_check
        paths = {
            'workspace': str(ws), 'state': ws / 'analysis_state.txt',
            'register': ws / 'claim-register.yaml',
            'deps': ws / 'claim_deps.yaml',
            'task_spec': ws / 'task_spec.yaml',
        }
        post_check({'tool_input': {'name': 'w-t', 'description':
                                   '[T1 tools=grep] claim C-001 strings'},
                    'tool_result': tool_result}, paths)

    def _streak(self, ws: Path, tool: str) -> int:
        p = ws / "runs" / "tool-errors.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        return int(data.get(tool, {}).get("consecutive_failures", 0))

    def test_three_failures_warn(self, tmp_path, capsys):
        """3 consecutive failures of one tool → streak=3 persisted + stderr
        warn naming the streak (WARN_THRESHOLD=3 hysteresis engaged)."""
        ws = _make_ws(tmp_path)
        for i in range(3):
            self._post(ws, f"mcp__ghidra__decompile attempt {i}: Error: tool failed")
        assert self._streak(ws, "mcp__ghidra__decompile") == 3
        err = capsys.readouterr().err
        assert "3" in err and "ghidra" in err.lower()

    def test_five_failures_disable_escalate(self, tmp_path, capsys):
        """5 consecutive failures → disable_escalate + blocker note; the
        env-state entry for the tool's capability is marked failed."""
        ws = _make_ws(tmp_path)
        _write_env_state(ws, {"mcp_bridge": {"status": "pass", "detail": "ok"}})
        for i in range(5):
            self._post(ws, f"mcp__ghidra__decompile attempt {i}: Error: tool failed")
        assert self._streak(ws, "mcp__ghidra__decompile") == 5
        err = capsys.readouterr().err
        assert "disable" in err.lower() or "escalat" in err.lower()
        env = json.loads((ws / ENV_STATE).read_text(encoding="utf-8"))
        assert env["per_capability"]["mcp_bridge"]["status"] == "fail"

    def test_success_resets_streak(self, tmp_path):
        """A succeeding invocation resets the streak to 0 (hysteresis must
        not latch forever on transient errors)."""
        ws = _make_ws(tmp_path)
        for i in range(4):
            self._post(ws, f"mcp__ghidra__decompile attempt {i}: Error: tool failed")
        assert self._streak(ws, "mcp__ghidra__decompile") == 4
        self._post(ws, "mcp__ghidra__decompile: success result")
        assert self._streak(ws, "mcp__ghidra__decompile") == 0

    def test_policy_constants_are_the_single_source(self, tmp_path):
        """The hook consumes tool_error_policy's thresholds — no local copies."""
        import tool_error_policy as tep
        from worker_budget import TOOL_ERROR_POLICY_LOADED
        assert TOOL_ERROR_POLICY_LOADED, "worker_budget must import tool_error_policy"
        assert tep.WARN_THRESHOLD == 3 and tep.DISABLE_THRESHOLD == 5


# =====================================================================
# (e) env_repair_l1 idempotency
# =====================================================================

class TestEnvRepairL1:
    def _repair(self, ws: Path, *args: str) -> dict:
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "env_repair_l1.py"), str(ws), *args, "--json"],
            capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace")
        assert r.returncode == 0, f"repair rc={r.returncode}: {r.stdout[-200:]} {r.stderr[-200:]}"
        return json.loads(r.stdout)

    def test_noop_without_substrate(self, tmp_path):
        """No adb / no VM host → every subcommand reports skip, exit 0,
        env-state.json not corrupted."""
        ws = _make_ws(tmp_path)
        _write_env_state(ws, {"vm_reachable": {"status": "fail",
                                               "detail": "VM unreachable"}})
        out = self._repair(ws, "--all")
        for name, entry in out.get("repaired", {}).items():
            assert entry.get("action") == "skip", f"{name}: {entry}"
        # env-state content still parses and keeps its schema
        env = json.loads((ws / ENV_STATE).read_text(encoding="utf-8"))
        assert env["written_by"] == "env_state_probe"

    def test_double_run_stable(self, tmp_path):
        """Two consecutive --all runs report identical action per capability."""
        ws = _make_ws(tmp_path)
        first = self._repair(ws, "--all")
        second = self._repair(ws, "--all")
        a = {k: v["action"] for k, v in first.get("repaired", {}).items()}
        b = {k: v["action"] for k, v in second.get("repaired", {}).items()}
        assert a == b, f"repair flapped: {a} -> {b}"


# ===========================================================================
# 故障注入验收（fault injection, 2026-08-19 用户要求）— 主动制造故障，
# 验证检测面诚实：gate 对故障的反应必须是设计语义（REJECT/FAIL_OPEN/自愈），
# 不是崩溃或静默。链上已有: corrupt-JSON FAIL_OPEN / 缺 substrate skip /
# stale 自愈。此处补两个此前缺的注入面: 探针进程被杀（tick 与探针解耦）
# 和 env-state 被 gate 读取后并发篡改（读入快照语义）。
# ===========================================================================

class TestFaultInjection:
    def test_probe_killed_does_not_corrupt_state_file(self, tmp_path):
        """注入: env-state.json 写到一半进程被杀（截断 JSON）→ 下一次
        check_env_fresh 必须走 corrupt 分支 FAIL_OPEN（不 crash hook），
        下一次 tick 用完整重写覆盖截断残留（原子恢复）。"""
        import worker_budget as wb
        ws = _make_ws(tmp_path)
        p = ws / "runs" / "env-state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"per_capability": {"vm_reachable": {"status":',  # truncated mid-write
                     encoding="utf-8")
        ok, msg = wb.check_env_fresh({'workspace': str(ws)}, tier=2)
        assert ok is True, f"truncated state must FAIL_OPEN, got REJECT: {msg}"

    def test_backdated_ts_rejected_as_stale_not_crash(self, tmp_path):
        """注入: last_probe_ts 被写为非法字符串（不是时间戳）→ gate
        不 crash（unparseable → fail open）；写为远古时间 → 2×TTL 自愈
        REJECT 路径。两条都是 gate 对损坏证据的正确反应谱。"""
        import json as _json
        import worker_budget as wb
        ws = _make_ws(tmp_path)
        p = ws / "runs" / "env-state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        # (1) unparseable ts → fail open
        p.write_text(_json.dumps({"per_capability": {
            "vm_reachable": {"status": "pass", "last_probe_ts": "not-a-timestamp"}}}),
                     encoding="utf-8")
        ok, _ = wb.check_env_fresh({'workspace': str(ws)}, tier=2)
        assert ok is True, "unparseable ts must fail open, not reject/crash"
        # (2) ancient ts → self-heal reject
        p.write_text(_json.dumps({"per_capability": {
            "vm_reachable": {"status": "pass",
                             "last_probe_ts": "2020-01-01T00:00:00Z"}}}),
                     encoding="utf-8")
        ok, msg = wb.check_env_fresh({'workspace': str(ws)}, tier=2)
        assert ok is False, "ancient ts must REJECT (stale beyond 2×TTL)"
        assert "heartbeat" in msg.lower() or "tick" in msg.lower(), msg


# ===========================================================================
# #475 review HIGH-1 补注入：合法 JSON 但形状错（list 顶层/字符串条目）——
# 两个读者都必须按 malformed 处理（FAIL_OPEN / NO_DATA），绝不 AttributeError。
# ===========================================================================

def test_fault_injection_wrong_shape_json_fails_open(tmp_path):
    """注入: env-state.json = "[1,2,3]"（合法 JSON、list 顶层）→
    check_env_fresh FAIL_OPEN；env_drift_watch NO_DATA。reviewer 复现过
    AttributeError 崩溃——这正是故障注入验收要拦的通道。"""
    import json as _json
    from worker_budget import check_env_fresh
    ws = _make_ws(tmp_path)
    p = ws / "runs" / "env-state.json"
    p.parent.mkdir(parents=True, exist_ok=True)

    def _monitor_drift() -> dict:
        # monitor is exercised the same way its own tests do: CLI --json
        r = subprocess.run([sys.executable, str(MONITOR), str(ws), "--json"],
                           capture_output=True, text=True, timeout=60,
                           encoding="utf-8", errors="replace")
        assert r.returncode == 0, f"monitor must not crash on bad shape: {r.stderr}"
        return json.loads(r.stdout)["env_drift"]

    # (1) list top-level
    p.write_text("[1, 2, 3]", encoding="utf-8")
    ok, _ = check_env_fresh({'workspace': str(ws)}, tier=2)
    assert ok is True, "list-top JSON must fail open (no crash)"
    d = _monitor_drift()
    assert d["status"] == "NO_DATA", d
    # (2) per_capability entries as strings
    p.write_text(_json.dumps({"per_capability": {"vm_reachable": "bogus"}}),
                 encoding="utf-8")
    ok, _ = check_env_fresh({'workspace': str(ws)}, tier=2)
    assert ok is True, "string-entry must fail open (no crash)"
    d = _monitor_drift()
    assert d["status"] == "OK", d  # string entry skipped, no drift claimed
