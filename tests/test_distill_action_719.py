# -*- coding: utf-8 -*-
"""tests/test_distill_action_719.py — distillation as a POLICY action.

issue-719: online distillation (issue-458) exists as a complete engine
but not as a CHOOSABLE action — the L1 policy can never decide "invest
in capability now"; distillation only fires reactively on shelf-miss
markers. Owner ruling (2026-10-16): the L1 action list must include it.

This module pins three faces:

  1. the action entry — `orchestration.distill` is selectable, with
     level / cost / precondition / budget linkage like every other
     registry row;
  2. the budget linkage — the policy's distill actuation goes through
     online_distill's existing budget guards (runs/distill-budget.json
     is the hard cap; the restraint ruling lives as BUDGET, never as a
     rule blocking the choice);
  3. the reactive defense-in-depth — shelf-miss markers still auto-fire
     without any policy selection (the marker path is unchanged).

Design principle (critical): the policy learns WHEN distillation is
worth its cost (value/cost). There are NO trigger rules here — no "if
shelf thin then distill". The precondition is an availability condition,
not a firing rule.
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(SCRIPTS),):
    if p not in sys.path:
        sys.path.insert(0, p)

import action_space as aspace  # noqa: E402
import online_distill as od  # noqa: E402


def mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def write_marker(ws: Path, name: str, token: str,
                 sample: str | None = None) -> Path:
    p = ws / "runs" / name
    line = f"shelf-miss: {token}"
    if sample:
        line += f" sample={sample}"
    p.write_text("# worker status (fixture)\nstatus: DONE\n"
                 f"{line}\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. the action entry: selectable, fully specified, budget-linked
# ---------------------------------------------------------------------------


def test_distill_is_selectable_action():
    """`orchestration.distill` is a registered L1 action alongside osint
    (both are workspace capability acquisition): level orchestration,
    cost 5 (a budgeted act — the distill budget ledger is the hard cap),
    a real availability precondition, and the budget machinery named in
    its references. The vocabulary count moves 23 -> 24."""
    spec = aspace.ACTIONS.get("orchestration.distill")
    assert spec is not None, (
        "distill must be in the action vocabulary — the policy cannot "
        "CHOOSE an action the registry does not carry")
    assert spec.level == aspace.ORCHESTRATION
    assert spec.cost == 5
    assert spec.precondition.strip()
    assert spec.proof_power.strip()
    assert spec.consumer.strip()
    # budget linkage: the entry reuses the engine's budget guards, never
    # rebuilds them
    refs = " ".join(spec.references)
    assert "online_distill" in refs
    assert "distill-budget" in refs
    # no trigger rule: the precondition is availability OR policy choice,
    # never "when the shelf is thin, fire"
    pre = spec.precondition.lower()
    assert "no viable candidate" in pre or "proactive" in pre
    assert "if " not in pre, (
        "the precondition must not read as a firing rule — the policy "
        "learns WHEN (value/cost), it is never told when")
    # the estimator stub is still a stub (v0.2 owns the estimators)
    assert spec.delta_estimator.implemented is False
    # the vocabulary is exactly 9 + 6 + 6 + 3
    assert len(aspace.ACTIONS) == 24


def test_distill_rides_standard_registry_metadata():
    """The new entry is a first-class registry row: namespaced key, the
    shared weight default, and the category table is untouched (the
    claim-category vocabulary is a different axis)."""
    assert "orchestration.distill" in aspace.DEFAULT_ACTION_WEIGHTS
    assert aspace.DEFAULT_ACTION_WEIGHTS["orchestration.distill"] == 1.0
    got = aspace.get("orchestration.distill")
    assert got.name == "orchestration.distill"
    assert got.settleable is False, (
        "distill acquires capability — it does not change the claim "
        "economy's candidate set (that is the policy tier's role)")


# ---------------------------------------------------------------------------
# 2. the budget linkage: actuation respects distill-budget.json caps
# ---------------------------------------------------------------------------


class TestDistillBudgetGuards:
    def test_distill_budget_guards_enforced(self, tmp_path):
        """The policy's distill actuation goes through online_distill's
        budget guards: per-run act cap, fail-closed corruption. The
        restraint ruling holds as BUDGET (蒸馏频率不许增 is the cap),
        never as a rule refusing the action outright."""
        ws = mk_ws(tmp_path)
        # within budget: the actuation reserves one act each
        first = aspace.actuate_distill(ws, "policy:proactive-a")
        assert first is not None and first["attempt"].startswith("attempt-")
        second = aspace.actuate_distill(ws, "policy:proactive-b")
        assert second is not None
        # per-run cap (2) exhausted -> refused, never over the cap
        assert aspace.actuate_distill(ws, "policy:proactive-c") is None
        state = od.ledger_state(ws)
        assert state["per_run_used"] == od.DISTILL_ACTS_PER_RUN == 2
        assert state["global"]["acts"] == 2

    def test_actuation_refusal_is_explicit(self, tmp_path):
        """A refused actuation names its reason through the engine's
        refuse face — the caller always knows WHY (cap, duplicate, or
        ledger), never a silent None without diagnosis."""
        ws = mk_ws(tmp_path)
        aspace.actuate_distill(ws, "policy:proactive-a")
        aspace.actuate_distill(ws, "policy:proactive-b")
        assert od.refuse_reason(ws, "policy:proactive-c") == \
            "per_run_act_budget_exhausted"
        # duplicate tokens are refused even with budget remaining
        ws2 = tmp_path / "ws2"
        (ws2 / "runs").mkdir(parents=True)
        assert aspace.actuate_distill(ws2, "policy:same") is not None
        assert aspace.actuate_distill(ws2, "policy:same") is None
        assert od.refuse_reason(ws2, "policy:same") == "duplicate_trigger_token"

    def test_corrupt_ledger_fails_closed(self, tmp_path):
        """An unreadable distill-budget.json never opens the gate — the
        capability is optional, corruption must not let the policy
        spend freely."""
        ws = mk_ws(tmp_path)
        (ws / "runs" / "distill-budget.json").write_text("{corrupt",
                                                         encoding="utf-8")
        assert aspace.actuate_distill(ws, "policy:proactive-a") is None
        assert od.refuse_reason(ws, "policy:proactive-a") == \
            "budget_ledger_unreadable"

    def test_stored_budget_above_ceiling_clamps(self, tmp_path):
        """The policy action cannot loosen the cap by writing a bigger
        budget into the ledger — stored ceilings clamp DOWN to the
        engine constants (蒸馏频率不许增)."""
        ws = mk_ws(tmp_path)
        (ws / "runs" / "distill-budget.json").write_text(json.dumps({
            "schema": od.BUDGET_SCHEMA, "run_id": "r1",
            "run_started_ts": "2026-10-16T00:00:00Z",
            "per_run_budget": 99, "per_run_used": 0,
            "hops_budget": 99, "hops_used": 0,
            "triggers": {}, "consumed_markers": [],
            "global": {"acts": 0, "hops": 0, "landed": 0}}),
            encoding="utf-8")
        assert aspace.actuate_distill(ws, "policy:proactive-a") is not None
        assert aspace.actuate_distill(ws, "policy:proactive-b") is not None
        assert aspace.actuate_distill(ws, "policy:proactive-c") is None
        state = od.ledger_state(ws)
        assert state["per_run_budget"] == od.DISTILL_ACTS_PER_RUN


# ---------------------------------------------------------------------------
# 3. the reactive marker path: unchanged (defense-in-depth, no policy gate)
# ---------------------------------------------------------------------------


def test_reactive_marker_path_unchanged(tmp_path):
    """Shelf-miss markers still auto-fire WITHOUT any policy selection:
    the worker's marker is detected by the engine scan and the budgeted
    act can be reserved on the reactive path alone. The policy action is
    an ADDITIONAL face, never a gate the marker must pass through."""
    ws = mk_ws(tmp_path)
    write_marker(ws, "worker-status-C-004.md", "crypto:decode",
                 sample="bins/blob.bin")
    triggers = od.scan_triggers(ws)
    assert [t.kind for t in triggers] == ["shelf-miss"]
    assert triggers[0].token == "crypto:decode"
    # the reactive actuation reserves its act with no policy involved
    receipt = od.reserve_act(ws, triggers[0].token,
                             source_file=triggers[0].source_file,
                             sample_hint=triggers[0].sample_hint)
    assert receipt is not None
    assert od.ledger_state(ws)["per_run_used"] == 1
    # the tick step still OWNS the auto-fire (the marker path is not
    # routed through action_space selection)
    from e2e import checkpoints
    assert callable(getattr(checkpoints, "_maybe_distill", None))
    src = inspect.getsource(checkpoints)
    assert "_maybe_distill(ctx" in src, (
        "the tick step must still auto-invoke the distill step on "
        "miss signals — the reactive path is defense-in-depth, not a "
        "policy choice")
    assert "scan_triggers" in inspect.getsource(checkpoints._maybe_distill), (
        "the auto-fire still begins at the engine's marker scan")
