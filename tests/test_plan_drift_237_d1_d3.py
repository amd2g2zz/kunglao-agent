# -*- coding: utf-8 -*-
"""TDD RED — issue #237: B1o deadlock + verify-record forgery surface.

Three defects (field incident wbtest 2026-09-12: a workspace agent under
gate pressure self-wrote runs/verify-redteam-C-001..004.md records with a
fabricated verifier identity, and the gate cleared 4 of 5 drifts on file
existence alone):

  D1  UNANSWERED_QUESTION requires an EXACT terminal answers_question match
      and walks no dependency chain -> mid-run workspaces drift while the
      answer chain is OPEN (liveness bug).
  D3  verify records count on file level (#827 content screen only) with no
      dispatch linkage and no maker!=checker binding -> the policed actor
      can mint them (forgery surface).

This file covers the detector faces (unit, fast tier). The dispatch-gate
verifier pass-through (D2) lives in
tests/test_dispatch_gate_237_passthrough.py (slow tier, hook-interaction).

All I/O is synthetic (tmp_path); pure unit tier.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import plan_drift_detector as pdd  # noqa: E402


# ---------- fixture helpers ---------------------------------------------


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _write_plan(ws: Path, ids: list[str]) -> None:
    (ws / "global_plan.txt").write_text(
        "plan body mentioning " + " ".join(ids) + "\n", encoding="utf-8")


def _write_task_spec(ws: Path, qids: list[str]) -> None:
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump({"primary_questions": [
            {"id": qid, "q": f"<{qid}>", "need": "yes_no_with_evidence"}
            for qid in qids]}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _write_deps(ws: Path, edges: dict[str, list[str]]) -> None:
    (ws / "claim_deps.yaml").write_text(
        yaml.safe_dump({"depends_on": edges}, sort_keys=False),
        encoding="utf-8")


def _write_verify_record(ws: Path, cid: str) -> Path:
    """Credible-content record — passes the #827 screen on its own."""
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    p = runs / f"verify-redteam-{cid}.md"
    p.write_text("RED-TEAM VERDICT: CONFIRMED\n\nindependent check body\n",
                 encoding="utf-8")
    return p


def _write_log_rows(ws: Path, rows: list[dict]) -> None:
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "kunglao-2026-09-18.jsonl", "a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _hook_dispatch_row(cid: str, agent: str = "kunglao-redteam") -> dict:
    """The #461 dispatch-lifecycle row shape (hook corridor)."""
    return {"ts": "2026-09-18T00:00:00Z", "actor": "hook:worker_budget",
            "action": "dispatch", "claim": cid,
            "detail": f"tier=1 tools=Read agent={agent} "
                      "(#461 linkage: renew + arm + phase=DISPATCH)"}


# =========================================================================
# D1 — in-progress credit via the claim_deps chain
# =========================================================================


class TestD1InProgressCredit:
    """UNANSWERED_QUESTION is drift only when nothing is in flight.

    Issue acceptance: 'Mid-run workspace with an OPEN chain answering q1's
    sub-questions -> no UNANSWERED_QUESTION.'
    """

    def test_open_chain_answering_subquestions_no_drift(self, tmp_path,
                                                        capsys):
        """OPEN answerer + OPEN sub-question chain -> rc 0, no drift."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [
            {"id": "C-001", "status": "OPEN", "answers_question": "q1"},
            {"id": "C-010", "status": "OPEN", "answers_question": "pq-1a",
             "depends_on": ["C-001"]},
            {"id": "C-011", "status": "OPEN", "answers_question": "pq-1b",
             "depends_on": ["C-001"]},
        ])
        _write_plan(ws, ["C-001", "C-010", "C-011"])
        _write_task_spec(ws, ["q1"])
        _write_deps(ws, {"C-010": ["C-001"], "C-011": ["C-001"]})

        rc = pdd.check(ws, active_only=True)
        out = capsys.readouterr().out
        assert rc == 0, f"mid-run chain must not drift, got rc={rc}: {out!r}"
        assert "UNANSWERED_QUESTION" not in out

    def test_lone_open_answerer_no_drift(self, tmp_path, capsys):
        """An answering claim at any non-terminal status is in-flight."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [
            {"id": "C-001", "status": "OPEN", "answers_question": "q1"},
        ])
        _write_plan(ws, ["C-001"])
        _write_task_spec(ws, ["q1"])

        rc = pdd.check(ws, active_only=True)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "UNANSWERED_QUESTION" not in out

    def test_deps_only_chain_credit(self, tmp_path, capsys):
        """Chain edges from claim_deps.yaml alone credit the in-flight work."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [
            {"id": "C-001", "status": "OPEN", "answers_question": "q1"},
            {"id": "C-010", "status": "OPEN"},
        ])
        _write_plan(ws, ["C-001", "C-010"])
        _write_task_spec(ws, ["q1"])
        _write_deps(ws, {"C-010": ["C-001"]})

        rc = pdd.check(ws, active_only=True)
        assert rc == 0, capsys.readouterr().out
        assert "UNANSWERED_QUESTION" not in capsys.readouterr().out

    def test_no_answerer_still_fires(self, tmp_path, capsys):
        """No claim answers q1 anywhere -> UNANSWERED_QUESTION stays."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "OPEN"}])
        _write_plan(ws, ["C-001"])
        _write_task_spec(ws, ["q1"])

        rc = pdd.check(ws, active_only=True)
        out = capsys.readouterr().out
        assert rc == 1
        assert "UNANSWERED_QUESTION" in out

    def test_cycle_in_deps_does_not_credit_or_hang(self, tmp_path, capsys):
        """A deps cycle with no answerer must not credit (and not hang)."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [
            {"id": "C-010", "status": "OPEN"},
            {"id": "C-011", "status": "OPEN"},
        ])
        _write_plan(ws, ["C-010", "C-011"])
        _write_task_spec(ws, ["q1"])
        _write_deps(ws, {"C-010": ["C-011"], "C-011": ["C-010"]})

        rc = pdd.check(ws, active_only=True)
        out = capsys.readouterr().out
        assert rc == 1
        assert "UNANSWERED_QUESTION" in out

    def test_question_progress_states(self, tmp_path):
        """Unit pin of the three question_progress states."""
        deps = tmp_path / "claim_deps.yaml"
        claims = [
            {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
            {"id": "C-2", "status": "OPEN", "answers_question": "q1"},
            {"id": "C-3", "status": "OPEN"},
        ]
        assert pdd.question_progress("q1", claims, deps) == "terminal"
        assert pdd.question_progress("q1", claims[1:], deps) == "in-progress"
        assert pdd.question_progress("q1", claims[2:], deps) == "none"


# =========================================================================
# D3 — verify-record provenance (forgery surface)
# =========================================================================


class TestD3ForgeryRejection:
    """A verify record counts only when the log corroborates a verifier
    dispatch from the hook corridor (maker != checker pin). Fail-closed.
    """

    def test_forged_records_without_dispatch_rejected(self, tmp_path, capsys):
        """Incident replay: 4 PROVEN claims + credible self-written records +
        NO dispatch rows -> UNVERIFIED_EVIDENCE still fires."""
        ws = _mk_ws(tmp_path)
        ids = ["C-001", "C-002", "C-003", "C-004"]
        _write_register(ws, [{"id": cid, "status": "PROVEN"} for cid in ids])
        _write_plan(ws, ids)
        for cid in ids:
            _write_verify_record(ws, cid)

        rc = pdd.check(ws, active_only=True)
        out = capsys.readouterr().out
        assert "UNVERIFIED_EVIDENCE" in out, (
            "self-minted records without dispatch linkage must not clear "
            f"the drift: {out!r}")
        assert rc >= 1

    def test_self_attested_worker_row_rejected(self, tmp_path, capsys):
        """The maker self-attesting a redteam dispatch does not corroborate
        (dispatch rows are minted by the hook corridor, not by the policed
        actor)."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
        _write_plan(ws, ["C-001"])
        _write_verify_record(ws, "C-001")
        _write_log_rows(ws, [{
            "ts": "2026-09-18T00:00:00Z", "actor": "worker:kunglao-worker-1",
            "action": "dispatch", "claim": "C-001",
            "detail": "agent=kunglao-redteam (self-attested)",
        }])

        rc = pdd.check(ws, active_only=True)
        out = capsys.readouterr().out
        assert rc == 1
        assert "UNVERIFIED_EVIDENCE" in out

    def test_self_attested_verifier_row_rejected(self, tmp_path, capsys):
        """A verifier:-prefixed actor row is not hook-attributed -> no
        corroboration (stricter than the #57 blind_gate contract by
        design)."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
        _write_plan(ws, ["C-001"])
        _write_verify_record(ws, "C-001")
        _write_log_rows(ws, [{
            "ts": "2026-09-18T00:00:00Z", "actor": "verifier:kunglao-redteam",
            "action": "dispatch", "claim": "C-001", "detail": "retroactive",
        }])

        rc = pdd.check(ws, active_only=True)
        assert rc == 1
        assert "UNVERIFIED_EVIDENCE" in capsys.readouterr().out

    def test_hook_row_for_other_claim_rejected(self, tmp_path, capsys):
        """A real verifier dispatch for C-002 does not cover a C-001 record."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [
            {"id": "C-001", "status": "PROVEN"},
            {"id": "C-002", "status": "PROVEN"},
        ])
        _write_plan(ws, ["C-001", "C-002"])
        _write_verify_record(ws, "C-001")
        _write_log_rows(ws, [_hook_dispatch_row("C-002")])

        rc = pdd.check(ws, active_only=True)
        out = capsys.readouterr().out
        assert "UNVERIFIED_EVIDENCE" in out
        assert "C-001" in out

    def test_missing_log_fail_closed(self, tmp_path, capsys):
        """No unified log at all -> nothing is corroborated."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
        _write_plan(ws, ["C-001"])
        _write_verify_record(ws, "C-001")

        rc = pdd.check(ws, active_only=True)
        assert rc == 1
        assert "UNVERIFIED_EVIDENCE" in capsys.readouterr().out

    def test_corroborated_record_accepted(self, tmp_path, capsys):
        """GREEN path: #461 hook dispatch row + screened record -> verified."""
        ws = _mk_ws(tmp_path)
        _write_register(ws, [{"id": "C-001", "status": "PROVEN"}])
        _write_plan(ws, ["C-001"])
        _write_verify_record(ws, "C-001")
        _write_log_rows(ws, [_hook_dispatch_row("C-001")])

        rc = pdd.check(ws, active_only=True)
        assert rc == 0, capsys.readouterr().out
        assert "UNVERIFIED_EVIDENCE" not in capsys.readouterr().out

    def test_corroborated_verified_ids_unit(self, tmp_path):
        """Unit pin: intersection of the #827 screen and log corroboration."""
        ws = _mk_ws(tmp_path)
        _write_verify_record(ws, "C-001")  # screened, NOT corroborated
        _write_verify_record(ws, "C-002")  # screened AND corroborated
        _write_log_rows(ws, [
            _hook_dispatch_row("C-002"),
            _hook_dispatch_row("C-001", agent="kunglao-worker"),  # not verifier
        ])

        assert pdd.corroborated_verified_ids(ws) == {"C-002"}

    def test_non_dispatch_hook_row_does_not_corroborate(self, tmp_path):
        """A hook row with a non-dispatch action (e.g. a WARN trace) is not
        dispatch evidence."""
        ws = _mk_ws(tmp_path)
        _write_verify_record(ws, "C-001")
        _write_log_rows(ws, [{
            "ts": "2026-09-18T00:00:00Z", "actor": "hook:dispatch_gate",
            "action": "plan_drift_crashed", "claim": "C-001",
            "detail": "agent=kunglao-redteam; rc=1",
        }])

        assert pdd.corroborated_verified_ids(ws) == set()
