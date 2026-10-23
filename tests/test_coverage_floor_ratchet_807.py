#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_coverage_floor_ratchet_807.py — measured-set coverage floor.

The floor card amends the observation-only policy: coverage on the MEASURED SET
(scripts/ + hooks/ production faces) becomes an ENFORCED FLOOR in CI, with a
raise-only ratchet file (`coverage-floor.json`, hygiene-baseline precedent).
The floor can only move UP, pinned two ways:

  1. TARGET: the declared climb target min_floor stays >= 70.0 forever —
     lowering the target fails this pin.
  2. SEED: the ratchet floor is seeded at (never below) the recorded
     baseline — hygiene-baseline precedent, refuse-only below truth.
  3. RELATIVE: CI runs `scripts/coverage_floor.py monotone --base-ref` —
     a PR floor lower than the base branch floor fails the job.

Enforcement deliberately does NOT use --cov-fail-under anywhere (the
guard keeps banning it): local pytest stays observation-only; enforcement is
scoped to the CI measured-set job via scripts/coverage_floor.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import coverage_floor as cf  # noqa: E402

FLOOR_FILE = ROOT / "coverage-floor.json"

# The enforced climb TARGET — immutable, pinned two ways.
TARGET_FLOOR = 70.0


# ---- pure monotonicity comparator ------------------------------------------


def test_monotone_lower_floor_is_a_violation() -> None:
    assert cf.monotone_violation(72.0, 70.5) is not None


def test_monotone_equal_floor_is_allowed() -> None:
    assert cf.monotone_violation(72.0, 72.0) is None


def test_monotone_higher_floor_is_allowed() -> None:
    assert cf.monotone_violation(72.0, 75.0) is None


def test_check_below_floor_violates() -> None:
    assert cf.check_violation(65.0, 70.0) is not None


def test_check_at_floor_passes() -> None:
    assert cf.check_violation(70.0, 70.0) is None


def test_check_above_floor_passes() -> None:
    assert cf.check_violation(70.42, 70.0) is None


# ---- ratchet file contract -------------------------------------------------


def test_floor_file_exists_with_schema() -> None:
    assert FLOOR_FILE.is_file(), (
        "coverage-floor.json missing — the #807 measured-set floor is a "
        "committed ratchet file, not a workflow constant"
    )
    data = json.loads(FLOOR_FILE.read_text(encoding="utf-8"))
    assert data.get("schema") == "coverage-floor/1"
    for key in ("floor", "min_floor", "measured_set", "baseline_measured"):
        assert key in data, f"coverage-floor.json missing key: {key}"


def test_target_minimum_is_immutable() -> None:
    """THE target pin: the declared climb target stays 70.0 forever."""
    data = json.loads(FLOOR_FILE.read_text(encoding="utf-8"))
    assert float(data["min_floor"]) >= TARGET_FLOOR, (
        f"coverage-floor.json target {data['min_floor']} < "
        f"{TARGET_FLOOR} — lowering the target is forbidden; "
        f"only the ratchet floor climbs, with real tests"
    )


def test_floor_not_far_below_recorded_baseline() -> None:
    """THE seed-at-truth pin: the ratchet may sit at most 5% below the
    recorded baseline (cross-platform tolerance); anything further is a
    silent bar-drop (hygiene-baseline precedent, refuse-only)."""
    data = json.loads(FLOOR_FILE.read_text(encoding="utf-8"))
    floor = float(data["floor"])
    assert floor >= cf.SEED_TOLERANCE * float(data["baseline_measured"]), (
        "coverage-floor.json floor is more than 5% below its recorded "
        "baseline — the ratchet is seeded at truth and only climbs"
    )


def test_floor_declares_the_measured_set() -> None:
    data = json.loads(FLOOR_FILE.read_text(encoding="utf-8"))
    assert list(data["measured_set"]) == ["scripts", "hooks"], (
        "measured set must stay scripts/ + hooks/ (#807 Face 2: production "
        "faces; tests/ and generated artifacts excluded)"
    )


def test_target_never_trails_the_ratchet() -> None:
    data = json.loads(FLOOR_FILE.read_text(encoding="utf-8"))
    assert float(data["min_floor"]) >= float(data["floor"])


def test_floor_loader_rejects_floor_below_baseline(tmp_path: Path) -> None:
    """Defense in depth: the tooling itself refuses a ratchet seeded
    below the recorded baseline (a silent bar-drop)."""
    bad = tmp_path / "coverage-floor.json"
    bad.write_text(json.dumps({
        "schema": "coverage-floor/1", "floor": 55.0, "min_floor": 70.0,
        "measured_set": ["scripts", "hooks"], "baseline_measured": 58.59,
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="baseline"):
        cf.load_floor(bad)


# ---- CI wiring truth -------------------------------------------------------


def test_monotone_first_landing_without_base_file_passes(
        tmp_path: Path, capsys) -> None:
    """The ratchet-introducing PR: the base ref has no
    coverage-floor.json, so there is nothing to regress from — the
    monotone step must PASS vacuously, never crash the job."""
    rc = cf.main(["monotone", "--repo", str(tmp_path),
                  "--base-ref", "nonexistent-ref",
                  "--floor-file", str(FLOOR_FILE)])
    assert rc == 0
    assert "vacuous" in capsys.readouterr().out


def test_release_check_enforces_the_floor() -> None:
    text = (ROOT / ".github" / "workflows" / "release-check.yml").read_text(
        encoding="utf-8")
    assert "coverage_floor.py check" in text, (
        "release-check.yml lost the #807 measured-set floor step"
    )


def test_release_check_enforces_ratchet_monotone() -> None:
    text = (ROOT / ".github" / "workflows" / "release-check.yml").read_text(
        encoding="utf-8")
    assert "coverage_floor.py monotone" in text, (
        "release-check.yml lost the #807 ratchet-monotone step "
        "(floor may only move UP vs the base ref)"
    )
