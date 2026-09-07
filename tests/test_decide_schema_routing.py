# -*- coding: utf-8 -*-
"""RED phase — prove schema mismatch (issue #97, F2).

Before the fix:
  1. cc --json output validated against decide-output.json → FAIL
     (missing top_actions, blocked, stale, drifts, explore_mode, selfcheck)
  2. cc --json output validated against convergence-check-output.json → PASS
     (schema does not exist yet → will fail with "schema file missing")
  3. kunglao-decide --json output validated against decide-output.json → PASS

After GREEN:
  1. cc --json vs decide-output.json → FAIL (by design: wrong schema)
  2. cc --json vs convergence-check-output.json → PASS
  3. kunglao-decide --json vs decide-output.json → PASS
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from _factories import write_claims_register

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _run_cc(ws: Path) -> dict:
    """Run convergence_check.py --json, return parsed output."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "convergence_check.py"), str(ws), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode in (0, 1, 2, 3, 4), f"cc failed: {r.stderr[:300]}"
    return json.loads(r.stdout)


def _run_kd(ws: Path) -> dict:
    """Run kunglao-decide.py --json, return parsed output."""
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "kunglao-decide.py"), str(ws), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    assert r.returncode in (0, 1, 2, 3, 4), f"kd failed: {r.stderr[:300]}"
    return json.loads(r.stdout)


def _make_ws(tmp_path, claims=None) -> Path:
    """Minimal workspace with claim-register.yaml (863-h factory)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    write_claims_register(ws, claims or [], defaults=True)
    return ws


class TestConvergenceCheckSchema:
    """convergence_check.decide() output must validate against convergence-check-output.json."""

    def test_cc_vs_wrong_schema_fails(self, tmp_path, contract_validator):
        """RED: cc --json output FAILS against decide-output.json (missing composite fields)."""
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        out = _run_cc(ws)
        with pytest.raises(AssertionError, match="schema\\[decide-output\\] violations"):
            contract_validator("decide-output", out)

    def test_cc_vs_correct_schema_passes(self, tmp_path, contract_validator):
        """GREEN: cc --json output passes against convergence-check-output.json."""
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        out = _run_cc(ws)
        contract_validator("convergence-check-output", out)

    def test_cc_converged_vs_correct_schema(self, tmp_path, contract_validator):
        """cc CONVERGED output also passes against convergence-check-output.json."""
        ws = _make_ws(tmp_path, claims=[])
        out = _run_cc(ws)
        contract_validator("convergence-check-output", out)


class TestKunglaoDecideSchema:
    """kunglao-decide.decide() output must validate against decide-output.json."""

    def test_kd_vs_schema_passes(self, tmp_path, contract_validator):
        """GREEN: kunglao-decide --json output passes against decide-output.json."""
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        out = _run_kd(ws)
        contract_validator("decide-output", out)

    def test_kd_converged_vs_schema(self, tmp_path, contract_validator):
        """kunglao-decide CONVERGED output also passes decide-output.json."""
        ws = _make_ws(tmp_path, claims=[])
        out = _run_kd(ws)
        contract_validator("decide-output", out)


class TestSchemaFieldIntegrity:
    """Verify that cc.decide() has NO composite fields and kd.decide() has NO raw fields."""

    def test_cc_output_has_no_composite_fields(self, tmp_path):
        """cc.decide() must NOT produce top_actions/blocked/stale/drifts/explore_mode/selfcheck."""
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        out = _run_cc(ws)
        for forbidden in ("top_actions", "blocked", "stale", "drifts", "explore_mode", "selfcheck"):
            assert forbidden not in out, f"cc.decide() must not produce '{forbidden}'"

    def test_cc_output_has_raw_fields(self, tmp_path):
        """cc.decide() must produce action/open_claims/active_workers/stuck_workers etc."""
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        out = _run_cc(ws)
        for required in ("action", "open_claims", "open_count", "active_workers",
                         "free_slots", "worker_cap", "stuck_workers", "active_blockers",
                         "orphan_claims", "unverified_primary_qs", "note_layer_gaps",
                         "pq_parse_error"):
            assert required in out, f"cc.decide() must produce '{required}'"

    def test_kd_output_has_composite_fields(self, tmp_path):
        """kd.decide() must produce top_actions/blocked/stale/drifts/selfcheck
        (#107 dropped explore_mode with the dual path)."""
        ws = _make_ws(tmp_path, claims=[{"id": "C-1", "status": "OPEN"}])
        out = _run_kd(ws)
        for required in ("top_actions", "blocked", "stale", "drifts", "selfcheck"):
            assert required in out, f"kd.decide() must produce '{required}'"
        assert "explore_mode" not in out, (
            "kd.decide() must not produce 'explore_mode' (#107 deleted the "
            "dual path)")


class TestKunglaoDecideInvalid:
    """Issue #371: INVALID is a NORMAL convergence_check.decide() return (non-empty
    malformed task_spec primary_questions — issue #77 fail-closed path), copied
    verbatim by kunglao-decide.decide() L134. The frozen decide-output.json enum
    lacked INVALID, so the composite CLI emitted contract-violating output on an
    untested path. INVALID reuses EXIT_BLOCKED=4 (convergence_check.py L29 —
    frozen exit surface 0-4 that worker_pulse parses); the schema enum, not the
    exit mapping, was wrong. Freeze ritual (specs/README): this RED test +
    schema amendment in the same commit."""

    def test_kd_invalid_vs_schema_passes(self, tmp_path, contract_validator):
        """RED before fix: kd --json on a malformed task_spec emits
        decision=INVALID → schema enum violation. GREEN: validates."""
        ws = _make_ws(tmp_path, claims=[])
        # non-string primary_questions item → _parse_primary_questions error →
        # decide() escalates INVALID (exit 4), never CONVERGED/exit 0
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n  - 42\n", encoding="utf-8")
        out = _run_kd(ws)
        assert out["decision"] == "INVALID"
        assert out["exit_code"] == 4
        contract_validator("decide-output", out)

    def test_cc_invalid_vs_correct_schema_passes(self, tmp_path, contract_validator):
        """Cross-check: the raw cc output for the same workspace already
        validates (convergence-check-output.json has INVALID since issue #77)."""
        ws = _make_ws(tmp_path, claims=[])
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n  - 42\n", encoding="utf-8")
        out = _run_cc(ws)
        assert out["decision"] == "INVALID"
        contract_validator("convergence-check-output", out)
