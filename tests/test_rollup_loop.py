# -*- coding: utf-8 -*-
"""Tests for #524 rollup write-loop automation.

When a claim hits a terminal state (PROVEN / NEGATIVE / REFUTED / etc), the
write loop MUST automatically:
  1. Run outcome_capture (capture runs/*.md -> OUTCOME rows on the ledger)
  2. Run failure_analysis_gate aggregate_lessons (if analysis exists) - so the
     closed-loop outcome lands in the global lessons library
  3. Emit a checkpoint-commit hook call so the workspace git side can record
     the terminal transition (shared mount point with #534)

The loop must be:
  - Idempotent: re-firing on a terminal claim is a no-op (no extra ledger
    rows, no extra lesson files, no extra commit)
  - Pure: each step is run via its existing public function
    (failure_analysis_gate.aggregate_lessons, outcome_capture.capture);
    the rollup is a thin orchestration over them, not a re-implementation
  - Explicit: the function returns a per-step status dict so callers (and
    tests) can verify each phase ran
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load(mod_name: str, file_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, SCRIPTS / file_name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


rag = _load("rollup_under_test", "rollup.py")
fag = _load("fag_under_test", "failure_analysis_gate.py")
oc = _load("oc_under_test", "outcome_capture.py")


def _write_register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_analysis(ws: Path, cid: str, **fields) -> None:
    base = {"claim": cid, "method_assumption": "m", "assumption_validity": "not-justified",
            "next_method": "n", "analyzed_at": "2026-08-22T00:00:00Z",
            # #525 nursery gate: aggregate_lessons routes entries missing a
            # complete trigger_precision block to the /reflect queue (reason=
            # missing-precision) instead of the lessons library — the rollup
            # integration tests want a CLOSED-LOOP lesson write, so the helper
            # seeds the required 4-key block by default (tests that need the
            # missing-precision path can override).
            "trigger_precision": {
                "tool": "test-tool",
                "error_signature": "test-sig",
                "family": "test-family",
                "unit": "test-unit",
            }}
    base.update(fields)
    adir = ws / "analyses"
    adir.mkdir(exist_ok=True)
    (adir / f"failure-{cid}.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _write_ledger_outcome(ws: Path, cid: str, result: str = "CONFIRMED",
                          checker: str = "red-team") -> None:
    row = {"type": "outcome", "ts": "2026-08-22T00:00:00Z",
           "claim_id": cid, "result": result, "checker": checker}
    with open(ws / ".convergence_ledger.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---------- core contract: terminal transition fires rollup ----------

def test_terminal_transition_fires_rollup(tmp_path):
    """Closing a claim as PROVEN -> rollup runs outcome_capture +
    aggregate_lessons + checkpoint_commit, all in one call."""
    ws = tmp_path / "ws"
    ws.mkdir()
    cid = "C-1"
    _write_register(ws, [{
        "id": cid, "status": "OPEN", "boundary_type": "positive_observation",
        "evidence_tier_attempted": 1, "promotion_attempts": 0,
        "statement": "rollup integration test",
    }])
    _write_analysis(ws, cid, outcome="PROVEN", what_happened="closed-loop confirmed")
    lib = tmp_path / "lib"
    lib.mkdir()

    res = rag.run_rollup(ws, cid, terminal_status="PROVEN",
                         lessons_library=lib,
                         reflect_queue=tmp_path / "q.json")

    assert res["fired"] is True
    assert res["terminal_status"] == "PROVEN"
    assert res["lessons_aggregate"] == 1
    assert res["checkpoint_commit_called"] is True
    ledger = ws / ".convergence_ledger.jsonl"
    assert ledger.exists()
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert any(r.get("type") == "operator_action" and r.get("action") == "rollup"
               for r in rows), rows
    assert len(list(lib.glob("lesson-*.md"))) == 1


def test_negative_status_fires_rollup_with_redteam_gate(tmp_path):
    """NEGATIVE terminal transition fires rollup; lessons gated on red-team."""
    ws = tmp_path / "ws"
    ws.mkdir()
    cid = "C-2"
    _write_register(ws, [{"id": cid, "status": "OPEN", "statement": "negative test"}])
    _write_analysis(ws, cid, outcome="NEGATIVE",
                    what_happened="no signal across 3 methods")
    lib = tmp_path / "lib"
    lib.mkdir()

    res1 = rag.run_rollup(ws, cid, terminal_status="NEGATIVE",
                          lessons_library=lib,
                          reflect_queue=tmp_path / "q.json")
    assert res1["fired"] is True
    assert res1["lessons_aggregate"] == 0

    # Re-fire same (cid, status) -> idempotent no-op. The red-team row write
    # itself does NOT crash the rollup.
    _write_ledger_outcome(ws, cid, result="CONFIRMED", checker="red-team")
    res2 = rag.run_rollup(ws, cid, terminal_status="NEGATIVE",
                          lessons_library=lib,
                          reflect_queue=tmp_path / "q.json")
    assert res2["fired"] is False
    assert res2["reason"] == "already-rolled-up"


# ---------- order contract: capture THEN aggregate ----------

def test_capture_runs_before_aggregate(tmp_path):
    """A verify-redteam run present at rollup time lands on the ledger BEFORE
    aggregate_lessons reads it - so NEGATIVE + red-team CONFIRMED produce a
    lesson file in a SINGLE rollup call."""
    ws = tmp_path / "ws"
    ws.mkdir()
    cid = "C-3"
    _write_register(ws, [{"id": cid, "status": "OPEN", "statement": "order test"}])
    _write_analysis(ws, cid, outcome="NEGATIVE",
                    what_happened="no signal found")
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    (runs / f"{cid}-verify-redteam.md").write_text(
        f"target: {cid}\n\nRED-TEAM VERDICT: CONFIRMED\n",
        encoding="utf-8",
    )
    lib = tmp_path / "lib"
    lib.mkdir()

    res = rag.run_rollup(ws, cid, terminal_status="NEGATIVE",
                         lessons_library=lib,
                         reflect_queue=tmp_path / "q.json")

    assert res["fired"] is True
    assert res["lessons_aggregate"] == 1, res
    assert len(list(lib.glob("lesson-*.md"))) == 1


# ---------- idempotency ----------

def test_idempotent_rerun_is_noop(tmp_path):
    """Re-firing rollup on an already-terminal claim records no extra
    ledger OUTCOME rows, no extra lesson files, only ONE rollup row."""
    ws = tmp_path / "ws"
    ws.mkdir()
    cid = "C-4"
    _write_register(ws, [{"id": cid, "status": "OPEN", "statement": "idempotency"}])
    _write_analysis(ws, cid, outcome="PROVEN", what_happened="ok")
    lib = tmp_path / "lib"
    lib.mkdir()

    res1 = rag.run_rollup(ws, cid, terminal_status="PROVEN",
                          lessons_library=lib,
                          reflect_queue=tmp_path / "q.json")
    res2 = rag.run_rollup(ws, cid, terminal_status="PROVEN",
                          lessons_library=lib,
                          reflect_queue=tmp_path / "q.json")

    assert res1["fired"] is True
    assert res2["fired"] is False
    assert res2["reason"] == "already-rolled-up"
    assert len(list(lib.glob("lesson-*.md"))) == 1
    rows = [json.loads(line) for line in (ws / ".convergence_ledger.jsonl")
            .read_text(encoding="utf-8").splitlines() if line.strip()]
    rollup_rows = [r for r in rows if r.get("type") == "operator_action"
                   and r.get("action") == "rollup"]
    assert len(rollup_rows) == 1, rollup_rows


# ---------- non-terminal transitions are rejected ----------

def test_non_terminal_status_rejected(tmp_path):
    """Calling run_rollup with a non-terminal status returns
    fired=False with reason='not-terminal' and writes nothing."""
    ws = tmp_path / "ws"
    ws.mkdir()
    cid = "C-5"
    _write_register(ws, [{"id": cid, "status": "OPEN", "statement": "non-terminal"}])
    _write_analysis(ws, cid, outcome="PROVEN", what_happened="ok")
    lib = tmp_path / "lib"
    lib.mkdir()

    res = rag.run_rollup(ws, cid, terminal_status="IN_PROGRESS",
                         lessons_library=lib,
                         reflect_queue=tmp_path / "q.json")

    assert res["fired"] is False
    assert res["reason"] == "not-terminal"
    assert not (ws / ".convergence_ledger.jsonl").exists()
    assert len(list(lib.glob("lesson-*.md"))) == 0


# ---------- checkpoint-commit hook (shared mount with #534) ----------

def test_checkpoint_commit_hook_called(tmp_path):
    """The rollup invokes the shared #534 checkpoint-commit hook with
    (workspace, claim_id, terminal_status)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    cid = "C-6"
    _write_register(ws, [{"id": cid, "status": "OPEN", "statement": "hook test"}])
    lib = tmp_path / "lib"
    lib.mkdir()

    with mock.patch.object(rag, "_checkpoint_commit",
                           wraps=mock.Mock(return_value="ok")) as ck:
        res = rag.run_rollup(ws, cid, terminal_status="PROVEN",
                             lessons_library=lib,
                             reflect_queue=tmp_path / "q.json")

    assert res["checkpoint_commit_called"] is True
    assert ck.call_count == 1
    args, _ = ck.call_args
    assert args[0] == ws
    assert args[1] == cid
    assert args[2] == "PROVEN"


# ---------- CLI wiring ----------

def test_cli_invokes_run_rollup(tmp_path):
    """CLI mode wires through to run_rollup and exits 0 on success."""
    import subprocess

    ws = tmp_path / "ws"
    ws.mkdir()
    cid = "C-7"
    _write_register(ws, [{"id": cid, "status": "OPEN", "statement": "cli test"}])
    lib = tmp_path / "lib"
    lib.mkdir()

    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "rollup.py"), str(ws), cid,
         "--status", "PROVEN", "--library", str(lib)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    assert "rollup" in r.stdout.lower()