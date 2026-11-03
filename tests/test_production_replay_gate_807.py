# -*- coding: utf-8 -*-
"""tests/test_production_replay_gate_807.py — production-shape replay
gate (Standard 12).

CI was green while production failed on shapes no unit exercised
(six-panel 2026-10-23 review, RC6). This file pins the gate layer:

  - the committed fixtures are SYNTHETIC shape distillations (the raw
    logs carry user content and never enter the repo);
  - the loader fails closed on contract violations;
  - the INV-003 family-level assertion is TWO-SIDED (arm-NULL broadcast
    shapes are rejected, arm-keyed control accepted);
  - the registration surface is live for the cross-card assertions
    (the warn-breaker card, the orphan-settlement card, the
    without this card reimplementing them.

Standard 11: the gate adds no warn() telemetry points — failures are
structural (report rows + non-zero exit), pinned by test_gate_adds_no_warn_points.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEVKIT = ROOT / "devkit"
for p in (str(ROOT), str(DEVKIT)):
    if p not in sys.path:
        sys.path.insert(0, p)

_spec = importlib.util.spec_from_file_location(
    "production_replay_gate", DEVKIT / "production_replay_gate.py")
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

SHAPES = DEVKIT / "production_shapes"


# ---- fixture contract -------------------------------------------------------

def test_every_committed_fixture_loads_and_is_synthetic() -> None:
    fs = rg.fixtures(SHAPES)
    assert len(fs) >= 3, "web/android production shapes + INV-003 control"
    for f in fs:
        assert f["synthetic"] is True
        assert f["events"], f"{f['id']}: empty events"
        assert f["shape"], f"{f['id']}: missing shape counts"


def test_loader_rejects_wrong_schema(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "other/9", "id": "x"}),
                   encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        rg.load_fixture(bad)


def test_loader_rejects_nonsynthetic_fixture(tmp_path: Path) -> None:
    bad = tmp_path / "raw.json"
    bad.write_text(json.dumps({
        "schema": "production-shape/1", "id": "x", "synthetic": False,
        "source": "raw log paste", "shape": {}, "events": [{"a": 1}],
        "expectations": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="SYNTHETIC"):
        rg.load_fixture(bad)


def test_loader_rejects_artifact_escape(tmp_path: Path) -> None:
    bad = tmp_path / "esc.json"
    bad.write_text(json.dumps({
        "schema": "production-shape/1", "id": "x", "synthetic": True,
        "source": "s", "shape": {}, "events": [{"a": 1}],
        "expectations": {},
        "artifacts": {"../etc/passwd": []}}), encoding="utf-8")
    with pytest.raises(ValueError, match="runs/"):
        rg.load_fixture(bad)


# ---- built-in INV-003 assertion (two-sided) ---------------------------------

def test_inv003_assertion_rejects_arm_null_production_shape() -> None:
    import tempfile
    fixture = next(f for f in rg.fixtures(SHAPES)
                   if f["id"] == "web-2026-10-22-shape")
    with tempfile.TemporaryDirectory() as td:
        ws = rg.materialize(Path(td), fixture)
        ok, detail = rg._inv003_posterior_family_key(ws, fixture)
    assert ok, detail  # the fixture EXPECTS the fingerprint to FAIL there


def test_inv003_assertion_accepts_arm_keyed_control() -> None:
    import tempfile
    fixture = next(f for f in rg.fixtures(SHAPES)
                   if f["id"] == "inv003-control-arm-keyed")
    with tempfile.TemporaryDirectory() as td:
        ws = rg.materialize(Path(td), fixture)
        ok, detail = rg._inv003_posterior_family_key(ws, fixture)
    assert ok, detail


# ---- runner -----------------------------------------------------------------

def test_runner_all_green_on_committed_shapes(capsys) -> None:
    rc = rg.run(SHAPES)
    out = capsys.readouterr().out
    assert rc == 0
    assert "PRODUCTION-SHAPES LIVE" in out


def test_runner_counts_failing_assertions(tmp_path: Path) -> None:
    def _always_red(ws, fixture):
        return False, "pinned red"

    rg.register_assertion("pin-always-red", _always_red)
    try:
        rc = rg.run(SHAPES, only={"pin-always-red"})
        assert rc == 1
    finally:
        rg.ASSERTIONS.pop("pin-always-red", None)


def test_duplicate_assertion_name_raises() -> None:
    def _fn(ws, fixture):
        return True, ""

    with pytest.raises(ValueError, match="already registered"):
        rg.register_assertion("inv003-posterior-family-key", _fn)


# ---- cross-card registration surface ---------------------------------------

def test_anchors_reserve_the_cross_card_surfaces() -> None:
    web = next(f for f in rg.fixtures(SHAPES)
               if f["id"] == "web-2026-10-22-shape")
    anchored = set(web.get("anchors", {}))
    assert {"800", "801", "809"} <= anchored, (
        "the production-shape fixture must keep anchoring the escaped "
        "failure classes owned by #800/#801/#809")


def test_gate_adds_no_warn_points() -> None:
    """Standard 11: new telemetry warn points need per-family counting;
    this gate deliberately adds none (structural reporting only)."""
    src = (DEVKIT / "production_replay_gate.py").read_text(encoding="utf-8")
    assert "warn(" not in src.replace("warn points", "").replace(
        "warn() telemetry points", ""), (
        "production_replay_gate.py must not emit telemetry warns "
        "(Standard 11: any new warn point needs per-family counting + "
        "escalation — use structural report rows instead)")
