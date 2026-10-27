#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_acceptance_battery_pins_818.py — #818 climb segment 4H.

Behavior pins for the acceptance_check faces the third climb leg left
unmeasured:

  the static battery checks run for REAL (oracle self-check, CLI --help
  surface, the #792 ranker determinism/composite/no-dh faces, the digest
  build, the pinned smoke-manifest loader with its loud failures, and the
  suite check's command contract over the real pinned smoke subset), the
  subprocess runner's timeout face (rc 124 + marker), and the category
  leaf functions pinned at the _run seam — command construction
  (markers/targets/xdist/junit paths), artifact log writes, summary
  shape, the mutation missing-tool and observation-only faces, and the
  complexity audit's tool-availability tiering.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import acceptance_check as ac  # noqa: E402


# ------------------------------------------------ static battery (real)

class TestStaticBattery:
    def test_oracle_selfcheck_is_ten_for_ten(self) -> None:
        row = ac._check_oracle()
        assert row["name"] == "oracle_10_10"
        assert row["passed"] is True
        assert row["detail"] == "10/10"

    def test_cli_surface_checks_all_eight(self) -> None:
        row = ac._check_cli_surface()
        assert row["name"] == "cli_surface_8"
        assert row["passed"] is True
        assert row["detail"] == "8/8"

    def test_priority_voi_pins_the_deterministic_composite(self) -> None:
        row = ac._check_priority_voi()
        assert row["name"] == "priority_voi_formula"
        assert row["passed"] is True, row["detail"]
        # the check token itself asserts determinism, the feed set
        # (case_value / case_flip_potential / downstream), the absence of
        # the retired dh/leverage faces, and the zero value channel of a
        # cold unlinked claim — a PASS here is the #792 formula pin.

    def test_digest_builds_six_sections(self) -> None:
        row = ac._check_digest()
        assert row["name"] == "digest_builds"
        assert row["passed"] is True, row["detail"]
        assert "six=True" in row["detail"]

    def test_smoke_manifest_loads_real_nodeids(self) -> None:
        nodeids = ac._load_smoke_nodeids()
        assert nodeids, "the pinned smoke manifest must never be empty"
        assert all(not n.startswith("#") for n in nodeids)
        assert all("::" in n for n in nodeids)  # real node ids

    def test_suite_check_runs_the_pinned_smoke_subset(self) -> None:
        row = ac._check_test_suite(full=False)
        assert row["name"] == "test_suite_green"
        assert row["passed"] is True, row["detail"]
        assert row["detail"].startswith("[smoke:")

    def test_run_acceptance_aggregates_the_battery(self) -> None:
        report = ac.run_acceptance(full_suite=False)
        assert report["overall_passed"] is True
        assert [c["name"] for c in report["checks"]] == [
            "oracle_10_10", "cli_surface_8", "priority_voi_formula",
            "digest_builds", "test_suite_green"]


# ------------------------------------------------ subprocess runner face

class TestRunner:
    def test_timeout_face_returns_124_with_a_marker(self) -> None:
        rc, out, err, duration = ac._run(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            Path("."), 1)
        assert rc == 124
        assert "[TIMEOUT after 1s]" in err
        assert duration >= 1.0

    def test_env_merge_reaches_the_child(self, tmp_path) -> None:
        rc, out, _err, _ = ac._run(
            [sys.executable, "-c",
             "import os; print(os.environ.get('KUNGLAO_PROBE', 'missing'))"],
            tmp_path, 30, env={"KUNGLAO_PROBE": "climb4"})
        assert rc == 0
        assert out.strip() == "climb4"


# -------------------------------------- category leaves at the _run seam

@pytest.fixture()
def out_root(tmp_path, monkeypatch):
    root = tmp_path / "matrix-out"
    monkeypatch.setattr(ac, "OUT_DIR", root)
    return root


def _stub_run(monkeypatch, rc=0, stdout="", stderr=""):
    calls: list[dict] = []

    def fake_run(cmd, cwd, timeout, env=None):
        calls.append({"cmd": cmd, "cwd": cwd, "timeout": timeout,
                      "env": env})
        return rc, stdout, stderr, 0.5

    monkeypatch.setattr(ac, "_run", fake_run)
    return calls


class TestCategoryLeaves:
    def test_regression_builds_the_parallel_gate_command(
            self, out_root, monkeypatch) -> None:
        calls = _stub_run(monkeypatch)
        summary = ac.category_regression()
        assert summary["category"] == "regression"
        assert summary["exit_code"] == 0
        cmd = calls[0]["cmd"]
        assert "-m" in cmd and "not replay" in cmd
        assert "-n" in cmd and "auto" in cmd  # xdist parallel
        junit = Path(cmd[cmd.index("--junitxml") + 1])
        assert junit == out_root / "regression" / "junit.xml"
        assert (out_root / "regression" / "stdout.log").exists()
        assert (out_root / "regression" / "summary.json").exists()

    def test_integration_and_fault_target_the_v013_files(
            self, out_root, monkeypatch) -> None:
        calls = _stub_run(monkeypatch)
        integ = ac.category_integration()
        assert integ["exit_code"] == 0
        assert "v013 and integration" in calls[0]["cmd"]
        assert any(str(c).endswith("test_integration_v013.py")
                   for c in calls[0]["cmd"])
        fault = ac.category_fault()
        assert fault["exit_code"] == 0
        assert "v013 and fault" in calls[1]["cmd"]
        assert "--tb=long" in calls[1]["cmd"]
        assert any(str(c).endswith("test_fault_injection_v013.py")
                   for c in calls[1]["cmd"])

    def test_smoke_is_the_fastest_signal_with_full_logs(
            self, out_root, monkeypatch) -> None:
        calls = _stub_run(monkeypatch, stdout="smoke output")
        summary = ac.category_smoke()
        assert summary["exit_code"] == 0
        assert "v013 and smoke" in calls[0]["cmd"]
        assert calls[0]["timeout"] == 120
        # the logs are the artifact surface — never truncated
        assert (out_root / "smoke" / "stdout.log").read_text(
            encoding="utf-8") == "smoke output"
        assert summary["stdout_bytes"] == len("smoke output")

    def test_mutation_without_mutmut_records_a_structured_skip(
            self, out_root, monkeypatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: None)
        summary = ac.category_mutation()
        assert summary["exit_code"] == 2
        assert "mutmut not installed" in summary["note"]
        assert (out_root / "mutation" / "summary.json").exists()

    def test_mutation_trampoline_mismatch_is_observation_only(
            self, out_root, monkeypatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/mutmut")
        _stub_run(monkeypatch, rc=1, stdout="Stopping early: trampoline")
        summary = ac.category_mutation()
        assert summary["observation_only"] is True
        assert summary["exit_code"] == 0  # never blocks ACCEPT
        assert "trampoline" in summary["observation_reason"]

    def test_complexity_audits_tier_on_tool_availability(
            self, out_root, monkeypatch) -> None:
        monkeypatch.setattr(
            "shutil.which",
            lambda name: f"/usr/bin/{name}" if name == "vulture" else None)
        _stub_run(monkeypatch, rc=0, stdout="no findings")
        summary = ac.category_complexity()
        assert summary["exit_code"] == 0  # observation never blocks
        assert set(summary["findings"]) == {"vulture"}
        assert summary["verdict"] == "clean"
        combined = (out_root / "complexity" / "combined.log").read_text(
            encoding="utf-8")
        assert "=== vulture ===" in combined

    def test_complexity_findings_change_the_verdict(
            self, out_root, monkeypatch) -> None:
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/x")
        _stub_run(monkeypatch, rc=1, stdout="findings!")
        summary = ac.category_complexity()
        assert summary["verdict"] == "findings-present"
