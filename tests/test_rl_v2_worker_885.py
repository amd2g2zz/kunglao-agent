# -*- coding: utf-8 -*-
"""tests/test_rl_v2_worker_885.py — the construction-style faces (issue 885).

RED-first pins for the worker-construction + observation-hook faces:

  1. ``workers/spawner`` — the spawn RECEIPT is the deliverable: it
     carries the frozen snapshot excerpt, the pattern cards, the
     budget envelope and the time-box the worker was CONSTRUCTED
     with, and is auditable + deterministic (content-hash spawn id,
     never wall clock). The face prepares, never launches — the
     launch stays caller-owned;
  2. ``workers/brief`` — dispatch brief assembly: the five sections
     (goal, facts, cards, budget, tools) complete, deterministic, and
     ORCHESTRATOR-FED (no retrieval face exists — the brief carries
     the knowledge);
  3. ``hooks/observer`` — observation-only capture: worker tool calls
     land in the consolidated TELEMETRY ledger (observer-call/1),
     fail-open (a broken capture path never raises into the caller),
     and carry no blocking semantics;
  4. ``hooks/budget_tracker`` — continuous budget visibility: spent
     vs the Budget envelope read from the ledger's result-row cost
     columns, remaining reported, observation only;
  5. the fail-closed reject pins at every boundary (empty goal,
     garbage budget, non-mapping snapshot, structural-garbage rows).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import hooks  # noqa: E402
import workers  # noqa: E402
from core import Budget  # noqa: E402
from hooks import budget_tracker, observer  # noqa: E402
from rlvr import consolidated_ledger as _cl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from workers import brief, spawner  # noqa: E402

SNAPSHOT = {"signature_hash": "a" * 12, "goal_depth": 2}
CARDS = ({"id": "card-1", "method_family": "mod-crypto",
          "verdict": "PROVEN"},
         {"id": "card-2", "method_family": "smc-x86",
          "verdict": "PROVEN"})


def _card(cid="card-1", **over):
    doc = {"id": cid, "method_family": "mod-crypto",
           "verdict": "PROVEN"}
    doc.update(over)
    return doc


def _spawn(**over):
    kwargs = dict(goal="recover the key schedule",
                  snapshot=dict(SNAPSHOT),
                  cards=[dict(c) for c in CARDS],
                  budget=Budget(wall_s=600.0, max_calls=8),
                  worker_id="w-885")
    kwargs.update(over)
    return spawner.prepare_spawn(**kwargs)


def _seed_results(ws, costs, rollout_id="ro-1", start=0):
    for i, cost in enumerate(costs, start=start):
        q_cells.append_result(ws, rollout_id=rollout_id,
                              step_id=f"s-{i}", verified=True,
                              cost=cost, verdict="pass")


# ------------------------------------------------------------ package faces

def test_workers_package_docstring_contract():
    assert workers.__doc__ is not None
    assert workers.__doc__.strip() == ("learning-loop ``workers`` — the "
                                       "construction-style worker faces "
                                       "(#885).")


def test_hooks_package_docstring_contract():
    assert hooks.__doc__ is not None
    assert hooks.__doc__.strip() == ("learning-loop ``hooks`` — "
                                     "observation-only hook faces "
                                     "(#885).")


# ---------------------------------------------------------------- spawner

def test_spawn_receipt_is_the_construction_audit():
    r = _spawn()
    assert r["schema"] == "spawn-receipt/1"
    assert r["worker_id"] == "w-885"
    assert r["goal"] == "recover the key schedule"
    assert r["snapshot_excerpt"] == dict(SNAPSHOT)
    assert r["cards"] == [dict(c) for c in CARDS]
    assert r["budget"] == {"wall_s": 600.0, "max_calls": 8}
    assert r["time_box_s"] == 600.0
    # the face prepares, never launches — the receipt says so
    assert r["launch"] == "caller-owned"


def test_spawn_receipt_is_deterministic_and_clock_free():
    r1, r2 = _spawn(), _spawn()
    assert r1 == r2                       # same construction, same receipt
    assert r1["spawn_id"] == r2["spawn_id"]
    assert "ts" not in r1                 # no wall clock on the receipt
    assert "spawned_at" not in r1


def test_spawn_id_moves_with_construction():
    base = _spawn()
    moved = _spawn(goal="a different goal")
    assert moved["spawn_id"] != base["spawn_id"]
    assert _spawn(cards=[_card("card-x")])["spawn_id"] != base["spawn_id"]


def test_spawn_snapshot_excerpt_is_a_frozen_copy():
    snap = dict(SNAPSHOT)
    r = _spawn(snapshot=snap)
    snap["goal_depth"] = 99               # caller-side mutation afterwards
    assert r["snapshot_excerpt"]["goal_depth"] == 2


def test_spawn_card_copies_are_frozen():
    cards = [_card("card-1")]
    r = _spawn(cards=cards)
    cards[0]["verdict"] = "REVOKED"
    assert r["cards"][0]["verdict"] == "PROVEN"


@pytest.mark.parametrize("over", [
    {"goal": ""},
    {"goal": "   "},
    {"goal": None},
    {"snapshot": "not-a-mapping"},
    {"snapshot": None},
    {"snapshot": [dict(SNAPSHOT)]},
    {"cards": ["not-a-mapping"]},
    {"cards": [None]},
    {"cards": [{"no-id-here": True}]},
    {"cards": [{"id": "   "}]},
    {"budget": None},
    {"budget": {"wall_s": 600.0}},
    {"budget": Budget(wall_s=0.0)},
    {"budget": Budget(wall_s=-1.0)},
    {"budget": Budget(wall_s=float("nan"))},
    {"budget": Budget(wall_s=float("inf"))},
    {"budget": Budget(wall_s=600.0, max_calls=0)},
    {"worker_id": ""},
    {"worker_id": "  "},
])
def test_spawn_rejects_structural_garbage(over):
    with pytest.raises(ValueError):
        _spawn(**over)


def test_record_spawn_lands_one_spawn_candidate_action(tmp_path):
    ws = tmp_path / "ws"
    r = _spawn()
    spawner.record_spawn(ws, r, rollout_id="ro-1", step_id="s-1",
                         policy_version="v2")
    (row,) = [x for x in q_cells.trajectory_rows(ws)
              if x["schema"] == q_cells.SCHEMA_ACTION_V2]
    assert row["kind"] == "spawn_candidate"
    assert row["target"] == "w-885"
    assert row["rollout_id"] == "ro-1"
    assert row["step_id"] == "s-1"
    assert row["params"]["spawn_id"] == r["spawn_id"]
    assert row["params"]["goal"] == r["goal"]
    assert row["params"]["snapshot_excerpt"] == dict(SNAPSHOT)
    assert row["budget"] == {"wall_s": 600.0, "max_calls": 8}
    assert row["policy_version"] == "v2"


def test_record_spawn_rejects_a_non_receipt(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        spawner.record_spawn(ws, {"schema": "spawn-receipt/2"},
                             rollout_id="ro-1")


# ------------------------------------------------------------------ brief

def _brief(**over):
    kwargs = dict(goal="recover the key schedule",
                  facts=("K constants live in .rodata",),
                  cards=[dict(c) for c in CARDS],
                  budget=Budget(wall_s=600.0, max_calls=8),
                  tools=("Bash", "Read"))
    kwargs.update(over)
    return brief.assemble_brief(**kwargs)


def test_brief_sections_complete_and_ordered():
    b = _brief()
    assert b["schema"] == "dispatch-brief/1"
    assert b["sections"] == ["goal", "facts", "cards", "budget", "tools"]
    assert b["goal"] == "recover the key schedule"
    assert b["facts"] == ["K constants live in .rodata"]
    assert b["cards"] == [dict(c) for c in CARDS]
    assert b["budget"] == {"wall_s": 600.0, "max_calls": 8}
    assert b["tools"] == ["Bash", "Read"]


def test_brief_is_deterministic():
    assert _brief() == _brief()


def test_brief_carries_the_knowledge_never_self_retrieves():
    """Memory retrieval is orchestrator-owned: the facts ride the brief
    verbatim and NO retrieval face exists on the module."""
    b = _brief(facts=("fact-a", "fact-b"))
    assert b["facts"] == ["fact-a", "fact-b"]
    assert b["retrieval"] == "orchestrator-owned"
    assert not hasattr(brief, "retrieve")


def test_brief_id_moves_with_content():
    base = _brief()
    assert _brief()["brief_id"] == base["brief_id"]
    assert _brief(tools=("Bash",))["brief_id"] != base["brief_id"]
    assert _brief(goal="other")["brief_id"] != base["brief_id"]


@pytest.mark.parametrize("over", [
    {"goal": ""},
    {"goal": None},
    {"facts": ("ok", "   ")},
    {"facts": ["ok", 7]},
    {"facts": "not-a-sequence-of-strs"},
    {"cards": [{"id": "x"}, "garbage"]},
    {"cards": [{"id": ""}]},
    {"budget": None},
    {"budget": "600s"},
    {"budget": Budget(wall_s=-0.5)},
    {"tools": ("Bash", "")},
    {"tools": [42]},
])
def test_brief_rejects_structural_garbage(over):
    with pytest.raises(ValueError):
        _brief(**over)


def test_brief_allows_honest_empty_sections():
    """A cold workspace carries an empty facts/cards list — the honest
    gap; the sections stay present, never fabricated."""
    b = _brief(facts=(), cards=(), tools=())
    assert b["facts"] == [] and b["cards"] == [] and b["tools"] == []
    assert b["sections"] == ["goal", "facts", "cards", "budget", "tools"]


# --------------------------------------------------------------- observer

def test_observed_tool_call_lands_one_ledger_row(tmp_path):
    ws = tmp_path / "ws"
    r = observer.observe_tool_call(ws, worker_id="w-885", tool="Bash",
                                   rollout_id="ro-1", step_id="s-2",
                                   detail={"cmd": "strings"},
                                   ts="2026-01-01T00:00:00Z")
    assert r["observed"] is True and r["reason"] is None
    (row,) = _cl.read(ws, "telemetry", schema_prefix="observer-call")
    assert row["schema"] == "observer-call/1"
    assert row["source"] == "observer"
    assert row["worker_id"] == "w-885"
    assert row["tool"] == "Bash"
    assert row["rollout_id"] == "ro-1"
    assert row["step_id"] == "s-2"
    assert row["detail"] == {"cmd": "strings"}
    assert row["ts"] == "2026-01-01T00:00:00Z"


def test_observed_calls_read_face_is_append_order(tmp_path):
    ws = tmp_path / "ws"
    observer.observe_tool_call(ws, worker_id="w-1", tool="Bash",
                               ts="2026-01-01T00:00:00Z")
    observer.observe_tool_call(ws, worker_id="w-1", tool="Read",
                               ts="2026-01-01T00:00:01Z")
    rows = observer.observed_calls(ws)
    assert [r["tool"] for r in rows] == ["Bash", "Read"]


def test_capture_is_fail_open_and_never_blocks(tmp_path):
    """A broken capture path (unwritable workspace) NEVER raises into
    the caller and carries no blocking semantics — the telemetry
    posture."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a workspace")
    r = observer.observe_tool_call(blocker, worker_id="w-1", tool="Bash")
    assert r["observed"] is False
    assert r["reason"]                    # named, never silent
    assert "block" not in r and "decision" not in r


def test_capture_survives_unserializable_detail(tmp_path):
    ws = tmp_path / "ws"
    r = observer.observe_tool_call(ws, worker_id="w-1", tool="Bash",
                                   detail={"obj": object()})
    assert r["observed"] is False
    assert r["reason"] == "write-failed"


@pytest.mark.parametrize("kwargs", [
    {"worker_id": ""},
    {"worker_id": "  "},
    {"tool": ""},
    {"tool": None},
    {"rollout_id": ""},
    {"step_id": "  "},
    {"detail": "not-a-mapping"},
    {"detail": ["nope"]},
])
def test_capture_boundary_rejects_structural_garbage(tmp_path, kwargs):
    ws = tmp_path / "ws"
    base = {"worker_id": "w-1", "tool": "Bash"}
    base.update(kwargs)
    with pytest.raises(ValueError):
        observer.observe_tool_call(ws, **base)


# ---------------------------------------------------------- budget tracker

def test_budget_report_sums_result_row_costs(tmp_path):
    ws = tmp_path / "ws"
    _seed_results(ws, [0.1, 0.2, 0.3])
    rows = q_cells.trajectory_rows(ws)
    r = budget_tracker.budget_report(Budget(wall_s=600.0, max_calls=8),
                                     rows)
    assert r["schema"] == "budget-report/1"
    assert r["calls_used"] == 3
    assert r["spent_s"] == pytest.approx(0.6)
    assert r["remaining_s"] == pytest.approx(600.0 - 0.6)
    assert r["over_budget"] is False
    assert r["calls_used"] == 3
    assert r["remaining_calls"] == 5
    assert r["over_calls"] is False


def test_budget_report_filters_by_rollout(tmp_path):
    ws = tmp_path / "ws"
    _seed_results(ws, [0.1], rollout_id="ro-1")
    _seed_results(ws, [5.0], rollout_id="ro-2", start=10)
    rows = q_cells.trajectory_rows(ws)
    r = budget_tracker.budget_report(Budget(wall_s=1.0), rows,
                                     rollout_id="ro-1")
    assert r["rollout_id"] == "ro-1"
    assert r["spent_s"] == pytest.approx(0.1)
    assert r["over_budget"] is False


def test_budget_report_floors_remaining_and_flags_over_budget(tmp_path):
    ws = tmp_path / "ws"
    _seed_results(ws, [0.7, 0.6])
    r = budget_tracker.budget_report(Budget(wall_s=1.0),
                                     q_cells.trajectory_rows(ws))
    assert r["spent_s"] == pytest.approx(1.3)
    assert r["remaining_s"] == 0.0        # floored, never negative
    assert r["over_budget"] is True


def test_budget_report_calls_leg_with_unbounded_max_calls(tmp_path):
    ws = tmp_path / "ws"
    _seed_results(ws, [0.1, 0.1])
    r = budget_tracker.budget_report(Budget(wall_s=1.0),
                                     q_cells.trajectory_rows(ws))
    assert r["remaining_calls"] is None   # no cap — the honest unbounded
    assert r["over_calls"] is False
    over = budget_tracker.budget_report(Budget(wall_s=1.0, max_calls=1),
                                        q_cells.trajectory_rows(ws))
    assert over["remaining_calls"] == 0
    assert over["over_calls"] is True


def test_budget_report_empty_ledger(tmp_path):
    r = budget_tracker.budget_report(Budget(wall_s=5.0, max_calls=2), [])
    assert r["spent_s"] == 0.0
    assert r["remaining_s"] == 5.0
    assert r["calls_used"] == 0
    assert r["remaining_calls"] == 2


def test_budget_report_is_deterministic(tmp_path):
    ws = tmp_path / "ws"
    _seed_results(ws, [0.25])
    rows = q_cells.trajectory_rows(ws)
    assert budget_tracker.budget_report(Budget(wall_s=1.0), rows) == \
        budget_tracker.budget_report(Budget(wall_s=1.0), rows)
    assert "ts" not in budget_tracker.budget_report(Budget(wall_s=1.0),
                                                    rows)


def test_budget_report_consumes_only_result_rows(tmp_path):
    """Mixed trajectory rows pass the wall (action rows are the
    trajectory's decision trace) but only result-row costs spend."""
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          step_id="s-0", target="step-0")
    _seed_results(ws, [0.5])
    r = budget_tracker.budget_report(Budget(wall_s=1.0),
                                     q_cells.trajectory_rows(ws))
    assert r["calls_used"] == 1
    assert r["spent_s"] == pytest.approx(0.5)


@pytest.mark.parametrize("budget", [
    None,
    "600s",
    {"wall_s": 600.0},
    Budget(wall_s=0.0),
    Budget(wall_s=-1.0),
    Budget(wall_s=float("nan")),
])
def test_budget_report_rejects_garbage_budget(tmp_path, budget):
    _ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        budget_tracker.budget_report(budget, [])


@pytest.mark.parametrize("rows", [
    "not-a-list",
    ["not-a-mapping"],
    [{"schema": "step-record/9"}],
    [{"schema": "q-cell-result/1", "rollout_id": "ro-1",
      "step_id": "s-0", "cost": "0.5"}],
    [{"schema": "q-cell-result/1", "rollout_id": "ro-1",
      "step_id": "s-0", "cost": -0.5}],
    [{"schema": "q-cell-result/1", "rollout_id": "ro-1",
      "step_id": "s-0", "cost": float("nan")}],
])
def test_budget_report_rejects_structural_garbage_rows(tmp_path, rows):
    with pytest.raises(ValueError):
        budget_tracker.budget_report(Budget(wall_s=1.0), rows)
