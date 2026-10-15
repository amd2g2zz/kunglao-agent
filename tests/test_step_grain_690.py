# -*- coding: utf-8 -*-
"""tests/test_step_grain_690.py — step grain: settlement at subagent
completion, the settle->update->decide sync barrier, session aggregation,
and the branch_budget hard constraint (issue #690).

The card's four pins:

  1. SubagentStop IS the settlement point — the round-closure hook closes
     the transition (runs/transitions.jsonl gains the per-step row; the
     launch stash is consumed) and lands the completion-grain
     step-record/2 row carrying claim_ref.
  2. Sync barrier — no dispatch while a prior step is unsettled (fail-open
     on a stale pending step so a crashed stop never deadlocks the loop).
  3. Steps aggregate by session — the per-tool-call step-record/1 rows of
     one session roll into ONE completion-grain step; step_id is a
     deterministic function of (session, ordinal).
  4. branch_budget is a hard constraint — a wall_s overrun lands in
     attributed-waste; a consumed retries budget blocks the next dispatch;
     dispatch_count accrues independently of promotion_attempts and is
     visible in the rank feed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import step_grain as sg  # noqa: E402
from rlvr import step_ledger as sl  # noqa: E402

from _factories import write_claims_register  # noqa: E402

TS = "2026-10-15T00:00:00Z"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [{"id": "C-5", "status": "OPEN"},
                               {"id": "C-6", "status": "OPEN"}])
    return ws


def _tool_rows(ws: Path, session: str, n: int) -> list[str]:
    """n hash-only step-record/1 rows for one session; returns call_ids."""
    ids = []
    for i in range(n):
        row = sl.build_step_row(
            session_id=session, tool="Bash",
            tool_input={"command": f"step-{i}"},
            tool_response={"stdout": "x"},
            ts=TS)
        assert sl.record_step(ws, row) is not None
        ids.append(row["call_id"])
    return ids


def _age_stash(ws: Path, claim: str, *, minutes: float) -> None:
    """Rewrite the launch stash's ts to the aged shape (the fixture does
    what time would — the stash itself is a plain json doc)."""
    p = ws / "runs" / f"dispatch-launch-{claim}.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    aged = (datetime.now(timezone.utc)
            - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    p.write_text(json.dumps({**doc, "ts": aged}), encoding="utf-8")


# ---------------------------------------------- 1. SubagentStop settles --

def test_subagent_completion_triggers_settlement(tmp_path, capsys) -> None:
    """A dispatch launch + SubagentStop closes the transition: the
    production settlement path runs from the round-closure hook (the
    append_transition production caller this issue demanded)."""
    import round_closure
    ws = _ws(tmp_path)
    launch = ir.record_launch(ws, "C-5", "static-first",
                              branch_budget={"wall_s": 3600, "retries": 2})
    assert launch is not None
    _tool_rows(ws, "sess-9", 3)
    rc = round_closure.main_with_payload(
        {"cwd": str(ws), "session_id": "sess-9",
         "transcript_path": str(ws / "transcript.jsonl")})
    capsys.readouterr()
    assert rc == 0
    rows = ir.read_transitions(ws)
    assert rows, "SubagentStop must close the step's transition"
    assert rows[-1]["dispatch_id"] == "C-5"
    assert not (ws / "runs" / "dispatch-launch-C-5.json").exists(), (
        "the settle consumes the launch stash")
    # the completion-grain step row lands with the claim_ref mapped from
    # the dispatch-launch stash (#721: via the read face)
    step2 = sl.read_step_grains(ws)
    assert len(step2) == 1
    assert step2[0]["claim_ref"] == "C-5"
    assert step2[0]["session_id"] == "sess-9"
    assert step2[0]["tool_calls"] == 3
    assert len(step2[0]["step_id"]) == 16


def test_settle_without_pending_step_is_silent(tmp_path, capsys) -> None:
    """SubagentStop also fires for non-worker subagents: with no pending
    step the settle writes nothing and never warns into the hook path."""
    import round_closure
    ws = _ws(tmp_path)
    rc = round_closure.main_with_payload(
        {"cwd": str(ws), "session_id": "sess-x",
         "transcript_path": str(ws / "t.jsonl")})
    capsys.readouterr()
    assert rc == 0
    assert ir.read_transitions(ws) == []


# ------------------------------------- 2. the sync barrier (settle first) --

def test_no_dispatch_before_prior_step_settled(tmp_path) -> None:
    """The settle->update->decide barrier: a fresh unsettled step blocks
    the next dispatch; settling clears it; a stale pending step (crashed
    stop) admits with the fail-open posture instead of deadlocking."""
    ws = _ws(tmp_path)
    ok, msg = sg.barrier_verdict(ws)
    assert ok, msg
    ir.record_launch(ws, "C-5", "static-first")
    ok, msg = sg.barrier_verdict(ws)
    assert not ok, "an unsettled step must block the next dispatch"
    assert "C-5" in msg
    settled = sg.settle_step(ws, "sess-9")
    assert settled is not None
    ok, msg = sg.barrier_verdict(ws)
    assert ok, "settle->update->decide: the barrier lifts after settle"
    # stale: the pending step outlives the TTL — fail-open with a warn
    ir.record_launch(ws, "C-6", "dynamic-second")
    _age_stash(ws, "C-6", minutes=sg.STEP_SETTLE_TTL_MINUTES + 5)
    ok, msg = sg.barrier_verdict(ws)
    assert ok, "a stale pending step admits (fail-open, never deadlock)"
    assert "stale" in msg.lower()


def test_gates_barrier_face_matches_step_grain(tmp_path) -> None:
    """The dispatch-gate wiring: worker_budget_gates.check_step_settled is
    the (ok, msg) battery face over the same verdict."""
    from worker_budget_gates import check_step_settled
    ws = _ws(tmp_path)
    paths = {"workspace": ws}
    assert check_step_settled(paths)[0] is True
    ir.record_launch(ws, "C-5", "static-first")
    ok, msg = check_step_settled(paths)
    assert ok is False and "C-5" in msg


# --------------------------------------- 3. aggregation by session id ----

def test_step_aggregates_by_session_id(tmp_path) -> None:
    """One subagent completion = one step: the per-tool-call rows of a
    session roll into ONE completion-grain aggregate; other sessions'
    rows never leak into it; step_id is deterministic in (session,
    ordinal)."""
    ws = _ws(tmp_path)
    a_ids = _tool_rows(ws, "sess-a", 3)
    _tool_rows(ws, "sess-b", 2)
    agg = sg.aggregate_session_steps(ws, "sess-a")
    assert agg["tool_calls"] == 3
    assert agg["call_ids"] == a_ids
    assert agg["first_ts"] == TS and agg["last_ts"] == TS
    empty = sg.aggregate_session_steps(ws, "sess-z")
    assert empty["tool_calls"] == 0 and empty["call_ids"] == []
    assert sg.step_id_for("sess-a", 0) == sg.step_id_for("sess-a", 0)
    assert sg.step_id_for("sess-a", 1) != sg.step_id_for("sess-a", 0)
    assert sg.step_id_for("sess-b", 0) != sg.step_id_for("sess-a", 0)


# ------------------------------------- 4. branch_budget hard constraint --

def test_branch_budget_overrun_lands_in_attributed_waste(tmp_path) -> None:
    """The act budget: a step whose wall time exceeds branch_budget.wall_s
    lands the overrun in runs/attributed-waste.jsonl — attributed to the
    claim and the step that spent it."""
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-5", "static-first",
                     branch_budget={"wall_s": 600, "retries": 2})
    _age_stash(ws, "C-5", minutes=15)   # 900s actual vs 600s budget
    _tool_rows(ws, "sess-9", 2)
    settled = sg.settle_step(ws, "sess-9")
    assert settled is not None
    waste = [json.loads(ln) for ln in
             (ws / "runs" / "attributed-waste.jsonl").read_text(
                 "utf-8").splitlines()]
    assert waste, "a wall_s overrun must land in attributed-waste"
    row = waste[-1]
    assert row["schema"] == "attributed-waste/1"
    assert row["claim_ref"] == "C-5"
    assert row["kind"] == "wall_s_overrun"
    assert row["budget_s"] == 600.0
    assert row["actual_s"] > row["budget_s"]
    assert row["waste_s"] == round(row["actual_s"] - row["budget_s"], 3)
    # within budget -> no waste row
    ir.record_launch(ws, "C-6", "fast", branch_budget={"wall_s": 86400})
    settled = sg.settle_step(ws, "sess-9")
    assert settled is not None
    assert len([json.loads(ln) for ln in
                (ws / "runs" / "attributed-waste.jsonl").read_text(
                    "utf-8").splitlines()]) == 1


def test_branch_budget_retries_blocks_the_next_dispatch(tmp_path) -> None:
    """retries is the branch act budget: once dispatch_count reaches it
    the next dispatch on the claim is REJECTED; no budget -> unconstrained
    (v1 envelope back-fill)."""
    from worker_budget_gates import check_branch_budget
    ws = _ws(tmp_path)
    paths = {"workspace": ws, "register": ws / "claim-register.yaml"}
    budget = {"wall_s": 3600, "retries": 2}
    assert check_branch_budget(paths, "C-5", budget)[0] is True
    sg.bump_dispatch_count(ws, "C-5")
    assert check_branch_budget(paths, "C-5", budget)[0] is True
    sg.bump_dispatch_count(ws, "C-5")
    ok, msg = check_branch_budget(paths, "C-5", budget)
    assert ok is False and "retries" in msg
    # absent budget: no constraint (v1 envelopes stay first-class)
    assert check_branch_budget(paths, "C-5", {})[0] is True
    # dispatch_count accrues independently of promotion_attempts
    reg = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "dispatch_count: 2" in reg
    assert "promotion_attempts" not in reg


def test_dispatch_count_visible_in_rank_feed(tmp_path) -> None:
    """The acceptance face: the accrued dispatch count rides the rank
    feeds; a claim with zero dispatches keeps the legacy feeds unchanged.
    Claims load from the register (the production path — the bumped
    counter lives there)."""
    import priority_ratio as pr
    import yaml
    ws = _ws(tmp_path)
    sg.bump_dispatch_count(ws, "C-5")
    sg.bump_dispatch_count(ws, "C-5")
    claims = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))["claims"]
    actions = pr.priority_ratio(claims, {}, pr.EvidenceView())
    by = {a.claim_id: a for a in actions}
    assert "dispatch_count" in by["C-5"].feeds
    assert "2" in by["C-5"].feeds["dispatch_count"]
    assert "dispatch_count" not in by["C-6"].feeds, (
        "absent when zero — the legacy feeds stay byte-identical")


# --------------------------------- 5. the #690 review hardening faces ----

def test_traversal_stash_identity_is_never_consumed(tmp_path) -> None:
    """#690 review CRITICAL: a stash doc is worker-writable, so its
    claim/action_type fields are an untrusted path component — a value
    like ``x/../../victim-important`` would make the settle's unlink
    (append_transition) resolve OUTSIDE runs/. The read boundary skips
    such a stash (never consumed, never guessed — the 1-F3 posture) and
    the shared sink refuses the same shape for every caller."""
    ws = _ws(tmp_path)
    victim = ws / "victim-important.json"
    victim.write_text(json.dumps({"phi": 0.5}), encoding="utf-8")
    (ws / "runs" / "dispatch-launch-x").mkdir()  # planted intermediate dir
    evil = {"schema": "dispatch-launch/1", "ts": TS,
            "claim": "x/../../victim-important",
            "action_type": "dispatch", "phi": 0.1}
    (ws / "runs" / "dispatch-launch-evil.json").write_text(
        json.dumps(evil), encoding="utf-8")
    assert sg.pending_step(ws) is None, (
        "a traversal claim is never a pending step")
    assert sg.settle_step(ws, "sess-9") is None
    assert victim.exists(), "settle must never unlink outside runs/"
    # the sink-side wall: every caller (settle, #550 acts, e2e replay)
    # is refused the same shape, for both path components
    assert ir.append_transition(
        ws, "x/../../victim-important", "completed") is None
    assert ir.record_launch(ws, "x/../../evil", "a") is None
    assert ir.append_transition(
        ws, "C-5", "completed", action_type="../evil") is None
    assert ir.record_launch(ws, "C-5", "a", action_type="/abs") is None
    assert victim.exists()
    assert ir.read_transitions(ws) == []


def test_rejected_dispatch_cancels_the_opened_step(tmp_path) -> None:
    """#690 review HIGH: a dispatch REJECTED after the approval point
    (the dispatch_gate rc=2 undo — the #623/#624 live path) never ran a
    worker, so the step _open_step opened must be cancelled: the launch
    stash is consumed (the sync barrier lifts immediately instead of
    riding out the stale TTL) and the dispatch_count bump is rolled back
    (the retries budget is not charged for a dispatch that never
    dispatched). Idempotent; foreign envelopes stay untouched."""
    from rlvr.step_grain import cancel_step_open
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-5", "static-first",
                     branch_budget={"wall_s": 600, "retries": 2})
    sg.bump_dispatch_count(ws, "C-5")
    assert sg.barrier_verdict(ws)[0] is False
    assert cancel_step_open(ws, "C-5") is True
    assert sg.barrier_verdict(ws)[0] is True, (
        "the reject-undo must lift the barrier at once")
    assert sg.dispatch_count(ws, "C-5") == 0, (
        "a never-dispatched attempt must not charge the retries budget")
    assert cancel_step_open(ws, "C-5") is False, "idempotent second call"
    # a foreign envelope (1-F3) parked at the claim's stash path is left
    # intact — cancel never deletes what it does not own
    foreign = {"schema": "other/1", "status": "PARKED",
               "claim": "C-6", "wake": "plan"}
    p = ws / "runs" / "dispatch-launch-C-6.json"
    p.write_text(json.dumps(foreign), encoding="utf-8")
    assert cancel_step_open(ws, "C-6") is False
    assert p.exists()


def test_dispatch_gate_undo_wires_the_step_cancel(tmp_path, monkeypatch) -> None:
    """#690 review HIGH wiring: dispatch_gate's rc=2 undo path cancels
    the opened step alongside the anchor undo + claim reopen — the seam
    the reviewer found untested (approve -> later REJECT -> the barrier
    froze until the stale TTL)."""
    import importlib.util
    hooks = ROOT / "hooks"
    spec = importlib.util.spec_from_file_location(
        "_dispatch_gate_for_690_undo_test", hooks / "dispatch_gate.py")
    dg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dg)
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-5", "static-first")
    sg.bump_dispatch_count(ws, "C-5")
    assert sg.barrier_verdict(ws)[0] is False
    monkeypatch.setattr(dg, "_main_inner", lambda: 2)
    dg._ATTEMPT.clear()
    dg._ATTEMPT["ws"], dg._ATTEMPT["cid"] = ws, "C-5"
    assert dg.main() == 2
    assert sg.barrier_verdict(ws)[0] is True
    assert sg.dispatch_count(ws, "C-5") == 0
