# -*- coding: utf-8 -*-
"""Issue #539 PR-1 — incremental reward + the transition ledger.

The 2026-10-06 owner ruling: every dispatch→outcome pair must produce a
transition (s, a, o, s', r) with a per-act incremental reward, because
one-shot settlement credit gives ordinary tool success zero signal.
These pins hold the pure-instrumentation contract:

  1. Φ(s) = verified-facts fraction + oracle green rate, renormalized
     over present dims (honest absence drops a dim);
  2. r_t = ALPHA·ΔΦ − LAMBDA·cost (potential-based: layering over the
     terminal credit cannot reorder optimal policies; Ng et al. 1999);
  3. the ledger is append-only runs/transitions.jsonl; a settle without
     a launch stash logs nothing (never invents a before-state);
  4. everything is fail-open telemetry — never an exception into the
     dispatch or settle path.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RLVR = ROOT / "scripts"
if str(RLVR) not in sys.path:
    sys.path.insert(0, str(RLVR))

from rlvr import incremental_reward as ir  # noqa: E402


def _ws(tmp_path: Path, *, facts: tuple[int, int] | None = None,
        oracle: tuple[int, int] | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "facts").mkdir(exist_ok=True)
    if facts is not None:
        verified, total = facts
        # grammar-clean, register-backed facts (the certification gate
        # honors a terminal status only when the cited claim is
        # register-PROVEN)
        import hashlib
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: PROVEN\n"
            "    question: q\n", encoding="utf-8")
        for i in range(total):
            status = "PROVEN" if i < verified else "OPEN"
            confidence = "high" if status == "PROVEN" else "medium"
            sha = hashlib.sha256(f"F{i:03d}:{status}".encode()).hexdigest()
            (ws / "facts" / f"F{i:03d}.md").write_text(
                f"---\nid: F{i:03d}-fact\ntype: fact\ntitle: fact {i}\n"
                f"created: 2026-10-11\nlast_reviewed: 2026-10-11\n"
                f"boundary_type: confirmed\npromotion_gate:\n"
                f"provenance:\n  - role: public_doc\n"
                f"    path: facts/F{i:03d}.md\n"
                f"    content_sha256: {sha}\n    credibility: B2\n"
                f"claim: claim statement\nreproduce: cmd\n"
                f"expected: out\nverified: pending\nclaim_id: C-001\n"
                f"source: public-osint\nconfidence: {confidence}\n"
                f"status: {status}\n---\n\nbody\n", encoding="utf-8")
    if oracle is not None:
        passed, total = oracle
        cases = {f"case-{i}": {"status": "pass" if i < passed else "fail"}
                 for i in range(total)}
        # 4-L7: the canonical writer shape (schema tag required by
        # the state reader's validation)
        (ws / "runs" / "oracle-status.json").write_text(
            json.dumps({"schema": "oracle-status/1", "cases": cases}),
            encoding="utf-8")
    return ws


# ---- face 1: Φ -------------------------------------------------------------

def test_potential_renormalizes_over_present_dims(tmp_path):
    # no organs at all: 0.0 (absent dims drop, never fabricate)
    assert ir.potential(_ws(tmp_path / "a")) == 0.0
    # only facts present: facts term alone (renormalized). NOTE
    # (issue-678 D-678.5): Φ's fact term reads fact_face's GRADED
    # weighted_fraction (grammar-clean certified 1.0 / substantive
    # non-terminal 0.5 / draft 0.25 / junk 0.0); this fixture's OPEN
    # fillers carry illegal source/confidence for OPEN (grammar-unclean)
    # and grade 0.0, so the numbers are unchanged from the binary era.
    ws = _ws(tmp_path / "b", facts=(2, 4))
    assert abs(ir.potential(ws) - 0.5) < 1e-9
    # both present: weighted mean of (0.5 facts, 1.0 oracle)
    ws = _ws(tmp_path / "c", facts=(2, 4), oracle=(2, 2))
    assert abs(ir.potential(ws) - (0.3 * 0.5 + 0.5 * 1.0) / 0.8) < 1e-9


# ---- face 2: r_t -----------------------------------------------------------

def test_incremental_reward_signs():
    # progress beats cost
    assert ir.incremental_reward(0.0, 0.5) == 0.5
    # no progress, pure cost: negative (the zero-signal gap closed)
    assert ir.incremental_reward(0.5, 0.5, seconds=3600.0) == -1.0
    assert ir.incremental_reward(0.5, 0.5, tokens=10_000.0) == -1.0
    # progress + cost combined
    assert ir.incremental_reward(0.0, 0.5, seconds=1800.0) == 0.0
    # regression (facts revoked): ΔΦ negative
    assert ir.incremental_reward(1.0, 0.5) == -0.5


# ---- face 3: the ledger ----------------------------------------------------

def test_launch_settle_roundtrip(tmp_path):
    ws = _ws(tmp_path, facts=(0, 2))
    ir.record_launch(ws, "C-007", action_key="strings-first")
    stash = ws / "runs" / "dispatch-launch-C-007.json"
    assert stash.is_file()  # launch recorded

    # settle: progress happened (one fact verified meanwhile)
    (ws / "facts" / "F000.md").write_text(
        "---\nid: F000-fact\ntype: fact\ntitle: fact 0\n"
        "created: 2026-10-11\nlast_reviewed: 2026-10-11\n"
        "boundary_type: confirmed\npromotion_gate:\n"
        "provenance:\n  - role: public_doc\n"
        "    path: facts/F000.md\n"
        "    content_sha256: "
        + hashlib.sha256(b"F000:PROVEN").hexdigest() + "\n"
        "    credibility: B2\nclaim: claim statement\n"
        "reproduce: cmd\nexpected: out\nverified: pending\n"
        "claim_id: C-001\nsource: public-osint\nconfidence: high\n"
        "status: PROVEN\n---\n\nbody\n", encoding="utf-8")
    row = ir.append_transition(ws, "C-007", "DISPATCHED",
                               status="done", facts=1,
                               seconds=600.0, r_settle=0.5)
    assert row is not None
    assert row["a"] == "strings-first"
    assert row["o"] == {"status": "DISPATCHED", "class": "done",
                        "facts": 1}
    assert row["r_settle"] == 0.5
    # NOTE (issue-678 D-678.5): the graded Φ fact term — the OPEN
    # fillers are grammar-unclean (illegal source/confidence for OPEN)
    # and grade 0.0, so launch Φ = 0.0 and settle Φ = 1 certified/2 =
    # 0.5 exactly as before; the graded pin lives in
    # test_reward_source_678.py
    assert abs(row["r_incr"] - (0.5 - 600.0 / 3600.0)) < 1e-6
    assert not stash.exists()  # consumed
    assert ir.read_transitions(ws) == [row]  # ledger has it


def test_settle_without_launch_logs_nothing(tmp_path):
    ws = _ws(tmp_path)
    assert ir.append_transition(ws, "C-999", "DISPATCHED") is None
    assert ir.read_transitions(ws) == []


def test_ledger_append_only_two_rows(tmp_path):
    ws = _ws(tmp_path, facts=(1, 2))
    for claim in ("C-004", "C-005"):
        ir.record_launch(ws, claim, action_key="f")
        row = ir.append_transition(ws, claim, "DISPATCHED",
                                   r_settle=1.0)
        assert row is not None
    rows = ir.read_transitions(ws)
    assert [r["dispatch_id"] for r in rows] == ["C-004", "C-005"]
