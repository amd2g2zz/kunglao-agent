#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_mechanism_scheduler_878.py — #878 机制调度器 (registry + single-host
tick + ledger event bus + cockpit health section).

Sections (TDD order):
  1. registry schema gate: the shipped mechanisms.yaml validates; missing
     trigger / cost_class / cockpit_signal (the three go-live prerequisites)
     is rejected one by one; unknown trigger.type / cost_class / gate /
     channel / depth is rejected; duplicate names rejected; host/channel
     shape cross-checked.
  2. 不入册不许跑: run_due only ever iterates the registry (a spy runner sees
     registered scripts only); an INVALID registry fails CLOSED — the runner
     is never called and a mech_reject face lands.
  3. scheduling decisions + budget: gate-not-due skips without spawning;
     cheap-first ordering under budget pressure; budget exhaustion drops
     (drops counter++) and never counts as a run; failure rc passes through
     (last_rc recorded, NOT a drop); the runner seam keeps legacy call names
     + argv byte-identical to the hand-wired tick steps.
  4. ledger event bus: settlement/stall/plan_review classes; byte-offset
     incremental read (offset advances, partial lines are not consumed,
     rotation resets); event classes wake the policy-retro gate even when
     the settlement lag is below N.
  5. faces: state file {last_run, next_eligible, drops}; --plan answers
     "what runs when" for every registry entry; --check rc contract; the
     real heartbeat_tick carries report["mechanisms"] + all legacy report
     keys; the statusline snapshot carries the mechanisms health section +
     mechanism_health probe; mech_run / mech_reject are registered words.

Constitutional invariant pinned here: the scheduler only ever dispatches
PROPOSAL-class mechanisms declared channel=tick — hooks/os/cli/host channels
are declarative-only (hooks 通道不迁移), no decision authority moves.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import kunglao_log  # noqa: E402
import mechanism_scheduler as ms  # noqa: E402


# ---------------------------------------------------------------- helpers --

def _ws(tmp: Path) -> Path:
    """Minimal workspace the chain scripts accept."""
    ws = tmp / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _entry(name: str, *, channel: str = "tick", ttype: str = "tick",
           gate: str = "always", cost: str = "cheap", depth: str = "workspace",
           argv: list | None = None, entry: str | None = None,
           **extra) -> dict:
    trig: dict = {"type": ttype, "gate": gate}
    trig.update(extra.pop("trigger_extra", {}))
    e = {"name": name,
         "entry": entry or f"scripts/{name}.py",
         "channel": channel,
         "trigger": trig, "cost_class": cost, "depth": depth,
         "cockpit_signal": f"runs/.{name}.json", "owner": "tests",
         "description": "test fixture", "argv": argv or []}
    e.update(extra)
    return e


def _ok_registry(*entries: dict) -> list[dict]:
    return list(entries)


def _spy_runner(calls: list, result: dict | None = None, sleep: float = 0.0):
    def _run(script, ws_arg, *extra):
        calls.append([script, list(extra)])
        if sleep:
            time.sleep(sleep)
        base = {"rc": 0, "stdout": "", "stderr": ""}
        if result is not None:
            base.update(result)
        return dict(base)

    return _run


def _read_state(ws: Path) -> dict:
    try:
        return json.loads(
            (ws / "runs" / ".mechanisms-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# ==========================================================================
# 1. registry schema gate
# ==========================================================================

class TestRegistrySchemaGate:
    def test_shipped_registry_validates(self):
        """随仓 mechanisms.yaml 必须过门——schema 门是机械化的，不是文档约定。"""
        out = ms.validate_registry()
        assert out["ok"], out["errors"]
        assert out["mechanisms"] >= 13, (
            "8 entries + tick advisory children must all be registered")

    def test_shipped_registry_covers_the_8_entries(self):
        entries, errors = ms.load_registry()
        assert not errors, errors
        names = {e["name"] for e in entries}
        for required in ("heartbeat_register", "loop_birth", "tick_host",
                         "liveness_touch", "dead_session_kicker", "decide_cli",
                         "workspace_monitor", "verify_watch"):
            assert required in names, required

    def test_shipped_every_entry_carries_three_prerequisites(self):
        entries, _ = ms.load_registry()
        for e in entries:
            assert e.get("trigger", {}).get("gate"), e["name"]
            assert e.get("cost_class"), e["name"]
            assert str(e.get("cockpit_signal") or "").strip(), e["name"]

    @pytest.mark.parametrize("prereq", ["trigger", "cost_class", "cockpit_signal"])
    def test_missing_prerequisite_rejected(self, tmp_path, prereq):
        """三项上线前置缺一即拒（issue：不入册不许跑的反向治愈）。"""
        entry = _entry("m1")
        if prereq == "trigger":
            entry.pop("trigger")
        elif prereq == "cost_class":
            entry.pop("cost_class")
        else:
            entry.pop("cockpit_signal")
        path = tmp_path / "mechanisms.yaml"
        import yaml
        path.write_text(yaml.safe_dump(
            {"schema": ms.SCHEMA, "cost_classes": list(ms.COST_CLASSES),
             "trigger_types": list(ms.TRIGGER_TYPES),
             "event_classes": list(ms.EVENT_CLASSES),
             "channels": list(ms.CHANNELS), "depths": list(ms.DEPTHS),
             "mechanisms": [entry]}, allow_unicode=True), encoding="utf-8")
        out = ms.validate_registry(path)
        assert not out["ok"]
        assert any(prereq in err for err in out["errors"]), out["errors"]

    def test_unknown_trigger_type_rejected(self, tmp_path):
        entry = _entry("m1", ttype="whenever")
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("trigger" in e for e in out["errors"])

    def test_unknown_cost_class_rejected(self, tmp_path):
        entry = _entry("m1", cost="free")
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("cost_class" in e for e in out["errors"])

    def test_unknown_gate_rejected(self, tmp_path):
        entry = _entry("m1", gate="vibes")
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("gate" in e for e in out["errors"])

    def test_unknown_channel_rejected(self, tmp_path):
        entry = _entry("m1", channel="smoke-signal")
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("channel" in e for e in out["errors"])

    def test_unknown_depth_rejected(self, tmp_path):
        entry = _entry("m1", depth="galaxy")
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("depth" in e for e in out["errors"])

    def test_duplicate_name_rejected(self, tmp_path):
        out = ms.validate_registry(_write_bad(
            tmp_path, _entry("m1"), _entry("m1")))
        assert not out["ok"] and any("duplicate" in e.lower()
                                     for e in out["errors"])

    def test_host_channel_shape_cross_check(self, tmp_path):
        """host 通道必须 trigger.host=true；channel=host 必须 host 标记。"""
        entry = _entry("tick_host", channel="host")
        entry["trigger"]["host"] = False
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("host" in e for e in out["errors"])

    def test_events_subset_of_event_classes(self, tmp_path):
        entry = _entry("m1", ttype="settlement",
                       trigger_extra={"events": ["settlement", "solar_flare"]})
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("events" in e for e in out["errors"])

    def test_tick_channel_never_manual(self, tmp_path):
        """调度通道的机制不允许 manual 触发（manual 属 cli/hooks/os 声明面）。"""
        entry = _entry("m1", ttype="manual")
        out = ms.validate_registry(_write_bad(tmp_path, entry))
        assert not out["ok"] and any("manual" in e for e in out["errors"])


def _write_bad(tmp_path: Path, *entries: dict) -> Path:
    import yaml
    path = tmp_path / "mechanisms.yaml"
    path.write_text(yaml.safe_dump(
        {"schema": ms.SCHEMA, "cost_classes": list(ms.COST_CLASSES),
         "trigger_types": list(ms.TRIGGER_TYPES),
         "event_classes": list(ms.EVENT_CLASSES), "channels": list(ms.CHANNELS),
         "depths": list(ms.DEPTHS), "mechanisms": list(entries)},
        allow_unicode=True), encoding="utf-8")
    return path


# ==========================================================================
# 2. 不入册不许跑 (fail-closed)
# ==========================================================================

class TestRegistryOnlyExecution:
    def test_only_registered_scripts_run(self, tmp_path, monkeypatch):
        """调度器只遍历注册表——runner 见到的脚本名物理上不可能出册。"""
        ws = _ws(tmp_path)
        monkeypatch.setattr(ms, "load_registry", lambda: (
            _ok_registry(_entry("registered_one", argv=["--flag"])), []))
        calls: list = []
        ms.run_due(ws, budget_s=30, runner=_spy_runner(calls))
        assert calls == [["registered_one.py", ["--flag"]]]

    def test_invalid_registry_fails_closed(self, tmp_path, monkeypatch):
        """册坏 = 整轮拒跑（"不入册不许跑"的反面），mech_reject 落账。"""
        ws = _ws(tmp_path)
        calls: list = []
        emitted: list = []
        monkeypatch.setattr(
            ms, "load_registry",
            lambda: (_ok_registry(), ["mechanism 'm1': missing cost_class"]))
        monkeypatch.setattr(kunglao_log, "emit",
                            lambda ws, a, action, **kw: emitted.append(action))
        report = ms.run_due(ws, budget_s=30, runner=_spy_runner(calls))
        assert calls == [], "fail-closed: nothing runs on a broken registry"
        assert report["error"]
        assert "mech_reject" in emitted


# ==========================================================================
# 3. scheduling decisions + budget
# ==========================================================================

class TestSchedulingDecisions:
    def _two_mechs(self, monkeypatch, first: dict, second: dict):
        monkeypatch.setattr(
            ms, "load_registry", lambda: (_ok_registry(first, second), []))

    def test_gate_not_due_skips_without_spawning(self, tmp_path, monkeypatch):
        """policy_retro 非 due：不 spawn 子进程（廉价门先行，贵机制门控排队）。"""
        ws = _ws(tmp_path)
        monkeypatch.setattr(ms, "load_registry", lambda: (_ok_registry(
            _entry("policy_retro", ttype="settlement", gate="policy_due",
                   cost="expensive", argv=["--policy"])), []))
        calls: list = []
        report = ms.run_due(ws, budget_s=30, runner=_spy_runner(calls))
        assert calls == []
        assert report["skipped"] == ["policy_retro"]
        assert report["results"]["policy_retro"]["skipped"] is True

    def test_policy_gate_due_runs(self, tmp_path, monkeypatch):
        """settlement lag ≥ N → 门开 → runner 被调（脚本名+argv 与 #882 手搓一致）。"""
        import backtrack_loop as bl
        ws = _ws(tmp_path)
        for i in range(bl.POLICY_EVERY_N_SETTLEMENTS):
            bl.record_settlement(ws, f"C-00{i}", "REFUTED", outcome="REFUTED")
        monkeypatch.setattr(ms, "load_registry", lambda: (_ok_registry(
            _entry("policy_retro", entry="scripts/backtrack_loop.py",
                   ttype="settlement", gate="policy_due",
                   cost="expensive", argv=["--policy"])), []))
        calls: list = []
        ms.run_due(ws, budget_s=30, runner=_spy_runner(calls))
        assert calls == [["backtrack_loop.py", ["--policy"]]]

    def test_cheap_first_under_budget(self, tmp_path, monkeypatch):
        """预算只够一个：注册表顺序 expensive 在前，cheap 仍先跑（cost 排队）。"""
        ws = _ws(tmp_path)
        self._two_mechs(
            monkeypatch,
            _entry("exp_first", cost="expensive"),
            _entry("cheap_second", cost="cheap"))
        calls: list = []
        report = ms.run_due(ws, budget_s=0.05,
                            runner=_spy_runner(calls, sleep=0.08))
        assert report["ran"] == ["cheap_second"], calls
        assert report["dropped"] == [{"name": "exp_first", "reason": "budget"}]

    def test_budget_drop_increments_drops(self, tmp_path, monkeypatch):
        ws = _ws(tmp_path)
        self._two_mechs(
            monkeypatch,
            _entry("cheap_a", cost="cheap"),
            _entry("exp_b", cost="expensive"))
        ms.run_due(ws, budget_s=0.05, runner=_spy_runner([], sleep=0.08))
        state = _read_state(ws)["mechanisms"]
        assert state["exp_b"]["drops"] == 1
        assert state["exp_b"]["last_drop_reason"] == "budget"
        assert state["cheap_a"]["drops"] == 0

    def test_failure_rc_passthrough_not_a_drop(self, tmp_path, monkeypatch):
        """失败是"跑了但失败"（last_rc 落账），不是"候选未跑"（drops 不动）。"""
        ws = _ws(tmp_path)
        monkeypatch.setattr(ms, "load_registry", lambda: (
            _ok_registry(_entry("failing_mech")), []))
        calls: list = []
        report = ms.run_due(
            ws, budget_s=30,
            runner=_spy_runner(calls, result={"rc": 1, "stderr": "boom"}))
        assert report["ran"] == ["failing_mech"]
        res = report["results"]["failing_mech"]
        assert res["rc"] == 1 and res["stderr"] == "boom"
        state = _read_state(ws)["mechanisms"]["failing_mech"]
        assert state["last_rc"] == 1 and state["drops"] == 0

    def test_state_records_last_run_and_next_eligible(self, tmp_path, monkeypatch):
        ws = _ws(tmp_path)
        monkeypatch.setattr(ms, "load_registry", lambda: (
            _ok_registry(_entry("some_mech")), []))
        ms.run_due(ws, budget_s=30, runner=_spy_runner([]))
        row = _read_state(ws)["mechanisms"]["some_mech"]
        assert row["last_run"]
        assert row["next_eligible"]
        assert row["runs"] == 1

    def test_scheduler_face_is_advisory(self, tmp_path, monkeypatch):
        """调度段全程 fail-open：机制崩溃永不产生异常（advisory 姿态）。"""
        ws = _ws(tmp_path)
        monkeypatch.setattr(ms, "load_registry", lambda: (
            _ok_registry(_entry("exploder")), []))

        def _explode(script, ws_arg, *extra):
            raise RuntimeError("runner exploded")

        report = ms.run_due(ws, budget_s=30, runner=_explode)
        assert report["results"]["exploder"]["rc"] == -1

    def test_legacy_report_key_mapping(self):
        """legacy tick 报告 key 的回填映射（monitor/feedback/verify_watch/
        rollup_sweep/think/backtrack/env_state）单源在调度器。"""
        assert ms.LEGACY_REPORT_KEYS == {
            "env_probe": "env_state",
            "workspace_monitor": "monitor",
            "stale_feedback": "feedback",
            "verify_watch": "verify_watch",
            "notes_rollup": "rollup_sweep",
            "think_seat": "think",
            "policy_retro": "backtrack",
        }


# ==========================================================================
# 4. ledger event bus (byte-offset incremental)
# ==========================================================================

class TestLedgerEventBus:
    def test_settlement_class_mapped(self, tmp_path):
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "hook:write_guard", "claim_settled",
                         claim="C-1", detail='{"to": "PROVEN"}')
        out = ms.read_new_events(ws)
        assert out["counts"].get("settlement") == 1
        out2 = ms.read_new_events(ws)
        assert out2["counts"] == {}, "offset must advance (增量读，不重读旧账)"

    def test_stall_and_plan_review_classes(self, tmp_path):
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "orchestrator", "mission_stall")
        kunglao_log.emit(ws, "orchestrator", "plan_stall")
        kunglao_log.emit(ws, "orchestrator", "plan_review",
                         detail='{"verdict": "adjust"}')
        out = ms.read_new_events(ws)
        assert out["counts"].get("stall") == 2
        assert out["counts"].get("plan_review") == 1

    def test_unknown_actions_ignored_but_offset_advances(self, tmp_path):
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "orchestrator", "tool_call")
        assert ms.read_new_events(ws)["counts"] == {}
        assert ms.read_new_events(ws)["counts"] == {}

    def test_partial_line_not_consumed(self, tmp_path):
        """半行不吞：无换行结尾的截断行留待下次（完成行推进）。"""
        ws = _ws(tmp_path)
        logs = ws / "runs" / "logs"
        logs.mkdir(parents=True)
        f = logs / "kunglao-2099-01-01.jsonl"
        f.write_text('{"ts": "2099-01-01T00:00:00Z", "actor": "orchestrator",'
                     ' "action": "claim_settled"}\n', encoding="utf-8")
        with f.open("a", encoding="utf-8") as fh:
            fh.write('{"ts": "2099-01-01T00:00:0')  # partial, no newline
        out = ms.read_new_events(ws)
        assert out["counts"].get("settlement") == 1
        state = _read_state(ws)["events"]
        fsize = f.stat().st_size
        assert state["offset"] < fsize, "offset must stop before the partial line"
        with f.open("a", encoding="utf-8") as fh:
            fh.write('1Z", "action": "claim_settled"}\n')
        out2 = ms.read_new_events(ws)
        assert out2["counts"].get("settlement") == 1, "残行补全后可读"

    def test_file_rotation_resets_offset(self, tmp_path):
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "orchestrator", "claim_settled")
        ms.read_new_events(ws)
        state = _read_state(ws)
        state["events"] = {"file": "kunglao-2098-01-01.jsonl", "offset": 999_999}
        (ws / "runs" / ".mechanisms-state.json").write_text(
            json.dumps(state), encoding="utf-8")
        out = ms.read_new_events(ws)
        assert out["counts"].get("settlement") == 1, "换日/截断 → 回退重读"

    def test_events_wake_policy_gate_below_lag(self, tmp_path):
        """stall / plan_review 事件类直接唤醒 policy_retro 门（lag < N 也触发）。"""
        ws = _ws(tmp_path)
        kunglao_log.emit(ws, "orchestrator", "plan_review")
        out = ms.read_new_events(ws)
        assert ms.GATES["policy_due"](ws, set(out["counts"])) is True

    def test_policy_gate_quiet_when_nothing_due(self, tmp_path):
        ws = _ws(tmp_path)
        out = ms.read_new_events(ws)
        assert ms.GATES["policy_due"](ws, set(out["counts"])) is False


# ==========================================================================
# 5. faces: --plan / --check / tick integration / statusline / vocabulary
# ==========================================================================

class TestPlanFace:
    def test_plan_answers_what_runs_when(self, tmp_path):
        """一条命令可答"什么机制在什么时候跑"——每条目含 trigger/gate/cost/
        next_eligible/drops 答案。"""
        ws = _ws(tmp_path)
        plan = ms.plan_view(ws)
        names = {r["name"] for r in plan["mechanisms"]}
        for required in ("heartbeat_register", "loop_birth", "tick_host",
                         "liveness_touch", "dead_session_kicker", "decide_cli",
                         "workspace_monitor", "verify_watch", "env_probe",
                         "stale_feedback", "notes_rollup", "think_seat",
                         "policy_retro"):
            assert required in names, required
        for row in plan["mechanisms"]:
            for field in ("channel", "trigger_type", "gate", "cost_class",
                          "depth", "cockpit_signal", "owner", "next_eligible",
                          "last_run", "drops"):
                assert field in row, (row.get("name"), field)

    def test_plan_live_gate_evaluation(self, tmp_path):
        """--plan 对声明面机制现场评估门（session_dead 判死真读心跳）。"""
        ws = _ws(tmp_path)
        plan = ms.plan_view(ws)
        kicker = next(r for r in plan["mechanisms"]
                      if r["name"] == "dead_session_kicker")
        assert kicker["gate_state"] in (True, False)


class TestCheckFace:
    def test_check_cli_ok(self):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "mechanism_scheduler.py"),
             "--check"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60)
        assert r.returncode == 0, r.stderr
        assert "mechanism registry OK" in r.stdout

    def test_check_cli_rejects_bad_registry(self, tmp_path):
        bad_entry = _entry("m1")
        bad_entry.pop("cost_class")  # a real go-live-prerequisite violation
        bad = _write_bad(tmp_path, bad_entry)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "mechanism_scheduler.py"),
             "--check", "--registry", str(bad)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60)
        assert r.returncode == 1
        assert "cost_class" in r.stdout + r.stderr


class TestTickIntegration:
    def _load_tick(self):
        spec = importlib.util.spec_from_file_location(
            "heartbeat_tick_878", SCRIPTS_DIR / "heartbeat_tick.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_real_tick_carries_mechanisms_face_and_legacy_keys(self, tmp_path):
        """真 tick：report["mechanisms"] 新面 + legacy key 全保留 + mech_run 落账。"""
        ws = _ws(tmp_path)
        (ws / "task_spec.yaml").write_text("mission: mech-test\n",
                                           encoding="utf-8")
        ht = self._load_tick()
        ht.main([str(ws)])  # rc is owned by the liveness core, not the scheduler
        report = json.loads((ws / "runs" / ".heartbeat-tick.json")
                            .read_text(encoding="utf-8"))
        mech = report["mechanisms"]
        assert isinstance(mech, dict) and "ran" in mech
        for name in ("env_probe", "workspace_monitor", "stale_feedback",
                     "verify_watch", "notes_rollup", "think_seat"):
            assert name in mech["ran"], (name, mech)
        assert "policy_retro" in mech["skipped"], mech
        for key in ("env_state", "monitor", "feedback", "verify_watch",
                    "rollup_sweep", "think", "backtrack"):
            assert key in report, key
        actions = [json.loads(ln)["action"] for ln in
                   (ws / "runs" / "logs").glob("kunglao-*.jsonl")
                   for ln in ln.read_text(encoding="utf-8").splitlines()
                   if ln.strip()]
        assert "mech_run" in actions

    def test_scheduler_crash_never_fails_the_tick(self, monkeypatch, tmp_path):
        """调度器本身崩溃 → tick 照常绿（fail-open，同 #883 快照挂法）。"""
        ws = _ws(tmp_path)
        ht = self._load_tick()

        def _boom(ws_arg, **kw):
            raise RuntimeError("scheduler down")

        monkeypatch.setattr(ht, "_run_mechanisms", _boom)
        ht.main([str(ws)])  # must not raise — advisory fail-open
        report = json.loads((ws / "runs" / ".heartbeat-tick.json")
                            .read_text(encoding="utf-8"))
        assert "error" in report["mechanisms"]


class TestStatuslineMechanismsSection:
    def test_snapshot_carries_mechanisms_rows(self, tmp_path):
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        (ws / "runs" / ".mechanisms-state.json").write_text(json.dumps({
            "schema": 1,
            "mechanisms": {"workspace_monitor": {
                "last_run": "2026-09-02T00:00:00Z", "next_eligible": "next tick",
                "drops": 2, "last_rc": 0, "runs": 5}}},
        ), encoding="utf-8")
        snap = sls.build_snapshot(ws)
        rows = {r["name"]: r for r in snap["mechanisms"]}
        assert rows["workspace_monitor"]["drops"] == 2
        assert rows["workspace_monitor"]["last_run"] == "2026-09-02T00:00:00Z"

    def test_snapshot_fail_open_without_state(self, tmp_path):
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        snap = sls.build_snapshot(ws)
        assert isinstance(snap["mechanisms"], list)

    def test_mechanism_health_probe_flags_failure(self, tmp_path):
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        (ws / "runs" / ".mechanisms-state.json").write_text(json.dumps({
            "schema": 1,
            "mechanisms": {"notes_rollup": {
                "last_run": "2026-09-02T00:00:00Z", "next_eligible": "next tick",
                "drops": 0, "last_rc": 3, "runs": 1}}},
        ), encoding="utf-8")
        entry = next(p for p in sls.PROBES if p["id"] == "mechanism_health")
        detail = sls.probe_mechanism_health(ws, entry)
        assert detail["ok"] is False
        assert "notes_rollup" in detail["detail"]

    def test_mechanism_health_probe_ok_when_clean(self, tmp_path):
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        entry = next(p for p in sls.PROBES if p["id"] == "mechanism_health")
        detail = sls.probe_mechanism_health(ws, entry)
        assert detail["ok"] is True

    def test_new_probe_requires_staleness_budget(self):
        import statusline_snapshot as sls
        entry = next(p for p in sls.PROBES if p["id"] == "mechanism_health")
        assert entry.get("staleness_budget")
        assert entry.get("enabled", True) is True


class TestVocabularyRegistration:
    def test_mech_words_registered(self):
        import event_taxonomy as et
        assert "mech_run" in et.EMIT_ACTIONS
        assert "mech_reject" in et.EMIT_ACTIONS
        assert et.EMIT_ACTIONS == sorted(et.EMIT_ACTIONS)
        assert len(et.EMIT_ACTIONS) == len(set(et.EMIT_ACTIONS))

    def test_scheduler_emits_registered_words_only(self, tmp_path, monkeypatch):
        """调度器两处 emit 的 action 词全部在册（#459 CI 锚的同源断言）。"""
        ws = _ws(tmp_path)
        monkeypatch.setattr(ms, "load_registry", lambda: (
            _ok_registry(_entry("m1")), []))
        emitted: list = []
        monkeypatch.setattr(kunglao_log, "emit",
                            lambda ws, a, action, **kw: emitted.append(action))
        ms.run_due(ws, budget_s=30, runner=_spy_runner([]))
        import event_taxonomy as et
        assert set(emitted) <= set(et.EMIT_ACTIONS)


# ==========================================================================
# constitutional invariant
# ==========================================================================

class TestConstitutionalIsolation:
    def test_only_tick_channel_dispatched(self, tmp_path, monkeypatch):
        """hooks/os/cli/host 通道永不派发——调度的是运行时机，不是决策权；
        hooks 通道不迁移（issue 排除项的机械化表达）。"""
        ws = _ws(tmp_path)
        monkeypatch.setattr(ms, "load_registry", lambda: (_ok_registry(
            _entry("hook_mech", channel="hooks"),
            _entry("os_mech", channel="os"),
            _entry("cli_mech", channel="cli"),
            _entry("host_mech", channel="host"),
            _entry("tick_mech", channel="tick")), []))
        calls: list = []
        report = ms.run_due(ws, budget_s=30, runner=_spy_runner(calls))
        assert [c[0] for c in calls] == ["tick_mech.py"]
        for name in ("hook_mech", "os_mech", "cli_mech", "host_mech"):
            assert name in report["skipped"]

    def test_shipped_registry_channel_postures(self):
        """随仓注册表的通道姿态钉死：heartbeat_touch 留 hooks 通道；
        kicker 留 os 通道；tick_host 是宿主；policy_retro 是唯一调度面的
        expensive 机制。"""
        entries, errors = ms.load_registry()
        assert not errors, errors
        by = {e["name"]: e for e in entries}
        assert by["liveness_touch"]["channel"] == "hooks"
        assert by["dead_session_kicker"]["channel"] == "os"
        assert by["tick_host"]["channel"] == "host"
        assert by["tick_host"]["trigger"].get("host") is True
        assert by["policy_retro"]["cost_class"] == "expensive"
        assert by["policy_retro"]["trigger"]["type"] == "settlement"
        assert set(by["policy_retro"]["trigger"].get("events") or []) == {
            "settlement", "stall", "plan_review"}
