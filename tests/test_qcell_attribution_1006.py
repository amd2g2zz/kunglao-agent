# -*- coding: utf-8 -*-
"""tests/test_qcell_attribution_1006.py — q-cell attribution coherence.

A dispatch-time q-cell row is addressed by its ``arm_key``, but the
sampler reconciliation (``sampled_family`` / ``propensity``) can describe
a DIFFERENT family than the arm when the dispatch overrides the draw.
These pins require:

  - an override row to carry an explicit marker (``family_override`` +
    the override source/reason) with the override's own propensity in a
    clearly labelled column — never a bare ``propensity`` paired with an
    arm the sampler did not draw;
  - the fold and the off-policy comparator to consume only coherent rows
    (``sampled_family == arm_key.family`` or an explicit override marker)
    and to report every excluded row; the calibration/amendment operands
    mirror the same admission, and credit rows (which never carry a
    sampler pair) keep the settlement ledger idempotent;
  - the round-strategy lead mismatch to ride the row with its reason.

Synthetic workspaces only — no private corpora.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pytest

from rlvr import consolidated_ledger as cl
from rlvr import incremental_reward as ir
from rlvr import policy_compare as pc
from rlvr import q_cells
from rlvr import strategy_store as ss

SIG = "44480d5e686b"
DISPATCHED = "red-team-verification"
DRAW = "hypothesis-falsification"
ARM = f"{DISPATCHED}|facts_snapshot|red_team|0"
REASON = "the decision table sends a verifier"

_V1 = json.dumps({"kunglao_dispatch": {
    "version": 1, "claim": "C-1", "tier": 1,
    "tools": ["Bash"], "method_family": DISPATCHED}})


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _prompt(reason: str = REASON) -> str:
    return f"{_V1}\nagent-reasoning: {reason}"


def _raw_row(ws, **over) -> dict:
    """A row written WITHOUT the append boundary — the legacy on-disk
    shape (the production counterexample predates this fix)."""
    row = {"schema": q_cells.OBS_SCHEMA, "ts": "2026-11-05T00:00:00Z",
           "source": "dispatch", "signature_hash": SIG,
           "method_family": DISPATCHED, "claim": "C-1", "agent": None,
           "dispatch_id": "d-1", "fingerprint": None, "credit": None,
           "arm_key": ARM}
    row.update(over)
    assert cl.append(ws, "experience", row)
    return row


def _dispatch(ws, *, view, claim="C-020", prompt=None) -> dict:
    out = q_cells.record_dispatch_observation(
        ws, prompt or _prompt(),
        envelope_meta={"method_family": DISPATCHED,
                       "context_recipe": "facts_snapshot",
                       "verification_mode": "red_team"},
        claim=claim, tier=1, sampler_view=view)
    assert out["appended"] is True, out
    return q_cells.JSONLQStore(ws).observations()[-1]


# ---------------------------------------------------------------- writer

def test_dispatch_override_row_is_self_consistent(tmp_path):
    """The production counterexample shape: the dispatched family is not
    the sampler's draw. The row must mark the override, keep the draw's
    propensity labelled as the draw's, carry the override's own
    propensity separately, and leave the bare pairing column empty."""
    ws = _ws(tmp_path)
    row = _dispatch(ws, view={
        "sampled_family": DRAW, "propensity": 0.168985,
        "sampled_propensity": 0.402,
        "prior_source": "history", "round_lead": "obfuscation-peeling"})
    assert row["method_family"] == DISPATCHED
    assert row["arm_key"] == ARM
    assert row["sampled_family"] == DRAW
    assert row["propensity"] is None, (
        "the bare propensity must never pair a draw with a foreign arm")
    assert row["family_override"] is True
    assert row["override_source"] == "agent-reasoning"
    assert row["override_reason"] == REASON
    assert row["override_propensity"] == 0.168985
    assert row["sampled_propensity"] == 0.402
    assert row["round_lead"] == "obfuscation-peeling"
    assert row["lead_override"] is True
    assert row["lead_override_reason"] == REASON
    assert q_cells.attribution_consistent(row) is True


def test_on_policy_row_keeps_the_draw_propensity(tmp_path):
    """The healthy face is unchanged: the sampler's draw IS the arm, so
    the propensity pairs legitimately with the arm_key."""
    ws = _ws(tmp_path)
    row = _dispatch(ws, claim="C-006", view={
        "sampled_family": DISPATCHED, "propensity": 0.344394,
        "prior_source": "history"})
    assert row["propensity"] == 0.344394
    assert "family_override" not in row
    assert "override_propensity" not in row
    assert "round_lead" not in row
    assert q_cells.attribution_consistent(row) is True


def test_round_lead_matching_the_dispatch_is_not_an_override(tmp_path):
    ws = _ws(tmp_path)
    row = _dispatch(ws, view={
        "sampled_family": DISPATCHED, "propensity": 0.3,
        "round_lead": DISPATCHED})
    assert "lead_override" not in row
    assert row["propensity"] == 0.3


# ---------------------------------------------------------------- reader

def test_attribution_consistent_matrix():
    assert q_cells.attribution_consistent(
        {"method_family": DISPATCHED, "arm_key": ARM})
    assert q_cells.attribution_consistent(
        {"method_family": DISPATCHED, "arm_key": ARM,
         "sampled_family": DISPATCHED})
    assert not q_cells.attribution_consistent(
        {"method_family": DISPATCHED, "arm_key": ARM,
         "sampled_family": DRAW})
    assert q_cells.attribution_consistent(
        {"method_family": DISPATCHED, "arm_key": ARM,
         "sampled_family": DRAW, "family_override": True})


def test_fold_excludes_inconsistent_rows_and_reports(tmp_path):
    ws = _ws(tmp_path)
    _raw_row(ws, credit=0.9, source="settlement", sampled_family=DRAW)
    q_cells.append_observation(ws, SIG, DISPATCHED, 0.8,
                               source="settlement", arm_key_col=ARM)
    view = q_cells.fold(q_cells.JSONLQStore(ws), gamma=1.0)
    (cell,) = list(view.cells.values())
    assert cell.success == pytest.approx(0.8)
    assert view.inconsistent == 1, (
        "the incoherent credit row must be excluded AND counted")


def test_marked_override_rows_stay_admissible(tmp_path):
    ws = _ws(tmp_path)
    _raw_row(ws, credit=0.7, source="settlement", sampled_family=DRAW,
             family_override=True, override_source="agent-reasoning")
    view = q_cells.fold(q_cells.JSONLQStore(ws), gamma=1.0)
    (cell,) = list(view.cells.values())
    assert cell.success == pytest.approx(0.7)
    assert view.inconsistent == 0


def test_calibration_operands_mirror_the_fold_exclusion(tmp_path):
    """The amendment/residual operands read the SAME log the fold
    consumes: an incoherent row the fold refuses must not count in
    ``banked_mass`` or ``step_credit_totals``, or a wrong residual can
    bank off mass the fold dropped."""
    ws = _ws(tmp_path)
    _raw_row(ws, credit=0.8, source="settlement", sampled_family=DRAW)
    _raw_row(ws, credit=0.8, source="settlement", sampled_family=DRAW,
             credit_kind=q_cells.CREDIT_KIND_STEP)
    assert q_cells.banked_mass(ws, "d-1") == (0.0, 0.0, 0)
    assert q_cells.step_credit_totals(ws, "d-1") == (0.0, 0)
    fold_view = q_cells.fold(q_cells.JSONLQStore(ws), gamma=1.0)
    assert fold_view.cells == {}
    assert fold_view.inconsistent == 2


def test_calibration_operands_count_marked_override_rows(tmp_path):
    ws = _ws(tmp_path)
    _raw_row(ws, credit=0.6, source="settlement", sampled_family=DRAW,
             family_override=True, override_source="agent-reasoning")
    _raw_row(ws, credit=0.4, source="settlement", sampled_family=DRAW,
             family_override=True, override_source="agent-reasoning",
             credit_kind=q_cells.CREDIT_KIND_STEP)
    assert q_cells.banked_mass(ws, "d-1") == (0.6, 0.4, 1)
    assert q_cells.step_credit_totals(ws, "d-1") == (0.4, 1)


def test_reports_expose_the_inconsistent_count(tmp_path):
    ws = _ws(tmp_path)
    _raw_row(ws, credit=0.9, source="settlement", sampled_family=DRAW)
    assert q_cells.reindex(tmp_path)["inconsistent"] == 1
    assert q_cells.cell_table(ws)["inconsistent"] == 1


def test_override_without_a_recorded_reason_is_explicitly_null(tmp_path):
    ws = _ws(tmp_path)
    row = _dispatch(ws, prompt=_V1, view={
        "sampled_family": DRAW, "propensity": 0.2,
        "prior_source": "history"})
    assert row["family_override"] is True
    assert row["override_source"] == "declared"
    assert "override_reason" in row and row["override_reason"] is None


def test_invalid_override_propensities_degrade_to_absent(tmp_path):
    ws = _ws(tmp_path)
    row = _dispatch(ws, view={
        "sampled_family": DRAW, "propensity": 1.5,
        "sampled_propensity": "nope", "prior_source": "history"})
    assert row["family_override"] is True
    assert "override_propensity" not in row
    assert "sampled_propensity" not in row


def test_settlement_credit_banks_into_the_dispatched_arm(tmp_path):
    """The credit row carries no sampler pair, so the fold banks it into
    the arm that actually did the work; the legacy dispatch row itself
    stays the excluded, counted attribution gap. (The alternative —
    propagating the pair onto the credit row — makes the settlement
    ledger's amendment/replay bookkeeping non-idempotent, so the pair
    stays on the dispatch record.)"""
    ws = _ws(tmp_path)
    _raw_row(ws, sampled_family=DRAW, propensity=0.168985)
    out = q_cells.observe_settlement(ws, "d-1", 0.8)
    assert out["matched"] is True
    rows = q_cells.JSONLQStore(ws).observations()
    settled = [r for r in rows if r.get("source") == "settlement"][-1]
    assert "sampled_family" not in settled
    assert q_cells.banked_mass(ws, "d-1") == (0.8, 0.2, 1)
    view = q_cells.fold(q_cells.JSONLQStore(ws), gamma=1.0)
    (cell,) = list(view.cells.values())
    assert cell.success == pytest.approx(0.8)
    assert view.inconsistent == 1  # the pending dispatch row only


def test_amendment_is_idempotent_with_a_legacy_incoherent_dispatch(tmp_path):
    """The credit row has no sampler pair, so the amendment operand sees
    the banked mass and converges: repeated corrections append nothing,
    and the final cell carries the corrected target."""
    ws = _ws(tmp_path)
    _raw_row(ws, sampled_family=DRAW)
    assert q_cells.observe_settlement(ws, "d-1", 0.5)["matched"] is True
    first = q_cells.amend_settlement(ws, "d-1", 0.8, reason="correction")
    assert first["appended"] is True
    for _ in range(3):
        again = q_cells.amend_settlement(ws, "d-1", 0.8, reason="correction")
        assert again["appended"] is False
    view = q_cells.fold(q_cells.JSONLQStore(ws), gamma=1.0)
    (cell,) = list(view.cells.values())
    assert cell.success == pytest.approx(0.8)
    assert cell.failure == pytest.approx(0.2)
    assert view.inconsistent == 1


def test_policy_compare_excludes_inconsistent_attribution(tmp_path):
    ws = _ws(tmp_path)
    (ws / "runs" / "logs").mkdir(parents=True)
    doc = ir.record_launch(ws, "C-1", DISPATCHED, phi=0.0, propensity=0.7)
    ir.append_transition(ws, "C-1", "SUCCESS", r_settle=1.0,
                         attempt_id=str((doc or {}).get("attempt_id")))
    env = {"family": DISPATCHED,
           "candidates": {DISPATCHED: {"weight": 0.7},
                          DRAW: {"weight": 0.3}},
           "propensity": 0.7}
    (ws / "runs" / "logs" / "e2e-audit.jsonl").write_text(
        json.dumps({"event": "method_family_recorded", "claim": "C-1",
                    "detail": json.dumps({"method_family": DISPATCHED,
                                          "envelope": env})}) + "\n",
        encoding="utf-8")
    _raw_row(ws, sampled_family=DRAW)
    report = pc.compare(ws)
    assert report["skipped_family_mismatch"] == 1
    assert report["decisions"] == 0


def test_policy_compare_earlier_incoherent_dispatch_is_not_masked(tmp_path):
    """A re-dispatch appends a second q-cell row; the earlier incoherent
    dispatch must still refuse the decision for that claim."""
    ws = _ws(tmp_path)
    (ws / "runs" / "logs").mkdir(parents=True)
    doc = ir.record_launch(ws, "C-1", DISPATCHED, phi=0.0, propensity=0.7)
    ir.append_transition(ws, "C-1", "SUCCESS", r_settle=1.0,
                         attempt_id=str((doc or {}).get("attempt_id")))
    env = {"family": DISPATCHED,
           "candidates": {DISPATCHED: {"weight": 0.7},
                          DRAW: {"weight": 0.3}},
           "propensity": 0.7}
    (ws / "runs" / "logs" / "e2e-audit.jsonl").write_text(
        json.dumps({"event": "method_family_recorded", "claim": "C-1",
                    "detail": json.dumps({"method_family": DISPATCHED,
                                          "envelope": env})}) + "\n",
        encoding="utf-8")
    _raw_row(ws, sampled_family=DRAW)
    _raw_row(ws, claim="C-1")   # the later, coherent re-dispatch row
    report = pc.compare(ws)
    assert report["skipped_family_mismatch"] == 1
    assert report["decisions"] == 0


def test_reconcile_declaration_carries_round_lead(tmp_path):
    ws = _ws(tmp_path)
    for fam in ("static-decompile", "dynamic-trace"):
        q_cells.append_observation(ws, SIG, fam, None, source="dispatch",
                                   claim=f"seed-{fam}")
    d = ws / "runs" / "round-strategy"
    d.mkdir(parents=True)
    (d / "tick-0007.yaml").write_text(
        "schema: round-strategy/1\n"
        "tick: 7\n"
        "dispatch:\n"
        "  method_lead: obfuscation-peeling\n", encoding="utf-8")
    view = ss.reconcile_declaration(ws, "static-decompile")
    assert view["round_lead"] == "obfuscation-peeling"


def test_deviation_event_records_the_round_lead(tmp_path):
    hooks = ROOT / "hooks"
    if str(hooks) not in sys.path:
        sys.path.insert(0, str(hooks))
    import worker_budget_sinks as sinks

    ws = _ws(tmp_path)
    view = {"sampled_family": DRAW, "propensity": 0.4,
            "prior_source": "history", "deviates": True,
            "round_lead": "obfuscation-peeling"}
    sinks._emit_sample_deviation(ws, "C-1", DISPATCHED, view, _prompt())
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    events = [r for r in rows if r.get("action") == "sample_deviation"]
    assert len(events) == 1
    det = events[0]["detail"]
    det = json.loads(det) if isinstance(det, str) else det
    assert det["round_lead"] == "obfuscation-peeling"
    assert det["lead_override"] is True
    assert det["reason"] == REASON
