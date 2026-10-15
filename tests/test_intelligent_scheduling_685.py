# -*- coding: utf-8 -*-
"""tests/test_intelligent_scheduling_685.py — the intelligent-scheduling
decision contract.

The heartbeat used to be a fixed cron driven by hand-written constants:
no alternative was ever chosen, no propensity was logged, and no wake
decision could be evaluated off-policy. This suite pins the contracts
that turn scheduling into a recorded decision surface:

  1. sleep / wake scheduling actions are recorded with propensity +
     source (the dispatch-action trichotomy sampled | declared | none);
  2. the selection width k = min(free_slots, f(entropy)) is observable
     and logged per decision;
  3. the null action ("do nothing") is a first-class selectable action
     (cost 0, value 0) and every decision carries its propensity — the
     baseline any timer action is measured against;
  4. the three budgets (tokens / tool_calls / verify_calls) are tracked
     and ride the decision record and the logged row.

Plus the watchdog demotion pin: the fixed cron is demoted to an ARMED
watchdog role (event-first, polling as fallback) — never deleted — and
the selection is a Gumbel top-k without replacement whose Plackett-Luce
sampling probability is the logged propensity.
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import action_space as aspace  # noqa: E402
import intelligent_scheduling as isch  # noqa: E402
import signals_stream  # noqa: E402

SCHEDULING_FIVE = {"sleep", "wake_on", "probe", "close_loop", "none"}


def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _sched_rows(ws: Path) -> list[dict]:
    return [r for r in signals_stream.read(ws)
            if r.get("kind") == isch.KIND_SCHEDULING]


def _last_row(ws: Path) -> dict:
    rows = _sched_rows(ws)
    assert rows, "no scheduling row landed on the signal stream"
    return rows[-1]


def _force(action: str) -> dict:
    """Logits that pin the sampler on `action`: the rival candidates sit a
    hundred nats down, so the pick is pinned for every seed."""
    logits = {name: -50.0 for name in isch.SCHEDULING_ACTIONS}
    logits[action] = 50.0
    return logits


# ---------- the vocabulary: scheduling actions live in the registry ----------

class TestSchedulingVocabulary:

    def test_scheduling_five_registered_at_orchestration_level(self):
        flagged = {s.name.split(".", 1)[1]
                   for s in aspace.actions_of(aspace.ORCHESTRATION)
                   if s.scheduling}
        assert flagged == SCHEDULING_FIVE
        # the module's constant IS the registry's flagged subset (registry
        # order), never a hand-kept parallel list
        assert set(isch.SCHEDULING_ACTIONS) == SCHEDULING_FIVE
        assert isch.SCHEDULING_ACTIONS == tuple(
            s.name.split(".", 1)[1]
            for s in aspace.actions_of(aspace.ORCHESTRATION) if s.scheduling)


# ---------- 1. scheduling actions are actions: propensity + source ----------

class TestSchedulingActionLogging:

    def test_sleep_action_with_propensity_is_logged(self, tmp_path):
        # (a) a DECLARED action is the behavior policy itself: pi = 1.0
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, declared_action="sleep")
        row = _last_row(ws)
        assert row["action"] == "sleep"
        assert row["source"] == "declared"
        assert row["propensity"] == 1.0
        assert d["selected"][0]["action"] == "sleep"

        # (b) a SAMPLED action carries its sampler probability: (0, 1]
        ws2 = _mk_ws(tmp_path, "ws2")
        isch.decide(ws2, rng=random.Random(7), logits=_force("sleep"))
        row2 = _last_row(ws2)
        assert row2["action"] == "sleep"
        assert row2["source"] == "sampled"
        assert 0.0 < row2["propensity"] <= 1.0
        # the row is off-policy evaluable: the same action under the flat
        # prior would weigh ~1/5, the pinned prior weighs higher
        ws3 = _mk_ws(tmp_path, "ws3")
        isch.decide(ws3, rng=random.Random(7))
        assert _last_row(ws3)["propensity"] < row2["propensity"]

    def test_propensity_sources_are_the_dispatch_trichotomy(self):
        assert isch.PROPENSITY_SOURCES == ("sampled", "declared", "none")

    def test_decision_record_persisted(self, tmp_path):
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, rng=random.Random(1))
        doc = json.loads(
            (ws / "runs" / ".scheduling-decision.json").read_text(
                encoding="utf-8"))
        assert doc["schema"] == isch.SCHEMA == "scheduling-decision/1"
        assert doc["k"] == d["k"]
        assert doc["action"] == _last_row(ws)["action"]


# ---------- 2. k rides the decision: observable + logged ----------

class TestAdaptiveWidth:

    def test_k_is_logged_and_derived_from_the_state_inputs(self, tmp_path):
        # the width the sampled decision committed to, with both inputs
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, entropy_bits=2.0, free_slots=1,
                        rng=random.Random(3))
        assert d["k"] == 1
        assert d["k_inputs"]["entropy_bits"] == 2.0
        assert d["k_inputs"]["free_slots"] == 1
        row = _last_row(ws)
        assert row["k"] == 1
        assert len(row["selected"]) == 1
        assert row["entropy_bits"] == 2.0
        assert row["free_slots"] == 1

        # a wider demand widens the batch: k = min(free, f(entropy))
        ws2 = _mk_ws(tmp_path, "ws2")
        d2 = isch.decide(ws2, entropy_bits=3.0, free_slots=3,
                         rng=random.Random(3))
        assert d2["k"] == 3
        assert len(d2["selected"]) == 3
        assert len(set(s["action"] for s in d2["selected"])) == 3
        assert len(_last_row(ws2)["selected"]) == 3
        # the logged propensity is the ordered BATCH's own probability
        # (1/5 * 1/4 * 1/3 under flat logits) — never one member's marginal
        assert abs(d2["propensity"] - 1.0 / 60.0) < 1e-9

        # the ENTROPY demand binds too (not just the slot room): with room
        # to spare, k follows f(2 bits) = 2
        ws3 = _mk_ws(tmp_path, "ws3")
        d3 = isch.decide(ws3, entropy_bits=2.0, free_slots=3,
                         rng=random.Random(3))
        assert d3["k"] == 2

    def test_flat_logits_decisions_actually_vary_across_seeds(self, tmp_path):
        # the recorder must ACTUATE its sampler: under flat priors the
        # chosen action varies across rng streams (a deterministic sort
        # would pin one action forever)
        ws = _mk_ws(tmp_path)
        picks = {isch.decide(ws, rng=random.Random(seed))["action"]
                 for seed in range(40)}
        assert len(picks) >= 3, f"decisions look deterministic: {picks}"


# ---------- 3. the null action: the do-nothing baseline ----------

class TestNullBaseline:

    def test_null_action_baseline_selectable(self, tmp_path):
        # first-class registry action: cost 0, value 0
        spec = aspace.ACTIONS["orchestration.none"]
        assert spec.cost == 0.0
        assert spec.scheduling is True
        assert isch.NULL_ACTION == "none"
        assert "none" in isch.SCHEDULING_ACTIONS

        # (a) selectable by the sampler
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, rng=random.Random(11), logits=_force("none"))
        row = _last_row(ws)
        assert row["action"] == "none"
        assert row["source"] == "none"    # the intervention IS none
        assert 0.0 < row["propensity"] <= 1.0

        # (b) forced when there is no room to act at all
        ws2 = _mk_ws(tmp_path, "ws2")
        d2 = isch.decide(ws2, free_slots=0)
        assert d2["k"] == 0
        assert d2["selected"][0]["action"] == "none"
        assert d2["selected"][0]["source"] == "none"
        assert d2["selected"][0]["propensity"] == 1.0

        # (c) EVERY decision carries the null baseline: the comparison
        # anchor any timer action is measured against off-policy
        ws3 = _mk_ws(tmp_path, "ws3")
        d3 = isch.decide(ws3, rng=random.Random(5))
        null = d3["null"]
        assert null["action"] == "none"
        assert 0.0 < null["propensity"] <= 1.0
        assert null["cost"] == 0.0 and null["value"] == 0.0
        row3 = _last_row(ws3)
        assert row3["null_propensity"] == null["propensity"]

    def test_null_baseline_tracks_the_candidate_logits(self, tmp_path):
        # the baseline is the null action's OWN probability under the same
        # logits — not a constant: with sleep one nat up, the null's
        # softmax is 1/(e + 4), far from the flat 1/5
        ws = _mk_ws(tmp_path)
        logits = {name: 0.0 for name in isch.SCHEDULING_ACTIONS}
        logits["sleep"] = 1.0
        d = isch.decide(ws, rng=random.Random(4), logits=logits)
        expected = 1.0 / (math.e + 4.0)
        assert abs(d["null"]["propensity"] - expected) < 1e-9
        assert abs(_last_row(ws)["null_propensity"] - expected) < 1e-9
        assert 0.0 < expected < 1.0

    def test_unknown_declared_action_is_refused(self, tmp_path):
        import pytest
        ws = _mk_ws(tmp_path)
        with pytest.raises(ValueError):
            isch.decide(ws, declared_action="teleport")
        assert _sched_rows(ws) == [], "a refused decision must not log"
        assert not (ws / "runs" / ".scheduling-decision.json").exists(), (
            "a refused decision must not persist a record")

    def test_non_finite_logits_are_refused(self, tmp_path):
        import pytest
        ws = _mk_ws(tmp_path)
        for bad in (float("nan"), float("inf"), float("-inf"), "heavy"):
            logits = {name: 0.0 for name in isch.SCHEDULING_ACTIONS}
            logits["sleep"] = bad
            with pytest.raises(ValueError):
                isch.decide(ws, logits=logits)
        assert _sched_rows(ws) == [], "a refused decision must not log"
        assert not (ws / "runs" / ".scheduling-decision.json").exists()

    def test_declared_action_wins_even_without_slot_room(self, tmp_path):
        # a declaration is the behavior policy itself: it overrides the
        # sampler, while k stays the state's own honest width
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, declared_action="probe", free_slots=0)
        assert d["k"] == 0
        assert d["selected"][0]["action"] == "probe"
        assert d["selected"][0]["source"] == "declared"
        assert d["selected"][0]["propensity"] == 1.0


# ---------- 4. the three budgets ----------

class TestThreeBudgets:

    def _seed_budgets(self, ws: Path) -> None:
        (ws / "cost_events.jsonl").write_text(
            json.dumps({"ts": "2026-01-01T00:00:00Z", "amount": 2.5}) + "\n"
            + json.dumps({"ts": "2026-01-01T00:01:00Z", "amount": 3.0}) + "\n",
            encoding="utf-8")
        rows = [{"schema": "step-record/1", "ts": "2026-01-01T00:00:00Z",
                 "session_id": "s1", "call_id": f"c{i}"} for i in range(3)]
        (ws / "runs" / "step-ledger.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        with (ws / "runs" / "signals.jsonl").open("a",
                                                  encoding="utf-8") as fh:
            for i in range(2):
                fh.write(json.dumps({"ts": "2026-01-01T00:00:00Z",
                                     "kind": "verify", "claim": "C-1"}) + "\n")

    def test_three_budgets_tracked(self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._seed_budgets(ws)
        b = isch.budget_face(ws)
        assert set(b) == {"tokens", "tool_calls", "verify_calls"}
        assert b["tokens"] == 5.5
        assert b["tool_calls"] == 3
        assert b["verify_calls"] == 2

        # the triple rides the decision record AND the logged row
        d = isch.decide(ws, rng=random.Random(1))
        assert d["budgets"] == b
        assert _last_row(ws)["budgets"] == b

    def test_absent_sources_read_zero_never_raise(self, tmp_path):
        ws = _mk_ws(tmp_path)
        b = isch.budget_face(ws)
        assert b == {"tokens": 0.0, "tool_calls": 0, "verify_calls": 0}

    def test_verify_stamps_count_independently_of_the_scheduling_rows(
            self, tmp_path):
        ws = _mk_ws(tmp_path)
        self._seed_budgets(ws)
        isch.decide(ws, rng=random.Random(1))
        isch.decide(ws, rng=random.Random(2))
        assert isch.budget_face(ws)["verify_calls"] == 2


# ---------- 5. the cron demotion: watchdog fallback ----------

class TestWatchdogDemotion:

    def test_cron_demoted_to_armed_watchdog_fallback(self, tmp_path):
        ws = _mk_ws(tmp_path)
        d = isch.decide(ws, rng=random.Random(2))
        wd = d["watchdog"]
        assert wd["role"] == "watchdog"
        # the cron path is DEMOTED, never deleted: always armed as the
        # fallback poll behind the event-first topology
        assert wd["armed"] is True
        assert isinstance(wd["interval_min"], int) and wd["interval_min"] >= 5
        assert wd["mode"] in ("event_first", "poll_fallback")

        # event-first when the event wake rides the selection
        ws2 = _mk_ws(tmp_path, "ws2")
        d2 = isch.decide(ws2, rng=random.Random(9), logits=_force("wake_on"))
        assert d2["selected"][0]["action"] == "wake_on"
        assert d2["watchdog"]["mode"] == "event_first"

        # otherwise the polling fallback carries the next wake
        ws3 = _mk_ws(tmp_path, "ws3")
        d3 = isch.decide(ws3, rng=random.Random(9), logits=_force("probe"))
        assert d3["watchdog"]["mode"] == "poll_fallback"

        # the events the topology already delivers are first-class names
        assert set(d["wake_events"]) == set(isch.WAKE_EVENTS)
        assert set(isch.WAKE_EVENTS) == {
            "worker_completion", "dispatch_return", "oracle_result",
            "user_signal"}
