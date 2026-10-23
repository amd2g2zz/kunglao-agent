# -*- coding: utf-8 -*-
"""tests/test_claims_store_800.py — claims_store: one state owner with a
legal-transition matrix (issue #800).

The card's pins:

  1. Illegal PROVEN->IN_PROGRESS is refused at the store and a
     provenance row is written (the matrix is DEFAULT-DENY).
  2. Crash-in-the-middle (SIGKILL between mutator steps) leaves NO
     partial state — the intent journal + verify recovery restores the
     before-image.
  3. The #623 (rejected dispatch leaves nothing behind) and #624
     (in-flight claim not dispatchable) scenarios replay green through
     the store.
  4. The rc=2 compensation saga is grep-clean from dispatch_gate and
     the worker_budget approval tail routes through the store.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _factories import write_claims_register  # noqa: E402
import claims_store as cs  # noqa: E402


def _ws(tmp_path: Path, claims: list[dict] | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, claims or [{"id": "C-1", "status": "OPEN",
                                         "dispatch_count": 0}])
    return ws


def _reg(ws: Path) -> list[dict]:
    import ws_yaml
    doc = ws_yaml.yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    return doc.get("claims") or []


def _prov(ws: Path) -> list[dict]:
    p = ws / cs.PROVENANCE_REL
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _anchor_rows(ws: Path, claim: str = "C-1") -> list[dict]:
    p = ws / "runs" / f".dispatch-anchor-{claim.replace('-', '')}.jsonl"
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ------------------------------------------- 1. the matrix is default-deny

def test_proven_to_in_progress_refused_with_provenance(tmp_path) -> None:
    """Pin 1: a terminal claim cannot re-enter the flight path; the
    refusal is not silent — one provenance row names it."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN"}])
    r = cs.apply(ws, "C-1", "dispatch", actor="test")
    assert r.ok is False
    assert r.reason and "illegal" in r.reason.lower()
    assert _reg(ws)[0]["status"] == "PROVEN", "register byte-unchanged"
    rows = _prov(ws)
    assert len(rows) == 1
    row = rows[0]
    assert row["outcome"] == "refused"
    assert row["claim"] == "C-1" and row["event"] == "dispatch"
    assert row["from"] == "PROVEN" and row["to"] is None
    assert row["schema"] == "claims-provenance/1"


def test_park_without_wake_condition_refused(tmp_path) -> None:
    """status_defs carrier-consistency rule (f): a PARK must carry a
    wake_condition — the store enforces it at the transition."""
    ws = _ws(tmp_path)
    r = cs.apply(ws, "C-1", "park", actor="test")
    assert r.ok is False
    assert "wake" in r.reason.lower()
    assert _reg(ws)[0]["status"] == "OPEN"
    r2 = cs.apply(ws, "C-1", "park", actor="test",
                  wake_condition="external gate lifts")
    assert r2.ok is True and _reg(ws)[0]["status"] == "PARK"


def test_in_progress_not_dispatchable_624(tmp_path) -> None:
    """Pin 3b (#624): a claim already in flight is NOT dispatchable —
    the double-dispatch is refused at the semantic owner."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    r = cs.apply(ws, "C-1", "dispatch", actor="test")
    assert r.ok is False
    assert _reg(ws)[0]["status"] == "IN_PROGRESS"


def test_settle_transition_applies_with_provenance(tmp_path) -> None:
    ws = _ws(tmp_path, [{"id": "C-1", "status": "IN_PROGRESS"}])
    r = cs.apply(ws, "C-1", "settle_proven", actor="settler",
                 evidence="oracle 3/3")
    assert r.ok is True and r.to_status == "PROVEN"
    row = _prov(ws)[-1]
    assert row["outcome"] == "applied" and row["actor"] == "settler"
    assert row["from"] == "IN_PROGRESS" and row["to"] == "PROVEN"


# --------------------------------- 2. the dispatch transaction is atomic

def test_dispatch_happy_path_commits_one_register_rewrite(tmp_path) -> None:
    ws = _ws(tmp_path)
    b = cs.begin_dispatch(ws, "C-1", actor="orchestrator", tier=2,
                          prompt="d", agent="w1",
                          method_family="static-decompile",
                          branch_budget={"wall_s": 300})
    assert b.ok is True
    c = cs.commit_dispatch(ws, "C-1")
    assert c.ok is True
    claim = _reg(ws)[0]
    assert claim["status"] == "IN_PROGRESS"
    assert claim["evidence_tier_attempted"] == 2
    assert claim["dispatch_count"] == 1
    rows = _anchor_rows(ws)
    assert len(rows) == 1 and rows[0]["claim"] == "C-1" and rows[0]["ts"]
    assert (ws / "runs" / "dispatch-launch-C-1.json").is_file()
    j = cs._journal_load(ws)
    assert j and j["state"] == "committed", "commit keeps the journal open"
    assert cs.confirm_dispatch(ws, "C-1") is True
    assert not (ws / cs.JOURNAL_REL).exists(), "confirm clears the journal"
    assert [r["outcome"] for r in _prov(ws)] == ["applied"]


def test_abort_inverts_exactly_623(tmp_path) -> None:
    """Pin 3a (#623): a REJECTED attempt leaves nothing behind — the
    journal-driven abort inverts exactly what the commit applied."""
    ws = _ws(tmp_path)
    cs.begin_dispatch(ws, "C-1", actor="orchestrator", tier=1,
                      prompt="d", agent="w1")
    cs.commit_dispatch(ws, "C-1")
    r = cs.abort_dispatch(ws, "C-1", actor="dispatch_gate")
    assert r.ok is True
    claim = _reg(ws)[0]
    assert claim["status"] == "OPEN", "flip rolled back"
    assert claim["dispatch_count"] == 0, "count not charged"
    assert "evidence_tier_attempted" not in claim
    assert _anchor_rows(ws) == [], "no anchor row left"
    assert not (ws / "runs" / "dispatch-launch-C-1.json").exists()
    assert not (ws / cs.JOURNAL_REL).exists()
    assert "aborted" in [r["outcome"] for r in _prov(ws)]


def _child_script(crash_after: str) -> str:
    return textwrap.dedent(f"""
        import os, signal, sys
        sys.path.insert(0, {str(SCRIPTS)!r})
        import claims_store as cs
        ws = sys.argv[1]
        cs.begin_dispatch(ws, "C-1", actor="hook", tier=1, prompt="d",
                          agent="w1")
        j = cs._journal_load(ws)
        name = "{crash_after}"
        step = dict(cs._TXN_STEPS)[name]
        cs._txn_run_step(ws, j, name, step)
        os.kill(os.getpid(), signal.SIGKILL)
    """)


def _dead_pid() -> int:
    """A real, reaped pid (for the crash-between-hooks fixture)."""
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def test_sigkill_between_steps_leaves_no_partial_state(tmp_path) -> None:
    """Pin 2: SIGKILL after step 1 of 3 — the next store open recovers
    the journal and the workspace shows NO partial state."""
    ws = _ws(tmp_path)
    script = tmp_path / "crash_child.py"
    script.write_text(_child_script("anchor"), encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run([sys.executable, str(script), str(ws)],
                       check=True)
    assert len(_anchor_rows(ws)) == 1, "step 1 did land"
    assert _reg(ws)[0]["status"] == "OPEN", "step 3 never ran"
    assert (ws / cs.JOURNAL_REL).is_file(), "journal survives the kill"
    rec = cs.recover(ws)
    assert rec and rec[0].ok is True
    assert _anchor_rows(ws) == [], "anchor tail rolled back"
    assert _reg(ws)[0]["status"] == "OPEN"
    assert _reg(ws)[0]["dispatch_count"] == 0
    assert not (ws / "runs" / "dispatch-launch-C-1.json").exists()
    assert not (ws / cs.JOURNAL_REL).exists()
    row = _prov(ws)[-1]
    assert row["outcome"] == "recovered"


def test_sigkill_after_register_step_restores_before_image(tmp_path) -> None:
    ws = _ws(tmp_path)
    script = tmp_path / "crash_child2.py"
    script.write_text(_child_script("register"), encoding="utf-8")
    with pytest.raises(subprocess.CalledProcessError):
        subprocess.run([sys.executable, str(script), str(ws)],
                       check=True)
    assert _reg(ws)[0]["status"] == "IN_PROGRESS", "step 3 did land"
    cs.recover(ws)
    claim = _reg(ws)[0]
    assert claim["status"] == "OPEN"
    assert claim["dispatch_count"] == 0
    assert _anchor_rows(ws) == []


def test_crash_between_hooks_recovers(tmp_path) -> None:
    """The #623/#624/#690 crash shape: the approval point committed, the
    gate never answered (dead pid), the journal rides — recovery rolls
    it back instead of leaving an orphan IN_PROGRESS + anchor + step."""
    ws = _ws(tmp_path)
    cs.begin_dispatch(ws, "C-1", actor="orchestrator", tier=1,
                      prompt="d", agent="w1")
    cs.commit_dispatch(ws, "C-1")
    j = cs._journal_load(ws)
    j["pid"] = _dead_pid()  # the hook process is gone
    cs._journal_save(ws, j)
    rec = cs.recover(ws)
    assert rec and rec[0].ok is True
    assert _reg(ws)[0]["status"] == "OPEN"
    assert _anchor_rows(ws) == []
    assert not (ws / cs.JOURNAL_REL).exists()


def test_reject_then_redispatch_replays_624(tmp_path) -> None:
    """After the abort the claim is honestly OPEN again — the frontier
    re-dispatches through the store without a stale in-flight marker."""
    ws = _ws(tmp_path)
    cs.begin_dispatch(ws, "C-1", actor="o", tier=1, prompt="d", agent="w")
    cs.commit_dispatch(ws, "C-1")
    cs.abort_dispatch(ws, "C-1", actor="dispatch_gate")
    cs.begin_dispatch(ws, "C-1", actor="o", tier=1, prompt="d", agent="w")
    r = cs.commit_dispatch(ws, "C-1")
    assert r.ok is True
    assert _reg(ws)[0]["status"] == "IN_PROGRESS"
    assert _reg(ws)[0]["dispatch_count"] == 1


# ------------------------------------------------- 4. the saga is deleted

def test_dispatch_gate_saga_grep_clean() -> None:
    """Pin 4: no undo_dispatch_anchor / reopen_claim_no_worker /
    cancel_step_open CALL remains in dispatch_gate (a historical note in
    a comment is documentation; a call or import is the saga)."""
    import re
    src = (ROOT / "hooks" / "dispatch_gate.py").read_text(encoding="utf-8")
    for name in ("undo_dispatch_anchor", "reopen_claim_no_worker",
                 "cancel_step_open"):
        assert not re.search(rf"\b{name}\s*\(", src), \
            f"compensation saga call remains: {name}"
        assert f"import {name}" not in src and f"{name}," not in src, \
            f"compensation saga import remains: {name}"


def test_worker_budget_tail_routes_through_store() -> None:
    src = (ROOT / "hooks" / "worker_budget_sinks.py").read_text(
        encoding="utf-8")
    assert "claims_store" in src, "approval tail must route through the store"
    assert "def _flip_claim_in_progress" not in src, \
        "the local flip writer is folded into the store"
