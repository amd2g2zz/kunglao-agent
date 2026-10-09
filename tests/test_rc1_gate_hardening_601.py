# -*- coding: utf-8 -*-
"""Issue 601 RC1 hardening — gate-side pins (S26a).

Fix 1 (audit 5-F6): a runs/proven-waiver-<cid>.md with a bare `justify:`
line was a one-file self-service PROVEN (the file lives in act-writable
runs/). The waiver now counts only when it carries the orchestrator stamp —
the review_gate canonical-stamp shape (HMAC frontmatter digest over
cid+ts, documented per-run constant, no new deps). An unstamped waiver
reads as ABSENT: loud warn, verify/red-team legs stay enforced.

"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from register_proven_gate import (  # noqa: E402
    check_register_transitions,
    stamp_waiver,
    waiver_stamp,
)

REG2 = (
    "claims:\n"
    "  - id: C-001\n"
    "    status: {s1}\n"
    "    statement: synthetic claim for gate tests\n"
    "  - id: C-002\n"
    "    status: {s2}\n"
    "    statement: second synthetic claim\n")


def _reg(s1: str = "OPEN", s2: str = "OPEN") -> str:
    return REG2.format(s1=s1, s2=s2)


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(_reg(), encoding="utf-8")
    return ws


def _waiver_text(cid: str, justify: str) -> str:
    return f"---\nclaim_id: {cid}\n---\n\njustify: {justify}\n"


# ---------- Fix 1 (5-F6): the waiver skip needs the orchestrator stamp ------

def test_unstamped_waiver_refuses_the_skip(tmp_path):
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "proven-waiver-C-001.md").write_text(
        _waiver_text("C-001", "self-serve: looks done to me"),
        encoding="utf-8")
    res = check_register_transitions(ws, _reg("PROVEN"), _reg())
    assert res["ok"] is False
    assert res["waivers"] == []
    # legs enforced: the violation names the missing verify/red-team face
    assert any("verify-note" in v or "red-team" in v
               for v in res["violations"]), res["violations"]


def test_stamped_waiver_skips_the_legs(tmp_path):
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "proven-waiver-C-001.md").write_text(
        _waiver_text("C-001", "operator override: family already public"),
        encoding="utf-8")
    minted = stamp_waiver(ws, "C-001")
    assert minted["ok"] is True, minted
    res = check_register_transitions(ws, _reg("PROVEN"), _reg())
    assert res["ok"] is True, res["violations"]
    assert res["waivers"] and res["waivers"][0]["claim_id"] == "C-001"
    assert "operator override" in res["waivers"][0]["justify"]


def test_stamp_binds_the_claim_id(tmp_path):
    """A stamp lifted from C-001's waiver onto C-002's file verifies against
    (C-002, ts) and fails — the digest binds the claim id."""
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "proven-waiver-C-001.md").write_text(
        _waiver_text("C-001", "operator override"), encoding="utf-8")
    assert stamp_waiver(ws, "C-001")["ok"] is True
    stamped = (ws / "runs" / "proven-waiver-C-001.md").read_text(
        encoding="utf-8")
    (ws / "runs" / "proven-waiver-C-002.md").write_text(
        stamped.replace("C-001", "C-002"), encoding="utf-8")
    res = check_register_transitions(ws, _reg("OPEN", "PROVEN"), _reg())
    assert res["ok"] is False
    assert all(w["claim_id"] != "C-002" for w in res["waivers"])


def test_stamped_empty_justify_still_blocks(tmp_path):
    """The stamp is authority, not a reason: a stamped waiver with no
    non-empty justify: line stays a violation (fail-closed mint means this
    only reaches the gate via a hand-crafted stamp)."""
    ws = _mk_ws(tmp_path)
    ts = 1760000000
    text = (f"---\nclaim_id: C-001\nts: {ts}\n"
            f"stamp: {waiver_stamp('C-001', ts)}\n---\n\njustify:\n")
    (ws / "runs" / "proven-waiver-C-001.md").write_text(text, encoding="utf-8")
    res = check_register_transitions(ws, _reg("PROVEN"), _reg())
    assert res["ok"] is False
    assert any("justify is empty" in v for v in res["violations"])


def test_mint_face_refuses_missing_waiver(tmp_path):
    ws = _mk_ws(tmp_path)
    assert stamp_waiver(ws, "C-404")["ok"] is False


def test_mint_face_refuses_empty_justify(tmp_path):
    """Fail-closed mint: an exemption without a stated reason never gets a
    stamp from the orchestrator face."""
    ws = _mk_ws(tmp_path)
    (ws / "runs" / "proven-waiver-C-001.md").write_text(
        _waiver_text("C-001", ""), encoding="utf-8")
    assert stamp_waiver(ws, "C-001")["ok"] is False
