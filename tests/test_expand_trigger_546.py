# -*- coding: utf-8 -*-
"""tests/test_expand_trigger_546.py — the discovery-layer trigger
recalibration pins (the approved owner ruling): the obstacle bar is
budget-calibrated (two rows — the shape a two-hour budget actually
stacks), and the loop-stall arm ORs into the predicate as a SPEND-ONLY
face. The invariant under test: the stall arm only spends the
discovery move — it never kills, parks, downweights, or writes
anywhere; the option-death estimator keeps sole authority over
parking."""
from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import expansion as ex  # noqa: E402
from rlvr import obstacles as obs  # noqa: E402
from rlvr import state as rlvr_state  # noqa: E402
from rlvr import termination  # noqa: E402

DEAD_FAM = "static-decompile"
LIVE_FAM = "kdf-chain-reconstruction"


def _dead(fam: str = DEAD_FAM) -> dict:
    return {fam: {"dead": True}}


def _alive(fam: str = LIVE_FAM) -> dict:
    return {fam: {"dead": False}}


def _stall(stalled: bool = True) -> dict:
    return {"stalled": stalled, "moves": [0.0, 0.0, 0.0],
            "window": 3, "epsilon": 0.02}


# ------------------------------------------------ the budget-calibrated bar

def test_the_obstacle_bar_is_two():
    """Two rows is the calibrated bar: the measured shape a two-hour
    budget stacks (about one hard kill per hour) — the canonical
    fixed-m stopping size, not a taller bar no budget can reach."""
    assert ex.EXPAND_OBSTACLE_K == 2
    doc = ex.trigger({"obstacles": {"count": 2}}, _dead())
    assert doc is not None
    assert doc["obstacle_count"] == 2
    assert doc["arm"] == "family-death"
    # one row still falls short of the bar
    assert ex.trigger({"obstacles": {"count": 1}}, _dead()) is None


# ---------------------------------------------------- the loop-stall arm

def test_slow_grind_fires_via_the_loop_stall_arm(tmp_path):
    """The measured near-miss shape: the registry stacks to the bar
    while every death cell stays under the line, and the flat
    potential tail spends the move — the receipt names the arm."""
    doc = ex.trigger({"obstacles": {"count": 2}}, _alive(), _stall())
    assert doc is not None
    assert doc["arm"] == "loop-stall"
    assert doc["collapsed_arms"] == []
    receipt = ex.record_receipt(tmp_path, doc, [], [])
    assert receipt["trigger"]["arm"] == "loop-stall"


def test_phi_moving_keeps_the_family_death_only_predicate():
    """A potential that still moves is not a stall: without a dead
    family the old no-fire behavior holds unchanged."""
    assert ex.trigger({"obstacles": {"count": 2}}, _alive(),
                      _stall(stalled=False)) is None
    assert ex.trigger({"obstacles": {"count": 2}}, _alive()) is None


def test_family_death_names_the_arm_when_both_arms_hold():
    """A family death is the stronger evidence: when both arms hold,
    the receipt names family-death."""
    doc = ex.trigger({"obstacles": {"count": 2}}, _dead(), _stall())
    assert doc is not None
    assert doc["arm"] == "family-death"


def test_stall_constants_carry_the_measured_defaults():
    """The window is half the transitions a two-hour budget settles
    (so a stall only reads in the run's back half) and the epsilon
    sits at the measured grind-phase move scale."""
    assert ex.STALL_WINDOW_TICKS == 3
    assert ex.STALL_EPSILON == 0.02


# -------------------------------------------------- the stall face reader

def test_loop_stalled_window_semantics():
    """A flat potential tail at the grind scale reads as stalled; one
    real move inside the window breaks it; the window is a TAIL read
    over the settlement stream's consecutive transitions."""
    flat = [0.10, 0.102, 0.104, 0.105]
    face = ex.loop_stalled(flat)
    assert face["stalled"] is True
    assert len(face["moves"]) == ex.STALL_WINDOW_TICKS
    assert all(m < ex.STALL_EPSILON for m in face["moves"])
    # one real move inside the window breaks the stall
    assert ex.loop_stalled([0.10, 0.102, 0.104, 0.30])["stalled"] is False
    # tail semantics: an old mover outside the window is spent history
    assert ex.loop_stalled(
        [0.10, 0.30, 0.302, 0.304, 0.305])["stalled"] is True
    # a backward move is not progress either: it counts toward stall
    assert ex.loop_stalled([0.50, 0.40, 0.30, 0.20])["stalled"] is True
    # too few transitions: no stall can be established yet
    assert ex.loop_stalled([0.10, 0.10])["stalled"] is False
    assert ex.loop_stalled([])["stalled"] is False
    # malformed series fails closed (the wiring then passes nothing)
    assert ex.loop_stalled(None) is None
    assert ex.loop_stalled("nope") is None
    # junk rows are skipped, not fatal — the stall just gets harder
    # to establish (the conservative direction)
    short = ex.loop_stalled([0.1, "x", object()])
    assert short is not None and short["stalled"] is False


# -------------------------------------------------------- the invariant

def _tree(root: Path) -> dict:
    out: dict = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


def _seed_two_walls(ws: Path) -> None:
    """Two attributed walls on DIFFERENT kinds: the registry stacks to
    the bar while every death cell stays under the line (one row per
    cell is short of the death threshold)."""
    ev = ws / "runs" / "ev.md"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text("cmd: uname\nrc=0\n-> Linux\n", encoding="utf-8")
    for kind, tag in (("tool_limit", "wall-a"), ("other", "wall-b")):
        obs.record(str(ws), kind=kind, cause=tag,
                   evidence_path="runs/ev.md",
                   method_family=DEAD_FAM, claim=f"C-{tag}")


def test_the_stall_arm_writes_nothing(tmp_path):
    """THE HARD INVARIANT: firing via the stall arm leaves the whole
    workspace byte-identical — no registry write, no receipt, no
    overlay, no estimator face touched — and the death verdicts it
    read are neither mutated nor re-folded differently."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _seed_two_walls(ws)
    fams = [DEAD_FAM]
    death_before = termination.verdicts(str(ws), fams)
    assert death_before[DEAD_FAM]["dead"] is False
    snap = rlvr_state.snapshot(str(ws))
    assert (snap.get("obstacles") or {}).get("count") == 2
    before = _tree(ws)
    death_frozen = copy.deepcopy(death_before)
    doc = ex.trigger(snap, death_frozen, _stall())
    assert doc is not None and doc["arm"] == "loop-stall"
    assert _tree(ws) == before, "the stall arm wrote somewhere"
    assert death_frozen == death_before, "the death verdicts were mutated"
    assert termination.verdicts(str(ws), fams) == death_before
    # the same purity holds for the family-death arm
    doc2 = ex.trigger(snap, _dead(), None)
    assert doc2 is not None and doc2["arm"] == "family-death"
    assert _tree(ws) == before


# ------------------------------------------------------------ fail-closed

def test_stall_face_absent_or_malformed_is_family_death_only():
    """An absent or malformed stall face degrades to the old
    family-death-only predicate — never to a stall fire."""
    for bad in (None, {}, {"stalled": "yes"}, {"stalled": 1}, 7, "x", []):
        assert ex.trigger({"obstacles": {"count": 2}}, _alive(),
                          bad) is None, f"stall fired on {bad!r}"
        doc = ex.trigger({"obstacles": {"count": 2}}, _dead(), bad)
        assert doc is not None
        assert doc["arm"] == "family-death"
