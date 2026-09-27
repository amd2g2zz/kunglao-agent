# -*- coding: utf-8 -*-
"""tests/test_reward_adapters_366.py — emission adapters + tick wiring +
prior feed (U1 adapters / U2 tick / U4).

Acceptance checkboxes covered here:
  - Adapters: task/lessons rows appear in the unified ledger from a
    synthetic workspace exercising both (the distill kind arrives with
    the distill card — its rules are declared, its producer is out of
    scope here);
  - Settlement runs on the rollup tick (extended, not replaced);
  - Prior interface: compute_priors consumes the unified settled rows as
    ONE additive source namespace (the Thompson family's prior feed).
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(mod_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPTS / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


rag = _load("rollup_366_under_test", "rollup.py")
import rollout_ledger as rl  # noqa: E402
import reward_settlement as rs  # noqa: E402


def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _write_analysis(ws: Path, cid: str, **fields) -> None:
    base = {"claim": cid, "method_assumption": "m",
            "assumption_validity": "not-justified",
            "next_method": "n", "analyzed_at": "2026-09-24T00:00:00Z",
            "what_happened": "closed-loop confirmed",
            "trigger_precision": {"tool": "t", "error_signature": "s",
                                  "family": "f", "unit": "u"}}
    base.update(fields)
    adir = ws / "analyses"
    adir.mkdir(exist_ok=True)
    (adir / f"failure-{cid}.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _proven_workspace(tmp_path: Path, cid: str = "C-101") -> tuple[Path, Path]:
    """Synthetic workspace whose claim closes PROVEN with a green oracle
    face and one closed-loop failure analysis (-> exactly one lesson)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "runs").mkdir()
    _write_register(ws, [{"id": cid, "status": "PROVEN",
                          "answers_question": "q1"}])
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: family\n", encoding="utf-8")
    (ws / "runs" / "oracle-status.json").write_text(json.dumps({
        "schema": "oracle-status/1",
        "cases": {"case-a": {"status": "pass", "pending_entries": 0}},
    }), encoding="utf-8")
    _write_analysis(ws, cid, outcome="PROVEN")
    lib = tmp_path / "lib"
    lib.mkdir()
    return ws, lib


# ---------- adapters: unified rows land from the rollup tick ----------

class TestRollupEmitsUnifiedRows:
    def test_proven_closure_lands_task_and_distill_rows(self, tmp_path):
        ws, lib = _proven_workspace(tmp_path)
        res = rag.run_rollup(ws, "C-101", terminal_status="PROVEN",
                             lessons_library=lib,
                             reflect_queue=tmp_path / "q.json")
        assert res["fired"] is True
        rows = rl.read(ws)
        kinds = {r["kind"] for r in rows}
        assert "task" in kinds, rows
        assert "self_distill" in kinds, rows
        task = next(r for r in rows if r["kind"] == "task"
                    and r["anchor"] == "C-101")
        types = {s["type"] for s in task["signals"]}
        assert "claim_terminal" in types
        assert "oracle_verdict" in types
        distill = next(r for r in rows if r["kind"] == "self_distill")
        assert distill["signals"], "lesson row carries its written signal"
        assert distill["anchor"], "lesson anchor = lesson identity"

    def test_task_rows_settle_on_the_same_tick(self, tmp_path):
        ws, lib = _proven_workspace(tmp_path)
        rag.run_rollup(ws, "C-101", terminal_status="PROVEN",
                       lessons_library=lib,
                       reflect_queue=tmp_path / "q.json")
        settled = {(r["rollout_id"], r["settlement"]["band"])
                   for r in rl.settled(ws)}
        assert ("task/C-101", "SETTLED_GREEN") in settled

    def test_unsettled_lesson_row_is_neutral_pending(self, tmp_path):
        """A fresh lesson has only its written signal -> NEUTRAL pending
        corroboration (single-signal pin through the live adapter path)."""
        ws, lib = _proven_workspace(tmp_path)
        rag.run_rollup(ws, "C-101", terminal_status="PROVEN",
                       lessons_library=lib,
                       reflect_queue=tmp_path / "q.json")
        distill = next(r for r in rl.settled(ws, kind="self_distill"))
        assert distill["settlement"]["band"] == "NEUTRAL"
        assert distill["settlement"]["rule_id"] == "self_distill/pending"

    def test_deferred_closure_without_oracle_is_neutral_pending(self, tmp_path):
        ws = tmp_path / "ws-def"
        ws.mkdir()
        (ws / "runs").mkdir()
        _write_register(ws, [{"id": "C-9", "status": "DEFERRED"}])
        lib = tmp_path / "lib"
        lib.mkdir()
        rag.run_rollup(ws, "C-9", terminal_status="DEFERRED",
                       lessons_library=lib,
                       reflect_queue=tmp_path / "q.json")
        task = [r for r in rl.read(ws) if r["kind"] == "task"]
        assert task and task[0]["anchor"] == "C-9"
        settled = [r for r in rl.settled(ws, kind="task")]
        assert settled and settled[0]["settlement"]["band"] == "NEUTRAL"

    def test_rollup_result_reports_the_settlement_face(self, tmp_path):
        ws, lib = _proven_workspace(tmp_path)
        res = rag.run_rollup(ws, "C-101", terminal_status="PROVEN",
                             lessons_library=lib,
                             reflect_queue=tmp_path / "q.json")
        assert "unified_reward" in res
        assert res["unified_reward"]["settled"] >= 1

    def test_rollup_without_ledger_writes_still_fires(self, tmp_path):
        """Fail-open: the unified-reward face never blocks the terminal
        transition (make the adapters crash and the rollup still fires)."""
        ws, lib = _proven_workspace(tmp_path)
        import unittest.mock as mock
        with mock.patch.object(rs, "settle_workspace",
                               side_effect=RuntimeError("boom")):
            res = rag.run_rollup(ws, "C-101", terminal_status="PROVEN",
                                 lessons_library=lib,
                                 reflect_queue=tmp_path / "q.json")
        assert res["fired"] is True
        assert "error" in res["unified_reward"]["settlement"]

    def test_idempotent_reroll_lands_no_duplicate_rows(self, tmp_path):
        ws, lib = _proven_workspace(tmp_path)
        cid = "C-101"
        # a claim is DEFERRED, then wakes and closes PROVEN: two closures,
        # one rollout fold, no duplicate identity rows.
        _write_register(ws, [{"id": cid, "status": "DEFERRED"}])
        rag.run_rollup(ws, cid, terminal_status="DEFERRED",
                       lessons_library=lib, reflect_queue=tmp_path / "q.json")
        _write_register(ws, [{"id": cid, "status": "PROVEN",
                              "answers_question": "q1"}])
        rag.run_rollup(ws, cid, terminal_status="PROVEN",
                       lessons_library=lib, reflect_queue=tmp_path / "q.json")
        folds = rl.read(ws)
        task_rows = [r for r in folds if r["rollout_id"] == "task/C-101"]
        assert len(task_rows) >= 2  # identity + amendment(s)
        settled = [r for r in rl.settled(ws, kind="task")]
        assert settled and settled[0]["settlement"]["band"] == "SETTLED_GREEN"


# ---------- U4: prior feed (one interface, the Thompson family) ----------

class TestPriorFeed:
    def test_compute_priors_consumes_settled_rollout_rows(self, tmp_path):
        """compute_priors gains ONE additive source namespace reading the
        unified ledger through rollout_ledger.settled — prior math itself
        is untouched (issue 137 contract)."""
        ws, lib = _proven_workspace(tmp_path)
        # a synthetic ADVERSE distill row -> beta
        rl.record(ws, kind="self_distill", anchor="lesson-adv",
                  signals=[{"type": "misleading_declaration",
                            "source": "red-team", "value": True,
                            "ts": "2026-09-24T00:00:00Z"},
                           {"type": "zero_recall", "source": "recall",
                            "value": True, "ts": "2026-09-24T00:00:00Z"},
                           {"type": "no_citation", "source": "lt",
                            "value": True, "ts": "2026-09-24T00:00:00Z"}])
        rag.run_rollup(ws, "C-101", terminal_status="PROVEN",
                       lessons_library=lib,
                       reflect_queue=tmp_path / "q.json")
        doc = _load("cp_366_under_test", "compute_priors.py")
        r = doc.compute_priors([ws])
        src = r["sources"]["rollout_ledger"]
        # task SETTLED_GREEN -> +1 alpha; fresh lesson NEUTRAL -> nothing;
        # adverse distill row (settled on the same tick) -> +1 beta
        assert src["alpha"] >= 1
        assert src["beta"] >= 1
        # decomposition contract: sources sum into the aggregate
        assert src["alpha"] + src["beta"] <= r["alpha"] + r["beta"]
        assert r["alpha"] >= 2.0 and r["beta"] >= 2.0

    def test_neutral_rows_contribute_nothing_to_the_prior(self, tmp_path):
        ws = tmp_path / "ws-neutral"
        ws.mkdir()
        (ws / "runs").mkdir()
        rl.record(ws, kind="self_distill", anchor="lesson-only",
                  signals=[{"type": "lesson_written", "source": "rollup",
                            "value": "sig", "ts": "2026-09-24T00:00:00Z"}])
        rs.settle_workspace(ws)
        doc = _load("cp_366_under_test2", "compute_priors.py")
        r = doc.compute_priors([ws])
        assert r["sources"]["rollout_ledger"] == {"alpha": 0, "beta": 0}
        assert r["alpha"] == 1.0 and r["beta"] == 1.0  # base prior only

    def test_settled_interface_accepts_mixed_kinds(self, tmp_path):
        ws = tmp_path / "ws-mixed"
        ws.mkdir()
        for kind, anchor, band in (("task", "C-1", "SETTLED_GREEN"),
                                   ("self_distill", "l-1", "HELPED"),
                                   ("hybrid_distill", "h-1", "ADVERSE")):
            rl.record(ws, kind=kind, anchor=anchor,
                      signals=[{"type": "oracle_verdict" if kind == "task"
                                else "distill_consumption",
                                "source": "s", "value": 1,
                                "ts": "2026-09-24T00:00:00Z"}])
            rl.settle(ws, f"{kind}/{anchor}",
                      settlement={"reward": 1.0 if band == "SETTLED_GREEN"
                                  else 0.5 if band == "HELPED" else 0.0,
                                  "band": band, "rule_id": f"{kind}/test",
                                  "evidence_refs": ["synthetic"]})
        by_kind = {k: rl.settled(ws, kind=k)
                   for k in ("task", "self_distill", "hybrid_distill")}
        assert len(by_kind["task"]) == 1
        assert len(by_kind["self_distill"]) == 1
        assert len(by_kind["hybrid_distill"]) == 1
