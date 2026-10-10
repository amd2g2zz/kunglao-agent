# -*- coding: utf-8 -*-
"""Issue 4-L8 — the SNIPS comparator's π discipline.

Lens finding: declared propensities enter SNIPS at π=1.0 by fiat (no
draw receipt backs them — mixing them violates the SNIPS assumption the
module docstring states), and a recorded π that differs from the true
draw corrupts the weights silently. The propensity reaches disk through
TWO independent carriers stamped from the same receipt at the same
dispatch — the audit envelope and the transition row (via the launch
stash) — so the comparator now (a) skips declared rows (counted) and
(b) refuses rows whose two carriers disagree (counted + ONE warn).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_log  # noqa: E402
from rlvr import policy_compare as pc  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    return ws


def _warn_recorder(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        pc, "warn",
        lambda op, reason, **kw: calls.append((str(op), str(reason))))
    return calls


def _transition(ws: Path, claim: str, family: str,
                propensity: float | None = None) -> None:
    """One settled transition row (+ its launch stash so the row carries
    the propensity exactly as production stamps it)."""
    doc = ir.record_launch(ws, claim, family, phi=0.0,
                           propensity=propensity)
    ir.append_transition(ws, claim, "SUCCESS", r_settle=1.0,
                         attempt_id=str((doc or {}).get("attempt_id")))


def _envelope(ws: Path, claim: str, family: str, *,
              propensity: float | None, declared: bool = False) -> None:
    env = {"family": family,
           "candidates": {family: {"weight": 0.7},
                          "other": {"weight": 0.3}}}
    if propensity is not None:
        env["propensity"] = propensity
    if declared:
        env["declared"] = True
    row = {"event": "method_family_recorded", "claim": claim,
           "detail": json.dumps({"method_family": family,
                                 "envelope": env})}
    with (ws / "runs" / "logs" / "e2e-audit.jsonl").open("a",
                                                         encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_declared_fiat_rows_leave_the_join(tmp_path) -> None:
    ws = _ws(tmp_path)
    _transition(ws, "C-1", "static", propensity=1.0)
    _envelope(ws, "C-1", "static", propensity=1.0, declared=True)
    report = pc.compare(ws)
    assert report["skipped_declared_fiat"] == 1
    assert report["decisions"] == 0


def test_mismatched_carriers_are_refused(tmp_path, monkeypatch) -> None:
    """A corrupted carrier (either side) can no longer move the verdict
    silently: the two π records must agree."""
    ws = _ws(tmp_path)
    _transition(ws, "C-2", "dynamic", propensity=0.42)
    _envelope(ws, "C-2", "dynamic", propensity=0.7)
    calls = _warn_recorder(monkeypatch)
    report = pc.compare(ws)
    assert report["skipped_propensity_mismatch"] == 1
    assert report["decisions"] == 0
    assert len(calls) == 1


def test_agreeing_carriers_join_the_estimate(tmp_path) -> None:
    ws = _ws(tmp_path)
    _transition(ws, "C-3", "static", propensity=0.7)
    _envelope(ws, "C-3", "static", propensity=0.7)
    report = pc.compare(ws)
    assert report["decisions"] == 1
    assert report["skipped_declared_fiat"] == 0
    assert report["skipped_propensity_mismatch"] == 0


def test_missing_envelope_still_counted_as_before(tmp_path) -> None:
    ws = _ws(tmp_path)
    _transition(ws, "C-4", "static", propensity=0.5)
    report = pc.compare(ws)
    assert report["skipped_no_propensity"] == 1
    assert report["decisions"] == 0
    assert "skipped_declared_fiat" in report
    assert "skipped_propensity_mismatch" in report
