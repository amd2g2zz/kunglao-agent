# -*- coding: utf-8 -*-
"""tests/test_lane_profile_791.py — #791 init v2: lane profiles + capability axis.

The 51job replay pins (owner logs-panel amendment, 2026-10-23):
  - a lane:web init produces ZERO binary prescan obligations
    (no apkid/die/java_reachability) and a web factor set in difficulty;
  - a lane:binary (malware) init keeps today's prescan + difficulty
    families (no regression);
  - an unknown lane falls back to current behavior (loud WARN, binary set);
  - zero capability-fabricated dispatches: a dispatch whose declared tools
    mechanically require an env capability that runs/env-state.json records
    DOWN is REJECTED (never dispatched on a fabricated capability).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

import lane_profile  # noqa: E402
import lane_spec  # noqa: E402
import intake_promise  # noqa: E402
import difficulty_calibration as dc  # noqa: E402
import env_state_probe  # noqa: E402


# ---------- fixtures ----------

def _report(*items) -> SimpleNamespace:
    return SimpleNamespace(items=list(items))


def _item(name: str, status: str, fix: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, status=status, fix=fix)


def _ws(tmp_path, task_spec=None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    if task_spec is not None:
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(task_spec, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    return ws


@pytest.fixture(autouse=True)
def _no_host_tools(monkeypatch):
    monkeypatch.setattr(intake_promise, "_which_tool", lambda tool: None)


# ---------- 1. the registry (single source) ----------

class TestLaneProfileRegistry:
    def test_every_enum_lane_has_a_profile(self) -> None:
        for lane in lane_spec.LANES:
            prof, exact = lane_profile.profile_for(lane)
            assert exact, f"lane {lane!r} missing from the registry"
            assert isinstance(prof, dict)

    def test_web_lane_declares_zero_binary_probes(self) -> None:
        prof, _ = lane_profile.profile_for("web")
        assert "apkid" not in prof["prescan_probes"]
        assert "die" not in prof["prescan_probes"]
        assert not prof.get("java_reachability")
        assert lane_profile.obligation_artifacts("web") == ()

    def test_malware_lane_keeps_the_binary_battery(self) -> None:
        assert lane_profile.prescan_probes("malware") == ("apkid", "die")
        assert lane_profile.obligation_artifacts("malware") == (
            "evidence/apkid.json", "evidence/die.json")

    def test_unknown_lane_fails_open_to_the_binary_set(self) -> None:
        prof, exact = lane_profile.profile_for("nonexistent-lane")
        assert exact is False
        # fail-open = today's (pre-#791) binary behavior
        assert lane_profile.prescan_probes("nonexistent-lane") == ("apkid", "die")

    def test_capability_vocabulary_includes_device_root(self) -> None:
        # R2 (logs panel): the lane capability axis carries device_root —
        # the machine-anchored counter-check the "device has no root"
        # narration lacked.
        caps = lane_profile.lane_capabilities("malware")
        assert "device_root" in caps
        assert "frida_server" in caps and "jdwp_debug" in caps

    def test_capability_family_reverse_map(self) -> None:
        assert lane_profile.capabilities_for_family("frida") == \
            ("frida_server",)
        assert lane_profile.capabilities_for_family("vm") == \
            ("vm_reachable",)
        assert lane_profile.capabilities_for_family("ghidra") == ()


# ---------- 2. the 51job replay pin: promise pruning ----------

class TestPromiseLanePruning:
    def test_web_lane_promise_has_zero_binary_entries(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        rep = _report(_item("apkid", "FAIL", fix="install apkid"),
                      _item("die", "FAIL", fix="install die"),
                      _item("jadx", "FAIL", fix="install jadx"))
        p = intake_promise.build(rep, {"lane": "web"}, ws)
        assert p["prescan"] == {}, (
            "out-of-lane probes are DROPPED at init, not emitted as WARN")
        assert "java_reachability" not in p
        assert "obfuscation_prior" not in p
        assert p["lane"] == "web"
        assert p["prescan_obligation"]["required"] == []
        assert p["prescan_obligation"]["lane"] == "web"

    def test_malware_lane_promise_unchanged(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "malware"})
        rep = _report(_item("apkid", "FAIL", fix="install apkid"),
                      _item("die", "FAIL", fix="install die"),
                      _item("jadx", "FAIL", fix="install jadx"))
        p = intake_promise.build(rep, {"lane": "malware"}, ws)
        assert set(p["prescan"]) == {"apkid", "die"}
        assert p["prescan"]["apkid"]["state"] == "missing"
        assert "java_reachability" in p
        assert p["prescan_obligation"]["required"] == [
            "evidence/apkid.json", "evidence/die.json"]

    def test_lane_undeclared_keeps_malware_default(self, tmp_path) -> None:
        ws = _ws(tmp_path, None)
        rep = _report(_item("apkid", "FAIL", fix="x"),
                      _item("die", "FAIL", fix="x"),
                      _item("jadx", "FAIL", fix="x"))
        p = intake_promise.build(rep, {}, ws)
        assert set(p["prescan"]) == {"apkid", "die"}

    def test_unknown_lane_falls_back_with_loud_warn(
            self, tmp_path, capsys) -> None:
        ws = _ws(tmp_path, {"lane": "web2"})
        rep = _report(_item("apkid", "FAIL", fix="x"),
                      _item("die", "FAIL", fix="x"),
                      _item("jadx", "FAIL", fix="x"))
        p = intake_promise.build(rep, {"lane": "web2"}, ws)
        assert set(p["prescan"]) == {"apkid", "die"}, (
            "unknown lane = today's binary yaml (fail-open)")
        blob = capsys.readouterr().err + capsys.readouterr().out
        assert "lane_profile" in blob or "WARN" in blob


# ---------- 3. difficulty: per-lane factor sets + honest unknown ----------

class TestDifficultyFactorSets:
    def test_web_lane_gets_web_factor_set_and_unknown_tier(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "web"})
        result = dc.calibrate_workspace(ws)
        assert result["factor_set"] == "web"
        assert result["tier"] == "unknown", (
            "panel amendment 2: absent extractors = UNKNOWN, never easy")
        assert set(result["families"]) == {
            "captcha_anti_bot", "auth_session",
            "pagination_integrity", "rate_limit"}
        assert all(not f["active"] for f in result["families"].values())

    def test_malware_lane_keeps_binary_families(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "malware"})
        result = dc.calibrate_workspace(ws)
        assert result["factor_set"] == "binary"
        assert set(result["families"]) == {
            "packing", "obfuscation", "anti_analysis", "surface_reduction"}
        # no evidence, no native entry -> the historic easy default
        assert result["tier"] == "easy"

    def test_unknown_lane_binary_fail_open(self, tmp_path) -> None:
        ws = _ws(tmp_path, {"lane": "nonexistent-lane"})
        result = dc.calibrate_workspace(ws)
        assert result["factor_set"] == "binary"

    def test_binary_scoring_regression_pin(self) -> None:
        # the locked #15 corpus shape must survive the factor_set plumbing
        die = {"derived": {"detected_packer": "themida",
                           "section_table": [{"entropy": 7.9}]}}
        feats = dc.features_from_evidence({"die": die, "apkid": None})
        feats["factor_set"] = "binary"
        out = dc.calibrate(feats)
        assert out["tier"] in ("hard", "max")

    def test_web_factors_without_weights_stay_unknown(self) -> None:
        # a future web extractor reporting factors must NOT silently
        # score easy under the unvalidated binary weights
        feats = {"factor_set": "web", "coverage": {},
                 "factors": {"captcha_signal": {"score": 1.0,
                                                "source": "web"}},
                 "gaps": []}
        out = dc.calibrate(feats)
        assert out["tier"] == "unknown"


# ---------- 4. env_state_probe: device_root vocabulary ----------

class TestEnvStateDeviceRoot:
    def test_android_caps_vocabulary_includes_device_root(self) -> None:
        assert "device_root" in env_state_probe.ANDROID_CAPS

    def test_android_probe_emits_device_root_entry(
            self, tmp_path, monkeypatch) -> None:
        ws = _ws(tmp_path, {"project_type": "android"})
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump({"project_type": "android"}), encoding="utf-8")
        monkeypatch.setattr(env_state_probe, "read_project_type",
                            lambda _ws: "android")
        monkeypatch.setattr(env_state_probe, "_adb_path", lambda: "/fake/adb")
        monkeypatch.setattr(env_state_probe, "_adb_device_attached",
                            lambda adb: (True, "adb devices: 1 attached"))
        monkeypatch.setattr(env_state_probe.tc, "_run_cmd", lambda *a, **k: (
            0, "uid=0(root) gid=0(root)", ""))
        state = env_state_probe.probe(ws)
        entry = state["per_capability"]["device_root"]
        assert entry["status"] == "pass"

    def test_device_root_fail_is_honest_not_fabricated(
            self, tmp_path, monkeypatch) -> None:
        ws = _ws(tmp_path)
        monkeypatch.setattr(env_state_probe, "read_project_type",
                            lambda _ws: "android")
        monkeypatch.setattr(env_state_probe, "_adb_path", lambda: "/fake/adb")
        monkeypatch.setattr(env_state_probe, "_adb_device_attached",
                            lambda adb: (True, "adb devices: 1 attached"))
        monkeypatch.setattr(env_state_probe.tc, "_run_cmd", lambda *a, **k: (
            1, "uid=2000(shell)", "su: not found"))
        state = env_state_probe.probe(ws)
        assert state["per_capability"]["device_root"]["status"] == "fail"

    def test_no_adb_skips_never_fabricates(self, tmp_path, monkeypatch) -> None:
        ws = _ws(tmp_path)
        monkeypatch.setattr(env_state_probe, "read_project_type",
                            lambda _ws: "android")
        monkeypatch.setattr(env_state_probe, "_adb_path", lambda: None)
        state = env_state_probe.probe(ws)
        entry = state["per_capability"]["device_root"]
        assert entry["status"] == "skip"


# ---------- 5. dispatch gate: zero capability-fabricated dispatches -----

def _dispatch_prompt(tools: list[str]) -> str:
    return json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1,
        "tools": tools, "agent": "kunglao-worker"}}) + "\ntrace the method"


def _ws_with_claim(tmp_path, task_spec) -> Path:
    ws = _ws(tmp_path, task_spec)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-1", "status": "OPEN",
                     "statement": "trace it", "answers_question": "q1"}]}),
        encoding="utf-8")
    return ws


def _env_state(ws: Path, caps: dict) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = {"per_capability": caps, "written_by": "env_state_probe",
           "ts": ts}
    (ws / "runs" / "env-state.json").write_text(json.dumps(doc),
                                                encoding="utf-8")


class TestLaneCapabilityGate:
    def test_frida_dispatch_with_frida_server_down_rejects(
            self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _ws_with_claim(tmp_path, {"lane": "malware",
                                       "project_type": "android"})
        _env_state(ws, {"frida_server": {
            "status": "fail", "last_probe_ts": "2026-10-25T00:00:00Z",
            "detail": "forward dead"}})
        rc = dg._lane_capability_gate(ws, "C-1",
                                      _dispatch_prompt(["mcp__frida__ps"]),
                                      trace_id=None)
        assert rc == 2, "a capability-DOWN dispatch must not leave the gate"

    def test_vm_dispatch_with_vm_down_rejects(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _ws_with_claim(tmp_path, {"lane": "malware",
                                       "project_type": "windows"})
        _env_state(ws, {"vm_reachable": {
            "status": "fail", "last_probe_ts": "2026-10-25T00:00:00Z",
            "detail": "lease rotated"}})
        rc = dg._lane_capability_gate(ws, "C-1",
                                      _dispatch_prompt(["vmr-shell"]),
                                      trace_id=None)
        assert rc == 2

    def test_capability_up_passes(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _ws_with_claim(tmp_path, {"lane": "malware",
                                       "project_type": "android"})
        _env_state(ws, {"frida_server": {
            "status": "pass", "last_probe_ts": "2026-10-25T00:00:00Z",
            "detail": "ok"}})
        assert dg._lane_capability_gate(
            ws, "C-1", _dispatch_prompt(["mcp__frida__ps"]),
            trace_id=None) is None

    def test_skip_or_absent_never_fabricates(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _ws_with_claim(tmp_path, {"lane": "malware",
                                       "project_type": "android"})
        _env_state(ws, {"frida_server": {
            "status": "skip", "last_probe_ts": "2026-10-25T00:00:00Z",
            "detail": "no device"}})
        assert dg._lane_capability_gate(
            ws, "C-1", _dispatch_prompt(["mcp__frida__ps"]),
            trace_id=None) is None

    def test_stale_or_missing_env_state_fails_open(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _ws_with_claim(tmp_path, {"lane": "malware"})
        assert dg._lane_capability_gate(
            ws, "C-1", _dispatch_prompt(["mcp__frida__ps"]),
            trace_id=None) is None

    def test_reject_names_component_and_wake_condition(
            self, tmp_path, capsys) -> None:
        import dispatch_gate as dg
        ws = _ws_with_claim(tmp_path, {"lane": "malware",
                                       "project_type": "android"})
        _env_state(ws, {"frida_server": {
            "status": "fail", "last_probe_ts": "2026-10-25T00:00:00Z",
            "detail": "forward dead"}})
        dg._lane_capability_gate(ws, "C-1",
                                 _dispatch_prompt(["mcp__frida__ps"]),
                                 trace_id=None)
        blob = capsys.readouterr().out + capsys.readouterr().err
        assert "frida_server" in blob
        assert "wake" in blob.lower() or "recover" in blob.lower()

    def test_reject_lands_in_unified_log(self, tmp_path) -> None:
        import dispatch_gate as dg
        ws = _ws_with_claim(tmp_path, {"lane": "malware",
                                       "project_type": "android"})
        _env_state(ws, {"frida_server": {
            "status": "fail", "last_probe_ts": "2026-10-25T00:00:00Z",
            "detail": "down"}})
        dg._lane_capability_gate(ws, "C-1",
                                 _dispatch_prompt(["mcp__frida__ps"]),
                                 trace_id=None)
        rows = []
        for log in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
            rows += [json.loads(ln) for ln in log.read_text(
                encoding="utf-8").splitlines() if ln.strip()]
        assert any(r.get("action") == "lane_capability_reject"
                   for r in rows), rows
