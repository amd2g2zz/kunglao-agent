# -*- coding: utf-8 -*-
"""#883 statusline 健康段 — 探针注册表 / 语义状态机 / 快照 writer suite.

Coverage map (issue #883 ten acceptance items, Python-side half):
  - registry completeness + "无 staleness_budget 不许上线" guard + slots inert
  - new-probe-declaration-auto-wires (registry-driven rendering)
  - alive probes (heartbeat mtime / ledger tail) -> HARD [ledger]
  - deployed probe declared-vs-disk both directions -> [hook] WARN/HARD
  - stall fingerprint (noop breaker count >= K + OPEN claims) -> [stall]
  - audit age severity grading (审计数据显示审计年龄)
  - state machine transition table + precedence (down > flawless > stall > toss > analyzing > idle)
  - flash triggers (milestone / every-N-ticks / state change) — 时间数字仅闪现的数据面
  - snapshot schema + atomic write
  - down auto-flip on stale heartbeat (kill kunglao -> down)
  - heartbeat_tick integration (snapshot written per tick, fail-open)
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
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import statusline_snapshot as sls  # noqa: E402

REQUIRED_PROBE_KEYS = {"id", "dimension", "probe", "threshold", "unit",
                       "staleness_budget", "severity", "short_code"}


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_ws(tmp_path: Path) -> Path:
    """Minimal kunglao workspace: identity + register + runs/."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=windows\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _touch_heartbeat(ws: Path, age_s: int = 0) -> None:
    hb = ws / "runs" / ".heartbeat.json"
    hb.write_text(json.dumps({
        "started_ts": _iso(datetime.now(timezone.utc) - timedelta(seconds=age_s + 60)),
        "last_tick_ts": _iso(datetime.now(timezone.utc) - timedelta(seconds=age_s)),
    }), encoding="utf-8")
    old = time.time() - age_s
    os.utime(hb, (old, old))


def _emit(ws: Path, action: str = "dispatch", age_s: int = 0,
          actor: str = "test") -> None:
    kunglao_log_emit(ws, actor=actor, action=action, age_s=age_s)


def kunglao_log_emit(ws: Path, *, actor: str, action: str, age_s: int = 0) -> None:
    import kunglao_log
    kunglao_log.emit(ws, actor, action, detail="test event")
    if age_s:
        p = kunglao_log.log_path(ws)
        old = time.time() - age_s
        os.utime(p, (old, old))


def _open_claim(ws: Path, cid: str = "C-001",
                status: str = "OPEN") -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{
            "id": cid, "status": status, "boundary_type": "static",
            "evidence_tier_attempted": "T1", "promotion_attempts": 0,
            "depends_on": [], "title": "t",
        }]}, sort_keys=False), encoding="utf-8")


def _mission(ws: Path, answered: int, total: int, v_m_hist=None) -> None:
    pqs = [{"id": f"PQ-{i}", "question": "q", "state":
            ("answered" if i < answered else "unattempted"),
            "coverage": (1.0 if i < answered else 0.0),
            "answered_by": [], "blocker": None, "wake": None, "weight": 1.0}
           for i in range(total)]
    hist = [{"ts": _iso(datetime.now(timezone.utc)), "v_m": float(v)}
            for v in (v_m_hist or [float(answered)])]
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump({"mission": {"pqs": pqs, "beta": 0.5,
                                    "history": hist,
                                    "feature_used": True}},
                       sort_keys=False), encoding="utf-8")


def _noop(ws: Path, count: int) -> None:
    (ws / "runs" / ".heartbeat-noop.json").write_text(
        json.dumps({"hash": "x" * 64, "count": count}), encoding="utf-8")


def _selfcheck_report(ws: Path, age_min: int = 1) -> None:
    p = ws / "runs" / ".hooks-selfcheck.json"
    p.write_text(json.dumps({"ts": _iso(datetime.now(timezone.utc))}),
                 encoding="utf-8")
    old = time.time() - age_min * 60
    os.utime(p, (old, old))


# ---------- registry ----------

class TestProbeRegistry:
    def test_registry_entries_complete(self):
        for probe in sls.PROBES:
            if not probe.get("enabled", True):
                continue
            missing = REQUIRED_PROBE_KEYS - set(probe)
            assert not missing, f"{probe.get('id')} missing {missing}"

    def test_no_probe_without_staleness_budget_goes_live(self):
        """无 staleness_budget 不许上线（issue §六）：enabled 探针必须有预算。"""
        for probe in sls.PROBES:
            if not probe.get("enabled", True):
                continue
            assert probe.get("staleness_budget"), (
                f"{probe['id']} enabled without staleness_budget")

    def test_v1_probes_and_slots_present(self):
        ids = {p["id"]: p for p in sls.PROBES}
        for pid in ("heartbeat_mtime", "ledger_tail",
                    "hooks_declared_vs_disk", "stall_fingerprint"):
            assert ids.get(pid, {}).get("enabled") is True, pid
        # slots went LIVE when their data sources landed (#879 -> rate,
        # #882 -> lag); both are guarded probes now (see test_backtrack_loop_882)
        for pid in ("unattributed_rate", "backtrack_lag"):
            assert ids.get(pid, {}).get("enabled") is True, pid

    def test_slots_execute_with_sources(self, tmp_path):
        """(#882 evolution of test_slots_never_execute): the former inert
        slots run and report like any guarded probe."""
        ws = _make_ws(tmp_path)
        snap = sls.build_snapshot(ws)
        ran = {d["id"] for d in snap["probe_detail"]}
        assert {"unattributed_rate", "backtrack_lag"} <= ran

    def test_new_probe_declaration_auto_wires(self, tmp_path, monkeypatch):
        """注册表驱动：声明即接入——新增探针条目无需改 writer 代码即出现在快照。"""
        ws = _make_ws(tmp_path)
        extra = {"id": "fake_probe", "dimension": "moving",
                 "probe": "always_fault", "threshold": 1, "unit": "tick",
                 "staleness_budget": "2 tick", "severity": "WARN",
                 "short_code": "[fake]", "enabled": True}
        registry = list(sls.PROBES) + [extra]
        monkeypatch.setattr(sls, "PROBES", registry)
        monkeypatch.setattr(sls, "run_probe", sls._make_run_probe(registry))
        snap = sls.build_snapshot(ws)
        by_id = {d["id"]: d for d in snap["probe_detail"]}
        assert "fake_probe" in by_id
        assert by_id["fake_probe"]["short_code"] == "[fake]"


# ---------- alive probes ----------

class TestAliveProbes:
    def test_fresh_heartbeat_ok(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _emit(ws, "tool_call")
        detail = {d["id"]: d for d in sls.build_snapshot(ws)["probe_detail"]}
        assert detail["heartbeat_mtime"]["ok"] is True

    def test_stale_heartbeat_fault_hard(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws, age_s=40 * 60)  # > HEARTBEAT_STALE_MINUTES
        _emit(ws, "tool_call")
        detail = {d["id"]: d for d in sls.build_snapshot(ws)["probe_detail"]}
        assert detail["heartbeat_mtime"]["ok"] is False
        assert detail["heartbeat_mtime"]["severity"] == "HARD"

    def test_missing_heartbeat_faults(self, tmp_path):
        ws = _make_ws(tmp_path)  # no heartbeat file at all
        _emit(ws, "tool_call")
        detail = {d["id"]: d for d in sls.build_snapshot(ws)["probe_detail"]}
        assert detail["heartbeat_mtime"]["ok"] is False

    def test_ledger_tail_stale_fault(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _emit(ws, "tool_call", age_s=120 * 60)  # ledger quiet for 2h
        detail = {d["id"]: d for d in sls.build_snapshot(ws)["probe_detail"]}
        assert detail["ledger_tail"]["ok"] is False
        assert detail["ledger_tail"]["short_code"] == "[ledger]"


# ---------- deployed probe ----------

def _declare_hooks(ws: Path, files, hook_dir: Path) -> None:
    entries = []
    for f in files:
        entries.append({"matcher": "Bash", "hooks": [{
            "type": "command",
            "command": f"PYTHONUTF8=1 uv run --project "
                       f"{ws.as_posix()} {(hook_dir / f).as_posix()}"}]})
    settings_dir = ws / ".claude"
    settings_dir.mkdir(exist_ok=True)
    (settings_dir / "settings.json").write_text(
        json.dumps({"hooks": {"PreToolUse": entries}}), encoding="utf-8")


_KONG4 = ["heartbeat_touch.py", "worker_budget.py", "dispatch_gate.py",
          "worker_pulse.py"]  # hooks_selfcheck liveness-chain subset


class TestDeployedProbe:
    def test_declared_and_on_disk_ok(self, tmp_path, monkeypatch):
        ws = _make_ws(tmp_path)
        hook_dir = ws / ".claude" / "hooks"
        hook_dir.mkdir(parents=True)
        for f in _KONG4:
            (hook_dir / f).write_text("# hook\n", encoding="utf-8")
        _declare_hooks(ws, _KONG4, hook_dir)
        monkeypatch.setattr(sls, "_hook_candidates", [hook_dir])
        _touch_heartbeat(ws)
        detail = {d["id"]: d for d in sls.build_snapshot(ws)["probe_detail"]}
        assert detail["hooks_declared_vs_disk"]["ok"] is True

    def test_deleted_declaration_flips_warn(self, tmp_path, monkeypatch):
        """删声明 hook → deployed 翻黄 + [hook] 短码指探针（验收 #2）。"""
        ws = _make_ws(tmp_path)
        hook_dir = ws / ".claude" / "hooks"
        hook_dir.mkdir(parents=True)
        for f in _KONG4:
            (hook_dir / f).write_text("# hook\n", encoding="utf-8")
        _declare_hooks(ws, _KONG4[:-1], hook_dir)  # worker_pulse NOT declared
        monkeypatch.setattr(sls, "_hook_candidates", [hook_dir])
        _touch_heartbeat(ws)
        snap = sls.build_snapshot(ws)
        detail = {d["id"]: d for d in snap["probe_detail"]}
        assert detail["hooks_declared_vs_disk"]["ok"] is False
        assert detail["hooks_declared_vs_disk"]["severity"] == "WARN"
        assert "[hook]" in snap["probe_codes"]

    def test_declared_but_file_missing_hard(self, tmp_path, monkeypatch):
        ws = _make_ws(tmp_path)
        hook_dir = ws / ".claude" / "hooks"
        hook_dir.mkdir(parents=True)
        _declare_hooks(ws, _KONG4, hook_dir)  # files absent on disk
        monkeypatch.setattr(sls, "_hook_candidates", [hook_dir])
        _touch_heartbeat(ws)
        detail = {d["id"]: d for d in sls.build_snapshot(ws)["probe_detail"]}
        assert detail["hooks_declared_vs_disk"]["ok"] is False
        assert detail["hooks_declared_vs_disk"]["severity"] == "HARD"


# ---------- stall + audit ----------

class TestStallAndAudit:
    def test_stall_fingerprint_trips(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _open_claim(ws)
        _emit(ws, "tool_call", age_s=30)
        _noop(ws, count=6)
        snap = sls.build_snapshot(ws)
        detail = {d["id"]: d for d in snap["probe_detail"]}
        assert detail["stall_fingerprint"]["ok"] is False
        assert "[stall]" in snap["probe_codes"]
        assert snap["state"] == "stall"

    def test_stall_needs_open_claims(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _emit(ws, "tool_call", age_s=30)
        _noop(ws, count=6)  # idle workspace: identical state is honest idle
        snap = sls.build_snapshot(ws)
        assert snap["state"] == "idle"

    def test_audit_age_severity_grading(self, tmp_path):
        """审计级数据显示审计年龄，不冒充实时（验收 #9）：fresh=ok / stale=WARN。"""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _selfcheck_report(ws, age_min=2)
        snap = sls.build_snapshot(ws)
        detail = {d["id"]: d for d in snap["probe_detail"]}
        assert detail["audit_age"]["ok"] is True
        assert snap["audit"]["age_min"] < 5

        # stale audit in a second fixture
        ws3 = tmp_path / "ws3"
        (ws3 / "runs").mkdir(parents=True)
        (ws3 / "analysis_state.txt").write_text("x\n", encoding="utf-8")
        (ws3 / "claim-register.yaml").write_text("claims: []\n",
                                                 encoding="utf-8")
        _touch_heartbeat(ws3)
        _selfcheck_report(ws3, age_min=90)
        snap3 = sls.build_snapshot(ws3)
        detail3 = {d["id"]: d for d in snap3["probe_detail"]}
        assert detail3["audit_age"]["ok"] is False
        assert detail3["audit_age"]["severity"] == "WARN"
        assert snap3["audit"]["age_min"] >= 60


# ---------- state machine ----------

class TestStateMachine:
    def _healthy_env(self, ws: Path) -> None:
        _touch_heartbeat(ws)
        _emit(ws, "tool_call", age_s=10)
        _selfcheck_report(ws)

    def test_transition_table(self, tmp_path):
        # idle: no OPEN claims
        ws = _make_ws(tmp_path)
        self._healthy_env(ws)
        assert sls.build_snapshot(ws)["state"] == "idle"

        # analyzing: OPEN claim + recent activity
        ws2 = tmp_path / "ws2"
        (ws2 / "runs").mkdir(parents=True)
        (ws2 / "analysis_state.txt").write_text("x\n", encoding="utf-8")
        (ws2 / "claim-register.yaml").write_text("claims: []\n",
                                                 encoding="utf-8")
        self._healthy_env(ws2)
        _open_claim(ws2)
        _mission(ws2, answered=1, total=4)
        assert sls.build_snapshot(ws2)["state"] == "analyzing"

        # toss: dispatch event within window
        _emit(ws2, "dispatch", age_s=5)
        assert sls.build_snapshot(ws2)["state"] == "toss"

        # stall: noop breaker tripped (already covered in TestStallAndAudit)

        # down: heartbeat stale
        _touch_heartbeat(ws2, age_s=40 * 60)
        assert sls.build_snapshot(ws2)["state"] == "down"

        # flawless: coverage 1.0, no open, no failed, alive
        ws3 = tmp_path / "ws3"
        (ws3 / "runs").mkdir(parents=True)
        (ws3 / "analysis_state.txt").write_text("x\n", encoding="utf-8")
        (ws3 / "claim-register.yaml").write_text("claims: []\n",
                                                 encoding="utf-8")
        self._healthy_env(ws3)
        _mission(ws3, answered=4, total=4)
        assert sls.build_snapshot(ws3)["state"] == "flawless"

    def test_down_wins_precedence(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws, age_s=40 * 60)
        _open_claim(ws)
        _noop(ws, count=9)  # stall conditions also met
        assert sls.build_snapshot(ws)["state"] == "down"

    def test_flawless_beats_stall(self, tmp_path):
        ws = _make_ws(tmp_path)
        self._healthy_env(ws)
        _mission(ws, answered=2, total=2)
        _noop(ws, count=9)
        assert sls.build_snapshot(ws)["state"] == "flawless"


# ---------- flash ----------

class TestFlash:
    def _ws_with_prev(self, tmp_path: Path, prev_coverage: float,
                      open_claim: bool = True):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        if open_claim:
            _open_claim(ws)
        answered = int(prev_coverage * 4)
        _mission(ws, answered=answered, total=4)
        sls.write_snapshot(ws)
        return ws

    def test_milestone_crossing_triggers_flash(self, tmp_path):
        ws = self._ws_with_prev(tmp_path, 0.25)  # exactly at 25%: cross to 50%
        _mission(ws, answered=2, total=4, v_m_hist=[1.0, 2.0])  # crosses 50%
        snap = sls.build_snapshot(ws)
        assert snap["flash"]["reason"] == "milestone_50"
        assert "剩" in snap["flash"]["text"]

    def test_no_trigger_keeps_seq(self, tmp_path):
        ws = self._ws_with_prev(tmp_path, 0.0)
        _emit(ws, "tool_call")  # activity but no milestone/state change
        prev = json.loads((ws / "runs" / ".kunglao-statusline.json")
                          .read_text(encoding="utf-8"))
        snap = sls.build_snapshot(ws)
        assert snap["flash"]["seq"] == prev["flash"]["seq"]

    def test_state_change_triggers_flash(self, tmp_path):
        ws = self._ws_with_prev(tmp_path, 0.0, open_claim=False)  # prev: idle
        _open_claim(ws)  # idle -> analyzing
        snap = sls.build_snapshot(ws)
        assert snap["flash"]["reason"] == "state_change"
        assert snap["flash"]["seq"] >= 1


# ---------- snapshot writer ----------

class TestSnapshotWriter:
    def test_schema_shape(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _emit(ws, "tool_call")
        _mission(ws, answered=1, total=4)
        snap = sls.build_snapshot(ws)
        assert snap["schema"] == 1
        for key in ("ts", "workspace", "state", "state_since", "prev_state",
                    "color", "probe_codes", "probe_detail", "pq", "v_m",
                    "d_slope", "eta_ticks", "eta_fade_cells", "elapsed",
                    "activity", "flash", "audit"):
            assert key in snap, key
        assert snap["pq"]["coverage"] == pytest.approx(0.25)
        assert snap["pq"]["total"] == 4

    def test_atomic_write_no_tmp_leftover(self, tmp_path):
        ws = _make_ws(tmp_path)
        sls.write_snapshot(ws)
        out = ws / "runs" / ".kunglao-statusline.json"
        assert out.exists()
        assert not (ws / "runs" / ".kunglao-statusline.json.tmp").exists()
        assert json.loads(out.read_text(encoding="utf-8"))["schema"] == 1

    def test_down_auto_flip(self, tmp_path):
        """kill kunglao（停 touch）→ 下一次 writer 看到陈旧 heartbeat → down。"""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _open_claim(ws)
        sls.write_snapshot(ws)
        first = json.loads((ws / "runs" / ".kunglao-statusline.json")
                           .read_text(encoding="utf-8"))
        assert first["state"] in ("analyzing", "toss")
        # ... kunglao dies: heartbeat mtime stops, 40 min pass
        _touch_heartbeat(ws, age_s=40 * 60)
        sls.write_snapshot(ws)
        second = json.loads((ws / "runs" / ".kunglao-statusline.json")
                            .read_text(encoding="utf-8"))
        assert second["state"] == "down"

    def test_tick_integration_writes_snapshot(self, tmp_path):
        """挂点集成：真实 heartbeat_tick CLI 跑完 → 快照在盘上（fail-open 不失败 tick）。"""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "heartbeat_tick.py"), str(ws)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180)
        out = ws / "runs" / ".kunglao-statusline.json"
        assert out.exists(), (
            f"tick must pre-write the statusline snapshot; rc={r.returncode} "
            f"stderr={r.stderr[-300:]}")
        assert json.loads(out.read_text(encoding="utf-8"))["schema"] == 1

    def test_tick_survives_snapshot_failure(self, tmp_path, monkeypatch):
        """writer 崩溃不得失败 tick：fail-open 同款（#873 cockpit 惯例）。"""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        import heartbeat_tick as hbt
        orig = sls.write_snapshot

        def boom(ws_, *a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(sls, "write_snapshot", boom)
        rc = hbt.main([str(ws)])
        monkeypatch.setattr(sls, "write_snapshot", orig)
        assert rc in (0, 1)  # tick ran to its own verdict, not a crash
