# -*- coding: utf-8 -*-
"""TDD tests — issue #460 intake probe battery (the instrument face).

Spec: openspec/changes/issue-460-intake-battery/specs/intake-battery/spec.md
Every test maps to a Requirement/Scenario there (names in comments).

The battery is an INSTRUMENT (owner ruling): it reads the environment
once at intake so die/apkid features exist from run #1 — feeding the
feature-conditioned prior and the mined table. Instruments degrade,
they never gate: probe failure = absent evidence + a fact row, never
an intake failure.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import intake_battery  # noqa: E402  (the module under test)
import intake_promise  # noqa: E402
import feature_mining  # noqa: E402

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# diec-style JSON shapes the fake emits (mirrors die_probe FLAG_CALLS):
# -j/-b -> detects; -e -> per-section entropy; -S Hash/Resource -> data.
_FAKE_DIE_DETECTS = json.dumps(
    {"detects": [{"values": [{"name": "UPX", "type": "packer",
                              "version": "3.96"}]}]})
_FAKE_DIE_ENTROPY = json.dumps(
    {"records": [{"name": "Section [.text]", "offset": 1024, "size": 4096,
                  "entropy": 7.2, "status": ""}],
     "status": "ok", "total": 7.2})
_FAKE_DIE_HASH = json.dumps({"data": {"Hash": {"md5": "0" * 32}}})
_FAKE_DIE_RESOURCE = json.dumps({"data": {"Resource": {}}})
_FAKE_APKID_SCAN = json.dumps({
    "apkid_version": "2.1.5-fake",
    "results": {"beacon.apk": {"findings": [
        {"rule": "Bangcle", "category": "packer",
         "description": "d", "matched_files": ["classes.dex"]},
        {"rule": "DexGuard", "category": "obfuscator",
         "description": "d", "matched_files": ["classes.dex"]}]}}})

# Fake probe executables: python scripts printing CONSTANT payloads per
# argument shape (the diec/apkid stand-ins; no external input reaches
# them — the bodies below are static test data).
_DIEC_FAKE_BODY = f"""#!/usr/bin/env python3
import sys
DETECTS = {_FAKE_DIE_DETECTS!r}
ENTROPY = {_FAKE_DIE_ENTROPY!r}
HASHES = {_FAKE_DIE_HASH!r}
RESOURCES = {_FAKE_DIE_RESOURCE!r}
args = sys.argv[1:]
if "-e" in args:
    print(ENTROPY)
elif "Hash" in args:
    print(HASHES)
elif "Resource" in args:
    print(RESOURCES)
else:
    print(DETECTS)
"""

_APKID_FAKE_BODY = f"""#!/usr/bin/env python3
import sys
SCAN = {_FAKE_APKID_SCAN!r}
if "--version" in sys.argv[1:]:
    print("apkid 2.1.5-fake")
else:
    print(SCAN)
"""


def _write_exec(dir_: Path, name: str, body: str) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    p = dir_ / name
    p.write_text(body, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return p


def _fake_diec(dir_: Path) -> Path:
    """A diec stand-in answering every die_probe flag shape."""
    return _write_exec(dir_, "fake-diec", _DIEC_FAKE_BODY)


def _fake_apkid(dir_: Path) -> Path:
    return _write_exec(dir_, "apkid", _APKID_FAKE_BODY)


def _ws_with_sample(tmp_path: Path, name: str = "beacon.apk") -> Path:
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "bins" / name).write_bytes(b"PK\x03\x04" + b"\x00" * 32)
    return ws


def _ledger(ws: Path) -> dict:
    return json.loads(
        (ws / "evidence" / "intake-battery.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Requirement: The intake probe battery runs the identification probes
# once at intake
# ---------------------------------------------------------------------------

class TestBatteryRuns:
    def test_battery_produces_both_evidence_files_and_facts(
            self, tmp_path, monkeypatch):
        """Scenario: battery produces both evidence files and facts."""
        ws = _ws_with_sample(tmp_path)
        tools = tmp_path / "tools-bin"
        monkeypatch.setenv("KUNGLAO_DIE", str(_fake_diec(tools)))
        _fake_apkid(tools)
        monkeypatch.setenv("PATH",
                           str(tools) + os.pathsep + os.environ["PATH"])

        report = intake_battery.run_battery(ws, "beacon.apk", "malware")

        die = json.loads(
            (ws / "evidence" / "die.json").read_text(encoding="utf-8"))
        assert die["derived"]["detected_packer"] == "upx"
        assert die["derived"]["section_table"][0]["entropy"] == 7.2
        apkid = json.loads(
            (ws / "evidence" / "apkid.json").read_text(encoding="utf-8"))
        assert apkid["status"] == "ok"
        assert apkid["summary"]["packer"] == ["Bangcle"]
        assert apkid["summary"]["obfuscator"] == ["DexGuard"]

        ledger = _ledger(ws)
        assert ledger["schema"] == "intake-battery/1"
        by_probe = {r["probe"]: r for r in ledger["probes"]}
        assert set(by_probe) == {"die-probe", "apkid-prescan"}
        assert by_probe["die-probe"]["outcome"] == "produced"
        assert by_probe["apkid-prescan"]["outcome"] == "produced"
        assert report["probes"] == ledger["probes"]

    def test_no_sample_is_an_explicit_noop(self, tmp_path):
        """Scenario: no sample is an explicit no-op."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)

        report = intake_battery.run_battery(ws, None, "web")

        ledger = _ledger(ws)
        assert all(r["outcome"] == "absent" and not r["ran"]
                   for r in ledger["probes"])
        assert all("web" in r["detail"] for r in ledger["probes"])
        assert not (ws / "evidence" / "die.json").exists()
        assert not (ws / "evidence" / "apkid.json").exists()
        assert report["sample"] is None


# ---------------------------------------------------------------------------
# Requirement: Probe failure records absence and never blocks intake
# ---------------------------------------------------------------------------

class TestFailureSemantics:
    def test_probe_clis_missing_records_absence(self, tmp_path, monkeypatch):
        """Scenario: probe CLI missing still succeeds intake — neither
        tool on the host: absent rows with reasons, no usable evidence,
        the battery returns normally."""
        ws = _ws_with_sample(tmp_path)
        empty = tmp_path / "empty-bin"
        empty.mkdir()
        monkeypatch.delenv("KUNGLAO_DIE", raising=False)
        monkeypatch.setenv("PATH", str(empty))

        report = intake_battery.run_battery(ws, "beacon.apk", "malware")

        ledger = _ledger(ws)
        by_probe = {r["probe"]: r for r in ledger["probes"]}
        # die: operational error -> NO evidence file, absent row
        assert not (ws / "evidence" / "die.json").exists()
        assert by_probe["die-probe"]["outcome"] == "absent"
        assert by_probe["die-probe"]["detail"]
        # apkid: fail-open contract -> unavailable artifact = absent fact
        apkid = json.loads(
            (ws / "evidence" / "apkid.json").read_text(encoding="utf-8"))
        assert apkid["status"] == "unavailable"
        assert by_probe["apkid-prescan"]["outcome"] == "absent"
        assert report["probes"] == ledger["probes"]

    def test_internal_defect_never_raises(self, tmp_path, monkeypatch):
        """An unexpected battery defect degrades to absent rows — the
        entry point never raises into the init flow."""
        ws = _ws_with_sample(tmp_path)

        def _boom(*a, **k):
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(intake_battery, "_run_die", _boom)
        monkeypatch.setattr(intake_battery, "_run_apkid", _boom)

        report = intake_battery.run_battery(ws, "beacon.apk", "malware")
        assert all(r["outcome"] == "absent" for r in report["probes"])
        assert _ledger(ws)["probes"] == report["probes"]

    def test_ledger_rows_enumerated_shape(self, tmp_path):
        """The ledger row vocabulary is enumerated (probe/ran/outcome/
        evidence/detail) and deterministic in order."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        report = intake_battery.run_battery(ws, None, None)
        assert [r["probe"] for r in report["probes"]] == \
            ["die-probe", "apkid-prescan"]
        for row in report["probes"]:
            assert set(row) == {"probe", "ran", "outcome", "evidence",
                                "detail"}


# ---------------------------------------------------------------------------
# Requirement: Capability facts derived from probe evidence require
# usable evidence
# ---------------------------------------------------------------------------

class TestUsableEvidenceFacts:
    def _build(self, ws):
        saved = intake_promise._which_tool
        intake_promise._which_tool = lambda tool: None
        try:
            return intake_promise.build(SimpleNamespace(items=[]), None, ws)
        finally:
            intake_promise._which_tool = saved

    def test_unavailable_apkid_evidence_is_missing(self, tmp_path):
        """Scenario: unavailable evidence records a missing capability."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "apkid.json").write_text(json.dumps({
            "tool": "apkid", "status": "unavailable",
            "reason": "apkid binary not found on PATH"}), encoding="utf-8")
        p = self._build(ws)
        assert p["prescan"]["apkid"]["state"] == "missing"

    def test_unusable_die_evidence_is_missing(self, tmp_path):
        """A parseable-but-empty die artifact (all calls failed) with no
        surviving data block is NOT a capability fact."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "die.json").write_text(json.dumps({
            "detects": [], "records": [], "derived": {}}),
            encoding="utf-8")
        p = self._build(ws)
        assert p["prescan"]["die"]["state"] == "missing"

    def test_usable_evidence_still_available(self, tmp_path):
        """Usable artifacts keep counting as capability facts."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "apkid.json").write_text(json.dumps({
            "status": "ok", "summary": {"obfuscator": []}}),
            encoding="utf-8")
        (ws / "evidence" / "die.json").write_text(json.dumps({
            "detects": [{"values": [{"name": "UPX", "type": "packer"}]}],
            "derived": {"detected_packer": "upx"}}), encoding="utf-8")
        p = self._build(ws)
        assert p["prescan"]["apkid"]["state"] == "available"
        assert p["prescan"]["die"]["state"] == "available"


# ---------------------------------------------------------------------------
# Requirement: Battery outputs land in the existing probe contracts and
# stay minable
# ---------------------------------------------------------------------------

class TestMinability:
    def test_battery_outputs_are_mined_probe_outputs(self, tmp_path,
                                                     monkeypatch):
        """Scenario: the mined table gains die/apkid values from run #1 —
        battery-produced evidence flows through feature_mining's
        extraction with zero miner changes."""
        ws = _ws_with_sample(tmp_path)
        tools = tmp_path / "tools-bin"
        monkeypatch.setenv("KUNGLAO_DIE", str(_fake_diec(tools)))
        _fake_apkid(tools)
        monkeypatch.setenv("PATH",
                           str(tools) + os.pathsep + os.environ["PATH"])

        intake_battery.run_battery(ws, "beacon.apk", "malware")

        po = feature_mining._probe_outputs(None, ws / "evidence")
        assert po["die"]["usable"] is True
        assert po["die"]["detected_packer"] == "upx"
        assert po["die"]["entropy_max"] == 7.2
        assert po["apkid"]["usable"] is True
        assert po["apkid"]["packers"] == ["Bangcle"]
        assert po["apkid"]["obfuscators"] == ["DexGuard"]

    def test_golden_table_row_a_carries_battery_fed_values(self):
        """The committed golden table's run A (battery-fed fixture
        workspace) mines die/apkid VALUES (usable, entropy, the
        evidence-derived prescan state), not absence."""
        golden = (_HERE / "fixtures" / "feature-mining-460" / "golden"
                  / "feature-table.jsonl")
        rows = [json.loads(line)
                for line in golden.read_text(encoding="utf-8").splitlines()]
        a = next(r for r in rows if r["run_id"] == "e2e-fix-211504-a")
        die, apkid = (a["features"]["probe_outputs"]["die"],
                      a["features"]["probe_outputs"]["apkid"])
        assert die["usable"] is True
        assert die["entropy_max"] == 6.8
        assert die["prescan_state"] == "available"
        assert apkid["usable"] is True
        assert apkid["prescan_state"] == "available"


# ---------------------------------------------------------------------------
# Wiring: init runs the battery before the promise block (never blocks)
# ---------------------------------------------------------------------------

def _load_init(name: str):
    spec = importlib.util.spec_from_file_location(
        name, SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestInitWiring:
    @pytest.fixture()
    def init_mod(self):
        return _load_init("kunglao_init_battery_460")

    def _run(self, mod, ws, monkeypatch, battery):
        import toolchain as tc

        def _check(*a, **k):
            return tc.ToolchainReport(project_type="windows")

        monkeypatch.setattr(mod.toolchain, "check", _check)
        monkeypatch.setattr(mod, "refuse_missing_required_mcp",
                            lambda *a, **k: None)
        monkeypatch.setattr(mod, "uv_sync_workspace",
                            lambda *a, **k: {"ok": False, "venv": None,
                                             "detail": "stubbed"})
        monkeypatch.setattr(mod.intake_battery, "run_battery", battery)
        monkeypatch.setenv(FLAG_NAME, "0")
        return mod.run(ws, skip_toolchain=False, project_type="windows",
                       profile_root=ws.parent / "profile-root",
                       answers={"host_exec_protection": "enabled"})

    def test_init_calls_battery_with_aligned_target(self, tmp_path,
                                                    monkeypatch, init_mod):
        """run() invokes the battery with (ws, aligned target, lane)
        before the promise block; init succeeds."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "bins").mkdir()
        (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00")
        (ws / "task_spec.yaml").write_text(
            "goal_verbatim: g\nsuccess_criterion: s\n"
            "verification_method: manual\n", encoding="utf-8")
        recorded: list[tuple] = []

        def _battery(ws_arg, target, lane=None):
            recorded.append((ws_arg, target, lane))
            return {"probes": []}

        rc = self._run(init_mod, ws, monkeypatch, _battery)
        assert rc == 0
        assert recorded and recorded[0][1] == "sample.exe"

    def test_init_battery_defect_does_not_block(self, tmp_path, monkeypatch,
                                                init_mod):
        """A battery defect keeps init rc 0 and stays visible (WARN-tier
        ERROR line), the promise block still lands after it."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "bins").mkdir()
        (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00")
        (ws / "task_spec.yaml").write_text(
            "goal_verbatim: g\nsuccess_criterion: s\n"
            "verification_method: manual\n", encoding="utf-8")

        def _boom(*a, **k):
            raise RuntimeError("battery defect")

        rc = self._run(init_mod, ws, monkeypatch, _boom)
        assert rc == 0
        # the promise block still landed (probe-then-record coherence)
        assert (ws / "task_spec.yaml").exists()


# ---------------------------------------------------------------------------
# Wiring: the e2e C1 face runs the battery over the staged entry
# ---------------------------------------------------------------------------

_ANCHORS = {"goal_verbatim": "g", "success_criterion": "s",
            "verification_method": "reproduction"}


def _pending_doc() -> str:
    return json.dumps({"decisions": [
        {"decision_id": "goal_verbatim"},
        {"decision_id": "success_criterion"},
        {"decision_id": "verification_method"}]})


class TestE2EWiring:
    def _ctx(self, repo: Path, tmp_path: Path, runner):
        from e2e import checkpoints, llm_faces, model

        task_dir = repo / "eval/v1/tasks/release/rust-apk-beacon-v1"
        (task_dir / "target").mkdir(parents=True, exist_ok=True)
        (task_dir / "target/beacon.apk").write_bytes(b"PK\x03\x04")
        (task_dir / "task.yaml").write_text(
            "schema: kunglao-eval-task/1\n"
            "task_id: rust-apk-beacon-v1\n"
            "workspace_scaffold:\n"
            "  language: rust/arm64-android\n"
            "  files:\n  - target/beacon.apk\n"
            "  entry: target/beacon.apk\n",
            encoding="utf-8")
        ws = tmp_path / "e2e-ws"
        ev_dir = tmp_path / "ev"
        state = model.RunState(
            run_id="b1", unit="rust-apk-beacon-v1", family="release",
            repo=str(repo), task_dir=str(task_dir), ws=str(ws),
            evidence_dir=str(ev_dir), budget_seconds=100, llm_mode="dry",
            started_ts="t", started_monotonic=0.0,
            anchors=dict(_ANCHORS))
        return checkpoints.RunContext(
            state=state, runner=runner,
            face=llm_faces.face_for("dry", runner, ev_dir),
            clock=SimpleNamespace(monotonic=lambda: 0.0),
            sleep_fn=lambda _s: None)

    def test_c1_runs_battery_over_staged_entry(self, tmp_path):
        """After the resolved init, C1 invokes intake_battery.py with the
        staged workspace entry; the sub-step rc rides the detail."""
        from e2e import checkpoints
        from test_e2e_runner import ScriptedRunner

        repo = tmp_path / "repo"
        (repo / "scripts").mkdir(parents=True)
        runner = ScriptedRunner()
        # rule order matters: the --resolve argv also carries --lane, so
        # the --resolve rule must match first (same order as the
        # existing budget-exhaustion test)
        runner.on("kunglao-init.py", "--resolve", rc=0)
        runner.on("kunglao-init.py", "--lane", rc=8,
                  stdout=_pending_doc())
        runner.on("intake_battery.py", rc=0)
        ctx = self._ctx(repo, tmp_path, runner)

        result = checkpoints.checkpoint_c1(ctx)

        assert result.status == "PASS", result.detail
        assert result.detail["sub_battery_rc"] == 0
        battery_calls = [c for c in runner.calls if "intake_battery.py" in c]
        assert battery_calls and "target/beacon.apk" in battery_calls[0]

    def test_c1_battery_failure_never_fails_the_checkpoint(self, tmp_path):
        """The battery is an instrument: a non-zero battery rc never
        changes C1's verdict."""
        from e2e import checkpoints
        from test_e2e_runner import ScriptedRunner

        repo = tmp_path / "repo"
        (repo / "scripts").mkdir(parents=True)
        runner = ScriptedRunner()
        runner.on("kunglao-init.py", "--resolve", rc=0)
        runner.on("kunglao-init.py", "--lane", rc=8,
                  stdout=_pending_doc())
        runner.on("intake_battery.py", rc=3, stderr="battery defect")
        ctx = self._ctx(repo, tmp_path, runner)

        result = checkpoints.checkpoint_c1(ctx)

        assert result.status == "PASS", result.detail
        assert result.detail["sub_battery_rc"] == 3


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-x", "-q"])
