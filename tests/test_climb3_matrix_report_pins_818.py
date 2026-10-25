#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb3_matrix_report_pins_818.py — #818 climb segment 3C.

Behavior pins on REAL fixtures for the capability-matrix readout face
the second climb leg left unmeasured:

  scripts/eval_matrix_report.py — the read side of the matrix runner:
  the child-run results doc reader, the consolidated transition read
  (rlvr read face with the legacy fallback posture), multi-sample B2
  cells (pass@k at summed equal cost, pooled decision primitives), the
  missing/refused cell states, arm aggregation with the regret total,
  the three B-ladder decompositions with the seeded bootstrap CI and
  the tier slice, the #585 milestone projection (stage evidence, prefix
  depth, stall funnel), build_report's regret face + report.json
  write-back, and the stdout readout.

Pin discipline: expectations derive from the fixture each test computed —
no repo-state literalization (no pinned matrix bytes; every cell here is
synthesized on disk from the module's own documented run-dir shapes).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import eval_matrix_report as mr  # noqa: E402


# ------------------------------------------------------------ fixtures

def _ws(tmp_path: Path, name: str, *, facts: int = 1,
        transitions: list[dict] | None = None,
        audit: list[dict] | None = None) -> Path:
    """A synthetic analysis workspace the report reads ledgers from."""
    ws = tmp_path / name
    (ws / "facts").mkdir(parents=True)
    for i in range(facts):
        (ws / "facts" / f"F{i:03d}-evidence.md").write_text(
            "fact\n", encoding="utf-8")
    if transitions is not None:
        lines = "".join(json.dumps(r) + "\n" for r in transitions)
        (ws / "runs").mkdir()
        (ws / "runs" / "experience.jsonl").write_text(
            lines, encoding="utf-8")
    if audit is not None:
        lines = "".join(json.dumps(r) + "\n" for r in audit)
        (ws / "runs").mkdir(exist_ok=True)
        (ws / "runs" / "logs").mkdir(exist_ok=True)
        (ws / "runs" / "logs" / "e2e-audit.jsonl").write_text(
            lines, encoding="utf-8")
    return ws


def _results_doc(run_dir: Path, *, verdict: str = "PASS",
                 cost: float = 1.5, wall: float = 42.0,
                 workspace: Path | None = None,
                 loop_status: str = "completed") -> None:
    """Write one child-runner results doc in the documented shape."""
    run_dir.mkdir(parents=True, exist_ok=True)
    doc = {"rows": [{
        "verdict": verdict,
        "loop": {"status": loop_status,
                 "workspace": str(workspace) if workspace else None,
                 "session": {"session_cost": {"total_cost_usd": cost},
                             "wall_s": wall}},
    }]}
    (run_dir / "eval-results-000.json").write_text(
        json.dumps(doc), encoding="utf-8")


def _by_cell(spine: dict) -> dict:
    """The (arm, unit) -> spine-rows grouping build_report performs."""
    out: dict = {}
    for row in spine.get("runs", []):
        out.setdefault((row.get("arm"), row.get("unit")), []).append(row)
    return out


def _transition(action_type: str, r_incr: float | None = None,
                propensity: float | None = None) -> dict:
    row = {"schema": "transition", "action_type": action_type}
    if r_incr is not None:
        row["r_incr"] = r_incr
    if propensity is not None:
        row["propensity"] = propensity
    return row


# ============================================== document readout faces

class TestDocReadFaces:
    def test_newest_results_doc_picks_the_last_and_refuses_dirty(
            self, tmp_path) -> None:
        run = tmp_path / "run"
        assert mr.newest_results_doc(run) is None
        run.mkdir()
        (run / "eval-results-001.json").write_text(
            json.dumps({"rows": [{"verdict": "FAIL"}]}), encoding="utf-8")
        (run / "eval-results-002.json").write_text(
            json.dumps({"rows": [{"verdict": "PASS"}]}), encoding="utf-8")
        (run / "eval-results-003.json").write_text(
            "{broken", encoding="utf-8")
        # sorted glob: the newest valid doc before the dirty tail wins on
        # the parse attempt, and a dirty newest is a None, never a guess
        (run / "eval-results-004.json").write_text(
            json.dumps({"rows": [{"verdict": "SKIP"}]}), encoding="utf-8")
        doc = mr.newest_results_doc(run)
        assert doc == {"rows": [{"verdict": "SKIP"}]}
        (run / "eval-results-004.json").write_text("not json",
                                                    encoding="utf-8")
        assert mr.newest_results_doc(run) is None

    def test_transitions_read_through_the_consolidated_face(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, "ws", transitions=[
            _transition("dispatch", 0.5, 0.25),
            "dirty line",
            _transition("verify"),
        ])
        rows = mr.read_transitions(ws)
        assert [r.get("action_type") for r in rows] == ["dispatch",
                                                        "verify"]
        assert mr._transitions_count(ws) == 2
        assert mr._facts_count(ws) == 1

    def test_rewarded_rows_and_decision_primitives(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, "ws", transitions=[
            _transition("dispatch", 0.5, 0.25),
            _transition("act", 0.25, None),
            _transition("verify", None, None),
        ])
        prim = mr._decision_primitives(ws)
        assert prim["decisions"] == 2
        assert prim["learned_decisions"] == 1
        assert prim["mean_r"] == 0.375
        assert mr._decision_primitives(None) == {
            "decisions": 0, "learned_decisions": 0, "mean_r": None}

    def test_sample_dirs_index_order(self, tmp_path) -> None:
        unit = tmp_path / "u"
        unit.mkdir()
        (unit / "s10").mkdir()
        (unit / "s2").mkdir()
        (unit / "notes").mkdir()
        (unit / "samples").mkdir()  # multi-char suffix that is not digits
        got = mr._sample_dirs(unit)
        assert [d.name for d in got] == ["s2", "s10"]


# ================================================ matrix cell aggregation

class TestCollectMatrix:
    def test_doc_cell_reads_verdict_cost_wall_and_ledgers(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        ws = _ws(tmp_path, "ws-a", transitions=[
            _transition("dispatch", 0.5, 0.5),
            _transition("act", -0.25, None),
        ], audit=[{"action": "dispatch_launch", "ts": 1}])
        _results_doc(out / "arm-a" / "u1", verdict="PASS", cost=0.7,
                     wall=12.0, workspace=ws)
        spine = {"runs": [{"arm": "arm-a", "unit": "u1",
                           "tier": "release"}]}
        matrix = mr._collect_matrix(out, _by_cell(spine))
        assert len(matrix) == 1
        cell = matrix[0]
        assert cell["arm"] == "arm-a" and cell["unit"] == "u1"
        assert cell["final_status"] == "PASS"
        assert cell["loop_status"] == "completed"
        assert cell["budget_usd"] == 0.7
        assert cell["wall_s"] == 12.0
        assert cell["transitions"] == 2
        assert cell["facts"] == 1
        assert cell["decisions"] == 2
        assert cell["learned_decisions"] == 1
        assert cell["tier"] == "release"

    def test_run_dir_without_doc_and_without_spine_is_missing(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        (out / "arm-a" / "u-empty").mkdir(parents=True)
        matrix = mr._collect_matrix(out, {})
        assert matrix == [{"arm": "arm-a", "unit": "u-empty",
                           "final_status": "missing"}]

    def test_spine_only_cells_surface_refused_states(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        out.mkdir()
        spine = {"runs": [
            {"arm": "arm-b", "unit": "u-refused", "status": "refused",
             "detail": "admission gate refused the unit",
             "workspace": None},
            {"arm": "arm-c", "unit": "u-planned", "status": "planned",
             "sample_count": 4, "tier": "smoke"},
        ]}
        matrix = mr._collect_matrix(out, _by_cell(spine))
        by_cell = {(c["arm"], c["unit"]): c for c in matrix}
        refused = by_cell[("arm-b", "u-refused")]
        assert refused["final_status"] == "refused"
        assert refused["detail"] == "admission gate refused the unit"
        assert refused["decisions"] == 0
        planned = by_cell[("arm-c", "u-planned")]
        assert planned["samples"] == 4
        assert planned["tier"] == "smoke"

    def test_multisample_cell_is_pass_at_k_at_summed_cost(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        unit_dir = out / "cc-multisample" / "u9"
        ws1 = _ws(tmp_path, "ws-s1", transitions=[
            _transition("dispatch", 1.0, 0.5)])
        ws2 = _ws(tmp_path, "ws-s2", transitions=[
            _transition("dispatch", 0.0, None)])
        _results_doc(unit_dir / "s0", verdict="FAIL", cost=2.0,
                     wall=10.0, workspace=ws1)
        _results_doc(unit_dir / "s1", verdict="PASS", cost=2.5,
                     wall=30.0, workspace=ws2)
        (unit_dir / "s2").mkdir(parents=True)  # no doc: rides the spine
        spine = {"runs": [{"arm": "cc-multisample", "unit": "u9",
                           "sample": 2, "status": "session_error",
                           "workspace": None}]}
        matrix = mr._collect_matrix(out, _by_cell(spine))
        assert len(matrix) == 1
        cell = matrix[0]
        assert cell["samples"] == 3
        assert cell["final_status"] == "PASS"  # pass@k: any PASS passes
        assert cell["pass_at_k"] == 1.0
        assert cell["budget_usd"] == 4.5  # summed, equal-cost contract
        assert cell["wall_s"] == 30.0  # max wall, not summed
        assert cell["decisions"] == 2  # pooled across samples
        assert cell["mean_r"] == 0.5

    def test_arm_aggregation_counts_and_learned_share(
            self, tmp_path) -> None:
        matrix = [
            {"arm": "a", "unit": "u1", "final_status": "PASS",
             "decisions": 4, "learned_decisions": 3,
             "regret_vs_best_arm": None},
            {"arm": "a", "unit": "u2", "final_status": "FAIL",
             "decisions": 2, "learned_decisions": 1,
             "regret_vs_best_arm": 0.25},
            {"arm": "a", "unit": "u3", "final_status": "missing",
             "decisions": 0, "learned_decisions": 0,
             "regret_vs_best_arm": None},
        ]
        arms = mr._aggregate_arms(matrix)
        acc = arms["a"]
        assert acc["units"] == 3 and acc["pass"] == 1 and \
            acc["fail"] == 1 and acc["other"] == 1
        assert acc["decisions"] == 6 and acc["learned_decisions"] == 4
        assert acc["learned_share"] == round(4 / 6, 4)
        assert acc["regret_total"] == 0.25 and acc["regret_cells"] == 1


# ================================================ B-ladder decompositions

class TestDecompositions:
    def _matrix(self) -> list[dict]:
        rows = []
        for unit, (ra, rb) in {"u1": (1.0, 0.25),
                               "u2": (0.5, -0.25)}.items():
            rows.append({"arm": "kunglao-warm", "unit": unit,
                         "final_status": "PASS", "mean_r": ra,
                         "decisions": 1, "learned_decisions": 1})
            rows.append({"arm": "kunglao-uniform", "unit": unit,
                         "final_status": "FAIL", "mean_r": rb,
                         "decisions": 1, "learned_decisions": 0})
        return rows

    def test_three_named_rows_render_deltas_with_seeded_ci(self) -> None:
        matrix = self._matrix() + [
            {"arm": "cc-bare", "unit": "u1", "final_status": "FAIL",
             "mean_r": 0.0, "decisions": 1, "learned_decisions": 0},
            {"arm": "cc-bare", "unit": "u2", "final_status": "FAIL",
             "mean_r": 0.0, "decisions": 1, "learned_decisions": 0},
        ]
        dec = mr._decompositions(matrix)
        assert set(dec) == set(mr.DECOMPOSITION_ARMS)
        learning = dec["learning_value"]
        assert learning["formula"] == "B4 - B3"
        assert learning["mean_delta"] == pytest.approx(0.75)
        # seeded bootstrap: the same matrix renders the same interval
        assert learning["ci95"] == mr._bootstrap_ci(
            [learning["per_unit"][u] for u in sorted(learning["per_unit"])])
        assert learning["pass_rate_a"] == 1.0
        assert learning["pass_rate_b"] == 0.0
        arch = dec["architecture_value"]
        assert arch["mean_delta"] == pytest.approx((0.25 + -0.25) / 2)

    def test_determinism_same_matrix_same_ci_twice(self) -> None:
        a = mr._decompositions(self._matrix())
        b = mr._decompositions(self._matrix())
        assert a["learning_value"]["ci95"] == \
            b["learning_value"]["ci95"]

    def test_missing_arm_waits_instead_of_fabricating(self) -> None:
        dec = mr._decompositions(self._matrix())  # no cc-bare rows
        assert dec["architecture_value"]["missing_arms"] == ["cc-bare"]
        assert dec["sampling_check"]["missing_arms"] == ["cc-multisample"]

    def test_rewardless_pair_renders_no_number(self) -> None:
        matrix = [
            {"arm": "kunglao-warm", "unit": "u1",
             "final_status": "PASS"},
            {"arm": "kunglao-uniform", "unit": "u1",
             "final_status": "FAIL"},
        ]
        row = mr._decompositions(matrix)["learning_value"]
        assert "per_unit" not in row
        assert "waits for data" in row["note"]

    def test_learning_value_slices_by_declared_tier(self) -> None:
        matrix = [
            {"arm": "kunglao-warm", "unit": "u1", "mean_r": 1.0,
             "final_status": "PASS", "tier": "release"},
            {"arm": "kunglao-warm", "unit": "u2", "mean_r": 0.0,
             "final_status": "FAIL"},
            {"arm": "kunglao-uniform", "unit": "u1", "mean_r": 0.5,
             "final_status": "FAIL", "tier": "release"},
            {"arm": "kunglao-uniform", "unit": "u2", "mean_r": -0.5,
             "final_status": "FAIL"},
        ]
        row = mr._decompositions(matrix)["learning_value"]
        assert set(row["tiers"]) == {"release"}
        face = row["tiers"]["release"]
        assert face["units"] == ["u1"]
        assert face["mean_delta"] == 0.5


# ================================================== milestone projection

class TestMilestones:
    def test_audit_stage_mapping(self) -> None:
        assert mr._audit_stage("dispatch_launch") == "dispatch"
        assert mr._audit_stage("dispatch_child") == "dispatch"
        assert mr._audit_stage("checkpoint_act") == "verification"
        assert mr._audit_stage("oracle_verdict") == "verification"
        assert mr._audit_stage("convergence_decision") == "convergence"
        assert mr._audit_stage("kernel_noop") is None
        assert mr._audit_stage("distill_thing") is None
        assert mr._audit_stage("harvest_row") is None

    def test_workspace_stage_evidence_off_the_real_ledgers(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, "ws", facts=2, transitions=[
            _transition("verify", 0.5),
        ], audit=[
            {"action": "dispatch_launch"},
            {"action": "convergence_decision"},
        ])
        (ws / "task_spec.yaml").write_text("primary_questions: []\n",
                                           encoding="utf-8")
        (ws / "runs" / "dispatch-launch-1.json").write_text(
            "{}", encoding="utf-8")
        ev = mr._ws_stage_evidence(ws)
        assert ev == {"intake": True, "dispatch": True, "facts": True,
                      "verification": True, "settlement": True,
                      "convergence": True}

    def test_empty_workspace_marks_no_stage(self, tmp_path) -> None:
        ws = tmp_path / "bare"
        ws.mkdir()
        assert not any(mr._ws_stage_evidence(ws).values())

    def test_redteam_transitions_evidence_verification(
            self, tmp_path) -> None:
        ws = _ws(tmp_path, "ws", transitions=[_transition("redteam")])
        assert mr._ws_stage_evidence(ws)["verification"] is True

    def test_prefix_depth_refuses_gap_inflation(self) -> None:
        # evidence past a gap never inflates depth (the Reveree reading)
        assert mr._prefix_depth(["intake", "dispatch", "facts"]) == 3
        assert mr._prefix_depth(["intake", "convergence"]) == 1
        assert mr._prefix_depth([]) == 0
        full = list(mr.MILESTONE_STAGES)
        assert mr._prefix_depth(full) == len(full)
        assert mr._stalled_at(full) is None
        assert mr._stalled_at(["intake", "convergence"]) == "dispatch"
        assert mr._stalled_at([]) == "intake"

    def test_milestone_reached_pools_samples_and_verdict_closes_ends(
            self, tmp_path) -> None:
        bare = tmp_path / "bare"
        bare.mkdir()
        reached = mr._milestone_reached([bare, None], has_verdict=True)
        # the outcome closes the two ends; a bare workspace contributes
        # no middle-stage evidence
        assert reached == ["intake", "convergence"]
        assert mr._milestone_reached([], False) == []

    def test_milestones_renders_cells_and_funnel_in_order(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        ws1 = _ws(tmp_path, "ws-full", facts=1, transitions=[
            _transition("verify", 0.5)], audit=[
                {"action": "dispatch_launch"},
                {"action": "checkpoint_act"},
                {"action": "convergence_decision"}])
        (ws1 / "task_spec.yaml").write_text("primary_questions: []\n",
                                            encoding="utf-8")
        ws2 = tmp_path / "ws-stall"  # intake + dispatch, then stalled
        (ws2 / "runs").mkdir(parents=True)
        (ws2 / "task_spec.yaml").write_text("primary_questions: []\n",
                                            encoding="utf-8")
        (ws2 / "runs" / "dispatch-launch-1.json").write_text(
            "{}", encoding="utf-8")
        _results_doc(out / "arm-a" / "u-green", verdict="PASS",
                     workspace=ws1)
        _results_doc(out / "arm-a" / "u-stall", verdict=None,
                     loop_status="exhausted", workspace=ws2)
        mil = mr.milestones(out, {})
        assert mil["stages"] == list(mr.MILESTONE_STAGES)
        cells = {(c["arm"], c["unit"]): c for c in mil["cells"]}
        green = cells[("arm-a", "u-green")]
        assert green["reached"] == list(mr.MILESTONE_STAGES)
        assert green["depth"] == 6 and green["stalled_at"] is None
        stall = cells[("arm-a", "u-stall")]
        assert stall["reached"] == ["intake", "dispatch"]
        assert stall["depth"] == 2 and stall["stalled_at"] == "facts"
        funnel = mil["funnel"]
        assert funnel["intake"]["reached"] == 2
        assert funnel["intake"]["stalled_here"] == 0
        assert funnel["dispatch"]["stalled_here"] == 1
        assert funnel["convergence"]["stalled_here"] == 0

    def test_milestone_input_walks_spine_only_cells_too(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        out.mkdir()
        spine = {"runs": [{"arm": "arm-z", "unit": "u-planned",
                           "status": "planned",
                           "workspace": str(tmp_path)}]}
        got = list(mr._milestone_input(out, _by_cell(spine)))
        # spine workspaces ride as the launcher wrote them (path strings)
        assert got == [("arm-z", "u-planned", [str(tmp_path)], False)]


# ======================================================= report assembly

class TestBuildReport:
    def test_regret_face_anchors_on_the_post_hoc_best_arm(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        ws = _ws(tmp_path, "ws", transitions=[
            _transition("dispatch", 1.0)])
        _results_doc(out / "warm" / "u1", verdict="PASS", workspace=ws)
        _results_doc(out / "bare" / "u1", verdict="FAIL")
        report = mr.build_report(out)
        cells = {(c["arm"], c["unit"]): c for c in report["matrix"]}
        assert cells[("warm", "u1")]["regret_vs_best_arm"] == 0.0
        assert cells[("bare", "u1")]["regret_vs_best_arm"] is None
        assert report["schema"] == mr.SCHEMA_REPORT
        assert (out / "report.json").is_file()
        assert report["milestones"]["cells"]

    def test_progress_spine_read_from_disk_with_dirty_fallback(
            self, tmp_path) -> None:
        out = tmp_path / "run"
        out.mkdir()
        (out / "progress.json").write_text("{broken", encoding="utf-8")
        report = mr.build_report(out)
        assert report["matrix"] == []
        spine = {"runs": [{"arm": "arm-a", "unit": "u1",
                           "status": "planned"}]}
        (out / "progress.json").write_text(json.dumps(spine),
                                           encoding="utf-8")
        report = mr.build_report(out)
        assert report["matrix"][0]["final_status"] == "planned"

    def test_full_readout_renders_every_section(self, tmp_path,
                                                capsys) -> None:
        out = tmp_path / "run"
        ws = _ws(tmp_path, "ws", facts=1, transitions=[
            _transition("dispatch", 0.5, 0.5)], audit=[
                {"action": "dispatch_launch"}])
        _results_doc(out / "kunglao-warm" / "u1", verdict="PASS",
                     workspace=ws)
        _results_doc(out / "kunglao-uniform" / "u1", verdict="FAIL",
                     cost=0.2, workspace=ws)
        _results_doc(out / "cc-bare" / "u1", verdict="SKIP")
        report = mr.build_report(out)
        mr.print_report(report)
        stream = capsys.readouterr().out
        assert "ARM" in stream and "kunglao-warm" in stream
        assert "learning_value: B4 - B3 =" in stream
        assert "architecture_value" in stream
        assert "WAITING" in stream  # cc-multisample absent
        assert "milestones (#585):" in stream
        assert "funnel:" in stream
        rc = mr.main(["--out", str(out)])
        assert rc == 0
        assert "REPORT" in capsys.readouterr().out
