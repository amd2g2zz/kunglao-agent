# -*- coding: utf-8 -*-
"""tests/test_workguard_434.py — event-wakeup topology: the WORKGUARD face.

Issue 434 topology finding: turn-exit was liveness-only (the Stop slot
recorded a beat, never judged the DAG). The Stop hook is redefined as
WORKGUARD — on a turn-exit attempt it computes the DAG actionable set:

    actionable := claims OPEN-or-returnable, no active worker on them,
                  not PARKed, no blocking wall (budget/deadline),
                  deps satisfied

  non-empty -> BLOCK the exit + inject next-decision guidance
  empty     -> allow the exit (all PARKed/blocked/budget-walled = LEGAL SLEEP)

Anti-runaway by construction: the predicate respects PARK and walls, and
the wiring passes through on stop_hook_active (a second stop is never
re-blocked by this guard — completion_gate owns that adjudication).

EX-4 (plan prerequisite): the predicate is unit-validated here against a
rehearsal-shaped workspace fixture (PARK / wall / blocked / returned-worker
cases). The live dry-run happens at E2E acceptance, not in this suite.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _factories import write_claims_register, write_hook_state, \
    write_worker_status

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _mk_ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, claims)
    write_hook_state(ws, active_hooks=["workguard_gate"])
    return ws


def _open(cid: str, **extra) -> dict:
    return {"id": cid, "status": "OPEN", "statement": f"probe {cid}",
            **extra}


# ===========================================================================
# the pure predicate (EX-4 rehearsal-shaped fixtures)
# ===========================================================================

class TestActionableSetPredicate:
    def test_open_claim_deps_satisfied_is_actionable(self, tmp_path):
        import workguard
        ws = _mk_ws(tmp_path, [_open("C-1")])
        res = workguard.actionable_set(ws)
        assert [c["id"] for c in res["claims"]] == ["C-1"], res
        assert res["claims"][0]["why"] == "dispatchable", res
        assert res["legal_sleep"] is False

    def test_parked_only_is_legal_sleep(self, tmp_path):
        """PARK respects the external gate: suspended claims never keep the
        session awake (revival is mission_stall's explicit job)."""
        import workguard
        ws = _mk_ws(tmp_path, [
            {"id": "C-1", "status": "PARK",
             "wake_condition": "vm reachable again"}])
        res = workguard.actionable_set(ws)
        assert res["claims"] == [], res
        assert res["legal_sleep"] is True

    def test_blocked_deps_not_actionable(self, tmp_path):
        """A child whose parent is still OPEN is dependency-blocked — legal
        sleep, not runaway fuel."""
        import workguard
        ws = _mk_ws(tmp_path, [
            _open("C-1"),
            {"id": "C-2", "status": "OPEN",
             "depends_on": ["C-1"]}])
        res = workguard.actionable_set(ws)
        assert [c["id"] for c in res["claims"]] == ["C-1"], res

    def test_satisfied_parent_unblocks_child(self, tmp_path):
        import workguard
        ws = _mk_ws(tmp_path, [
            {"id": "C-1", "status": "PROVEN"},
            {"id": "C-2", "status": "OPEN", "depends_on": ["C-1"]}])
        res = workguard.actionable_set(ws)
        assert [c["id"] for c in res["claims"]] == ["C-2"], res

    def test_budget_wall_is_legal_sleep(self, tmp_path):
        """tier=HARD_PAUSE (cost gate) walls every dispatchable claim off
        the actionable set — the session may sleep."""
        import workguard
        ws = _mk_ws(tmp_path, [_open("C-1")])
        write_hook_state(ws, active_hooks=["workguard_gate"],
                         tier="HARD_PAUSE")
        res = workguard.actionable_set(ws)
        assert res["claims"] == [], res
        assert any(w["wall"] == "budget" for w in res["walls"]), res
        assert res["legal_sleep"] is True

    def test_deadline_wall_is_legal_sleep(self, tmp_path):
        """task_spec.time_budget_minutes elapsed since the heartbeat start
        = the run's deadline passed — no further work is sanctioned."""
        import workguard
        ws = _mk_ws(tmp_path, [_open("C-1")])
        (ws / "task_spec.yaml").write_text(
            "constraints:\n  time_budget_minutes: 30\n",
            encoding="utf-8")
        started = datetime.now(timezone.utc) - timedelta(minutes=31)
        (ws / "runs" / ".heartbeat.json").write_text(json.dumps(
            {"started_ts": _iso(started), "interval_min": 5}),
            encoding="utf-8")
        res = workguard.actionable_set(ws)
        assert res["claims"] == [], res
        assert any(w["wall"] == "deadline" for w in res["walls"]), res

    def test_in_progress_with_active_worker_not_actionable(self, tmp_path):
        """An in-flight claim has a worker — its wake is the dispatch return
        / completion notification, never the guard."""
        import workguard
        ws = _mk_ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
        write_worker_status(ws, "w1", "in-progress")
        res = workguard.actionable_set(ws)
        assert res["claims"] == [], res
        assert res["active_workers"] == 1, res

    def test_in_progress_zero_workers_is_returned(self, tmp_path):
        """THE returned-worker case: the claim says IN_PROGRESS but no
        worker is alive anywhere — the dispatch came back and nobody
        settled it. Actionable (settle + re-dispatch)."""
        import workguard
        ws = _mk_ws(tmp_path, [{"id": "C-3", "status": "IN_PROGRESS"}])
        write_worker_status(ws, "w1", "done")
        res = workguard.actionable_set(ws)
        assert [c["id"] for c in res["claims"]] == ["C-3"], res
        assert res["claims"][0]["why"] == "returned-worker", res

    def test_saturation_with_open_claim_is_legal_sleep(self, tmp_path):
        """All worker slots busy + one queued OPEN claim: the wake is the
        slot-freeing completion event, not the guard."""
        import workguard
        claims = [{"id": f"C-{i}", "status": "IN_PROGRESS"}
                  for i in (1, 2, 3)]
        claims.append(_open("C-4"))
        ws = _mk_ws(tmp_path, claims)
        for i in (1, 2, 3):
            write_worker_status(ws, f"w{i}", "in-progress")
        res = workguard.actionable_set(ws)
        assert res["claims"] == [], res
        assert res["free_slots"] == 0, res
        assert res["legal_sleep"] is True

    def test_exhausted_attempts_not_actionable(self, tmp_path):
        """promotion_attempts >= 3 is the dead-letter band — the claim is
        poison for dispatch purposes (mark_dead owns the terminal write)."""
        import workguard
        ws = _mk_ws(tmp_path, [_open("C-1", promotion_attempts=3)])
        res = workguard.actionable_set(ws)
        assert res["claims"] == [], res

    def test_empty_register_is_legal_sleep(self, tmp_path):
        import workguard
        ws = _mk_ws(tmp_path, [])
        res = workguard.actionable_set(ws)
        assert res["claims"] == [] and res["legal_sleep"] is True


# ===========================================================================
# the Stop-hook wiring (hooks/workguard_gate.py)
# ===========================================================================

def _payload(ws: Path, **extra) -> dict:
    return {"cwd": str(ws), "stop_hook_active": False, **extra}


class TestWorkguardGateWiring:
    def test_blocks_with_guidance_when_actionable(self, tmp_path, capsys):
        import workguard_gate
        ws = _mk_ws(tmp_path, [
            {"id": "C-3", "status": "IN_PROGRESS"},
            _open("C-9")])
        write_worker_status(ws, "w1", "done")
        rc = workguard_gate.process_event(_payload(ws))
        out = capsys.readouterr().out
        assert rc == 1, out
        decision = json.loads(out)
        assert decision["decision"] == "block"
        assert "C-3" in decision["reason"] and "C-9" in decision["reason"]
        # guidance must name the two action shapes (issue example: the
        # returned worker is settled, the open claim dispatched or parked)
        assert "settle" in decision["reason"].lower()
        assert "dispatch" in decision["reason"].lower()

    def test_legal_sleep_allows_exit_silently(self, tmp_path, capsys):
        import workguard_gate
        ws = _mk_ws(tmp_path, [
            {"id": "C-1", "status": "PARK",
             "wake_condition": "vm reachable again"}])
        rc = workguard_gate.process_event(_payload(ws))
        out = capsys.readouterr().out
        assert rc == 0
        assert out == "", f"legal sleep must pass silently, got {out!r}"

    def test_second_stop_passes_through(self, tmp_path, capsys):
        """stop_hook_active=true is Claude Code's second-stop face — the
        guard never blocks twice in a row (anti-deadlock by construction;
        the completion gate owns second-stop adjudication)."""
        import workguard_gate
        ws = _mk_ws(tmp_path, [_open("C-1")])
        rc = workguard_gate.process_event(
            _payload(ws, stop_hook_active=True))
        out = capsys.readouterr().out
        assert rc == 0 and out == ""

    def test_not_activated_passes_through(self, tmp_path, capsys):
        import workguard_gate
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        write_claims_register(ws, [_open("C-1")])
        # no .hook_state.json -> strict activation refuses to fire
        rc = workguard_gate.process_event(_payload(ws))
        out = capsys.readouterr().out
        assert rc == 0 and out == ""

    def test_no_workspace_passes_through(self, tmp_path, capsys):
        import workguard_gate
        rc = workguard_gate.process_event({"cwd": str(tmp_path)})
        out = capsys.readouterr().out
        assert rc == 0 and out == ""

    def test_block_lands_guard_fired_row(self, tmp_path, capsys):
        """Every guard FIRE is recorded — no silent gate decisions. The
        row lands in the kunglao_log event stream under action=guard_fired
        (the registered fix-as-guard fire word)."""
        import workguard_gate
        ws = _mk_ws(tmp_path, [_open("C-1")])
        workguard_gate.process_event(_payload(ws))
        capsys.readouterr()
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        assert logs, "guard fire must leave a ledger row"
        rows = [json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        fired = [r for r in rows if r.get("action") == "guard_fired"]
        assert fired, rows
        assert fired[0]["actor"] == "hook:workguard_gate"
        assert "C-1" in str(fired[0].get("detail"))

    def test_guidance_carries_strategy_sections_when_present(
            self, tmp_path, capsys):
        """The block reason appends the round-strategy sections through the
        versioned seam when the strategy object exists (absent -> the seam
        renders nothing and the guidance stays clean)."""
        import workguard_gate
        ws = _mk_ws(tmp_path, [_open("C-1")])
        (ws / "runs" / "round-strategy.json").write_text(json.dumps({
            "schema": "round-strategy/1", "round": 7,
            "sections": [{"title": "focus",
                          "body": "verify chain before new claims"}]}),
            encoding="utf-8")
        rc = workguard_gate.process_event(_payload(ws))
        out = capsys.readouterr().out
        assert rc == 1
        assert "verify chain before new claims" in json.loads(out)["reason"]
