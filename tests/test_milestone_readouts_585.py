# -*- coding: utf-8 -*-
"""tests/test_milestone_readouts_585.py — the milestone-progress pins (#585).

The Reveree-style diagnosis face over the audit trail: the readout
projects the ledgers the runs ALREADY wrote (e2e-audit stream, the
transition ledger, the fact bank, the intake anchors) onto the
kunglao-shaped stage lattice — intake → dispatch → facts → verification
→ settlement → convergence — and reports, per arm x unit:

  coverage    which stages the cell's evidence marks;
  depth       the longest UNBROKEN prefix over the lattice;
  stalled_at  the first lattice stage the prefix did not reach.

…aggregated across arms/units into the stall funnel (per-stage reach
and the marginal drop — where runs stop progressing). Pins here:

  1. the lattice declaration (six stages, kunglao order);
  2. a run that stalls at verification (depth 4, stalled at settlement);
  3. a run that converges (full lattice, no stall);
  4. the honest-absence faces (intake-only, nothing-at-all, spine-only
     refused cells);
  5. the unbroken-prefix semantics (evidence past a gap never inflates
     depth);
  6. the stall funnel aggregation;
  7. multi-sample cells pool evidence across samples;
  8. the additive face — the existing aggregations carry NO milestone
     keys; the section is separate;
  9. the vocabulary pin — the local audit-action → stage classifier
     stays consistent with scripts/e2e/audit.py's controlled
     vocabulary (drift = red);
 10. the contamination probe note is recorded in the report-face docs.

Read-only aggregation: nothing enters the loop, no agent-side stage
schema exists — the lattice is evaluation-shaped.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_matrix_report as mr  # noqa: E402
from e2e import audit as e2e_audit  # noqa: E402


# ---- fixture builders (synthetic audit trails) ----------------------------

def _write_audit(ws: Path, rows: list[dict]) -> None:
    p = ws / "runs" / "logs" / "e2e-audit.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows),
                 encoding="utf-8")


def _write_transitions(ws: Path, rows: list[dict]) -> None:
    p = ws / "runs" / "transitions.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows),
                 encoding="utf-8")


def _write_results(run_dir: Path, unit: str, ws: Path,
                   verdict: str | None, loop_status: str = "completed") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "eval-results-20260101T000000Z-1.json").write_text(
        json.dumps({"schema": "kunglao-eval-results/1", "rows": [{
            "task_id": unit, "verdict": verdict,
            "loop": {"status": loop_status,
                     "session": {"session_cost": {"total_cost_usd": 1.0},
                                 "wall_s": 90.0},
                     "workspace": str(ws)},
        }]}),
        encoding="utf-8")


def _cell(tmp_path: Path, arm: str, unit: str, *, ws_name: str | None = None,
          audit: list[dict] | None = None, transitions: list[dict] | None = None,
          facts: int = 0, task_spec: bool = True, verdict: str | None = None,
          loop_status: str = "completed",
          sample: str | None = None) -> Path:
    """One synthetic run: results doc + whatever ledgers the caller
    staged. ``sample`` nests the run dir one level deeper (the B2 face)."""
    ws = tmp_path / "ws" / (ws_name or f"{arm}-{unit}")
    ws.mkdir(parents=True, exist_ok=True)
    if task_spec:
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n  - id: PQ-DELIVER\n    q: q\n",
            encoding="utf-8")
    if audit:
        _write_audit(ws, audit)
    if transitions:
        _write_transitions(ws, transitions)
    if facts:
        (ws / "facts").mkdir(exist_ok=True)
        for i in range(facts):
            (ws / "facts" / f"F{i:03d}.md").write_text(
                "---\nstatus: PROVEN\n---\n", encoding="utf-8")
    run_dir = tmp_path / arm / unit / (sample or "")
    _write_results(run_dir, unit, ws, verdict, loop_status)
    return run_dir


AUDIT_DISPATCH = [{"ts": "t", "actor": "orchestrator",
                   "action": "dispatch_attempt", "claim": "C-1"}]
AUDIT_VERIFY = [{"ts": "t", "actor": "orchestrator",
                 "action": "oracle_verdict", "claim": "C-1"},
                {"ts": "t", "actor": "orchestrator",
                 "action": "checkpoint_pass", "claim": "C-1"}]
AUDIT_CONVERGE = [{"ts": "t", "actor": "orchestrator",
                   "action": "convergence_decision", "claim": None}]
TRANS_DISPATCH = [{"dispatch_id": "C-1", "action_type": "dispatch",
                   "r_incr": None}]
TRANS_VERIFY = [{"dispatch_id": "C-1", "action_type": "verify",
                 "r_incr": None}]
TRANS_SETTLE = [{"dispatch_id": "C-1", "action_type": "dispatch",
                 "r_incr": 0.5}]


# ---- 1. the lattice declaration -------------------------------------------

def test_stage_lattice_is_the_kunglao_shape():
    assert mr.MILESTONE_STAGES == ("intake", "dispatch", "facts",
                                   "verification", "settlement",
                                   "convergence")


# ---- 2/3. the issue's two fixture runs ------------------------------------

def test_run_that_stalls_at_verification(tmp_path):
    """Full evidence through verification, nothing after: depth 4, the
    stall point names settlement."""
    _cell(tmp_path, "arm-a", "u-1", audit=AUDIT_DISPATCH + AUDIT_VERIFY,
          transitions=TRANS_DISPATCH + TRANS_VERIFY, facts=2,
          verdict=None, loop_status="exhausted")
    report = mr.build_report(tmp_path)
    cells = {(c["arm"], c["unit"]): c
             for c in report["milestones"]["cells"]}
    cell = cells[("arm-a", "u-1")]
    assert cell["reached"] == ["intake", "dispatch", "facts",
                               "verification"]
    assert cell["depth"] == 4
    assert cell["stalled_at"] == "settlement"


def test_run_that_converges(tmp_path):
    """The full lattice walked: settlement rows banked, the convergence
    decision emitted, a mechanical verdict rendered — no stall."""
    _cell(tmp_path, "arm-a", "u-2",
          audit=AUDIT_DISPATCH + AUDIT_VERIFY + AUDIT_CONVERGE,
          transitions=TRANS_SETTLE, facts=1, verdict="PASS")
    report = mr.build_report(tmp_path)
    cell = report["milestones"]["cells"][0]
    assert cell["reached"] == list(mr.MILESTONE_STAGES)
    assert cell["depth"] == 6
    assert cell["stalled_at"] is None


# ---- 4. the honest-absence faces -------------------------------------------

def test_intake_only_run_stalls_at_dispatch(tmp_path):
    """task_spec.yaml alone: intake reached, nothing else."""
    _cell(tmp_path, "arm-a", "u-3")
    report = mr.build_report(tmp_path)
    cell = report["milestones"]["cells"][0]
    assert cell["reached"] == ["intake"]
    assert cell["depth"] == 1
    assert cell["stalled_at"] == "dispatch"


def test_no_evidence_at_all_reports_depth_zero(tmp_path):
    """No task_spec, no ledgers, no verdict: the cell reached nothing;
    the first lattice stage is where it stopped."""
    _cell(tmp_path, "arm-a", "u-4", task_spec=False)
    report = mr.build_report(tmp_path)
    cell = report["milestones"]["cells"][0]
    assert cell["reached"] == []
    assert cell["depth"] == 0
    assert cell["stalled_at"] == "intake"


def test_spine_only_refused_cell_stalls_at_intake(tmp_path):
    """A launcher-refused cell with no run dir: the spine row names the
    state; no workspace, no evidence — stalled at intake."""
    progress = {"runs": [{"arm": "arm-b", "unit": "u-1",
                          "status": "refused", "workspace": None}]}
    report = mr.build_report(tmp_path, progress)
    cell = report["milestones"]["cells"][0]
    assert cell["arm"] == "arm-b" and cell["unit"] == "u-1"
    assert cell["reached"] == []
    assert cell["depth"] == 0
    assert cell["stalled_at"] == "intake"


# ---- 5. unbroken-prefix semantics ------------------------------------------

def test_evidence_past_a_gap_never_inflates_depth(tmp_path):
    """A settlement row with NO verification evidence: settlement is in
    the coverage set, but the prefix breaks at verification — depth 3,
    stalled at verification."""
    _cell(tmp_path, "arm-a", "u-5", audit=AUDIT_DISPATCH,
          transitions=TRANS_SETTLE, facts=2, verdict=None,
          loop_status="exhausted")
    report = mr.build_report(tmp_path)
    cell = report["milestones"]["cells"][0]
    assert cell["reached"] == ["intake", "dispatch", "facts",
                               "settlement"]
    assert cell["depth"] == 3
    assert cell["stalled_at"] == "verification"


# ---- 6. the stall funnel ----------------------------------------------------

def test_stall_funnel_aggregates_marginal_reach(tmp_path):
    """Three cells — one converges, one stalls at the verification ->
    settlement edge, one never leaves intake. The funnel reads: intake
    drops the intake-only cell, verification drops the stalled run, and
    settlement holds (its one runner converged)."""
    _cell(tmp_path, "arm-a", "u-a",
          audit=AUDIT_DISPATCH + AUDIT_VERIFY + AUDIT_CONVERGE,
          transitions=TRANS_SETTLE, facts=1, verdict="PASS")
    _cell(tmp_path, "arm-b", "u-a", audit=AUDIT_DISPATCH + AUDIT_VERIFY,
          transitions=TRANS_VERIFY, facts=1, verdict=None,
          loop_status="exhausted")
    _cell(tmp_path, "arm-b", "u-b")
    report = mr.build_report(tmp_path)
    funnel = report["milestones"]["funnel"]
    assert funnel["intake"] == {"reached": 3, "stalled_here": 1}
    assert funnel["dispatch"] == {"reached": 2, "stalled_here": 0}
    assert funnel["facts"] == {"reached": 2, "stalled_here": 0}
    assert funnel["verification"] == {"reached": 2, "stalled_here": 1}
    assert funnel["settlement"] == {"reached": 1, "stalled_here": 0}
    assert funnel["convergence"] == {"reached": 1, "stalled_here": 0}


# ---- 7. multi-sample pooling ------------------------------------------------

def test_multi_sample_cell_pools_evidence_across_samples(tmp_path):
    """The B2 face: sample s0 carries dispatch+facts, s1 carries the
    settlement; the cell's coverage is the POOLED set."""
    s0 = tmp_path / "arm-m" / "u-1" / "s0"
    s1 = tmp_path / "arm-m" / "u-1" / "s1"
    ws0 = tmp_path / "ws" / "m0"
    ws1 = tmp_path / "ws" / "m1"
    for ws, audit, trans in ((ws0, AUDIT_DISPATCH, None),
                             (ws1, None, TRANS_SETTLE)):
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "task_spec.yaml").write_text("primary_questions:\n",
                                           encoding="utf-8")
        if audit:
            _write_audit(ws, audit)
        if trans:
            _write_transitions(ws, trans)
    for run_dir, ws in ((s0, ws0), (s1, ws1)):
        _write_results(run_dir, "u-1", ws, None)
    (ws0 / "facts").mkdir()
    (ws0 / "facts" / "F000.md").write_text("x\n", encoding="utf-8")
    report = mr.build_report(tmp_path)
    cell = [c for c in report["milestones"]["cells"]
            if (c["arm"], c["unit"]) == ("arm-m", "u-1")][0]
    assert cell["reached"] == ["intake", "dispatch", "facts",
                               "settlement"]
    assert cell["depth"] == 3


# ---- 8. the additive face ----------------------------------------------------

def test_existing_aggregations_carry_no_milestone_keys(tmp_path):
    """The matrix cells and the arm aggregates stay byte-shaped as they
    were: the milestone readout is a SEPARATE section, nothing leaks in."""
    _cell(tmp_path, "arm-a", "u-1", audit=AUDIT_DISPATCH,
          transitions=TRANS_SETTLE, facts=1, verdict="PASS")
    report = mr.build_report(tmp_path)
    assert "milestones" in report
    for cell in report["matrix"]:
        for key in ("reached", "depth", "stalled_at", "coverage"):
            assert key not in cell
    for arm in report["arms"].values():
        for key in ("reached", "depth", "stalled_at"):
            assert key not in arm
    # the cells in the milestone section stay in (arm, unit) order
    keys = [(c["arm"], c["unit"]) for c in report["milestones"]["cells"]]
    assert keys == sorted(keys)


# ---- 9. the vocabulary pin ---------------------------------------------------

def test_audit_action_stage_classifier_matches_the_controlled_vocabulary():
    """The local action -> stage map stays consistent with
    scripts/e2e/audit.py: every registered action classified through the
    SAME category buckets (dispatch -> dispatch, checkpoint/oracle ->
    verification, the convergence decision -> convergence)."""
    category_stage = {"dispatch": "dispatch", "checkpoint": "verification",
                      "oracle": "verification", "decision": "convergence"}
    for action in sorted(e2e_audit.AUDIT_ACTIONS):
        cat = e2e_audit._category(action)
        assert mr._audit_stage(action) == category_stage.get(cat), action


# ---- 10. the contamination probe note ----------------------------------------

def test_contamination_probe_note_is_recorded_in_the_report_face_docs():
    """Reveree's flag-recall + surface-mutation probes map onto the
    constructed corpus + the held-out contract; the mapping lives in the
    report-face docstring, documentation only."""
    doc = mr.__doc__ or ""
    for needle in ("flag-recall", "surface-mutation", "contamination",
                   "eval_dataset", "held-out"):
        assert needle in doc, needle
