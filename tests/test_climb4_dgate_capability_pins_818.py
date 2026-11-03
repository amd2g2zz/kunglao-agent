#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_dgate_capability_pins_818.py — #818 climb segment 4F.

Behavior pins on REAL synthetic workspaces for the dispatch-gate faces the
first three climb legs left unmeasured:

  #600 capability-dormant observability (the one-time WARN + additionalContext
  + trace + sentinel; armed/empty/unreadable registers stay silent),
  the #812 capability-probe gate wiring (verifier-remediation early pass,
  the undeclared-lane sleep, the probe-outage fail-open with its trace,
  the skip-visibility trace, and the dead-lane REJECT carrying the
  alternative arm), the #791 lane-capability gate (mechanical
  tools->families->capabilities mapping against a REAL runs/env-state.json
  snapshot: DOWN rejects with the wake condition, healthy passes, no
  near-time state has no opinion), the #772 redo-leak WARN heuristic
  (marker + value overlap on both faces, the silent no-marker/no-diff/
  no-overlap faces), and the #625 verify-before-unwake contract
  (delivery verification over declared fact files, the wait-signal
  write, the withheld wake).

Leaf modules (capability_probe / init_state) are stubbed only for the
gate-WIRING faces; the modules' own behavior is pinned in their own
test files.
"""
from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
SCRIPTS = ROOT / "scripts"
for _p in (str(HOOKS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _factories import stamp_current  # noqa: E402

import dispatch_gate as dg  # noqa: E402


# ------------------------------------------------------------ fixtures

def _ws(tmp_path: Path, claims: list[dict] | None = None,
        name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir()
    stamp_current(ws)
    if claims is None:
        text = "claims:\n- id: C-1\n  status: OPEN\n"
    else:
        text = yaml_dump({"claims": claims})
    (ws / "claim-register.yaml").write_text(text, encoding="utf-8")
    (ws / "runs").mkdir(exist_ok=True)
    return ws


def yaml_dump(data: dict) -> str:
    import yaml
    return yaml.safe_dump(data, allow_unicode=True)


def _v1_prompt(tools: list[str], extra: str = "") -> str:
    return json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-1", "tier": 1, "tools": tools,
    }}) + " analyze the sample" + extra


def _read_stderr(capsys) -> str:
    return capsys.readouterr().err


def _trace_rows(ws: Path) -> list[dict]:
    """The unified-log rows the gate emitted (kunglao-*.jsonl, action key)."""
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if logs.is_dir():
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
    return out


# ================================================= #600 dormant WARN

class TestCapabilityDormant:
    def test_dormant_register_emits_once_with_a_sentinel(
            self, tmp_path, capsys) -> None:
        ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
        dg._emit_capability_dormant(ws, "C-1")
        cap = capsys.readouterr()
        assert "capability_dormant" in cap.err
        out = cap.out
        payload = json.loads(out)
        assert "DORMANT" in payload["hookSpecificOutput"]["additionalContext"]
        assert "obstacle_for" in payload["hookSpecificOutput"][
            "additionalContext"]
        rows = _trace_rows(ws)
        assert any(r.get("action") == "capability_dormant" for r in rows)
        assert (ws / "runs" / ".capability-dormant-warned").exists()

    def test_sentinel_makes_the_warning_one_time(self, tmp_path,
                                                 capsys) -> None:
        ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"}])
        dg._emit_capability_dormant(ws, "C-1")
        capsys.readouterr()
        dg._emit_capability_dormant(ws, "C-1")
        assert _read_stderr(capsys) == ""

    def test_armed_or_empty_or_unreadable_registers_stay_silent(
            self, tmp_path, capsys) -> None:
        armed = _ws(tmp_path, [{"id": "C-1", "status": "OPEN",
                                "obstacle_for": "C-0"}], name="armed")
        dg._emit_capability_dormant(armed, "C-1")
        empty = _ws(tmp_path, [], name="empty")
        dg._emit_capability_dormant(empty, "C-1")
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / "claim-register.yaml").write_text(": :\n[", encoding="utf-8")
        dg._emit_capability_dormant(bad, "C-1")
        assert _read_stderr(capsys) == ""
        assert capsys.readouterr().out == ""


# ============================================ #812 capability-probe gate

class _FakeCP:
    PROBE_TTL_SECONDS = 900

    @staticmethod
    def match_required(prompt: str, ptype: str) -> list:
        if "frida" in prompt.lower():
            return [("dynamic-trace", ("frida_server",))]
        return []

    @staticmethod
    def facts(ws: Path, required: list[str]) -> dict:
        return {name: {"status": "pass", "detail": ""} for name in required}

    @staticmethod
    def alternative_for(family: str) -> str:
        return "static arm (ghidra batch decompile)"


def _fake_init_state(ptype: str | None) -> types.ModuleType:
    mod = types.ModuleType("init_state")

    def read_project_type(_ws: Path):
        return ptype

    mod.read_project_type = read_project_type
    return mod


@pytest.fixture()
def fake_probe_modules(monkeypatch):
    monkeypatch.setitem(sys.modules, "capability_probe", _FakeCP)
    monkeypatch.setitem(sys.modules, "init_state",
                        _fake_init_state("android-app"))


class TestCapabilityProbeGate:
    def test_verifier_remediation_flag_passes_before_any_probe(
            self, tmp_path, fake_probe_modules) -> None:
        ws = _ws(tmp_path)
        rc = dg._capability_probe_gate(ws, "C-1", _v1_prompt(["rev-frida"]),
                                       verifier_remediation=True)
        assert rc is None
        assert _trace_rows(ws) == []

    def test_undeclared_lane_sleeps(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "capability_probe", _FakeCP)
        monkeypatch.setitem(sys.modules, "init_state", _fake_init_state(None))
        ws = _ws(tmp_path)
        assert dg._capability_probe_gate(
            ws, "C-1", _v1_prompt(["rev-frida"])) is None
        assert _trace_rows(ws) == []

    def test_no_matched_family_passes(self, tmp_path,
                                      fake_probe_modules) -> None:
        ws = _ws(tmp_path)
        assert dg._capability_probe_gate(
            ws, "C-1", _v1_prompt(["mcp__ghidra__decompile"])) is None

    def test_probe_infra_outage_fails_open_with_a_trace(
            self, tmp_path, monkeypatch, fake_probe_modules) -> None:
        def broken(ws, required):
            raise RuntimeError("cache bricked")

        monkeypatch.setattr(_FakeCP, "facts", staticmethod(broken))
        ws = _ws(tmp_path)
        assert dg._capability_probe_gate(
            ws, "C-1", _v1_prompt(["rev-frida"])) is None  # never blocks
        rows = _trace_rows(ws)
        assert any(r.get("action") == "capability_probe_fail_open"
                   for r in rows)

    def test_skipped_required_fact_is_visible_not_refused(
            self, tmp_path, monkeypatch, fake_probe_modules, capsys) -> None:
        monkeypatch.setattr(_FakeCP, "facts", staticmethod(
            lambda ws, required: {
                name: {"status": "skip", "detail": "check did not run"}
                for name in required}))
        ws = _ws(tmp_path)
        assert dg._capability_probe_gate(
            ws, "C-1", _v1_prompt(["rev-frida"])) is None
        rows = _trace_rows(ws)
        assert any(r.get("action") == "capability_probe_unverified"
                   for r in rows)

    def test_failed_probe_rejects_with_the_alternative_arm(
            self, tmp_path, monkeypatch, fake_probe_modules,
            capsys) -> None:
        monkeypatch.setattr(_FakeCP, "facts", staticmethod(
            lambda ws, required: {
                name: {"status": "fail", "detail": "no rooted device"}
                for name in required}))
        ws = _ws(tmp_path)
        rc = dg._capability_probe_gate(ws, "C-1",
                                       _v1_prompt(["rev-frida"]))
        assert rc == 2
        rows = _trace_rows(ws)
        assert any(r.get("action") == "capability_probe_reject"
                   for r in rows)
        cap = capsys.readouterr()
        assert "dead capability lane" in cap.err
        # the fix path rides the stdout additionalContext, not stderr
        fix = json.loads(cap.out)["hookSpecificOutput"]["additionalContext"]
        assert "static arm" in fix  # the alternative arm is named
        assert "SEPARATE facts" in fix  # the anti-fabrication guidance


# ============================================ #791 lane-capability gate

def _env_state(ws: Path, caps: dict) -> None:
    (ws / "runs" / "env-state.json").write_text(json.dumps({
        "ts": datetime.now(timezone.utc).isoformat(),
        "per_capability": caps,
    }), encoding="utf-8")


class TestLaneCapabilityGate:
    def test_unparseable_or_toolless_prompts_have_no_opinion(
            self, tmp_path) -> None:
        ws = _ws(tmp_path)
        _env_state(ws, {"frida_server": {"status": "fail",
                                         "detail": "no device"}})
        assert dg._lane_capability_gate(ws, "C-1", "not-a-dispatch") is None
        assert dg._lane_capability_gate(ws, "C-1", _v1_prompt([])) is None

    def test_down_capability_rejects_with_the_wake_condition(
            self, tmp_path, capsys) -> None:
        ws = _ws(tmp_path)
        _env_state(ws, {"frida_server": {"status": "fail",
                                         "detail": "device offline"}})
        rc = dg._lane_capability_gate(ws, "C-1", _v1_prompt(["rev-frida"]))
        assert rc == 2
        rows = _trace_rows(ws)
        assert any(r.get("action") == "lane_capability_reject" for r in rows)
        cap = capsys.readouterr()
        assert "frida_server" in cap.err
        fix = json.loads(cap.out)["hookSpecificOutput"]["additionalContext"]
        assert "component:frida_server recovered" in fix
        assert "Do NOT narrate" in fix

    def test_healthy_capability_passes(self, tmp_path) -> None:
        ws = _ws(tmp_path)
        _env_state(ws, {"frida_server": {"status": "pass", "detail": ""}})
        assert dg._lane_capability_gate(
            ws, "C-1", _v1_prompt(["rev-frida"])) is None

    def test_capability_agnostic_tools_pass(self, tmp_path) -> None:
        ws = _ws(tmp_path)
        _env_state(ws, {"frida_server": {"status": "fail",
                                         "detail": "down"}})
        # ghidra carries no capability dependency in the reverse map
        assert dg._lane_capability_gate(
            ws, "C-1", _v1_prompt(["mcp__ghidra__decompile"])) is None

    def test_stale_state_has_no_opinion(self, tmp_path) -> None:
        ws = _ws(tmp_path)
        (ws / "runs" / "env-state.json").write_text(json.dumps({
            "ts": "2020-01-01T00:00:00+00:00",  # far outside proximity
            "per_capability": {"frida_server": {"status": "fail",
                                                "detail": "stale"}},
        }), encoding="utf-8")
        assert dg._lane_capability_gate(
            ws, "C-1", _v1_prompt(["rev-frida"])) is None


# ==================================================== #772 redo-leak WARN

class TestRedoLeak:
    def _diff_file(self, ws: Path, text: str) -> Path:
        p = ws / "runs" / "verify-redteam-latest.md"
        p.write_text(text, encoding="utf-8")
        return p

    def test_marker_with_value_overlap_warns_on_both_faces(
            self, tmp_path, capsys) -> None:
        ws = _ws(tmp_path)
        self._diff_file(ws, "RED-TEAM VERDICT: CONFIRMED\n"
                             "oracle derived 123456 and "
                             "deadbeefcafebabe0123456789abcdef\n")
        dg._redo_leak_check(ws, "redo the probe with nonce 123456", "C-1")
        cap = capsys.readouterr()
        assert "redo-leak" in cap.err and "123456" in cap.err
        out = cap.out
        payload = json.loads(out)
        assert "123456" in payload["hookSpecificOutput"][
            "additionalContext"]
        rows = _trace_rows(ws)
        assert any(r.get("action") == "redo_leak_warn" for r in rows)

    def test_silent_without_marker_or_diff_or_overlap(
            self, tmp_path, capsys) -> None:
        no_marker = _ws(tmp_path, name="nomarker")
        dg._redo_leak_check(no_marker, "fresh dispatch", "C-1")
        no_diff = _ws(tmp_path, name="nodiff")
        dg._redo_leak_check(no_diff, "redo the probe", "C-1")
        no_overlap = _ws(tmp_path, name="nooverlap")
        self._diff_file(no_overlap, "verdict text with 99999 inside\n")
        dg._redo_leak_check(no_overlap, "redo the probe", "C-1")
        assert _read_stderr(capsys) == ""
        assert capsys.readouterr().out == ""

    def test_diff_values_never_block(self, tmp_path) -> None:
        ws = _ws(tmp_path)
        self._diff_file(ws, "leak 123456\n")
        assert dg._redo_leak_check(
            ws, "redo with 123456", "C-1") is None  # WARN-only face


# ============================================ #625 verify-before-unwake

def _waiting_worker(ws: Path, worker: str = "w1") -> None:
    (ws / "runs" / f"worker-status-{worker}.md").write_text(
        f"# worker {worker}\nstatus: waiting\n"
        "declared: facts/F001.md\n", encoding="utf-8")


def _fact(ws: Path, name: str, frontmatter: str) -> Path:
    p = ws / "facts" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text(f"---\n{frontmatter}\n---\nbody\n", encoding="utf-8")
    return p


class TestVerifyBeforeUnwake:
    def test_faces_without_evidence_fail_open_verified(
            self, tmp_path) -> None:
        ws = _ws(tmp_path)
        assert dg._delivery_verified(ws, None)[0] is True
        assert dg._delivery_verified(ws, "ghost")[0] is True
        _waiting_worker(ws, "w2")
        (ws / "runs" / "worker-status-w2.md").write_text(
            "status: waiting\n", encoding="utf-8")
        ok, why = dg._delivery_verified(ws, "w2")
        assert ok is True and why == "no declared facts"

    def test_verified_delivery_passes(self, tmp_path) -> None:
        ws = _ws(tmp_path)
        _waiting_worker(ws)
        _fact(ws, "F001.md", "status: PROVEN")
        ok, why = dg._delivery_verified(ws, "w1")
        assert ok is True and why == "delivery verified"

    def test_unverified_delivery_is_withheld(self, tmp_path) -> None:
        ws = _ws(tmp_path)
        _waiting_worker(ws)
        _fact(ws, "F001.md", "status: CANDIDATE")
        ok, why = dg._delivery_verified(ws, "w1")
        assert ok is False
        assert "unverified delivery" in why and "F001.md" in why

    def test_wait_signal_writes_for_a_verified_waiting_worker(
            self, tmp_path) -> None:
        ws = _ws(tmp_path)
        _waiting_worker(ws)
        _fact(ws, "F001.md", "verify_status: passes")
        dg._write_wait_signal(ws, "worker-status-w1", "C-1")
        signal = json.loads(
            (ws / "runs" / "wait-signal-w1.json").read_text(
                encoding="utf-8"))
        assert signal["type"] == "dispatch"
        assert signal["claim"] == "C-1"

    def test_wait_signal_withheld_until_verified(self, tmp_path,
                                                 capsys) -> None:
        ws = _ws(tmp_path)
        _waiting_worker(ws)
        _fact(ws, "F001.md", "status: CANDIDATE")
        dg._write_wait_signal(ws, "w1", "C-1")
        assert "UNWAIT withheld" in _read_stderr(capsys)
        assert not (ws / "runs" / "wait-signal-w1.json").exists()

    def test_wait_signal_for_an_unknown_worker_writes_nothing(
            self, tmp_path) -> None:
        ws = _ws(tmp_path)
        dg._write_wait_signal(ws, "nobody", "C-1")
        assert not list((ws / "runs").glob("wait-signal-*"))
