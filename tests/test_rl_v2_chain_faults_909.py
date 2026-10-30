# -*- coding: utf-8 -*-
"""tests/test_rl_v2_chain_faults_909.py — FULL-CHAIN coherence + fault
injection (issue 909).

The battery (issue 887) proves the loop LEARNS; this suite proves the
loop is COHERENT under faults. ``chain_test_harness`` drives N laps of
the COMPLETE protocol over the real faces — select (DTS) -> assign (P⊗Q)
-> execute (flat mock worker) -> settle (draft->commit) -> credit
(returns->advantage->fold bank) -> belief (state snapshot) -> next
select — with the terminator gating every step, the one-shot watchdog
armed per rollout, and EVERY seam's receipt captured into a per-lap
record. The pins:

  ORDERING  every stage's ledger row lands AFTER its upstream's row
            (append-order asserts over the whole experience file and
            the settlement file);
  CREDIT    lap N's settled credit is VISIBLE in lap N+1's select
            receipt (exact posterior equality with the ledger
            reconstruction — the battery's visibility pattern, chained);
  BELIEF    the belief snapshot after lap N equals the reconstruction
            from lap N's ledger prefix alone (no look-ahead);
  P(s)      monotone on verified transitions across the WHOLE chain,
            each lap's delta the exact ladder arithmetic;
  FAULTS    the nine-mode matrix — each fault injects at its defined
            seam and the OBSERVED response is pinned (refuse / clamp /
            exclude / recover / cold-default / honest-empty);
  DET       two identical multi-lap runs -> identical ledgers modulo
            ts.

Mock worker only; deterministic seeds; no wall clock in any assertion.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import chain_test_harness as chain  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import q_cells  # noqa: E402
from settlement import draft_commit, per_dispatch  # noqa: E402
from state import belief, progress  # noqa: E402

SIG = chain.situation_signature(chain.CHAIN_SITUATION)
CORE_TASK = chain.CORE_TASK


@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """Default seal posture: rows pass through unsigned in this suite
    (the issue-903/issue-887 suite posture). The unsealed-row pin
    re-arms the seal locally — the wall's refusal is an ARMED posture."""
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


def _run(tmp_path, name: str = "ws", **kw: Any):
    ws = tmp_path / name
    ws.mkdir()
    return chain.run_chain(ws, **kw)


def _no_ts(value: Any) -> Any:
    """Deep ts-strip — the determinism comparator (stamps excluded,
    every other byte pinned)."""
    if isinstance(value, dict):
        return {k: _no_ts(v) for k, v in value.items() if k != "ts"}
    if isinstance(value, list):
        return [_no_ts(v) for v in value]
    return value


def _idx(rows: list[dict], pred) -> list[int]:
    return [i for i, row in enumerate(rows) if pred(row)]


def _is_action(row: dict, kind: str, rid: str | None = None) -> bool:
    if row.get("schema") != q_cells.SCHEMA_ACTION_V2 \
            or row.get("kind") != kind:
        return False
    return rid is None or str(row.get("rollout_id") or "") == rid


def _is_result(row: dict, rid: str) -> bool:
    return row.get("schema") == q_cells.SCHEMA_RESULT_V2 \
        and str(row.get("rollout_id") or "") == rid


def _belief_row(row: dict) -> bool:
    return row.get("schema") == q_cells.OBS_SCHEMA \
        and str(row.get("reason") or "") == belief.REASON_BELIEF


# ------------------------------------------------- the clean FULL chain

def test_full_chain_three_lap_ordering_and_receipts(tmp_path):
    """3 laps of the COMPLETE protocol: every seam's receipt is
    captured, and across the WHOLE experience file every stage's row
    lands AFTER its upstream's — select < assign < step result <
    terminal action < terminal return < belief, lap over lap; in the
    settlement file the drafts precede their commit marker."""
    run, ws = _run(tmp_path, name="chain", laps=3, seed=11)
    report = run["report"]
    assert [lap["lap"] for lap in report["per_lap"]] == [1, 2, 3]
    rows = q_cells.trajectory_rows(ws)
    srows = cl.read(ws, "settlement")
    beliefs = _idx(rows, _belief_row)
    assert len(beliefs) == 3
    for lap_no, lap_rec in enumerate(report["per_lap"]):
        rid = lap_rec["rollouts"][0]["rollout_id"]
        sel = _idx(rows, lambda r: _is_action(r, "select_task", rid))
        asg = _idx(rows, lambda r: _is_action(r, "assign_step", rid))
        res = [i for i in _idx(rows, lambda r: _is_result(r, rid))
               if str(rows[i].get("step_id")) != f"{rid}-terminal"]
        term_res = _idx(rows, lambda r: _is_result(r, rid)
                        and str(r.get("step_id")) == f"{rid}-terminal")
        trm = _idx(rows, lambda r, rid=rid: _is_action(r, "rollback", rid)
                   or _is_action(r, "terminate_rollout", rid))
        # every seam landed its row
        assert sel and asg and res and trm and term_res, (rid, len(rows))
        # append-order: upstream strictly before downstream (the
        # terminal return prices the WHOLE trajectory, so it lands
        # after the terminal action — the loop_sim_v3 protocol shape)
        assert sel[0] < asg[0] < res[0], (rid, sel, asg, res)
        assert res[-1] < trm[0] < term_res[0], (rid, res, trm, term_res)
        assert trm[0] < beliefs[lap_no]          # belief closes the lap
        if lap_no:                               # lap over lap
            assert beliefs[lap_no - 1] < sel[0]
        # per-seam receipts captured in the lap record
        assert lap_rec["picks"][0]["receipt"]["schema"] == "task-select/1"
        assert lap_rec["picks"][0]["row"]["schema"] \
            == q_cells.SCHEMA_ACTION_V2
        for step in lap_rec["rollouts"][0]["steps"]:
            assert step["assign"]["schema"] == "method-assign/1"
            assert step["action_row"]["row"]["schema"] \
                == q_cells.SCHEMA_ACTION_V2
            assert step["result_row"]["row"]["schema"] \
                == q_cells.SCHEMA_RESULT_V2
            assert step["draft"]["schema"] == per_dispatch.DRAFT_SCHEMA
        assert lap_rec["watchdog"]["deadline"]["schema"] \
            == "watchdog-deadline/1"
        assert lap_rec["belief"]["snapshot"]["schema"] == belief.SCHEMA
        # settlement file: this lap's drafts all precede its marker
        marker = [i for i, r in enumerate(srows)
                  if r.get("schema") == draft_commit.COMMIT_SCHEMA
                  and r.get("rollout_id") == rid]
        assert marker, rid
        drafts = [i for i, r in enumerate(srows)
                  if r.get("schema") == per_dispatch.DRAFT_SCHEMA
                  and r.get("rollout_id") == rid]
        assert max(drafts) < marker[0], (drafts, marker)
    # the belief snapshots grew with the chain (areas accumulate)
    areas = [lap["belief"]["snapshot"]["analyzed_areas"]
             for lap in report["per_lap"]]
    assert all(set(a) <= set(b) for a, b in zip(areas, areas[1:]))


def test_credit_flow_end_to_end_across_laps(tmp_path):
    """THE learning chain, end-to-end: lap N's settled credit is
    VISIBLE in lap N+1's receipts — the select receipt's posterior for
    the recurring task EXACTLY equals the incremental accumulation of
    every upstream lap's terminal return (one rollout per lap, so the
    Beta mass is (1,1) + Σ (max(r,0), max(1-r,0))), and the assign
    receipt's keyed fold cell carries exactly the run's banked TRACKED
    observations. Neither receipt can move without the upstream credit
    having landed."""
    run, ws = _run(tmp_path, name="credit", laps=3, seed=5)
    report = run["report"]
    alpha, beta = 1.0, 1.0
    moved = False
    for lap_rec in report["per_lap"]:
        sel_receipt = lap_rec["picks"][0]["receipt"]
        # EXACT: this lap's select posterior IS the accumulated
        # upstream credit chain (the receipt cannot move on its own)
        assert sel_receipt["candidates"][CORE_TASK]["alpha"] \
            == pytest.approx(alpha)
        assert sel_receipt["candidates"][CORE_TASK]["beta"] \
            == pytest.approx(beta)
        terminal_r = lap_rec["rollouts"][0].get("terminal_r_t")
        if terminal_r is None:
            continue
        moved = True
        alpha += max(terminal_r, 0.0)
        beta += max(1.0 - terminal_r, 0.0)
    assert moved, "no lap ever banked a terminal return — nothing to see"
    # the assign axis: the tracked family's keyed cell carries EXACTLY
    # the run's banked TRACKED observations (success = the credits,
    # failure = the misses, one observation per banked row)
    tracked = [st["banked_credit"] for lap in report["per_lap"]
               for st in lap["rollouts"][0]["steps"]
               if st.get("banked_credit") is not None
               and st["family"] == chain.TRACKED]
    fold_view = q_cells.fold(q_cells.default_store(ws), gamma=chain.GAMMA)
    cell = fold_view.cells.get((SIG, chain.arm_key(chain.TRACKED)))
    assert cell is not None or not tracked
    if cell is not None:
        assert cell.success == pytest.approx(sum(tracked))
        assert cell.success + cell.failure == pytest.approx(float(len(tracked)))


def test_belief_coherence_snapshot_equals_prefix_reconstruction(tmp_path):
    """The belief snapshot after lap N equals the reconstruction from
    lap N's ledger rows ALONE — the snapshot never looks ahead, and the
    captured receipt is the ledger's own function (the file-sourced
    question element rides the reconstruction as the constant it is)."""
    run, ws = _run(tmp_path, name="belief", laps=3, seed=7)
    rows = q_cells.trajectory_rows(ws)
    beliefs = _idx(rows, _belief_row)
    assert len(beliefs) == 3
    questions = belief._read_questions(ws)
    for lap_no, lap_rec in enumerate(run["report"]["per_lap"]):
        prefix_actions = [r for i, r in enumerate(rows[:beliefs[lap_no]])
                          if r.get("schema") == q_cells.SCHEMA_ACTION_V2]
        rebuilt = belief.snapshot((), (), (), prefix_actions, questions)
        assert rebuilt == lap_rec["belief"]["snapshot"], lap_no


def test_p_monotone_on_verified_transitions_whole_chain(tmp_path):
    """P(s) across the WHOLE chain: the cumulative subgoal ladder is
    non-decreasing lap over lap, each lap's delta the EXACT ladder
    arithmetic over its new subgoals (w(PROVEN) per verified dispatch,
    w(UNVERIFIED) per unverified one — a verified climb is worth
    strictly more than a cold entry), and the PROVEN count equals the
    ledger's verified dispatch count (the ladder prices the ledger,
    nothing else)."""
    run, ws = _run(tmp_path, name="ps", laps=3, seed=5)
    series = run["report"]["p_series"]
    assert len(series) == 3
    assert all(b >= a for a, b in zip(series, series[1:])), series
    w_proven = progress.status_weight("PROVEN")
    w_floor = progress.status_weight("UNVERIFIED")
    for lap_rec, before, after in zip(run["report"]["per_lap"],
                                      [0.0, *series], series):
        steps = lap_rec["rollouts"][0]["steps"]
        verified = sum(1 for st in steps if st["verified"])
        expected = (len(steps) - verified) * w_floor \
            + verified * w_proven
        assert after - before == pytest.approx(expected), lap_rec["lap"]
        if verified:
            # the verified-transition climb is strictly above the floor
            assert after - before \
                > verified * w_floor
    rows = q_cells.trajectory_rows(ws)
    ledger_verified = sum(1 for r in rows
                          if r.get("schema") == q_cells.SCHEMA_RESULT_V2
                          and r.get("verified") is True
                          and r.get("step_id") is not None
                          and "terminal" not in str(r.get("step_id")))
    harness_verified = sum(1 for lap in run["report"]["per_lap"]
                           for st in lap["rollouts"][0]["steps"]
                           if st["verified"])
    assert harness_verified == ledger_verified


# ------------------------------------------------ the fault matrix

def test_fault_worker_garbage_settlement_refuses_loop_continues(tmp_path):
    """worker_garbage at the execute seam (lap 2): the result face
    fail-closes the non-bool verdict (ValueError), NOTHING banks — no
    result row, no draft, zero credit — settlement's own spend read
    refuses the unexecuted dispatch, and the LOOP CONTINUES: lap 3's
    rows land after the fault point with full ordering."""
    run, ws = _run(tmp_path, name="garbage", laps=3, seed=5,
                   faults={"execute": "worker_garbage"})
    rec = run["report"]["per_lap"][1]["rollouts"][0]["fault"]
    assert rec["seam"] == "execute" and rec["mode"] == "worker_garbage"
    assert rec["response"] == "result-refused"
    assert "must be a bool" in rec["error"]
    rid2 = run["report"]["per_lap"][1]["rollouts"][0]["rollout_id"]
    rows = q_cells.trajectory_rows(ws)
    assert not [r for r in rows if _is_result(r, rid2)]
    # settlement refuses: no draft, and the spend read has no row
    srows = draft_commit._rows(ws)
    assert not [r for r in srows
                if r.get("rollout_id") == rid2
                and r.get("schema") == per_dispatch.DRAFT_SCHEMA]
    with pytest.raises(ValueError, match="nothing to settle"):
        per_dispatch.dispatch_spend(ws, rid2, f"{rid2}-s01")
    # zero credit banked on the faulted lap
    assert run["report"]["per_lap"][1]["credit_banked"] == 0.0
    # the loop continued: lap 3 landed a full coherent chain
    rid3 = run["report"]["per_lap"][2]["rollouts"][0]["rollout_id"]
    assert _idx(rows, lambda r: _is_action(r, "select_task", rid3))
    assert _idx(rows, lambda r: _is_result(r, rid3))


def test_fault_worker_exception_zero_credit_loop_continues(tmp_path):
    """worker_exception: the raised worker crash is captured at the
    execute seam, the rollout aborts honestly (rollback terminal), no
    result/draft/credit exists, and lap 3 runs to its own terminal."""
    run, ws = _run(tmp_path, name="exc", laps=3, seed=5,
                   faults={"execute": "worker_exception"})
    rec = run["report"]["per_lap"][1]["rollouts"][0]["fault"]
    assert rec["response"] == "worker-raise-captured"
    rid2 = run["report"]["per_lap"][1]["rollouts"][0]["rollout_id"]
    rows = q_cells.trajectory_rows(ws)
    assert not [r for r in rows if _is_result(r, rid2)]
    trm = [r for r in rows if _is_action(r, "rollback", rid2)]
    assert trm          # the abort is an audited terminal, not a gap
    assert run["report"]["per_lap"][1]["credit_banked"] == 0.0
    rid3 = run["report"]["per_lap"][2]["rollouts"][0]["rollout_id"]
    assert _idx(rows, lambda r: _is_action(r, "terminate_rollout", rid3)) \
        or _idx(rows, lambda r: _is_action(r, "rollback", rid3))


def test_fault_empty_candidates_fail_closed_raise(tmp_path):
    """empty_candidates at the select seam: the selector raises
    (fail-closed, no silent skip) and NOT ONE row lands for the
    faulted lap — the chain stops there honestly."""
    run, ws = _run(tmp_path, name="empty", laps=3, seed=5,
                   faults={"select": "empty_candidates"})
    rec = run["report"]["per_lap"][1]["fault"]
    assert rec["response"] == "raised-fail-closed"
    assert "empty" in rec["error"]
    rows = q_cells.trajectory_rows(ws)
    rid2 = "ro-core-lap2"
    assert not [r for r in rows
                if str(r.get("rollout_id") or "") == rid2]
    assert run["report"]["chain_stopped_lap"] == 2
    # lap 1 was complete; nothing fabricated after the stop
    assert len(run["report"]["per_lap"]) == 2
    before = len(rows)
    assert before > 0


def test_fault_out_of_rail_credit_clamped_and_flagged(tmp_path):
    """out_of_rail_credit at the bank seam: the boundary clamps every
    injected 2.5 into the [0, 1] rail EXACTLY (banked 1.0 — never 2.5)
    and the receipt FLAGS the clamp (banked != injected); the folded
    cells carry exactly the CLAMPED mass per family."""
    run, ws = _run(tmp_path, name="rail", laps=2, seed=5,
                   faults={"credit": "out_of_rail_credit"})
    report = run["report"]
    faulted = report["per_lap"][1]
    flags = [st["bank_receipt"] for st in faulted["rollouts"][0]["steps"]
             if st.get("bank_receipt")]
    assert flags, "the faulted bank never fired"
    for flag in flags:
        assert flag["clamped"] is True
        assert flag["injected"] == chain.OUT_OF_RAIL_CREDIT
        assert flag["banked"] == pytest.approx(1.0)
    # the folded cells carry exactly the CLAMPED mass per family
    expected: dict[str, float] = {}
    for lap_rec in report["per_lap"]:
        for st in lap_rec["rollouts"][0]["steps"]:
            if st.get("banked_credit") is None:
                continue
            key = chain.arm_key(st["family"])
            expected[key] = expected.get(key, 0.0) + st["banked_credit"]
    fold_view = q_cells.fold(q_cells.default_store(ws), gamma=chain.GAMMA)
    assert expected
    for key, total in expected.items():
        cell = fold_view.cells[(SIG, key)]
        assert cell.success == pytest.approx(total), (key, total)
    # the unclamped figure appears NOWHERE: no cell exceeds its banked
    # clamped mass
    for (row_sig, key), cell in fold_view.cells.items():
        if row_sig == SIG:
            assert cell.success <= expected.get(key, 0.0) + 1e-9


def test_fault_unsealed_and_foreign_rows_excluded_by_the_walls(tmp_path):
    """Ledger noise: an UNSEALED q-cell-action row injected raw into
    the experience file is refused by the seal wall (armed posture —
    no mass, no read), and a FOREIGN-SCHEMA row is excluded by the
    prefix wall even unarmed; the chain's ordering reads are untouched
    either way."""
    key = tmp_path / "chain.key"
    key.write_bytes(b"k" * 64)
    monkey_key = pytest.MonkeyPatch()
    monkey_key.setattr(seal, "KEY_PATH", key)
    monkey_key.setattr(seal, "_ANCHOR", {"build": None})
    try:
        run_u, ws_u = _run(tmp_path, name="unsealed", laps=3, seed=5,
                           faults={"ledger": "unsealed_row"})
        rec = run_u["report"]["per_lap"][1]["noise"]
        assert rec["mode"] == "unsealed_row"
        assert rec["observed"] == "excluded"
        rows = q_cells.trajectory_rows(ws_u)
        assert not [r for r in rows
                    if str(r.get("target") or "") == chain.NOISE_MARK]
        # raw file truth: the noise row IS on disk, the read refuses it
        raw = cl.read(ws_u, "experience")
        assert [r for r in raw if str(r.get("target") or "")
                == chain.NOISE_MARK]
        # coherence holds across the refused row: lap 3 landed rows
        rid3 = run_u["report"]["per_lap"][2]["rollouts"][0]["rollout_id"]
        rows_u = q_cells.trajectory_rows(ws_u)
        assert _idx(rows_u, lambda r: _is_action(r, "select_task", rid3))
    finally:
        monkey_key.undo()
    run_f, ws_f = _run(tmp_path, name="foreign", laps=3, seed=5,
                       faults={"ledger": "foreign_schema"})
    rec = run_f["report"]["per_lap"][1]["noise"]
    assert rec["mode"] == "foreign_schema"
    assert rec["observed"] == "excluded"
    rows = q_cells.trajectory_rows(ws_f)
    assert not [r for r in rows
                if str(r.get("target") or "") == chain.NOISE_MARK]
    rid3 = run_f["report"]["per_lap"][2]["rollouts"][0]["rollout_id"]
    sel3 = _idx(rows, lambda r: _is_action(r, "select_task", rid3))
    bel12 = _idx(rows, _belief_row)[:2]     # laps 1-2 close before lap 3
    assert sel3 and len(bel12) == 2 and bel12[-1] < sel3[0]


def test_fault_crash_mid_rollout_draft_survives_late_commit(tmp_path):
    """Crash between draft and commit (the issue-884 chain): the drafts
    SURVIVE the crash, the re-draft is IDEMPOTENT (already-drafted,
    never a second row), the LATE commit is still valid (the batch
    certifies its own drafts), and the committed aggregate is exact.
    A post-commit draft attempt is refused."""
    run, ws = _run(tmp_path, name="crash", laps=3, seed=5,
                   faults={"settle": "crash_mid_rollout"})
    lap_rec = run["report"]["per_lap"][1]
    rid2 = lap_rec["rollouts"][0]["rollout_id"]
    rec = lap_rec["rollouts"][0]["fault"]
    assert rec["response"] == "crash-simulated-pre-commit"
    # the recovery ran inside the run: every re-draft converged and the
    # late commit certified the batch
    assert [r["reason"] for r in rec["recovery"]["re_drafts"]] \
        == ["already-drafted"] * len(rec["recovery"]["re_drafts"])
    assert rec["recovery"]["late_commit"]["appended"] is True
    # drafts survived: the crash minted no second row
    drafts = draft_commit.draft_rows(ws, rid2)
    assert len(drafts) == rec["recovery"]["late_commit"]["dispatch_count"]
    # re-draft is STILL idempotent from the caller's side
    for d in drafts:
        again = draft_commit.ensure_draft(
            ws, rid2, d["dispatch_id"], float(d["spend"]), d["verdicts"])
        assert again["appended"] is False
        assert again["reason"] == "already-drafted"
    assert len(draft_commit.draft_rows(ws, rid2)) == len(drafts)
    # a second commit is refused (the marker is one-shot)
    commit = draft_commit.commit_batch(ws, rid2)
    assert commit["appended"] is False
    assert commit["reason"] == "already-committed"
    # the committed aggregate is exact
    agg = draft_commit.committed_rollout(ws, rid2)
    assert agg["committed"] is True
    assert agg["credits_sum"] \
        == pytest.approx(sum(float(d["credit"]) for d in drafts))
    # a late draft after the marker is refused
    late = draft_commit.ensure_draft(ws, rid2, f"{rid2}-late", 0.5,
                                     {"mechanical": True,
                                      "scope_verifier": True,
                                      "redteam": True})
    assert late["appended"] is False
    assert late["reason"] == "batch-already-committed"
    # the loop continued into lap 3
    assert run["report"]["per_lap"][2]["rollouts"][0]["steps"]


def test_fault_malformed_deadline_cold_default_path(tmp_path):
    """malformed_deadline at the arming seam: the terminator refuses
    the garbage rows fail-closed (ValueError), the loop re-arms through
    the documented COLD default (prior never zero, cold=True) and the
    rollout runs to its terminal under the cold watchdog."""
    run, ws = _run(tmp_path, name="deadline", laps=2, seed=5,
                   faults={"watchdog": "malformed_deadline"})
    wd = run["report"]["per_lap"][1]["watchdog"]
    assert wd["fault"]["response"] == "cold-default-rearmed"
    assert "outside the q-cell trajectory" in wd["fault"]["error"]
    assert wd["deadline"]["cold"] is True
    assert wd["deadline"]["prior"] \
        == pytest.approx(chain.terminator.COLD_FAMILY_PRIOR)
    assert wd["deadline"]["deadline_s"] > 0.0
    assert wd["checks"]          # the cold deadline was really spent
    rid2 = run["report"]["per_lap"][1]["rollouts"][0]["rollout_id"]
    rows = q_cells.trajectory_rows(ws)
    assert _idx(rows, lambda r: rid2 == str(r.get("rollout_id") or "")
                and r.get("schema") == q_cells.SCHEMA_RESULT_V2)


def test_fault_malformed_spec_honest_empty_element(tmp_path):
    """malformed_spec at the belief seam: the issue-903 mapping guard
    renders the HONEST EMPTY open-questions element (never a crash,
    never fabricated content), the snapshot still lands, and the loop
    continues into the next lap."""
    run, ws = _run(tmp_path, name="spec", laps=3, seed=5,
                   faults={"belief": "malformed_spec"})
    lap_rec = run["report"]["per_lap"][1]
    rec = lap_rec["belief"]["fault"]
    assert rec["observed"] == "honest-empty"
    snap = lap_rec["belief"]["snapshot"]
    assert snap["open_questions"] == []
    assert snap["schema"] == belief.SCHEMA
    assert snap["current_goal"] == CORE_TASK
    # the loop continued; lap 3's belief still reads the honest empty
    assert run["report"]["per_lap"][2]["belief"]["snapshot"] \
        ["open_questions"] == []


# --------------------------------------------------------- determinism

def test_determinism_two_identical_multi_lap_runs(tmp_path):
    """Same seed -> byte-identical ledgers modulo ts, identical fault
    receipts modulo ts; the seed moves the streams."""
    r1, ws1 = _run(tmp_path, name="det-1", laps=3, seed=9,
                   faults={"execute": "worker_garbage"})
    r2, ws2 = _run(tmp_path, name="det-2", laps=3, seed=9,
                   faults={"execute": "worker_garbage"})
    rows1 = [{k: v for k, v in row.items() if k != "ts"}
             for row in q_cells.trajectory_rows(ws1)]
    rows2 = [{k: v for k, v in row.items() if k != "ts"}
             for row in q_cells.trajectory_rows(ws2)]
    assert rows1 == rows2
    assert _no_ts(r1["report"]) == _no_ts(r2["report"])
    r3, _ = _run(tmp_path, name="det-3", laps=3, seed=10,
                 faults={"execute": "worker_garbage"})
    assert _no_ts(r3["report"]) != _no_ts(r1["report"])


def test_clean_chain_matches_the_battery_faces(tmp_path):
    """The harness rides the SAME faces the issue-887 battery pins: a clean
    run's settled credit, folded cell and terminal shaping agree with
    the battery's own driver reading the same ledger — the harness
    EXTENDS the battery, it does not fork it."""
    run, ws = _run(tmp_path, name="faces", laps=2, seed=5)
    settled = [float(d["credit"])
               for lap in run["report"]["per_lap"]
               for d in draft_commit.draft_rows(
                   ws, lap["rollouts"][0]["rollout_id"])]
    banked = [st["banked_credit"] for lap in run["report"]["per_lap"]
              for st in lap["rollouts"][0]["steps"]
              if st.get("banked_credit") is not None]
    assert banked == pytest.approx(settled)
    for lap_rec in run["report"]["per_lap"]:
        rid = lap_rec["rollouts"][0]["rollout_id"]
        agg = draft_commit.committed_rollout(ws, rid)
        assert agg["committed"] is True
        assert lap_rec["rollouts"][0]["terminal"] \
            == ("completed" if agg["terminal"] == "completed"
                else "rolled_back")
