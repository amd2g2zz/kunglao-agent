#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_template_hygiene_676.py — plan face vs terminal claims (issue 676).

The rendered global_plan.txt carries the OPEN thread only (timeline_face
filters TERMINAL statuses out by construction), while the plan-drift
detector used to flag every register claim absent from the plan — so
terminal claims fired ORPHAN_CLAIM after EVERY re-render and the B1o
blocker refused dispatch forever. Repro pinned here: a render-marker plan
plus a register holding terminal and non-terminal claims; the detector
exempts terminal claims from ORPHAN_CLAIM (an unlogged frontier item is
by definition not terminal) while every other class keeps auditing them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plan_drift_detector as pdd  # noqa: E402
import timeline_face  # noqa: E402


def _mk_ws(tmp_path: Path, claims: list[dict], plan_text: str | None = None,
           *, render: bool = False) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    if plan_text is not None:
        (ws / "global_plan.txt").write_text(plan_text, encoding="utf-8")
    if render:
        out = timeline_face.render_and_write(ws)
        assert out["status"] == "rendered", out
    return ws


def test_plan_drift_no_orphan_after_re_render(tmp_path, capsys):
    """Terminal claims never surface as ORPHAN_CLAIM on a rendered face,
    and a re-render keeps the clean verdict (the drift used to return)."""
    ws = _mk_ws(tmp_path, [
        {"id": "C-001", "status": "VERIFIED"},
        {"id": "C-002", "status": "OPEN"},
        {"id": "C-003", "status": "REFUTED"},
        {"id": "C-009", "status": "DEFERRED"},
    ], render=True)
    plan = (ws / "global_plan.txt").read_text(encoding="utf-8")
    assert timeline_face.plan_is_rendered(ws)
    assert "C-002:" in plan          # the open thread renders
    assert "C-001" not in plan       # terminal claims are filtered out

    rc = pdd.check(ws, active_only=True)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "OK: no plan drift detected" in out
    assert "ORPHAN_CLAIM" not in out

    # the re-render is a no-op (write-on-diff) and the verdict holds
    again = timeline_face.render_and_write(ws)
    assert again["plan_wrote"] is False, again
    assert pdd.check(ws, active_only=True) == 0


def test_plan_drift_proven_exempt_from_orphan_but_still_unverified(
        tmp_path, capsys):
    """Exempting terminal claims from ORPHAN does NOT weaken the reality
    check: a PROVEN claim without its verify file still drifts."""
    ws = _mk_ws(tmp_path, [
        {"id": "C-001", "status": "OPEN"},
        {"id": "C-003", "status": "PROVEN"},
    ], render=True)
    rc = pdd.check(ws, active_only=True)
    out = capsys.readouterr().out
    assert "ORPHAN_CLAIM" not in out, out
    assert "UNVERIFIED_EVIDENCE" in out, out
    assert rc == 1, out


def test_plan_drift_orphan_still_fires_for_frontier_claims(tmp_path, capsys):
    """The exemption is scoped to terminal statuses only: an OPEN claim
    missing from the plan remains a hard drift."""
    ws = _mk_ws(
        tmp_path,
        [{"id": "C-001", "status": "OPEN"},
         {"id": "C-002", "status": "OPEN"}],
        plan_text="## plan\n- C-001 do the thing\n")
    rc = pdd.check(ws, active_only=True)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "ORPHAN_CLAIM" in out, out
    assert "C-002" in out, out


def test_plan_drift_stale_next_step_still_flags_terminal(tmp_path, capsys):
    """Leaving ORPHAN_CLAIM does not exempt terminal claims from the
    next-step check: a PROVEN claim still listed in that section drifts."""
    ws = _mk_ws(
        tmp_path,
        [{"id": "C-001", "status": "PROVEN"}],
        plan_text="## next steps\n- C-001 do the thing\n")
    rc = pdd.check(ws, active_only=True)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "STALE_NEXT_STEP" in out, out
