#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_runner_settlement_face_966.py — the runner-native
settlement face (issue #966).

A solo eval session never dispatches (single-session topology): the
ALLOW tail's pending dispatch row shapes never land, q_cells.observe_
settlement always hits the honest gap, and the settlement→Q-bank→store
chain was structurally dead — live sessions accumulated ZERO credit.
The approved fix shape (option a): the EVAL RUNNER writes the dispatch
row itself for solo sessions and settles the graded credit at terminal
through the same scalar handler a worker settlement uses. Pinned here:

  B1  the chain fires: PASS settles one pending dispatch row + one
      settlement observation + EXACTLY ONE posterior-store/1 row keyed
      by the declared arm-key dims (family|recipe|verif|tier)
  B2  the honest FAIL face: a FAIL verdict ALSO settles (credit 0.0 —
      the fold's failure mass must move; a silent-skip FAIL is the
      exact zero-credit wall #966 tears down)
  B3  no graded work settles nothing (SKIP: no row, no store write —
      never a fabricated credit)
  B4  retry is one-shot: the deterministic session-stable dispatch id
      plus the already-settled guard keep a retried workspace from
      double-writing the bank or the store
  B5  fail-open + honest gaps: a crashed bank leaves the verdict row
      unaffected (one WARN, settled=False), and an undeclared family is
      the honest gap (no row, never a fabricated bucket)

stdlib + pytest only (house eval-script rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import q_cells  # noqa: E402
from rlvr import scalar as rl_scalar  # noqa: E402
from rlvr import strategy_store  # noqa: E402

import eval_loop_runner as lr  # noqa: E402


# ---- fixtures --------------------------------------------------------------
@pytest.fixture(autouse=True)
def _store_env(monkeypatch, tmp_path):
    """Every test gets an isolated cross-task store root (the env var
    the store's own write face resolves at call time)."""
    monkeypatch.setenv(strategy_store.STORE_ENV, str(tmp_path / "store"))


def _task() -> dict:
    """Minimal task dict carrying the dims the face declares on the
    envelope (family / tier / verification method)."""
    return {
        "task_id": "unit-966",
        "family": "tf-snake",
        "tier": "smoke",
        "anchors": {"verification_method": "reproduction"},
    }


def _ws(tmp: Path) -> Path:
    """A minimal evidence-bearing workspace (the signature face walks
    whatever exists — a bare dir would work too)."""
    ws = tmp / "ws"
    (ws / "facts").mkdir(parents=True, exist_ok=True)
    (ws / "facts" / "F001-probe.md").write_text("evidence text\n",
                                                encoding="utf-8")
    return ws


def _store_rows(tmp: Path) -> list[dict]:
    """The cross-task store's rows (tolerant JSONL read — the file may
    not exist when the face settled nothing). issue-1004 R2c: rows land
    in the knowledge family file under the guarded root."""
    p = tmp / "store" / "knowledge-store.jsonl"
    if not p.is_file():
        return []
    return [r for r in (json.loads(line) for line in
                        p.read_text(encoding="utf-8").splitlines()
                        if line.strip())
            if isinstance(r, dict)]


# ---- B1: the chain fires ----------------------------------------------------
class TestChainFires:
    def test_pass_settles_one_store_row(self, tmp_path):
        ws = _ws(tmp_path)
        out = lr.runner_settlement_face(ws, task=_task(), verdict="PASS")
        assert out["settled"] is True
        assert out["credit"] == 1.0
        assert out["dispatch_id"] == "runner-loop-unit-966"

        rows = q_cells.JSONLQStore(ws).observations()
        dispatch = [r for r in rows if r.get("source") == "dispatch"]
        settle = [r for r in rows if r.get("source") == "settlement"]
        assert len(dispatch) == 1, "ONE pending dispatch row"
        assert len(settle) == 1, "ONE settled credit row"
        assert dispatch[0]["method_family"] == "tf-snake"
        assert dispatch[0]["claim"] == "runner-loop-unit-966"

        store = _store_rows(tmp_path)
        assert len(store) == 1, "EXACTLY ONE posterior-store/1 row"
        row = store[0]
        assert row["schema"] == "posterior-store/1"
        # the arm-key dims the runner declared: family|recipe|verif|tier
        # (the string task tier buckets to 0 — the boundary's coercion)
        assert row["arm_key"] == "tf-snake|facts_snapshot|reproduction|0"
        assert row["method_family"] == "tf-snake"
        assert row["credit"] == 1.0
        assert row["status"] == "ROUND_CREDIT"
        assert row["provenance"]["dispatch_id"] == "runner-loop-unit-966"

    def test_dispatch_row_envelope_dims(self, tmp_path):
        ws = _ws(tmp_path)
        out = lr.runner_settlement_face(ws, task=_task(), verdict="PASS")
        assert out["settled"] is True
        dispatch = [r for r in q_cells.JSONLQStore(ws).observations()
                    if r.get("source") == "dispatch"][0]
        assert dispatch["arm_key"] == \
            "tf-snake|facts_snapshot|reproduction|0"
        assert dispatch["signature_hash"], "a state signature was computed"
        assert dispatch["action_type"] == "dispatch"
        assert out["arm_key"] == dispatch["arm_key"], \
            "the bank result threads the matched row's arm key"


# ---- B2: the honest FAIL face ----------------------------------------------
class TestFailFace:
    def test_fail_settles_zero_credit(self, tmp_path):
        ws = _ws(tmp_path)
        out = lr.runner_settlement_face(ws, task=_task(), verdict="FAIL")
        assert out["settled"] is True, "the FAIL face must ALSO settle"
        assert out["credit"] == 0.0
        store = _store_rows(tmp_path)
        assert len(store) == 1
        assert store[0]["credit"] == 0.0
        # the settlement row banks the honest zero, so the fold's
        # failure mass (1 - credit) moves — the #966 point
        assert store[0]["arm_key"] == \
            "tf-snake|facts_snapshot|reproduction|0"


# ---- B3: no graded work settles nothing --------------------------------------
class TestNoGradedWork:
    @pytest.mark.parametrize("verdict", ["SKIP", "", None])
    def test_ungraded_settles_nothing(self, tmp_path, verdict):
        ws = _ws(tmp_path)
        out = lr.runner_settlement_face(ws, task=_task(), verdict=verdict)
        assert out["settled"] is False
        assert out["reason"] == f"ungraded:{verdict or 'none'}"
        assert q_cells.JSONLQStore(ws).observations() == []
        assert _store_rows(tmp_path) == []


# ---- B4: retry is one-shot ---------------------------------------------------
class TestRetryOneShot:
    def test_second_call_refuses_double_write(self, tmp_path):
        ws = _ws(tmp_path)
        first = lr.runner_settlement_face(ws, task=_task(), verdict="PASS")
        assert first["settled"] is True
        second = lr.runner_settlement_face(ws, task=_task(), verdict="PASS")
        assert second["settled"] is False
        assert second["reason"] == "already-settled"
        assert len(_store_rows(tmp_path)) == 1, "no second store row"
        rows = q_cells.JSONLQStore(ws).observations()
        assert len([r for r in rows
                    if r.get("source") == "settlement"]) == 1, \
            "no second banked credit row"


# ---- B5: fail-open + honest gaps ---------------------------------------------
class TestFailOpen:
    def test_bank_crash_is_one_warn_verdict_unaffected(self, tmp_path,
                                                       monkeypatch,
                                                       capsys):
        def boom(ws, row):
            raise RuntimeError("bank exploded")

        monkeypatch.setattr(rl_scalar, "_bank_q_cell_credit", boom)
        ws = _ws(tmp_path)
        out = lr.runner_settlement_face(ws, task=_task(), verdict="FAIL")
        assert out["settled"] is False
        assert out["reason"] == "error:RuntimeError"
        assert _store_rows(tmp_path) == [], "no store row on a crashed bank"
        assert "runner_settlement" in capsys.readouterr().err, \
            "ONE WARN names the operation"

    def test_undeclared_family_honest_gap(self, tmp_path):
        task = _task()
        del task["family"]
        ws = _ws(tmp_path)
        out = lr.runner_settlement_face(ws, task=task, verdict="PASS")
        assert out["settled"] is False
        assert out["reason"] == "undeclared"
        assert q_cells.JSONLQStore(ws).observations() == []
        assert _store_rows(tmp_path) == []
