# -*- coding: utf-8 -*-
"""Issue #654 1-F1 + 1-F2 — launch-stash integrity.

The audit's lens-1 report found two accumulating shapes on the
``runs/dispatch-launch-*.json`` ↔ ``runs/transitions.jsonl`` pair:

  1-F1 — a stash whose transition never lands is dropped silently (the
  live instance: a ``--redteam`` stash written with the pre-#550 typed
  name while the settle reader read the ``verify`` name; no row, no
  trace). Fix: an end-of-run sweep that diffs the stash set against the
  transition rows on (claim, action_type) and leaves ONE warn trace when
  orphans exist.

  1-F2 — ``record_launch`` overwrites the per-claim stash with no attempt
  id; a settle that runs after a re-dispatch banks ``phi_before`` / ``a``
  from the NEWER launch. Fix: every stash carries an ``attempt_id`` and
  ``append_transition`` refuses a settle whose expected attempt id does
  not match the stash (the newer launch keeps ownership of its stash).

Back-compat pin: a settle that passes no attempt id keeps the exact
legacy behavior (in-flight/legacy callers are never broken).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_log  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _rows(ws: Path) -> list[dict]:
    return ir.read_transitions(ws)


def _warn_recorder(monkeypatch) -> list[tuple[str, str]]:
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        kunglao_log, "warn",
        lambda op, reason, **kw: calls.append((str(op), str(reason))))
    return calls


# ---------------------------------------------------------------- 1-F2

def test_record_launch_stamps_an_attempt_id(tmp_path):
    ws = _ws(tmp_path)
    doc = ir.record_launch(ws, "C-1", "strings-first")
    assert isinstance(doc, dict)
    assert str(doc.get("attempt_id") or "").strip()
    on_disk = json.loads(
        (ws / "runs" / "dispatch-launch-C-1.json").read_text("utf-8"))
    assert on_disk["attempt_id"] == doc["attempt_id"]


def test_stale_settle_refused_after_redispatch(tmp_path):
    ws = _ws(tmp_path)
    first = ir.record_launch(ws, "C-1", "strings-first")
    second = ir.record_launch(ws, "C-1", "packer-first")  # re-dispatch
    assert first["attempt_id"] != second["attempt_id"]

    # the older attempt's settle must NOT bank the newer launch's state
    assert ir.append_transition(
        ws, "C-1", "TIMEOUT", attempt_id=first["attempt_id"]) is None
    assert _rows(ws) == []
    # the newer stash is untouched — it still owns its own settle
    stash = ws / "runs" / "dispatch-launch-C-1.json"
    assert stash.is_file()
    assert json.loads(stash.read_text("utf-8"))["attempt_id"] \
        == second["attempt_id"]

    row = ir.append_transition(ws, "C-1", "DISPATCHED",
                               attempt_id=second["attempt_id"])
    assert row is not None and row["a"] == "packer-first"
    assert not stash.exists()


def test_refused_stale_settle_leaves_one_warn_trace(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    first = ir.record_launch(ws, "C-1", "a")
    ir.record_launch(ws, "C-1", "b")
    calls = _warn_recorder(monkeypatch)
    assert ir.append_transition(
        ws, "C-1", "TIMEOUT", attempt_id=first["attempt_id"]) is None
    assert len(calls) == 1
    assert calls[0][0] == "incremental_reward.append_transition"


def test_settle_without_attempt_id_keeps_legacy_behavior(tmp_path):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-2", "strings-first")
    row = ir.append_transition(ws, "C-2", "DISPATCHED", r_settle=1.0)
    assert row is not None and row["a"] == "strings-first"


def test_typed_stashes_carry_independent_attempt_ids(tmp_path):
    ws = _ws(tmp_path)
    d = ir.record_launch(ws, "C-3", "strings-first")
    v = ir.record_launch(ws, "C-3", "verify", action_type="verify")
    assert d["attempt_id"] != v["attempt_id"]
    # the dispatch settle (no id) consumes only the dispatch stash
    assert ir.append_transition(ws, "C-3", "DISPATCHED") is not None
    stale = ir.append_transition(ws, "C-3", "DISPATCHED",
                                 action_type="verify",
                                 attempt_id=d["attempt_id"])
    assert stale is None  # the dispatch id never matches the verify stash
    assert ir.append_transition(ws, "C-3", "TIMEOUT", action_type="verify",
                                attempt_id=v["attempt_id"]) is not None


# ---------------------------------------------------------------- 1-F1

def test_sweep_flags_orphan_with_one_warn(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    # the pair key is (claim, action_type); the redteam variant rides the
    # doc beside action_type="verify" (the #550 scoping), never the pair
    ir.record_launch(ws, "C-005", "x", action_type="verify",
                     variant="redteam")
    calls = _warn_recorder(monkeypatch)
    orphans = ir.sweep_orphan_launches(ws)
    assert [(o["claim"], o["action_type"]) for o in orphans] \
        == [("C-005", "verify")]
    assert len(calls) == 1
    assert calls[0][0] == "incremental_reward.sweep_orphan_launches"


def test_sweep_clean_when_the_pair_has_a_transition_row(tmp_path,
                                                        monkeypatch):
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-1", "x")
    assert ir.append_transition(ws, "C-1", "DISPATCHED") is not None
    calls = _warn_recorder(monkeypatch)
    assert ir.sweep_orphan_launches(ws) == []
    assert calls == []


def test_sweep_is_action_type_scoped(tmp_path):
    """A dispatch row never excuses an orphaned verify stash (the live
    1-F1 shape: the pair key is (claim, action_type))."""
    ws = _ws(tmp_path)
    ir.record_launch(ws, "C-1", "x")
    ir.record_launch(ws, "C-1", "verify", action_type="verify")
    assert ir.append_transition(ws, "C-1", "DISPATCHED") is not None
    orphans = ir.sweep_orphan_launches(ws)
    assert [(o["claim"], o["action_type"]) for o in orphans] \
        == [("C-1", "verify")]


def test_sweep_reads_foreign_stash_from_the_filename(tmp_path):
    """A stash doc that carries no claim/action_type fields (the parked
    orchestrator envelope, 1-F3's live shape) still gets diffed by its
    filename identity."""
    ws = _ws(tmp_path)
    (ws / "runs" / "dispatch-launch-C-004--redteam.json").write_text(
        json.dumps({"status": "PARKED_NOT_LAUNCHED"}), encoding="utf-8")
    orphans = ir.sweep_orphan_launches(ws)
    assert [(o["claim"], o["action_type"]) for o in orphans] \
        == [("C-004", "redteam")]


def test_sweep_never_raises_on_a_broken_workspace(tmp_path):
    ws = tmp_path / "bare"
    assert ir.sweep_orphan_launches(ws) == []
