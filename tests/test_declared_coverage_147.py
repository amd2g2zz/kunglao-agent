# -*- coding: utf-8 -*-
"""#147 declared oracle coverage — the convergence gate consumes the #128 bit.

Final semantics (issue body + owner amendments):

  convergence requires DECLARED oracle coverage. The Phase-0
  goal-operationalization.yaml ``generalization`` bit
  (required | not-applicable | unknown, scripts/goal_operationalization.py)
  is the coverage contract the DRAIN oracle face now enforces:

    - operationalization missing / invalid / unstamped -> BLOCK
      ("verification requirements undeclared — complete the Phase-0
      operationalization") — fail-closed on the undeclared;
    - generalization required|unknown AND zero ARMED oracle cases -> BLOCK
      ("verification declared required but no oracle coverage delivered");
      absence of the oracle status file is this block, never untouched;
    - required|unknown + armed cases present -> the #108 oracle_blocks()
      behavior unchanged (red / pending-instrumented block);
    - generalization not-applicable -> the DECLARED fast path: converge
      without cases, the timestamped declaration is the audit record;
    - a red verdict on an existing case blocks regardless of the bit
      (a declaration covers ABSENCE of coverage, not failed cases).

  Legacy carve-out (deliberate, per the fail-closed posture): a workspace
  with NO goal-operationalization.yaml AND NO task-oracle.yaml predates the
  contract entirely (pre-#473) and keeps the #108 untouched behavior —
  task-oracle.yaml registration (#473, heartbeat_tick._oracle_registered)
  is the marker that a workspace owes the Phase-0 operationalization.

Fixtures: (A) required + zero armed -> BLOCKED (this is THE hole — audit
passes it pre-fix); (B) not-applicable + declared -> converges untouched,
declaration visible in decide output; (C) missing operationalization ->
BLOCKED; (D) unknown + zero -> BLOCKED; (E) required + armed green ->
converges (normal path intact).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
TESTS = Path(__file__).parent
if str(TESTS) not in sys.path:  # sibling-module import under and outside pytest
    sys.path.insert(0, str(TESTS))

import convergence_check as cc
import goal_operationalization as go

# Anchor builders: the converged-workspace factory shape is shared with the
# #443 matrix and the #108 block in test_decide_state_machine.py.
import test_decide_regression_anchor as anchor


# ------------------------------------------------------------- factories

def _mk_converged_ws(base: Path, name: str) -> Path:
    """The fully drained claim face (same shape as the #108 block): claim
    terminal/PROVEN, pq answered with a passes note, clean facts."""
    ws = anchor._ws(base, name)
    anchor._reg(ws, [{"id": "C-1", "status": "PROVEN",
                      "answers_question": "q1"}])
    anchor._ts(ws, anchor._pq_canonical())
    anchor._notes(ws, {"n1.md": ("C-1", "passes")})
    anchor._fact_dir(ws)
    return ws


def _write_task_oracle(ws: Path) -> None:
    """#473-style verbatim task file (existence is the contract marker)."""
    (ws / "task-oracle.yaml").write_text(
        "task_text: analyze the payload\nopen_items: []\ndeferrals: []\n",
        encoding="utf-8")


def _goal_op_doc(generalization: str = "required",
                 declared_ts: str = "2026-09-07T01:02:03+00:00") -> dict:
    """A VALID goal-operationalization document (passes the #128 validator).

    required/unknown carry the mandatory fresh-input probe case;
    not-applicable carries the mandatory explicit diff_vs_verbatim entry
    (declaring non-generalization IS a visible narrowing, R3)."""
    doc = {
        "schema": go.SCHEMA_ID,
        "verbatim_ref": "task-oracle.yaml",
        "declared_ts": declared_ts,
        "generalization": generalization,
        "deliverables": [
            "the client generates valid output for never-captured inputs"],
        "acceptance": ["oracle cases pass on fresh-input generation"],
        "not_done": ["a replay of captured traffic does not count as done"],
        "diff_vs_verbatim": [
            "translated the verbatim ask into mechanically checkable lists"],
        "probe_cases": ["fresh-input: generate valid output for a "
                        "never-captured request"],
    }
    if generalization == "not-applicable":
        doc["diff_vs_verbatim"].append(
            "generalization not-applicable: the deliverable is judged on "
            "the captured evidence only, no beyond-evidence inputs")
        doc["probe_cases"] = []
    return doc


def _write_goal_op(ws: Path, doc: dict) -> None:
    go.dump(ws / "goal-operationalization.yaml", doc)


def _set_oracle_status(ws: Path, cases: dict) -> None:
    """Synthetic convention (#108): runs/oracle-status.json, written by the
    oracle runner — {"cases": {id: {"status", "pending_entries", ...}}}."""
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "oracle-status.json").write_text(
        json.dumps({"schema": "oracle-status/1", "cases": cases}),
        encoding="utf-8")


# ------------------------------------------------- the acceptance fixtures

def test_a_required_zero_armed_cases_blocks_147(tmp_path: Path) -> None:
    """Fixture A (THE hole): generalization=required, zero armed cases.
    Pre-fix the audit PASSES this workspace — CONVERGED with no oracle
    coverage at all. Post-fix: BLOCKED, reason names the missing coverage."""
    ws = _mk_converged_ws(tmp_path, "required_zero_armed")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("required"))
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED", (
        f"#147: required + zero armed cases must not converge, "
        f"got {d['decision']}")
    assert d["exit_code"] == cc.EXIT_BLOCKED
    assert "no oracle coverage delivered" in d["action"], d["action"][:300]
    face = d.get("declared_coverage") or {}
    assert face.get("generalization") == "required"
    assert face.get("status") == "declared"


def test_b_not_applicable_declared_converges_147(tmp_path: Path) -> None:
    """Fixture B: the DECLARED fast path. not-applicable + timestamped
    declaration -> converges untouched, and the declaration is VISIBLE in
    the decide output (the audit record that the speed was declared, not
    snuck)."""
    ws = _mk_converged_ws(tmp_path, "not_applicable_declared")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("not-applicable"))
    d = cc.decide(ws)
    assert d["decision"] == "CONVERGED", (
        f"#147: a declared not-applicable task converges without cases, "
        f"got {d['decision']}: {d['action'][:200]}")
    face = d.get("declared_coverage") or {}
    assert face.get("generalization") == "not-applicable", (
        "#147: the declaration must be visible in the decide output")
    assert face.get("declared") is True
    assert face.get("declared_ts"), "#147: the timestamp is the audit record"
    assert face.get("blocks") == []


def test_c_missing_operationalization_blocks_147(tmp_path: Path) -> None:
    """Fixture C: a registered workspace (task-oracle.yaml present) with NO
    goal-operationalization.yaml -> BLOCK, fail-closed on the undeclared."""
    ws = _mk_converged_ws(tmp_path, "missing_op")
    _write_task_oracle(ws)
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED", (
        f"#147: a registered workspace without the operationalization must "
        f"block, got {d['decision']}")
    assert "verification requirements undeclared" in d["action"], \
        d["action"][:300]
    face = d.get("declared_coverage") or {}
    assert face.get("status") == "undeclared"


def test_d_unknown_zero_cases_blocks_147(tmp_path: Path) -> None:
    """Fixture D: unknown is fail-closed (= required, #128 R3). Zero armed
    cases -> BLOCK."""
    ws = _mk_converged_ws(tmp_path, "unknown_zero_cases")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("unknown"))
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED", (
        f"#147: unknown + zero armed cases must block (default-closed), "
        f"got {d['decision']}")
    assert "no oracle coverage delivered" in d["action"], d["action"][:300]


def test_e_required_armed_green_converges_147(tmp_path: Path) -> None:
    """Fixture E: the normal path intact. required + armed GREEN cases ->
    converges (coverage delivered, acceptance face clean)."""
    ws = _mk_converged_ws(tmp_path, "required_armed_green")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("required"))
    _set_oracle_status(ws, {
        "case-g1": {"status": "pass", "pending_entries": 0,
                    "instrumented": True},
        "case-g2": {"status": "pass", "pending_entries": 0,
                    "instrumented": True},
    })
    d = cc.decide(ws)
    assert d["decision"] == "CONVERGED", (
        f"#147: required + armed green cases converge, got {d['decision']}: "
        f"{d['action'][:200]}")
    face = d.get("declared_coverage") or {}
    assert face.get("armed_cases") == 2
    assert face.get("blocks") == []


# ------------------------------------------------- the contract boundaries

def test_true_legacy_carveout_untouched_147(tmp_path: Path) -> None:
    """True legacy (pre-#473: NO goal-operationalization.yaml AND NO
    task-oracle.yaml) keeps the #108 untouched behavior — no coverage gate,
    no declaration face (the workspace predates the contract entirely)."""
    ws = _mk_converged_ws(tmp_path, "true_legacy")
    d = cc.decide(ws)
    assert d["decision"] == "CONVERGED"
    assert "declared_coverage" not in d, (
        "#147: a true-legacy workspace has no coverage contract to report")


def test_invalid_generalization_value_blocks_147(tmp_path: Path) -> None:
    """An undeclared bit value ('maybe') is a #128 loud-rejection wall —
    the gate reads it as undeclared and blocks (fail-closed)."""
    ws = _mk_converged_ws(tmp_path, "invalid_bit")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("maybe"))
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED"
    assert "verification requirements undeclared" in d["action"], \
        d["action"][:300]
    assert d["declared_coverage"]["status"] == "invalid"


def test_unstamped_operationalization_blocks_147(tmp_path: Path) -> None:
    """#128 R4: a pre-registration without a timestamp is not a record —
    the unstamped translation is an undeclared verification requirement."""
    ws = _mk_converged_ws(tmp_path, "unstamped_op")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("required", declared_ts=""))
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED", (
        f"#147: an unstamped operationalization is not a record, "
        f"got {d['decision']}")
    assert "verification requirements undeclared" in d["action"], \
        d["action"][:300]


def test_malformed_operationalization_blocks_147(tmp_path: Path) -> None:
    """Unreadable/malformed YAML -> loud rejection (#128 GoalOpError) ->
    the gate blocks with the cause (fail-closed, contradiction-gate
    precedent)."""
    ws = _mk_converged_ws(tmp_path, "malformed_op")
    _write_task_oracle(ws)
    (ws / "goal-operationalization.yaml").write_text(
        "{not yaml: [", encoding="utf-8")
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED"
    assert "verification requirements undeclared" in d["action"], \
        d["action"][:300]


def test_required_scaffold_only_still_blocks_147(tmp_path: Path) -> None:
    """A status file with only UNINSTRUMENTED scaffold cases is still zero
    ARMED coverage (#108: a scaffold never ran live instrumentation) —
    required -> BLOCK, never a laundering path."""
    ws = _mk_converged_ws(tmp_path, "required_scaffold_only")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("required"))
    _set_oracle_status(ws, {"case-001": {"status": "pending",
                                         "pending_entries": 2,
                                         "instrumented": False}})
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED", (
        f"#147: scaffold-only is not delivered coverage, got {d['decision']}")
    assert "no oracle coverage delivered" in d["action"], d["action"][:300]
    assert d["declared_coverage"]["armed_cases"] == 0


def test_not_applicable_red_case_still_blocks_147(tmp_path: Path) -> None:
    """A declaration covers ABSENCE of coverage, not failed cases: an armed
    RED case blocks regardless of the bit (#108 acceptance face intact)."""
    ws = _mk_converged_ws(tmp_path, "not_applicable_red")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("not-applicable"))
    _set_oracle_status(ws, {"case-204": {"status": "fail",
                                         "pending_entries": 0,
                                         "instrumented": True}})
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED", (
        f"#147: a red case blocks under not-applicable too, "
        f"got {d['decision']}")
    assert "case-204" in d["action"], d["action"][:300]


def test_required_pending_instrumented_blocks_147(tmp_path: Path) -> None:
    """required + armed PENDING-instrumented cases: coverage delivered but
    not satisfiable — the #108 pending block rides unchanged."""
    ws = _mk_converged_ws(tmp_path, "required_pend_instr")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("required"))
    _set_oracle_status(ws, {"case-207": {"status": "pending",
                                         "pending_entries": 3,
                                         "instrumented": True}})
    d = cc.decide(ws)
    assert d["decision"] == "BLOCKED"
    assert "case-207" in d["action"], d["action"][:300]
    assert d["declared_coverage"]["armed_cases"] == 1


def test_segment_boundary_interim_marker_147(tmp_path: Path) -> None:
    """The v0.1.5 SKELETON marker (explicitly interim): the #147 coverage
    action notes that the segment boundary routes through failure-analysis
    routing, and that the policy-driven action space is the #12/#13/#59
    v0.2 design landing."""
    ws = _mk_converged_ws(tmp_path, "boundary_marker")
    _write_task_oracle(ws)
    _write_goal_op(ws, _goal_op_doc("required"))
    d = cc.decide(ws)
    assert "failure-analysis routing" in d["action"], d["action"][:400]
    assert "interim" in d["action"]
    assert "#12/#13/#59" in d["action"]


# ------------------------------------------------------- structural pins

def test_gate_composes_into_oracle_predicate_147() -> None:
    """ORACLE_CASE_RED stays the single DRAIN acceptance event: the #147
    coverage blocks compose into its predicate (no second probe row — the
    issue scopes the gate INTO the existing oracle face)."""
    pred = cc._EVENT_PREDICATES[cc.Event.ORACLE_CASE_RED]
    assert callable(pred)
    row = cc.TRANSITIONS[(cc.State.DRAIN, cc.Event.ORACLE_CASE_RED)]
    assert row[0] is cc.State.BLOCKED


def test_declaration_face_absent_for_legacy_anchor_shape(tmp_path: Path) -> None:
    """The anchor corpus shape (no contract files) keeps its byte-frozen
    decide() shape: no new keys, no verdict drift (#829 conditional-key
    precedent; the frozen matrix stays valid without a re-pin)."""
    ws = _mk_converged_ws(tmp_path, "anchor_shape")
    d = cc.decide(ws)
    assert d["decision"] == "CONVERGED"
    assert d["oracle"] == {"red": 0, "green": 0, "pending": 0,
                           "low_discriminativity": [], "blocked": [],
                           "absent": True}
    assert "declared_coverage" not in d
