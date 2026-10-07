# -*- coding: utf-8 -*-
"""tests/test_verify_transitions_550.py — verify/red-team acts enter
the transition ledger (#550: action_type=verify produces (s,a,r,s')
rows; the SMDP record face no longer excludes the verification-cadence
actions the policy is supposed to schedule).

Pinned:
  1. stash scoping — a verify act's launch stash NEVER clobbers a
     pending dispatch stash for the same claim (action-type-scoped
     paths; the dispatch path stays byte-identical for in-flight
     workspaces).
  2. row shape — verify rows carry action_type="verify" (+ the variant
     marker: verify | redteam), everything else the ledger contract
     already demands.
  3. credit — the verifier verdict maps to r_settle: verified /
     CONFIRMED ⇒ 1.0; refuted / UNVERIFIED / timeout ⇒ 0.0.
  4. back-compat — the untyped faces keep the exact legacy paths and
     behaviors (dispatch rows gain only the additive action_type
     column).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import incremental_reward as ir  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _rows(ws: Path) -> list[dict]:
    p = ws / "runs" / "transitions.jsonl"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip()]


# ------------------------------------------------------ 1. stash scoping

def test_verify_stash_never_clobbers_the_dispatch_stash(tmp_path):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-1", "static-decompile")
    ir.record_launch(ws, "C-1", "verify", action_type="verify")
    # two distinct stash files; the dispatch one is the legacy path
    assert (ws / "runs" / "dispatch-launch-C-1.json").is_file()
    assert (ws / "runs" / "dispatch-launch-C-1--verify.json").is_file()
    row_d = ir.append_transition(ws, "C-1", "TIMEOUT", r_settle=0.5)
    assert row_d is not None and row_d["action_type"] == "dispatch"
    # the verify stash survived the dispatch settle
    assert (ws / "runs" / "dispatch-launch-C-1--verify.json").is_file()
    assert not (ws / "runs" / "dispatch-launch-C-1.json").exists()


def test_verify_settle_consumes_only_the_verify_stash(tmp_path):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-1", "static-decompile")
    ir.record_launch(ws, "C-1", "verify:redteam",
                     action_type="verify", variant="redteam")
    row = ir.append_transition(ws, "C-1", "DISPATCHED", r_settle=1.0,
                               action_type="verify", variant="redteam")
    assert row is not None
    assert row["action_type"] == "verify"
    assert row["a"] == "verify:redteam"
    assert row["o"]["variant"] == "redteam"
    # the dispatch stash is still pending its own settle
    assert (ws / "runs" / "dispatch-launch-C-1.json").is_file()


# --------------------------------------------------------- 2. row shape

def test_dispatch_rows_gain_only_the_additive_column(tmp_path):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-2", "static-decompile", propensity=0.42)
    row = ir.append_transition(ws, "C-2", "DISPATCHED", r_settle=1.0)
    assert row["action_type"] == "dispatch"
    assert row["propensity"] == 0.42
    assert "variant" not in row["o"]


def test_verify_row_carries_the_full_ledger_contract(tmp_path):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-3", "verify", action_type="verify")
    row = ir.append_transition(ws, "C-3", "TIMEOUT", status="verify",
                               facts=2, seconds=1800.0, r_settle=0.0,
                               action_type="verify", variant="verify")
    assert row["dispatch_id"] == "C-3"
    assert row["action_type"] == "verify"
    assert row["o"] == {"status": "TIMEOUT", "class": "verify",
                        "facts": 2, "variant": "verify"}
    assert isinstance(row["s_prime_phi"], float)
    assert row["r_incr"] < 0.0  # 1800s of cost with no Φ move


# ------------------------------------------------------------ 3. credit

def test_verifier_verdict_credit_mapping(tmp_path):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-4", "verify", action_type="verify")
    row = ir.append_transition(ws, "C-4", "DISPATCHED", r_settle=1.0,
                               action_type="verify", variant="verify")
    assert row["r_settle"] == 1.0
    # the credit mapping helper itself (the wiring passes the verdict)
    assert ir.verify_credit("verified") == 1.0
    assert ir.verify_credit("CONFIRMED") == 1.0
    assert ir.verify_credit("refuted") == 0.0
    assert ir.verify_credit("REFUTED") == 0.0
    assert ir.verify_credit("UNVERIFIED-WITH-GAP") == 0.0
    assert ir.verify_credit("TIMEOUT") == 0.0
    assert ir.verify_credit("") == 0.0


# ------------------------------------------------------- 4. back-compat

def test_untyped_faces_keep_the_legacy_paths(tmp_path):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-5", "static-decompile")
    assert (ws / "runs" / "dispatch-launch-C-5.json").is_file()
    row = ir.append_transition(ws, "C-5", "DISPATCHED", r_settle=1.0)
    assert row is not None
    assert not (ws / "runs" / "dispatch-launch-C-5.json").exists()


def test_typed_settle_without_stash_is_a_silent_none(tmp_path):
    ws = _ws(tmp_path)
    assert ir.append_transition(
        ws, "C-6", "TIMEOUT", action_type="verify") is None
    assert _rows(ws) == []
