# -*- coding: utf-8 -*-
"""tests/test_pricing_760.py — the pricing face (issue 760, the pricing
slice only).

The belief (component b, already landed) represents what we SAW and
what we DECLARED unknown; the pricing face makes "what we do NOT know"
computable and prices information-gathering against it:

  - the unknown set: a workspace-level projection over EXISTING keys
    (claim-register statuses + PQ bindings, the obstacle registry, the
    issue-800 dispatch ledger) — which primary_questions are undecided,
    which obstacles are open. No new ledger is invented; the projection
    is a pure view.
  - the price: expected information gain (bits) x the undecided value
    weight, decayed by the target's committed-dispatch repeat count.
    A probe of a DECIDED target prices exactly 0 (the production
    pathology: a dead path re-probed 9 times); a high-info probe
    outprices a low-info one.
  - the joins: emitted price rows land in the issue-721 telemetry family
    (schema probe-price/1 — no new file), the issue-801 cockpit consumption
    face carries a `pricing` block, and the dispatch supply-admission
    face reads the price as advisory telemetry (never a gate decision).

Determinism: price_action is pure computation over workspace reads —
no RNG, no wall-clock; the identity ts is stamped only at emit time.

All fixtures SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import consolidated_ledger  # noqa: E402
from rlvr import obstacles  # noqa: E402
from rlvr import pricing  # noqa: E402


# ------------------------------------------------------------- fixtures

def _write_obstacle(ws: Path, *, kind: str = "tool_limit",
                    claim: str | None = None) -> dict:
    """One valid obstacle row via the registry's own producer (the
    evidence artifact carries a real probe marker)."""
    ev = ws / "evidence" / "probe.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text("command: which frida; rc=1; observed: absent\n",
                  encoding="utf-8")
    out = obstacles.record(ws, kind=kind, cause="frida-server absent",
                           evidence_path="evidence/probe.txt",
                           method_family="dynamic", claim=claim)
    assert out["appended"], out["errors"]
    return out["row"]


def _retract_obstacle(ws: Path, obs_id: str) -> None:
    assert obstacles.retract(ws, obs_id, "env repaired (synthetic)")


def _dispatch_rows(ws: Path, claims: list[str]) -> None:
    """Committed issue-800 dispatch-ledger rows for the given claims."""
    import claims_store as cs
    p = Path(ws) / cs.DISPATCH_LEDGER_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for c in claims:
            fh.write(json.dumps({
                "schema": cs.DISPATCH_LEDGER_SCHEMA,
                "ts": "2026-10-24T00:00:00Z",
                "dispatch_id": f"d{c}".replace("-", ""),
                "claim": c, "state": "committed",
                "actor": "test"}) + "\n")


def _ws(tmp_path: Path, *, q2_candidates: int = 2) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "evidence").mkdir()
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(
        {"primary_questions": ["q-1", "q-2", "q-3"]}),
        encoding="utf-8")
    claims = [
        {"id": "C-1", "status": "PROVEN", "answers_question": "q-1"},
        {"id": "C-3", "status": "OPEN"},
    ]
    for i in range(q2_candidates):
        claims.append({"id": f"C-2{chr(97 + i)}", "status": "OPEN",
                       "answers_question": "q-2"})
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": claims}), encoding="utf-8")
    return ws


# ------------------------------------------------- 1. the unknown set

class TestUnknownSet:
    def test_projection_pins_decided_vs_undecided(self, tmp_path):
        """q-1 is decided (a terminal claim answers it); q-2/q-3 are
        undecided with their open-candidate counts; counts add up."""
        ws = _ws(tmp_path)
        u = pricing.unknown_set(ws)
        assert u["decided"] == ["q-1"]
        assert [d["qid"] for d in u["undecided"]] == ["q-2", "q-3"]
        by_q = {d["qid"]: d["candidates"] for d in u["undecided"]}
        assert by_q["q-2"] == 2
        assert by_q["q-3"] == 0
        assert u["counts"] == {"pqs": 3, "undecided": 2, "decided": 1,
                               "open_obstacles": 0}

    def test_open_obstacles_enter_the_unknown_set(self, tmp_path):
        """An ACTIVE obstacle row is an open (unexplored) blocker; a
        RETRACTED one is resolved and leaves the set."""
        ws = _ws(tmp_path)
        row = _write_obstacle(ws)
        u = pricing.unknown_set(ws)
        assert [o["id"] for o in u["open_obstacles"]] == [row["id"]]
        _retract_obstacle(ws, row["id"])
        u2 = pricing.unknown_set(ws)
        assert u2["open_obstacles"] == []
        assert u2["counts"]["open_obstacles"] == 0

    def test_absent_task_spec_is_an_empty_honest_set(self, tmp_path):
        """No task_spec -> no PQs, no fabrication; the projection stays
        fail-open (an unreadable register reads the same way)."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        u = pricing.unknown_set(ws)
        assert u["undecided"] == [] and u["decided"] == []
        assert u["counts"]["pqs"] == 0


# --------------------------------------- 2. the information-gain price

class TestPriceAction:
    def test_decided_target_prices_zero(self, tmp_path):
        """THE repeat-probe pin: probing an already-decided PQ gains no
        information — the price is exactly 0 (a dead path re-probed 9
        times is 9 zero-value billings, never 9 fresh bets)."""
        ws = _ws(tmp_path)
        p = pricing.price_action(ws, "pq", "q-1")
        assert p["status"] == "decided"
        assert p["gain_bits"] == 0.0
        assert p["price"] == 0.0

    def test_retracted_obstacle_reprobe_prices_zero(self, tmp_path):
        """A retracted obstacle is resolved knowledge: re-probing it
        prices 0; an ABSENT obstacle id prices 0 too (never fabricated)."""
        ws = _ws(tmp_path)
        row = _write_obstacle(ws)
        _retract_obstacle(ws, row["id"])
        assert pricing.price_action(
            ws, "obstacle", row["id"])["price"] == 0.0
        assert pricing.price_action(
            ws, "obstacle", "OBS-999")["status"] == "absent"
        assert pricing.price_action(
            ws, "obstacle", "OBS-999")["price"] == 0.0

    def test_high_info_beats_low_info(self, tmp_path):
        """Four live rivals on q-2 (log2(4)=2 bits) outprice a cold
        q-3 (floor 1 bit): the price orders probes by expected gain."""
        ws4 = _ws(tmp_path / "a", q2_candidates=4)
        hi = pricing.price_action(ws4, "pq", "q-2")
        lo = pricing.price_action(ws4, "pq", "q-3")
        assert hi["status"] == "undecided"
        assert hi["candidates"] == 4
        assert hi["gain_bits"] == pytest.approx(2.0)
        assert lo["gain_bits"] == pytest.approx(1.0)
        assert hi["price"] > lo["price"]

    def test_repeat_dispatch_decay(self, tmp_path):
        """The issue-800 join: each committed dispatch on the target's claims
        halves the marginal gain — q-2 with two prior dispatches prices
        0.25x the fresh probe (the 9th re-probe is ~0.4% of fresh)."""
        ws = _ws(tmp_path)
        fresh = pricing.price_action(ws, "pq", "q-2")
        _dispatch_rows(ws, ["C-2a", "C-2b"])
        again = pricing.price_action(ws, "pq", "q-2")
        assert again["repeat"] == 2
        assert again["price"] == pytest.approx(fresh["price"] * 0.25)

    def test_obstacle_repeat_joins_its_claim(self, tmp_path):
        """An obstacle row carrying `claim` joins the dispatch ledger on
        that claim; a claim-less obstacle reads repeat 0."""
        ws = _ws(tmp_path)
        row = _write_obstacle(ws, claim="C-3")
        _dispatch_rows(ws, ["C-3"])
        p = pricing.price_action(ws, "obstacle", row["id"])
        assert p["repeat"] == 1
        assert p["status"] == "undecided"

    def test_price_action_is_deterministic(self, tmp_path):
        """Pure computation: same workspace reads -> identical rows
        (replay does not drift; no ts, no RNG inside the price)."""
        ws = _ws(tmp_path)
        assert pricing.price_action(ws, "pq", "q-2") == \
            pricing.price_action(ws, "pq", "q-2")

    def test_bad_kind_refuses_fast(self, tmp_path):
        ws = _ws(tmp_path)
        with pytest.raises(ValueError):
            pricing.price_action(ws, "distill", "q-1")

    def test_price_for_claim_resolves_the_pq(self, tmp_path):
        """The claim-shaped face the dispatch read consumes: C-2a rides
        its PQ's price; a claim with no answers_question prices None
        (sub-task claims are out of the v1 PQ scope, honestly)."""
        ws = _ws(tmp_path)
        p = pricing.price_for_claim(ws, "C-2a")
        assert p is not None and p["kind"] == "pq"
        assert p["target"] == "q-2"
        assert pricing.price_for_claim(ws, "C-3") is None


# --------------------------------------------- 3. the consumption joins

class TestConsumptionJoins:
    def test_emit_price_lands_in_telemetry_family(self, tmp_path):
        """No new ledger: emitted rows ride the issue-721 telemetry family
        under their own probe-price/1 stamp, ts stamped at emit."""
        ws = _ws(tmp_path)
        row = pricing.price_action(ws, "pq", "q-1")
        assert pricing.emit_price(ws, row) is True
        rows = consolidated_ledger.read(
            ws, "telemetry", schema_prefix="probe-price")
        assert len(rows) == 1
        assert rows[0]["schema"] == pricing.PRICING_SCHEMA
        assert rows[0]["ts"]
        assert rows[0]["target"] == "q-1"
        assert consolidated_ledger.liveness(ws).get(
            "telemetry:probe-price/1") == 1

    def test_emit_refuses_a_priceless_row(self, tmp_path):
        """The append boundary stays loud: a row that never went through
        price_action (no gain/price keys) is refused, not appended."""
        ws = _ws(tmp_path)
        assert pricing.emit_price(ws, {"schema": "probe-price/1"}) is False
        assert consolidated_ledger.read(
            ws, "telemetry", schema_prefix="probe-price") == []

    def test_probe_consumption_counts(self, tmp_path):
        """The issue-801-shaped account: zero-info (decided re-probes) and
        repeat probes count separately; the billed price sums."""
        ws = _ws(tmp_path)
        _dispatch_rows(ws, ["C-2a"])
        for kind, tid in (("pq", "q-1"),   # decided -> zero info
                          ("pq", "q-2"),   # repeat 1
                          ("pq", "q-3")):  # fresh
            assert pricing.emit_price(
                ws, pricing.price_action(ws, kind, tid)) is True
        c = pricing.probe_consumption(ws)
        assert c["probes"] == 3
        assert c["zero_info_probes"] == 1
        assert c["repeat_probes"] == 1
        assert c["billed_price"] == pytest.approx(
            sum(pricing.price_action(ws, k, t)["price"]
                for k, t in (("pq", "q-1"), ("pq", "q-2"),
                             ("pq", "q-3"))))

    def test_cockpit_face_carries_the_pricing_block(self, tmp_path):
        """The issue-801 join: the cockpit consumption face carries the
        pricing account next to the ratio (probes are no longer free —
        they are visible in the same account the ratio reads)."""
        import cost_input_capture as cic
        ws = _ws(tmp_path)
        assert pricing.emit_price(
            ws, pricing.price_action(ws, "pq", "q-1")) is True
        tx = tmp_path / "t.jsonl"
        tx.write_text(json.dumps(
            {"message": {"usage": {"input_tokens": 10,
                                   "output_tokens": 5000}},
             "isSidechain": True}) + "\n", encoding="utf-8")
        face = cic.cockpit_ratio(ws, tx)
        assert face is not None
        assert face["pricing"]["probes"] == 1
        assert face["pricing"]["zero_info_probes"] == 1

    def test_supply_admission_reads_the_price(self, tmp_path, monkeypatch):
        """The dispatch qualification join: on the linked (allow) path
        the supply-admission face reads the claim's probe price and
        rides ONE advisory trace — never a gate decision. Fail-open:
        a broken pricing face degrades to the fail-open trace, and the
        allow verdict is untouched either way."""
        import dispatch_gate as dg
        ws = _ws(tmp_path)
        (ws / "hypotheses").mkdir()
        (ws / "hypotheses" / "H-1.md").write_text(
            "---\nid: H-1\nclaim_id: C-2a\n"
            "candidates: [variant-a, variant-b]\nstatus: open\n"
            "schema_rev: 1\n---\n\n# H-1 mechanism X\n",
            encoding="utf-8")
        seen: list[tuple] = []
        monkeypatch.setattr(
            dg, "_emit_trace",
            lambda ws_, action, claim_id, detail="", **kw:
                seen.append((action, claim_id)))
        rc = dg._supply_admission(ws, "C-2a", {})
        assert rc is None, "the advisory read must not gate"
        actions = [a for a, _ in seen]
        assert "probe_price" in actions
        assert "probe_price_fail_open" not in actions
