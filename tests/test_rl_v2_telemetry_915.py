# -*- coding: utf-8 -*-
"""tests/test_rl_v2_telemetry_915.py — unified loop telemetry (915).

RED-first pins for the four observability axes unified on ONE rule:
**screen logging is NOT recording; only FILE logging counts.**

  1. the file-logging rule — ``emit`` lands a ``loop-telemetry/1`` row
     in the consolidated ledger's TELEMETRY family (the FILE is the
     proof — read back from ``runs/telemetry.jsonl``); the row is
     ALWAYS attempted (a telemetry layer that silently skips recording
     is the bug class this card kills);
  2. the CODE registry — a CLOSED per-seam vocabulary of dotted
     machine-sortable codes; unknown codes fail-closed (raise, never
     write); human text rides ``detail``;
  3. fail-open posture — a ledger-write failure degrades to ONE warn +
     a named refusal receipt, never raises into the caller;
  4. ``loop_summary`` — ``loop-metrics/1`` per-lap aggregates read
     deterministic from the ledger alone; an empty ledger reads honest
     zeros; the events face is a group-by over codes;
  5. ``trace`` — one rollout's full row chain (action/result/telemetry
     rows carrying its rollout_id) in append order;
  6. ``trend`` — the P variance-profile statistic delegated to #904's
     ``channel_pins.variance_profile`` over the P history;
  7. the wired seams — each seam's notable path lands its code through
     the real loop faces (settlement drafted/committed/discarded/
     refused, terminator armed/fired/early-cancel/loss-cut/covered,
     assigner assigned/widened, selector prior-moved/widened, belief
     snapshot/empty-spec, credit rail-clamped).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop_sim_v3 as v3  # noqa: E402
import loop_sim  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from settlement import draft_commit, per_dispatch  # noqa: E402
from state import belief, channel_pins, progress, telemetry  # noqa: E402


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """Deterministic seal posture: rows pass through unsigned in this
    suite (the same posture the sibling rl-v2 suites pin)."""
    from rlvr import learning_seal as seal
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


# ------------------------------------------------------------- helpers

def _file_rows(ws) -> list[dict]:
    """The FILE is the proof: parse ``runs/telemetry.jsonl`` back."""
    p = Path(ws) / "runs" / "telemetry.jsonl"
    assert p.is_file(), "no telemetry family file — screen logging is \
not recording"
    return [json.loads(line)
            for line in p.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _emitted(ws) -> list[dict]:
    return [r for r in _file_rows(ws)
            if r.get("schema") == telemetry.SCHEMA]


def _codes(ws) -> list[str]:
    return [str(r.get("event")) for r in _emitted(ws)]


def _rollout(ws, rid: str = "ro-1", situation: str = "offsets", **kw):
    """One rollout through the loop's REAL path (the seam-wiring
    driver): bootstrap -> seed ctx -> run_rollout."""
    loop_sim._bootstrap(ws)
    ctx = v3._seed_ctx(ws, seed=0, lap=1, gamma=v3.GAMMA)
    return v3.run_rollout(ws, ctx, rid=rid, task_id=kw.pop("task_id", "t-1"),
                          situation=situation, gamma=v3.GAMMA,
                          ablate_credit=False, scramble_credit=False,
                          ablate_selector=False, **kw)


_REF = "evidence/F001.md#L4-L6"


def _sub(gid: str, status: str) -> progress.Subgoal:
    return progress.Subgoal(id=gid, status=status,
                            evidence_refs=(_REF,), confidence=0.8)


# ---------------------------------------------------- 1. the file rule

def test_emit_lands_a_row_in_the_telemetry_family_file(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    receipt = telemetry.emit(ws, "terminator", "TERM_WATCHDOG_ARMED",
                             lap=1, rollout_id="ro-1",
                             detail="cold family default armed")
    assert receipt["emitted"] is True
    assert receipt["reason"] is None
    rows = _file_rows(ws)
    assert len(rows) == 1, "exactly ONE row in the FILE"
    row = rows[0]
    assert row["schema"] == "loop-telemetry/1"
    assert row["seam"] == "terminator"
    assert row["event"] == "terminator.TERM_WATCHDOG_ARMED"
    assert row["lap"] == 1
    assert row["rollout_id"] == "ro-1"
    assert row["detail"] == "cold family default armed"
    assert isinstance(row["ts"], str) and row["ts"]
    # the row also reads back through the consolidated read face
    back = cl.read(ws, "telemetry", schema_prefix="loop-telemetry")
    assert [r["event"] for r in back] == ["terminator.TERM_WATCHDOG_ARMED"]


def test_every_registry_code_is_landable(tmp_path):
    """The closed vocab is fully landable: every registered code emits
    (a code that cannot land is dead weight, never a vocabulary)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    for dotted in sorted(telemetry.CODES):
        seam, event = dotted.split(".", 1)
        receipt = telemetry.emit(ws, seam, event, lap=1)
        assert receipt["emitted"] is True, dotted
    assert len(_emitted(ws)) == len(telemetry.CODES)


def test_code_format_is_dotted_and_machine_sortable():
    pattern = re.compile(r"^[a-z][a-z_]*\.[A-Z][A-Z0-9_]*$")
    assert telemetry.CODES, "the registry is not empty"
    for dotted in telemetry.CODES:
        assert pattern.fullmatch(dotted), dotted


# --------------------------------------------------- 2. fail-closed vocab

def test_unknown_event_code_fails_closed(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ValueError):
        telemetry.emit(ws, "terminator", "TOTALLY_MADE_UP")
    with pytest.raises(ValueError):
        telemetry.emit(ws, "no-such-seam", "TERM_LOSSCUT")
    with pytest.raises(ValueError):
        telemetry.emit(ws, "terminator", "term_losscut")  # case-exact
    assert not (ws / "runs" / "telemetry.jsonl").exists(), \
        "an unknown code never writes a row"


# ------------------------------------------------------- 3. fail-open

def test_emit_fail_open_on_ledger_write_failure(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()

    def boom(*_a, **_kw):
        raise OSError("disk gone")

    monkeypatch.setattr(telemetry._cl, "append", boom)
    receipt = telemetry.emit(ws, "settlement", "SETTLE_COMMITTED",
                             rollout_id="ro-9")
    assert receipt["emitted"] is False
    assert receipt["reason"] == "error:OSError", "the refusal is NAMED"
    assert receipt["rollout_id"] == "ro-9"


def test_emit_named_refusal_when_append_returns_false(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(telemetry._cl, "append", lambda *a, **k: False)
    receipt = telemetry.emit(ws, "belief", "BELIEF_SNAPSHOT")
    assert receipt["emitted"] is False
    assert receipt["reason"] == "write-failed"


def test_emit_still_attempts_the_row_after_a_failure(tmp_path, monkeypatch):
    """The row is ALWAYS attempted: a refused write must not put the
    face into a skip-everything state — the next emit tries again."""
    ws = tmp_path / "ws"
    ws.mkdir()
    real = telemetry._cl.append
    state = {"n": 0}

    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise OSError("transient")
        return real(*a, **k)

    monkeypatch.setattr(telemetry._cl, "append", flaky)
    assert telemetry.emit(ws, "credit", "CREDIT_V_CLAMPED")["emitted"] \
        is False
    assert telemetry.emit(ws, "credit", "CREDIT_V_CLAMPED")["emitted"] \
        is True
    assert len(_emitted(ws)) == 1


# ---------------------------------------------------- 4. loop_summary

def test_empty_ledger_reads_honest_zeros(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    s = telemetry.loop_summary(ws)
    assert s["schema"] == "loop-metrics/1"
    assert s["rollouts"] == 0
    assert s["dispatches"] == 0
    assert s["verified_steps"] == 0
    assert s["rollback_count"] == 0
    assert s["stagnation_count"] == 0
    assert s["delta_series"] == []
    assert s["p_series"] == []
    assert s["cost_total"] == 0.0
    assert s["events"] == {}
    assert s["credit"] == {"drafted": 0.0, "committed": 0.0,
                           "discarded": 0}


def test_loop_summary_is_deterministic_from_the_ledger_alone(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    loop_sim._bootstrap(ws)
    v3.settle_one_dispatch(ws, "offsets", v3.TRACKED, rollout="ro-d")
    telemetry.emit(ws, "stagnation", "STAG_ADVICE", lap=1,
                   rollout_id="ro-d")
    first = telemetry.loop_summary(ws)
    second = telemetry.loop_summary(ws)
    assert first == second, "no clock, no sampling — pure ledger read"
    assert "ts" not in first


def test_loop_summary_aggregates_the_group_by_over_codes(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    loop_sim._bootstrap(ws)
    v3.settle_one_dispatch(ws, "offsets", v3.TRACKED, rollout="ro-a")
    telemetry.emit(ws, "stagnation", "STAG_ADVICE", lap=1)
    telemetry.emit(ws, "stagnation", "STAG_ADVICE", lap=2)
    s = telemetry.loop_summary(ws)
    assert s["rollouts"] >= 1
    assert s["dispatches"] >= 1
    assert s["verified_steps"] >= 1
    assert s["credit"]["drafted"] > 0.0
    assert s["credit"]["committed"] > 0.0
    assert s["cost_total"] > 0.0
    assert s["stagnation_count"] == 2
    # the events face is the group-by: file counts are the truth
    from collections import Counter
    file_counts = Counter(_codes(ws))
    assert s["events"] == dict(file_counts)
    assert s["events"]["stagnation.STAG_ADVICE"] == 2


def test_loop_summary_reads_the_p_series_from_state_rows(tmp_path):
    """The ΔP series comes from the state face's own transition rows
    (progress.record_transition) — the ledger is the only source."""
    ws = tmp_path / "ws"
    ws.mkdir()
    before = [_sub("g1", "UNVERIFIED")]
    after = [_sub("g1", "VERIFIED")]
    progress.record_transition(ws, before=before, after=after)
    progress.record_transition(ws, before=after, after=after)
    s = telemetry.loop_summary(ws)
    d = progress.delta_P(before, after)
    assert s["delta_series"] == [d, 0.0]
    assert s["p_series"] == [round(d, 6), round(d, 6)]


# --------------------------------------------------------- 5. trace

def test_trace_returns_the_rollout_chain_in_append_order(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-t",
                          step_id="ro-t-s01", target="f",
                          params={"method_family": "f"},
                          ts="2026-01-01T00:00:01Z")
    q_cells.append_result(ws, rollout_id="ro-t", step_id="ro-t-s01",
                          verified=True, cost=0.1,
                          ts="2026-01-01T00:00:02Z")
    telemetry.emit(ws, "terminator", "TERM_WATCHDOG_ARMED", lap=1,
                   rollout_id="ro-t")
    q_cells.append_action(ws, kind="rollback", rollout_id="ro-other",
                          target="x", ts="2026-01-01T00:00:03Z")
    chain = telemetry.trace(ws, "ro-t")
    stamps = [r.get("schema") for r in chain]
    assert stamps == ["q-cell-action/1", "q-cell-result/1",
                      "loop-telemetry/1"]
    assert all(str(r.get("rollout_id")) == "ro-t" for r in chain)
    # the foreign rollout's row never leaks in
    assert len(chain) == 3
    ts_list = [r["ts"] for r in chain]
    assert ts_list == sorted(ts_list), "append order on the chain"


def test_trace_unknown_rollout_reads_empty(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    telemetry.emit(ws, "belief", "BELIEF_SNAPSHOT", rollout_id="ro-x")
    assert telemetry.trace(ws, "ro-absent") == []


def test_trace_refuses_blank_rollout_id(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(ValueError):
        telemetry.trace(ws, "  ")


# ---------------------------------------------------------- 6. trend

def test_trend_delegates_the_variance_statistic(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    before = [_sub("g1", "UNVERIFIED")]
    mid = [_sub("g1", "VERIFIED"), _sub("g2", "UNVERIFIED")]
    top = [_sub("g1", "VERIFIED"), _sub("g2", "PROVEN")]
    progress.record_transition(ws, before=before, after=mid)
    progress.record_transition(ws, before=mid, after=top)
    s = telemetry.loop_summary(ws)
    t = telemetry.trend(ws)
    assert t["schema"] == "loop-trend/1"
    assert t["points"] == len(s["p_series"])
    assert t["profile"] == channel_pins.variance_profile(s["p_series"])
    assert t["dark_room_flag"] \
        == t["profile"]["dark_room_flag"]


def test_trend_on_an_empty_ledger_is_honest(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    t = telemetry.trend(ws)
    assert t["points"] == 0
    assert t["profile"] is None
    assert t["dark_room_flag"] is False


# ------------------------------------- 7. the wired seams (per-seam pin)

def test_settlement_seam_lands_drafted_and_committed(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    v3.settle_one_dispatch(ws, "offsets", v3.TRACKED, rollout="ro-s")
    codes = _codes(ws)
    assert "settlement.SETTLE_DRAFTED" in codes
    assert "settlement.SETTLE_COMMITTED" in codes
    rid_rows = [r for r in _emitted(ws)
                if r.get("event") == "settlement.SETTLE_DRAFTED"]
    assert all(r["rollout_id"] == "ro-s" for r in rid_rows)


def test_settlement_discard_and_refusal_land(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    loop_sim._bootstrap(ws)
    ctx = v3._seed_ctx(ws, seed=0, lap=1, gamma=v3.GAMMA)
    sig = v3.situation_signature("offsets")
    disp = v3._dispatch(ws, ctx, "ro-dsc", sig, "offsets", 1,
                        candidates=[v3.TRACKED])
    assert disp["draft_appended"] is True
    out = draft_commit.discard_drafts(ws, "ro-dsc", reason="the card")
    assert out["appended"] is True
    assert "settlement.SETTLE_DISCARDED" in _codes(ws)
    # a re-draft of the same identity is refused -> the refusal lands
    priced = per_dispatch.price_dispatch("ro-dsc", disp["step_id"],
                                         disp["cost"],
                                         {"mechanical": True,
                                          "scope_verifier": True,
                                          "redteam": True})
    refusal = draft_commit.land_draft(ws, priced)
    assert refusal["appended"] is False
    assert refusal["reason"] == "already-drafted"
    assert "settlement.SETTLE_REFUSED" in _codes(ws)


def test_terminator_seam_lands_armed_covered_and_cancelled(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _rollout(ws, rid="ro-ok", pinned_family=v3.TRACKED)
    codes = _codes(ws)
    assert "terminator.TERM_WATCHDOG_ARMED" in codes
    assert "terminator.TERM_QUESTION_COVERED" in codes
    assert "terminator.TERM_WATCHDOG_CANCELLED" in codes


def test_terminator_watchdog_fired_lands(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(v3, "PER_DISPATCH_BUDGET_S", 1e-09)
    monkeypatch.setattr(v3, "_worker_execute",
                        lambda s, f, p: {"verified": False, "tokens": 100,
                                         "seconds": 0.5})
    run = _rollout(ws, rid="ro-late", pinned_family=v3.TRACKED)
    assert run["terminal"] == "rolled_back"
    assert "terminator.TERM_WATCHDOG_FIRED" in _codes(ws)


def test_terminator_losscut_lands(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(v3, "_worker_execute",
                        lambda s, f, p: {"verified": False, "tokens": 100,
                                         "seconds": 0.5})
    run = _rollout(ws, rid="ro-dead", pinned_family=v3.TRACKED)
    assert run["terminal_rule"] == "loss_cut"
    assert "terminator.TERM_LOSSCUT" in _codes(ws)


def test_assigner_seam_lands_assigned_and_widened(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    _rollout(ws, rid="ro-as")   # default candidates = the FULL family set
    codes = _codes(ws)
    assert "assigner.ASSIGN_ASSIGNED" in codes
    assert "assigner.ASSIGN_WIDENED" in codes


def test_credit_clamp_code_is_telemetry_visible(tmp_path):
    """The out-of-rail credit (the #909 carried gap's sibling): the
    boundary clamps; the clamp lands a row the metrics count."""
    ws = tmp_path / "ws"
    ws.mkdir()
    loop_sim._bootstrap(ws)
    ctx = v3._seed_ctx(ws, seed=0, lap=1, gamma=v3.GAMMA)
    row = v3._bank_settled_credit(ws, ctx, v3.situation_signature("offsets"),
                                  v3.TRACKED, 2.5, claim="t-1",
                                  dispatch_id="d-1", scramble=False)
    banked = float(row["row"]["credit"])
    assert banked == 1.0, "the rail clamp held"
    assert "credit.CREDIT_V_CLAMPED" in _codes(ws)
    assert telemetry.loop_summary(ws)["events"][
        "credit.CREDIT_V_CLAMPED"] == 1


def test_belief_seam_lands_snapshot_and_empty_spec(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    empty = belief.snapshot((), (), (), (), ())
    belief.record_belief(ws, empty)
    assert "belief.BELIEF_EMPTY_SPEC" in _codes(ws)
    full = dict(empty)
    full["confirmed_facts"] = [{"id": "F001", "status": "VERIFIED"}]
    belief.record_belief(ws, full)
    assert "belief.BELIEF_SNAPSHOT" in _codes(ws)


def test_selector_seam_lands_prior_move_and_widening_in_the_loop(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    v3.run_v3_loop(ws, laps=2, seed=0)
    codes = _codes(ws)
    assert "selector.SELECT_PRIOR_MOVED" in codes
    assert "selector.SELECT_CANDIDATES_WIDENED" in codes
    moved = [r for r in _emitted(ws)
             if r.get("event") == "selector.SELECT_PRIOR_MOVED"]
    assert any(r.get("lap") == 2 for r in moved), \
        "the prior moves AT the lap (batch) boundary"


def test_loop_report_per_lap_keeps_one_row_per_lap(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    run = v3.run_v3_loop(ws, laps=2, seed=0)
    assert [lap["lap"] for lap in run["report"]["per_lap"]] == [1, 2], \
        "exactly one per_lap row per lap — the telemetry insert must not \
re-append the lap record"


def test_assign_telemetry_follows_the_durable_row(tmp_path, monkeypatch):
    """The assign emits sit AFTER ``q_cells.append_action``: when the
    ledger row never lands, the telemetry must not describe a phantom
    assignment."""
    ws = tmp_path / "ws"
    ws.mkdir()

    def _boom(*a, **k):
        raise ValueError("append_action unavailable")

    monkeypatch.setattr(v3.q_cells, "append_action", _boom)
    with pytest.raises(ValueError, match="append_action unavailable"):
        v3.settle_one_dispatch(ws, "offsets", v3.TRACKED,
                               rollout="ro-phantom")
    tel = Path(ws) / "runs" / "telemetry.jsonl"
    assert not tel.is_file() or "assigner.ASSIGN_ASSIGNED" not in _codes(ws), \
        "a failed ledger append must not leave an assignment receipt behind"


def test_stagnation_code_counts_through_the_metrics(tmp_path):
    """STAG_ADVICE is registry-wired; the advisory receipt's landing is
    the caller's standard path — the metrics count it (the fault-matrix
    posture: the corruption/advisory event is telemetry-visible)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    telemetry.emit(ws, "stagnation", "STAG_ADVICE", lap=1,
                   rollout_id="ro-st", detail="2 flat segments")
    telemetry.emit(ws, "selector", "SELECT_POSTERIOR_CORRUPTED", lap=1,
                   detail="schema-valid garbage value in the read")
    s = telemetry.loop_summary(ws)
    assert s["stagnation_count"] == 1
    assert s["events"]["selector.SELECT_POSTERIOR_CORRUPTED"] == 1


def test_wiring_changed_no_face_return_semantics(tmp_path):
    """Additive rows only: the wired faces' receipts read exactly as
    the pre-#915 contracts pin them."""
    ws = tmp_path / "ws"
    ws.mkdir()
    out = v3.settle_one_dispatch(ws, "offsets", v3.TRACKED, rollout="ro-c")
    assert out["step_r_t"] == 1.0
    assert out["credit"] == pytest.approx(1.0)
    assert out["committed"]["committed"] is True
    # Σ(draft credits) + the terminal bonus (the rollout_agg contract)
    assert out["committed"]["total_credit"] == pytest.approx(2.0)
