# -*- coding: utf-8 -*-
"""Tests for the closure citation protocol (issue 233).

`closed_by` free text was the one unbound negative exit on the completion
surface. The uniform rule (positive AND negative closures): a closure must
cite a claim id; the cited claim must be terminal; a closure citing an
obstacle claim must meet the pinned standard for its scope (path-scoped =
REFUTED; task-scoped = the DEFERRED standard markers). No "negative-flavored"
text classification — one mechanical check: claim-id grammar + claim-state
lookup against the workspace claim-register.yaml (fail-closed on
unverifiable, mirroring find_death_evidence).
"""
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"

_spec = importlib.util.spec_from_file_location(
    "completion_gate_scripts_233", SCRIPTS / "completion_gate.py")
cg = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("completion_gate_scripts", cg)
_spec.loader.exec_module(cg)


# ---------------------------------------------------------------------------
# Fixtures — a workspace register exercising every claim state the protocol
# distinguishes (synthetic ids; no live data).
# ---------------------------------------------------------------------------

REGISTER_CLAIMS = [
    {"id": "C-1", "status": "OPEN"},
    {"id": "C-2", "status": "REFUTED", "origin": "failure-obstacle",
     "obstacle_for": "C-1"},
    {"id": "C-3", "status": "OPEN", "origin": "failure-obstacle",
     "obstacle_for": "C-1"},
    {"id": "C-4", "status": "VERIFIED"},
    {"id": "C-5", "status": "DEFERRED", "deferred_reason": "infeasible",
     "wake_condition": "new firmware sample arrives",
     "infeasible_ladder": "runs/infeasible-ladder-C-5.yaml"},
    {"id": "C-6", "status": "DEFERRED"},
    {"id": "C-7", "status": "STALE"},
]


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": REGISTER_CLAIMS}, allow_unicode=True),
        encoding="utf-8")
    return ws


def _oracle(ws: Path, items: list) -> dict:
    return {
        "task_text": "do X",
        "workspace_path": str(ws),
        "open_items": items,
        "deferrals": [],
    }


def _judge(oracle):
    return cg.judge(oracle)


# ---------------------------------------------------------------------------
# (1) The incident: prose closed_by — no claim id
# ---------------------------------------------------------------------------

def test_prose_closure_fails_with_named_reason(ws):
    """Issue 233 acceptance: 'app only trusts system certs' closes nothing."""
    oracle = _oracle(ws, [
        {"id": "G4", "desc": "traffic capture", "closed_by":
         "app only trusts system certs"}])
    code, reason = _judge(oracle)
    assert code == 1, f"prose closure must fail, got {code}: {reason}"
    assert "INVALID_CLOSURE" in reason, reason
    assert "G4" in reason, "reason must name the item"
    assert "claim id" in reason, reason


def test_prose_closure_positive_flavor_also_fails(ws):
    """Uniform rule: positive-flavored prose ('commit 0001') fails too."""
    oracle = _oracle(ws, [
        {"id": "A", "desc": "A", "closed_by": "commit 0001"}])
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" in reason


# ---------------------------------------------------------------------------
# (2) Terminality: OPEN citation rejected
# ---------------------------------------------------------------------------

def test_open_claim_citation_rejected(ws):
    oracle = _oracle(ws, [{"id": "A", "desc": "A", "closed_by": "C-1 OPEN"}])
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" in reason
    assert "C-1" in reason and "OPEN" in reason, reason


def test_unknown_claim_citation_rejected(ws):
    oracle = _oracle(ws, [{"id": "A", "desc": "A", "closed_by": "C-99"}])
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" in reason
    assert "C-99" in reason, reason


# ---------------------------------------------------------------------------
# (3) Obstacle scope: path-scoped standard = REFUTED
# ---------------------------------------------------------------------------

def test_obstacle_claim_not_refuted_rejected(ws):
    """A settled-but-not-REFUTED obstacle claim cannot license a closure;
    an OPEN obstacle claim certainly cannot."""
    oracle = _oracle(ws, [{"id": "A", "desc": "A", "closed_by": "C-3"}])
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" in reason
    assert "C-3" in reason, reason


def test_refuted_obstacle_claim_citation_passes(ws):
    """Path-scoped standard met: obstacle claim REFUTED -> closure passes."""
    oracle = _oracle(ws, [{"id": "A", "desc": "A",
                           "closed_by": "C-2 REFUTED obstacle"}])
    code, reason = _judge(oracle)
    assert code == 0, reason


# ---------------------------------------------------------------------------
# (4) Task-scoped negative: the DEFERRED standard
# ---------------------------------------------------------------------------

def test_deferred_without_standard_rejected(ws):
    oracle = _oracle(ws, [{"id": "A", "desc": "A", "closed_by": "C-6"}])
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" in reason
    assert "C-6" in reason, reason


def test_deferred_with_standard_passes(ws):
    """wake_condition + infeasible_ladder present (the proposal markers) -> pass."""
    oracle = _oracle(ws, [{"id": "A", "desc": "A", "closed_by": "C-5 DEFERRED"}])
    code, reason = _judge(oracle)
    assert code == 0, reason


# ---------------------------------------------------------------------------
# (5) Positive closures cite too
# ---------------------------------------------------------------------------

def test_verified_claim_citation_passes(ws):
    oracle = _oracle(ws, [{"id": "A", "desc": "A", "closed_by": "C-4"}])
    code, reason = _judge(oracle)
    assert code == 0, reason


def test_mixed_valid_and_invalid_named_individually(ws):
    oracle = _oracle(ws, [
        {"id": "OK", "desc": "ok", "closed_by": "C-4"},
        {"id": "BAD", "desc": "bad", "closed_by": "not a citation"},
    ])
    code, reason = _judge(oracle)
    assert code == 1
    assert "BAD" in reason
    assert "OK" not in reason.split("INVALID_CLOSURE")[1], \
        "only the invalid item is named in the INVALID_CLOSURE clause"


# ---------------------------------------------------------------------------
# (6) Fail-closed: unverifiable citation
# ---------------------------------------------------------------------------

def test_no_workspace_path_citation_unverifiable(tmp_path):
    oracle = {"task_text": "do X",
              "open_items": [{"id": "A", "desc": "A", "closed_by": "C-4"}]}
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" in reason
    assert "unverifiable" in reason.lower(), reason


def test_missing_register_citation_unverifiable(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    oracle = {"task_text": "do X", "workspace_path": str(ws),
              "open_items": [{"id": "A", "desc": "A", "closed_by": "C-4"}]}
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" in reason
    assert "unverifiable" in reason.lower(), reason


def test_empty_closed_by_stays_plainly_unresolved(ws):
    """No citation at all = the pre-existing unresolved path (not
    INVALID_CLOSURE) — the empty case keeps its original semantics."""
    oracle = _oracle(ws, [{"id": "A", "desc": "A", "closed_by": ""}])
    code, reason = _judge(oracle)
    assert code == 1
    assert "INVALID_CLOSURE" not in reason
    assert "A" in reason
