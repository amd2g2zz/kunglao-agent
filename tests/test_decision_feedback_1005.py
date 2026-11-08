# -*- coding: utf-8 -*-
"""Dispatch-gate REJECT feedback into the decision machine (issue-1005, S8 face).

Pins the closed loop between the two faces of the dispatch seam:

  - a dispatch the gate REJECTS (rc=2, any reason family) lands exactly
    ONE ``dispatch-reject/1`` row into the unified experience ledger,
    carrying ``claim_ref`` + the gate reason + the identity ``ts`` with
    ``action_type: "dispatch"`` and ``o.status: "rejected"`` (the house
    transition-row vocabulary, mirrored — the row shape is identical for
    every reject reason: ONE seam, not per-reason copies);
  - ``convergence_check.decide()`` consumes those rows (pure read) and
    CHANGES its decision: a fresh reject is a PARK backoff (never the
    DISPATCH_VERIFIER verdict whose dispatch the gate just refused);
    repeated rejects of the SAME claim for the SAME reason reaching
    ``REJECT_RETRY_MAX`` (pinned at 3) go terminal — the BLOCKED verdict
    whose action carries the ATTEMPTED_EXHAUSTED disposition word from
    the seven-word vocabulary (consumed, never extended);
  - the stuck-state guard: partial facts, zero open claims, zero active
    workers and a claim at the retry max replay to a terminal decision
    within four decide() calls — the ledger tail shows the reject rows
    and the terminal decision, never a fourth DISPATCH_VERIFIER;
  - fail-open on both faces: a broken ledger never raises into decide()
    or the gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import convergence_check as cc  # noqa: E402
import rlvr.consolidated_ledger as consolidated_ledger  # noqa: E402
import rlvr.dispatch_reject as dispatch_reject  # noqa: E402
import rlvr.disposition as disposition  # noqa: E402
import rlvr.strategic_action as strategic_action  # noqa: E402

TS = "2026-11-05T12:00:00Z"
STAMP = "dispatch-reject/1"
EXPERIENCE_REL = Path("runs") / "experience.jsonl"
ENVELOPE = ('{"kunglao_dispatch": {"version": 1, "claim": "C-1",'
            ' "tier": 1, "tools": [%s]}}\n')


# ---------- workspace + gate harness (the stuck shape) ----------

def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")


def _stuck_ws(root: Path, *, status: str = "IN_PROGRESS",
              with_fact: bool = True) -> Path:
    """The audited stuck shape: one live claim excluded from opens
    (in-flight), one PARTIAL fact row, zero worker dirs — the surface
    whose decide() face used to repeat DISPATCH_VERIFIER forever."""
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True, exist_ok=True)
    _write_yaml(ws / "claim-register.yaml", {"claims": [
        {"id": "C-1", "status": status, "statement": "background work",
         "promotion_attempts": 1},
    ]})
    _write_yaml(ws / "claim_deps.yaml",
                {"depends_on": {}, "competitor_groups": {}})
    _write_yaml(ws / "task_spec.yaml", {
        "primary_questions": [],
        "goal_verbatim": "retrieve the family config",
        "success_criterion": "family named with evidence",
        "verification_method": "static",
    })
    if with_fact:
        fdir = ws / "facts"
        fdir.mkdir(exist_ok=True)
        (fdir / "_INDEX.md").write_text(
            "F001 | PARTIAL | C-1 | a partial finding\n", encoding="utf-8")
        (fdir / "F001.md").write_text(
            "---\nid: F001\ntype: fact\nstatus: INFERRED\n"
            "created: 2026-11-01\nclaim_id: C-1\n---\n\nbody.\n",
            encoding="utf-8")
    (ws / "runs").mkdir(exist_ok=True)
    from _factories import write_hook_state
    write_hook_state(ws, active_hooks=["dispatch_gate"])
    return ws


def _run_gate(root: Path, ws: Path, prompt: str) -> subprocess.CompletedProcess:
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(ws),
        "tool_input": {"prompt": prompt},
    })
    return subprocess.run(
        [sys.executable, str(ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(ROOT), errors="replace",
    )


def _experience_rows(ws: Path, stamp: str = STAMP) -> list[dict]:
    return consolidated_ledger.read(ws, "experience", schema_prefix=stamp)


def _seed_reject(ws: Path, *, claim: str = "C-1", reason: str = "granularity",
                 base_ts: str = TS, n: int = 1) -> list[dict]:
    """Append n reject rows through the module face (the setup helper)."""
    rows = []
    for i in range(n):
        row = dispatch_reject.build_reject_row(
            claim=claim, reason=reason, detail="gate said no",
            trace_id=None, ts=base_ts)
        assert dispatch_reject.append_reject(ws, row)["appended"] is True
        rows.append(row)
    return rows


# ---------- the writer at the dispatch seam ----------

class TestGateRejectWritesTheRow:
    def test_structural_reject_writes_exactly_one_row(self, tmp_path) -> None:
        """A hard rc=2 reject on a fresh claim lands exactly ONE
        dispatch-reject row carrying claim_ref + reason + ts."""
        root = tmp_path / "structural"
        ws = _stuck_ws(root)
        prompt = ENVELOPE % '"mcp__external__boom"'
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 2, f"the dispatch must hard-reject: {r.stderr!r}"
        rows = _experience_rows(ws)
        assert len(rows) == 1, f"exactly one row, got {rows}"
        row = rows[0]
        assert row["schema"] == STAMP
        assert row["claim_ref"] == "C-1"
        assert row["dispatch_id"] == "C-1"
        assert row["action_type"] == "dispatch"
        assert row["o"]["status"] == "rejected"
        assert row["o"]["class"] == "mcp_prefix"
        datetime.strptime(row["ts"], "%Y-%m-%dT%H:%M:%SZ")

    def test_plan_first_reject_rides_the_same_seam(self, tmp_path) -> None:
        """The plan-first family rejects through the same single seam: the
        row shape (key set) is byte-identical to the structural family's,
        only the reason face differs."""
        root = tmp_path / "planfirst"
        ws = _stuck_ws(root)
        # a plan that shares the register's id namespace but omits the
        # live claim -> ORPHAN_CLAIM, a non-WARN drift class ->
        # drift-severe -> rc=2 at the drift sink (the terminal sibling
        # keeps the plan/register id intersection non-empty, the
        # detector's phase-level-plan guard)
        _write_yaml(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "IN_PROGRESS", "statement": "background work",
             "promotion_attempts": 1},
            {"id": "C-2", "status": "PROVEN", "statement": "closed sibling"},
        ]})
        (ws / "global_plan.txt").write_text("plan covers C-2 only\n",
                                            encoding="utf-8")
        prompt = ENVELOPE % '"grep"'
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 2, f"drift-severe must hard-reject: {r.stderr!r}"
        rows = _experience_rows(ws)
        assert len(rows) == 1, f"exactly one row, got {rows}"
        structural = dict(rows[0])
        assert structural["o"]["class"] == "plan_drift"
        assert structural["claim_ref"] == "C-1"
        # same key set as every other reason's row (the one-seam pin,
        # asserted cross-family against the structural shape)
        reference = dispatch_reject.build_reject_row(
            claim="C-1", reason="x", ts=TS)
        assert sorted(structural.keys()) == sorted(reference.keys())

    def test_a_rejected_dispatch_writes_no_declaration_row(
            self, tmp_path) -> None:
        """A reject is not an allow: the strategic declaration stamp must
        stay absent (the recovery face reads declaration rows as allow
        evidence — a reject must never fabricate one)."""
        root = tmp_path / "nodecl"
        ws = _stuck_ws(root)
        prompt = ENVELOPE % '"mcp__external__boom"'
        assert _run_gate(root, ws, prompt).returncode == 2
        assert _experience_rows(ws, strategic_action.SCHEMA) == []

    def test_an_allowed_dispatch_still_writes_no_reject_row(
            self, tmp_path) -> None:
        """The seam fires on rc=2 only: a passing dispatch (no teeth, no
        drift) lands no dispatch-reject row."""
        root = tmp_path / "allowed"
        ws = _stuck_ws(root)
        (ws / "global_plan.txt").write_text("plan covers C-1\n",
                                            encoding="utf-8")
        prompt = ENVELOPE % '"grep"'
        assert _run_gate(root, ws, prompt).returncode == 0
        assert _experience_rows(ws) == []

    def test_must_stop_refusal_lands_a_non_retryable_row(
            self, tmp_path) -> None:
        """An irreversible-action refusal lands its row with its OWN
        reason class (never the unnamed default) — and the class is
        non-retryable: the audit row exists, the retry counter never
        sees it."""
        root = tmp_path / "muststop"
        ws = _stuck_ws(root)
        prompt = ENVELOPE % '"grep"' + "git push --force origin main\n"
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 2, f"must-stop must hard-reject: {r.stderr!r}"
        rows = _experience_rows(ws)
        assert len(rows) == 1
        assert rows[0]["o"]["class"] == "must_stop"
        assert rows[0]["claim_ref"] == "C-1"
        face = dispatch_reject.feedback_face(ws)
        assert face["rows"] == 1
        assert face["by_claim"] == {}, "a refusal never counts"
        assert face["active"] == [] and face["exhausted"] == []


# ---------- decide() consumes the rows ----------

class TestDecideConsumesTheRow:
    def test_fresh_reject_changes_the_decision(self, tmp_path) -> None:
        """One reject on a live claim: the decision leaves the
        repeat-forever verdict and PARKS with a backoff note naming the
        claim and the gate reason."""
        ws = _stuck_ws(tmp_path)
        assert cc.decide(ws, emit_snapshot=False)["decision"] == \
            "DISPATCH_VERIFIER", "baseline: the stuck shape repeats the verdict"
        _seed_reject(ws, n=1)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "PARK", d["action"]
        assert "C-1" in d["action"] and "granularity" in d["action"]
        face = d["dispatch_rejects"]
        assert face["active"] == ["C-1"]
        assert face["retry_max"] == dispatch_reject.REJECT_RETRY_MAX
        assert d["exit_code"] == cc.EXIT_PARK

    def test_boundary_two_rejects_are_not_terminal(self, tmp_path) -> None:
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX - 1)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "PARK", d["action"]
        assert "ATTEMPTED_EXHAUSTED" not in d["action"]

    def test_boundary_three_rejects_go_terminal(self, tmp_path) -> None:
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "BLOCKED", d["action"]
        assert dispatch_reject.EXHAUSTED_DISPOSITION in d["action"]
        assert d["exit_code"] == cc.EXIT_BLOCKED
        assert d["dispatch_rejects"]["exhausted"] == ["C-1"]

    def test_retry_max_constant_is_pinned(self) -> None:
        assert dispatch_reject.REJECT_RETRY_MAX == 3

    def test_the_terminal_word_is_the_vocabulary_own(self) -> None:
        """The exhausted word is DERIVED from the disposition algebra's
        route-ledger gate — the seven-word set is consumed, never
        extended."""
        assert dispatch_reject.EXHAUSTED_DISPOSITION == "ATTEMPTED_EXHAUSTED"
        assert dispatch_reject.EXHAUSTED_DISPOSITION in \
            disposition.DISPOSITIONS
        assert len(disposition.DISPOSITIONS) == 7
        assert "route_ledger" in disposition.GATE_FOR_DISPOSITION[
            dispatch_reject.EXHAUSTED_DISPOSITION]

    def test_first_dispatch_bounce_reaches_terminal(self, tmp_path) -> None:
        """The first-dispatch bounce class (the journal undo rolls the
        rejected claim back to OPEN): an OPEN claim at the retry max,
        zero partial facts, no other dispatchable work — the bounced
        claim never masks the stuck face, and the decision goes
        terminal (never a per-tick DISPATCH re-emission)."""
        ws = _stuck_ws(tmp_path, status="OPEN", with_fact=False)
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "BLOCKED", d["action"]
        assert dispatch_reject.EXHAUSTED_DISPOSITION in d["action"]
        assert d["exit_code"] == cc.EXIT_BLOCKED

    def test_first_dispatch_bounce_submax_parks(self, tmp_path) -> None:
        """The same bounce class one tick earlier: an OPEN claim at
        MAX-1 rejects parks with the backoff note instead of re-emitting
        the DISPATCH verdict whose dispatch just bounced."""
        ws = _stuck_ws(tmp_path, status="OPEN", with_fact=False)
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX - 1)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "PARK", d["action"]
        assert "C-1" in d["action"]

    def test_open_frontier_with_other_work_stays_clear(
            self, tmp_path) -> None:
        """A second, never-rejected OPEN claim is a real move: the
        feedback stays silent and the machine dispatches the other
        claim (the bounced claim does not mask the healthy frontier)."""
        ws = _stuck_ws(tmp_path, status="OPEN", with_fact=False)
        _write_yaml(ws / "claim-register.yaml", {"claims": [
            {"id": "C-1", "status": "OPEN", "statement": "bounced",
             "promotion_attempts": 3},
            {"id": "C-2", "status": "OPEN", "statement": "healthy",
             "promotion_attempts": 0},
        ]})
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "DISPATCH", d["action"]

    def test_stuck_guard_needs_zero_active_workers(self, tmp_path) -> None:
        """Live in-flight work means the loop is busy, not stuck: the
        busy-poll face wins and the feedback stays silent."""
        ws = _stuck_ws(tmp_path)
        (ws / "runs" / "worker-status-C-1-a1b2c3d4.md").write_text(
            "status: in-progress\n", encoding="utf-8")
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "DISPATCH_VERIFIER", d["action"]

    def test_terminal_claims_go_quiet(self, tmp_path) -> None:
        """Reject rows for a closed claim never fire: the live-set scoping
        keeps settled history from parking a finished loop."""
        ws = _stuck_ws(tmp_path, status="PROVEN")
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] != "BLOCKED"
        assert d["decision"] != "PARK"

    def test_an_allow_after_the_last_reject_recovers(self, tmp_path) -> None:
        """The recovery face: a dispatch the gate ALLOWED after the last
        reject (its declaration row is newer) silences the feedback —
        the pipeline is flowing again."""
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX,
                     base_ts="2026-11-05T12:00:00Z")
        decl = strategic_action.build_declaration_row(
            claim="C-1", route="FIGHT", propensity=0.5, declared=True,
            trace_id="tr-m-1", ts="2026-11-05T13:00:00Z")
        assert strategic_action.append_declaration(ws, decl)["appended"] is True
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "DISPATCH_VERIFIER", d["action"]

    def test_reason_scoping_same_reason_only_counts_together(
            self, tmp_path) -> None:
        """REJECT_RETRY_MAX counts SAME claim + SAME reason: two rejects
        for one reason and one for another never exhaust the claim."""
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, reason="granularity", n=2)
        _seed_reject(ws, reason="plan_drift", n=1)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "PARK", d["action"]
        face = d["dispatch_rejects"]["by_claim"]["C-1"]
        assert face["reason"] == "granularity"
        assert face["count"] == 2

    def test_unparsed_marker_rows_are_audit_only(self, tmp_path) -> None:
        """Rows under the explicit unparsed marker land for the audit
        but never fire: the marker is never a live register claim, so
        the face scopes it out of both classification sets."""
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, claim=dispatch_reject.UNPARSED_CLAIM,
                     n=dispatch_reject.REJECT_RETRY_MAX)
        face = dispatch_reject.feedback_face(ws)
        assert face["rows"] == dispatch_reject.REJECT_RETRY_MAX
        assert face["by_claim"][dispatch_reject.UNPARSED_CLAIM]["count"] \
            == dispatch_reject.REJECT_RETRY_MAX
        assert face["active"] == [] and face["exhausted"] == []
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "DISPATCH_VERIFIER", d["action"]

    def test_exhaustion_is_window_stable(self, tmp_path) -> None:
        """A burst of newer rows can never window an at-max claim out of
        its evidence: the counts run over the claim's COMPLETE reject
        set (schema-filtered), not a capped window."""
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, claim="C-1", reason="granularity",
                     n=dispatch_reject.REJECT_RETRY_MAX)
        # a non-live sibling buries the tail with far more than a
        # window's worth of newer rows
        _seed_reject(ws, claim="C-9", reason="granularity",
                     n=dispatch_reject.REJECT_HISTORY_MAX + 10)
        assert len(_experience_rows(ws)) > \
            dispatch_reject.REJECT_HISTORY_MAX
        face = dispatch_reject.feedback_face(ws)
        assert face["exhausted"] == ["C-1"], face
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "BLOCKED", d["action"]

    def test_derivation_mismatch_degrades_to_the_sentinel(
            self, monkeypatch) -> None:
        """A vocabulary refactor assigning the route-ledger gate to any
        OTHER disposition must never silently rename the terminal
        decision: the derivation warns and degrades to the documented
        sentinel."""
        # the healthy algebra derives its own word
        assert dispatch_reject._derive_exhausted_word() == \
            "ATTEMPTED_EXHAUSTED"
        monkeypatch.setattr(disposition, "DISPOSITIONS",
                            ("SOLVED", "route_ledger"))
        monkeypatch.setattr(disposition, "GATE_FOR_DISPOSITION",
                            {"SOLVED": ("oracle_pass",),
                             "route_ledger": ("route_ledger",)})
        assert dispatch_reject._derive_exhausted_word() == \
            dispatch_reject.EXHAUSTED_SENTINEL


# ---------- the stuck-loop replay ----------

class TestStuckLoopReplay:
    def test_replay_reaches_terminal_within_four_decides(
            self, tmp_path) -> None:
        """The audited loop, replayed: three gate rejects (same claim,
        same reason) over a partial-only, worker-less surface replay to a
        terminal decision within four decide() calls; the decision
        ledger never shows a fourth DISPATCH_VERIFIER."""
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX)
        decisions = []
        for _ in range(4):
            d = cc.decide(ws)
            decisions.append(d["decision"])
            # the CLI contract pairs every decide() with the snapshot
            # append (silent side channel) — mirror it for the tail read
            cc._append_ledger(ws, d)
        assert "DISPATCH_VERIFIER" not in decisions, decisions
        assert decisions[-1] == "BLOCKED"
        ledger = json.loads((ws / ".convergence_ledger.jsonl")
                            .read_text(encoding="utf-8").splitlines()[-1])
        assert ledger["decision"] == "BLOCKED"
        assert ledger["partial_count"] == 1
        assert ledger["open_count"] == 0
        assert ledger["active_workers"] == 0
        assert len(_experience_rows(ws)) == \
            dispatch_reject.REJECT_RETRY_MAX


# ---------- the one-seam row shape ----------

class TestOneSeamRowShape:
    @pytest.mark.parametrize("reason", [
        "granularity plan-size split required",
        "plan_drift ORPHAN_CLAIM drift-severe",
        "top1 rank-deviation budget face",
    ])
    def test_every_reason_produces_the_same_row_shape(self, reason) -> None:
        row = dispatch_reject.build_reject_row(
            claim="C-1", reason=reason, detail=None, trace_id=None, ts=TS)
        assert row["schema"] == STAMP
        assert row["claim_ref"] == "C-1"
        assert row["dispatch_id"] == "C-1"
        assert row["action_type"] == "dispatch"
        assert row["o"] == {"status": "rejected", "class": reason}
        assert row["detail"] is None
        assert row["trace_id"] is None
        assert row["ts"] == TS

    def test_reasons_count_separately_in_the_face(self, tmp_path) -> None:
        ws = tmp_path
        (ws / "runs").mkdir()
        _seed_reject(ws, reason="a-reason", n=2)
        _seed_reject(ws, reason="b-reason", n=1)
        face = dispatch_reject.feedback_face(ws)
        assert face["by_claim"]["C-1"] == {
            "count": 2, "reason": "a-reason",
            "last_ts": TS}
        assert face["exhausted"] == []
        assert face["retry_max"] == dispatch_reject.REJECT_RETRY_MAX


# ---------- fail-open pins ----------

class TestFailOpen:
    def test_broken_ledger_read_never_raises_into_decide(
            self, tmp_path) -> None:
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, n=1)
        (ws / EXPERIENCE_REL).write_text("\xff\xfe not json at all\n",
                                         encoding="utf-8")
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] in cc.VERDICTS or \
            d["decision"] in {v[0] for v in cc.VERDICTS.values()}
        assert d["decision"] == "DISPATCH_VERIFIER"

    def test_face_layer_error_degrades_to_the_plain_verdict(
            self, tmp_path, monkeypatch) -> None:
        ws = _stuck_ws(tmp_path)
        _seed_reject(ws, n=dispatch_reject.REJECT_RETRY_MAX)

        def _boom(_ws, *a, **k):
            raise OSError("reader outage")

        monkeypatch.setattr(dispatch_reject, "feedback_face", _boom)
        d = cc.decide(ws, emit_snapshot=False)
        assert d["decision"] == "DISPATCH_VERIFIER", d["action"]
        assert "dispatch_rejects" not in d

    def test_gate_writer_fail_open_keeps_the_reject(
            self, tmp_path) -> None:
        """The ledger append failing must never change the gate verdict:
        the REJECT still lands rc=2 (the append failure degrades to one
        loud warn on stderr, never a traceback, never a pass)."""
        root = tmp_path / "failopen"
        ws = _stuck_ws(root)
        (ws / EXPERIENCE_REL).mkdir()  # a directory: every append fails
        prompt = ENVELOPE % '"mcp__external__boom"'
        r = _run_gate(root, ws, prompt)
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        assert "REJECT mcp_prefix" in r.stderr
        assert "Traceback" not in r.stderr


# ---------- structural pins (the STATE_TABLE discipline) ----------

class TestMachineTablePins:
    def test_events_and_transitions_declared(self) -> None:
        assert "REJECT_SEEN" in cc.Event.__members__
        assert "REJECT_RETRY_EXHAUSTED" in cc.Event.__members__
        backoff = cc.TRANSITIONS.get(
            (cc.State.SCHEDULE, cc.Event.REJECT_SEEN))
        exhausted = cc.TRANSITIONS.get(
            (cc.State.SCHEDULE, cc.Event.REJECT_RETRY_EXHAUSTED))
        assert backoff is not None and backoff[0] is cc.State.PARK
        assert callable(backoff[1])
        assert exhausted is not None and exhausted[0] is cc.State.BLOCKED
        assert callable(exhausted[1])

    def test_feedback_precedes_the_verdict_it_corrects(self) -> None:
        """The forcing order: the reject feedback is probed BEFORE the
        verify-forcing flavors — the verdict whose dispatch the gate
        keeps refusing can never mask the feedback."""
        probes = cc.STAGE_PROBES[cc.State.SCHEDULE]
        exhausted = probes.index(cc.Event.REJECT_RETRY_EXHAUSTED)
        backoff = probes.index(cc.Event.REJECT_SEEN)
        assert exhausted < probes.index(cc.Event.VERIFY_STALE)
        assert backoff < probes.index(cc.Event.VERIFY_STALE)
        assert exhausted < backoff, "escalation wins over the backoff"

    def test_predicate_registration_is_complete(self) -> None:
        for event in (cc.Event.REJECT_SEEN,
                      cc.Event.REJECT_RETRY_EXHAUSTED):
            assert event in cc.STAGE_PROBES[cc.State.SCHEDULE]
            assert event in cc._EVENT_PREDICATES
            assert callable(cc._EVENT_PREDICATES[event])


# ---------- import hygiene (the facade-neutral pin) ----------

def test_the_test_imports_are_facade_neutral():
    """This module itself must never become a facade consumer: the rlvr
    faces are imported by module path (``import rlvr.x as x``), never
    through a ``from rlvr import ...`` re-export bind."""
    import ast
    import tests.test_decision_feedback_1005 as this_module
    tree = ast.parse(
        Path(this_module.__file__).read_text(encoding="utf-8"))
    facade_binds = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
        and (node.module or "").split(".")[0] == "rlvr"]
    assert facade_binds == []
