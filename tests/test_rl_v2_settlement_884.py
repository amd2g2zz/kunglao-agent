# -*- coding: utf-8 -*-
"""tests/test_rl_v2_settlement_884.py — per-dispatch settlement (#884).

RED-first pins for the superseding settlement faces (the live
``scripts/rlvr/episode_settle.py`` cumulative-spend booking is replaced
by the #886 removal card; these faces pin the new semantics):

  1. per-dispatch rows book each dispatch's OWN spend — two dispatches
     with different costs each carry their own figure, never cumulative;
  2. the three verification-layer verdicts ride the row as DATA (the
     settlement records them verbatim, never re-litigates them);
  3. the priced credit is the conjunctive three-layer gate;
  4. the draft lands and an idempotent re-draft of the same
     (rollout_id, dispatch identity) is refused — no double-draft;
  5. the commit marker flips the batch into the committed view; the
     committed view joins drafts by batch_id at read time;
  6. rollback = no commit → the committed view stays honestly empty;
  7. the explicit discard marker is audited and blocks later commits;
  8. rollout aggregation = Σ(per-dispatch credits) + the terminal
     adjustment (+bonus completed / −bonus rolled_back, the
     credit/returns TERMINALS vocabulary);
  9. crash re-compute: drafts are derivable from the trajectory ledger
     (spend from the result rows) and a re-draft is idempotent;
 10. fail-closed reject pins.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import consolidated_ledger as _cl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from settlement import draft_commit, per_dispatch, rollout_agg  # noqa: E402

ALL_PASS = {"mechanical": True, "scope_verifier": True, "redteam": True}
BONUS = 2.0


def _verdicts(**overrides: bool) -> dict[str, bool]:
    out = dict(ALL_PASS)
    out.update(overrides)
    return out


# --------------------------------------------- per-dispatch pricing face

def test_per_dispatch_rows_book_own_spend_never_cumulative():
    first = per_dispatch.price_dispatch("ro-1", "d-1", 0.2, ALL_PASS)
    second = per_dispatch.price_dispatch("ro-1", "d-2", 1.5, ALL_PASS)
    assert first["spend"] == pytest.approx(0.2)
    assert second["spend"] == pytest.approx(1.5)
    assert second["spend"] != pytest.approx(0.2 + 1.5)


def test_three_verdicts_ride_the_row_verbatim():
    v = _verdicts(redteam=False)
    row = per_dispatch.price_dispatch("ro-1", "d-1", 0.5, v)
    assert row["verdicts"] == v


def test_priced_credit_is_the_conjunctive_three_layer_gate():
    assert per_dispatch.price_dispatch(
        "ro-1", "d-1", 0.5, ALL_PASS)["credit"] == pytest.approx(1.0)
    for failed in ("mechanical", "scope_verifier", "redteam"):
        row = per_dispatch.price_dispatch(
            "ro-1", "d-1", 0.5, _verdicts(**{failed: False}))
        assert row["credit"] == pytest.approx(0.0)


def test_batch_id_deterministic_and_stable_across_dispatches():
    assert (per_dispatch.batch_id("ro-1")
            == per_dispatch.batch_id("ro-1"))
    assert per_dispatch.batch_id("ro-1") != per_dispatch.batch_id("ro-2")
    first = per_dispatch.price_dispatch("ro-1", "d-1", 0.2, ALL_PASS)
    second = per_dispatch.price_dispatch("ro-1", "d-2", 1.5, ALL_PASS)
    assert first["batch_id"] == second["batch_id"]


# ------------------------------------------------ draft/commit two-phase

def test_draft_lands_in_settlement_family_and_redraft_refused(tmp_path):
    ws = tmp_path / "ws"
    priced = per_dispatch.price_dispatch("ro-1", "d-1", 0.4, ALL_PASS)
    first = draft_commit.land_draft(ws, priced)
    assert first["appended"] is True
    again = draft_commit.land_draft(ws, priced)
    assert again["appended"] is False
    assert again["reason"] == "already-drafted"
    drafts = _cl.read(ws, "settlement", schema_prefix="settlement-draft")
    assert len(drafts) == 1
    assert drafts[0]["schema"] == "settlement-draft/1"
    assert drafts[0]["rollout_id"] == "ro-1"


def test_ensure_draft_is_the_crash_recovery_entry(tmp_path):
    ws = tmp_path / "ws"
    landed = draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    assert landed["appended"] is True
    recovered = draft_commit.ensure_draft(
        ws, "ro-1", "d-1", 0.4, ALL_PASS)
    assert recovered["appended"] is False
    assert recovered["reason"] == "already-drafted"


def test_commit_marker_flips_batch_into_committed_view(tmp_path):
    ws = tmp_path / "ws"
    for did, spend in (("d-1", 0.2), ("d-2", 1.5)):
        draft_commit.ensure_draft(ws, "ro-1", did, spend, ALL_PASS)
    q_cells.append_action(ws, kind="terminate_rollout",
                          rollout_id="ro-1", target="C-1")
    before = draft_commit.committed_rollout(ws, "ro-1")
    assert before["committed"] is False
    assert before["total_credit"] == pytest.approx(0.0)
    marker = draft_commit.commit_batch(ws, "ro-1")
    assert marker["appended"] is True
    assert marker["total_credit"] == pytest.approx(2.0)
    view = draft_commit.committed_rollout(ws, "ro-1", terminal_bonus=BONUS)
    assert view["committed"] is True
    assert view["terminal"] == "completed"
    assert view["credits_sum"] == pytest.approx(2.0)
    assert view["total_credit"] == pytest.approx(2.0 + BONUS)
    assert view["dispatch_count"] == 2


def test_commit_rows_live_in_the_settlement_family_file(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    draft_commit.commit_batch(ws, "ro-1")
    markers = _cl.read(ws, "settlement",
                       schema_prefix="settlement-commit")
    assert len(markers) == 1
    assert markers[0]["schema"] == "settlement-commit/1"
    assert markers[0]["rollout_id"] == "ro-1"
    assert (Path(ws) / "runs" / "settlement.jsonl").is_file()


def test_committed_view_joins_by_batch_and_isolates_rollouts(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-A", "d-1", 0.2, ALL_PASS)
    draft_commit.ensure_draft(ws, "ro-B", "d-1", 0.2, ALL_PASS)
    q_cells.append_action(ws, kind="terminate_rollout",
                          rollout_id="ro-A", target="C-1")
    q_cells.append_action(ws, kind="terminate_rollout",
                          rollout_id="ro-B", target="C-1")
    draft_commit.commit_batch(ws, "ro-A")
    committed = draft_commit.committed_rollout(ws, "ro-A")
    assert committed["committed"] is True
    uncommitted = draft_commit.committed_rollout(ws, "ro-B")
    assert uncommitted["committed"] is False
    assert uncommitted["terminal"] is None


def test_double_commit_refused_single_marker(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    assert draft_commit.commit_batch(ws, "ro-1")["appended"] is True
    second = draft_commit.commit_batch(ws, "ro-1")
    assert second["appended"] is False
    assert second["reason"] == "already-committed"
    markers = _cl.read(ws, "settlement",
                       schema_prefix="settlement-commit")
    assert len(markers) == 1


# -------------------------------------------------------- rollback faces

def test_rollback_no_commit_keeps_committed_view_empty(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    view = draft_commit.committed_rollout(ws, "ro-1")
    assert view["committed"] is False
    assert view["total_credit"] == pytest.approx(0.0)
    assert view["credits_sum"] == pytest.approx(0.0)


def test_discard_marker_audited_and_blocks_commit(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    out = draft_commit.discard_drafts(ws, "ro-1", reason="rolled_back")
    assert out["appended"] is True
    markers = _cl.read(ws, "settlement",
                       schema_prefix="settlement-discard")
    assert len(markers) == 1
    assert markers[0]["schema"] == "settlement-discard/1"
    assert markers[0]["reason"] == "rolled_back"
    again = draft_commit.discard_drafts(ws, "ro-1")
    assert again["appended"] is False
    assert again["reason"] == "already-discarded"
    late = draft_commit.commit_batch(ws, "ro-1")
    assert late["appended"] is False
    assert late["reason"] == "batch-discarded"
    # the committed view stays honestly empty after a discard
    view = draft_commit.committed_rollout(ws, "ro-1")
    assert view["committed"] is False
    # staging into a DEAD batch is refused (the sealed audit holds)
    priced = per_dispatch.price_dispatch("ro-1", "d-late", 0.2, ALL_PASS)
    dead = draft_commit.land_draft(ws, priced)
    assert dead["appended"] is False
    assert dead["reason"] == "batch-discarded"


def test_rolled_back_commit_prices_negative_terminal(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    q_cells.append_action(ws, kind="rollback",
                          rollout_id="ro-1", target="C-1")
    draft_commit.commit_batch(ws, "ro-1")
    view = draft_commit.committed_rollout(ws, "ro-1", terminal_bonus=BONUS)
    assert view["terminal"] == "rolled_back"
    assert view["terminal_adjustment"] == pytest.approx(-BONUS)
    assert view["total_credit"] == pytest.approx(1.0 - BONUS)


def test_land_draft_after_commit_is_refused_not_silently_joined(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    q_cells.append_action(ws, kind="terminate_rollout",
                          rollout_id="ro-1", target="C-1")
    draft_commit.commit_batch(ws, "ro-1")
    late = draft_commit.ensure_draft(ws, "ro-1", "d-2", 0.9, ALL_PASS)
    assert late["appended"] is False
    assert late["reason"] == "batch-already-committed"
    view = draft_commit.committed_rollout(ws, "ro-1")
    assert view["dispatch_count"] == 1


# ------------------------------------------------------ rollout agg face

def test_rollout_aggregation_is_sum_plus_terminal_adjustment():
    rows = [per_dispatch.price_dispatch("ro-1", f"d-{i}", 0.1 * i, ALL_PASS)
            for i in (1, 2, 3)]
    done = rollout_agg.aggregate(rows, terminal="completed",
                                 terminal_bonus=BONUS)
    assert done["credits_sum"] == pytest.approx(3.0)
    assert done["terminal_adjustment"] == pytest.approx(BONUS)
    assert done["total_credit"] == pytest.approx(3.0 + BONUS)
    back = rollout_agg.aggregate(rows, terminal="rolled_back",
                                 terminal_bonus=BONUS)
    assert back["total_credit"] == pytest.approx(3.0 - BONUS)
    assert rollout_agg.TERMINALS == ("completed", "rolled_back")


def test_rollout_aggregation_spend_is_the_rows_own_sum():
    rows = [per_dispatch.price_dispatch("ro-1", f"d-{i}", 0.2 * i, ALL_PASS)
            for i in (1, 2)]
    out = rollout_agg.aggregate(rows, terminal="completed",
                                terminal_bonus=0.0)
    assert out["spend"] == pytest.approx(0.2 + 0.4)


# ---------------------------------------------------- crash re-compute

def test_crash_recompute_derives_drafts_from_trajectory_rows(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_result(ws, rollout_id="ro-1", step_id="d-1",
                          r_t=None, verified=True, cost=0.7)
    spend = per_dispatch.dispatch_spend(ws, "ro-1", "d-1")
    assert spend == pytest.approx(0.7)
    pre_crash = per_dispatch.price_dispatch("ro-1", "d-1", spend, ALL_PASS)
    draft_commit.land_draft(ws, pre_crash)
    # ... crash ... the ledger survives; the re-derivation replays it
    spend2 = per_dispatch.dispatch_spend(ws, "ro-1", "d-1")
    assert spend2 == pytest.approx(spend)
    rederived = per_dispatch.price_dispatch("ro-1", "d-1", spend2, ALL_PASS)
    assert rederived["batch_id"] == pre_crash["batch_id"]
    assert rederived["credit"] == pre_crash["credit"]
    assert rederived["spend"] == pre_crash["spend"]
    assert rederived["verdicts"] == pre_crash["verdicts"]
    retry = draft_commit.land_draft(ws, rederived)
    assert retry["appended"] is False
    assert retry["reason"] == "already-drafted"


# ------------------------------------------------------- reject pins

def test_reject_pins_fail_closed():
    with pytest.raises(ValueError):
        per_dispatch.price_dispatch("", "d-1", 0.1, ALL_PASS)
    with pytest.raises(ValueError):
        per_dispatch.price_dispatch("ro-1", " ", 0.1, ALL_PASS)
    with pytest.raises(ValueError):
        per_dispatch.price_dispatch("ro-1", "d-1", -0.1, ALL_PASS)
    with pytest.raises(ValueError):
        per_dispatch.price_dispatch("ro-1", "d-1", float("nan"), ALL_PASS)
    with pytest.raises(ValueError):
        per_dispatch.price_dispatch("ro-1", "d-1", 0.1,
                                    {"mechanical": True, "redteam": True})
    with pytest.raises(ValueError):
        per_dispatch.price_dispatch(
            "ro-1", "d-1", 0.1,
            {"mechanical": True, "scope_verifier": True, "redteam": True,
             "extra": True})
    with pytest.raises(ValueError):
        per_dispatch.price_dispatch(
            "ro-1", "d-1", 0.1,
            {"mechanical": 1, "scope_verifier": True, "redteam": True})


def test_land_draft_rejects_tampered_batch_id(tmp_path):
    ws = tmp_path / "ws"
    priced = per_dispatch.price_dispatch("ro-1", "d-1", 0.4, ALL_PASS)
    tampered = dict(priced, batch_id=per_dispatch.batch_id("ro-OTHER"))
    with pytest.raises(ValueError):
        draft_commit.land_draft(ws, tampered)


def test_aggregate_reject_pins():
    rows = [per_dispatch.price_dispatch("ro-1", "d-1", 0.4, ALL_PASS)]
    with pytest.raises(ValueError):
        rollout_agg.aggregate([], terminal="completed", terminal_bonus=1.0)
    with pytest.raises(ValueError):
        rollout_agg.aggregate([{"schema": "settlement-draft/1",
                                "credit": "x", "spend": 0.1}],
                              terminal="completed", terminal_bonus=1.0)
    with pytest.raises(ValueError):
        rollout_agg.aggregate(rows, terminal="meh", terminal_bonus=1.0)
    with pytest.raises(ValueError):
        rollout_agg.aggregate(rows, terminal="completed",
                              terminal_bonus=-1.0)
    with pytest.raises(ValueError):
        rollout_agg.aggregate(rows, terminal="completed",
                              terminal_bonus=float("nan"))
    with pytest.raises(ValueError):
        rollout_agg.aggregate([{"schema": "q-cell-result/1"}],
                              terminal="completed", terminal_bonus=1.0)


def test_committed_rollout_needs_a_terminal_action(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    draft_commit.commit_batch(ws, "ro-1")
    with pytest.raises(ValueError):
        draft_commit.committed_rollout(ws, "ro-1")


def test_read_face_rejects_post_commit_draft_garbage(tmp_path):
    ws = tmp_path / "ws"
    draft_commit.ensure_draft(ws, "ro-1", "d-1", 0.4, ALL_PASS)
    draft_commit.commit_batch(ws, "ro-1")
    # a rogue writer slips a draft in AFTER the marker — the committed
    # view must refuse to decide on the tampered stream
    rogue = per_dispatch.price_dispatch("ro-1", "d-9", 9.9, ALL_PASS)
    assert _cl.append(ws, "settlement", rogue) is True
    with pytest.raises(ValueError):
        draft_commit.committed_rollout(ws, "ro-1")
