#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""coeff_sim.py — the pre-implementation experiment for the rollout-timer
host wiring (issue 1001 workstream B).

Drives the REAL host faces (rlvr.rollout_timer_host: arm_for_dispatch /
round_close_face / deadline_wake_face) OFFLINE over 200 synthetic
rollouts — two difficulty families with log-normal true durations —
passing an explicit synthetic clock into the arm and wake faces (the
policy helpers are pure; this experiment never reads the wall clock as
policy input). It is the sanity gate the host wiring must pass before
it lands: if the bounded coefficient table produces an insane
trajectory (a coefficient pegged at a clamp, budgets ignoring the
family history, deadline-stop rows leaking into the strategic feed),
the wiring is wrong, not the math.

Pins asserted here (each printed as PASS/FAIL, exit 1 on any FAIL):

  P1 bounds     every coefficient the table ever produces (and every
                armed timer's coefficient) stays inside [0.5, 4.0];
                every derived budget stays inside [15, 480] minutes.
  P2 censoring  every deadline-fired rollout is censored from the
                strategic feed: its timer row carries stop_reason
                ``deadline`` + excluded_from_strategy_learning, the
                settlement-facing stop record introduces NO disposition
                key, and the strategic-feed exclusion filter drops
                exactly the fired set. The outcome vocabulary stays the
                closed five-word set (the stop reason rides outside it).
  P3 one chain  the coefficient stays ONE global chain across both
                difficulty families while a bucket is under its sample
                floor — and even after bucket_ready flips (the split is
                a later card), every budget row's coeff_before equals
                the previous row's coeff_after.
  P4 sane run   the final coefficient sits strictly inside the bounds
                (never parked on a clamp), the clamped-update share is
                small, and the learned base estimates separate the
                families (the hard family's base ends above the easy
                family's).

Usage:
    python experiments/scheduler/coeff_sim.py [--rollouts 200] [--seed 1001]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
for _p in (SCRIPTS,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import rlvr.rollout_timer as rollout_timer  # noqa: E402
import rlvr.rollout_timer_host as rollout_timer_host  # noqa: E402
from rlvr import consolidated_ledger as ledger  # noqa: E402

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
GAP_MIN = 5.0

#: the two synthetic difficulty families (log-normal parameters)
FAMILIES = (
    ("easy", math.log(20.0), 0.35),
    ("hard", math.log(90.0), 0.50),
)

#: share of over-budget rollouts that still finish during the wrap-up
LATE_FINISH_SHARE = 0.2


def _draw_duration(rng: random.Random, mu: float, sigma: float) -> float:
    return math.exp(rng.gauss(mu, sigma))


def _seed_dispatch_ledger(ws: Path, rid: str, claim: str) -> None:
    """Seed the dispatch-ledger row the round-close face resolves the
    rollout identity from (the dispatch transaction's committed row
    shape; the experiment simulates the lifecycle without the gate
    chain)."""
    p = ws / "runs" / "dispatch-ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"schema": "dispatch-ledger/1", "ts": "2026-01-01T00:00:00Z",
           "dispatch_id": rid, "claim": claim, "state": "committed",
           "actor": "coeff-sim"}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def run_sim(rollouts: int = 200, seed: int = 1001) -> dict:
    rng = random.Random(seed)
    rows: list[dict] = []
    stop_records: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="coeff-sim-") as tmp:
        ws = Path(tmp) / "ws"
        (ws / "runs").mkdir(parents=True)
        now = T0
        for i in range(rollouts):
            family, mu, sigma = FAMILIES[i % len(FAMILIES)]
            rid = f"sim-{i:04d}"
            claim = f"C-{i:04d}"
            _seed_dispatch_ledger(ws, rid, claim)
            # the lifecycle runs through the REAL host faces: the arm
            # publishes into the per-rollout wake map, the round close
            # resolves the rollout from the dispatch ledger, the wake
            # face fires + records + cancels + learns
            armed = rollout_timer_host.arm_for_dispatch(
                ws, claim, rid, method_family=family, now=now)
            if armed is None:
                raise SystemExit(f"arm refused for {rid} — host wiring "
                                 "broken")
            row = armed["row"]
            budget = float(row["budget_min"])
            actual = _draw_duration(rng, mu, sigma)
            fired = actual > budget
            outcome = ""
            late_finish = False
            if not fired:
                outcome = ("early" if actual <= rollout_timer.EARLY_RATIO
                           * budget else "on_time")
                close = rollout_timer_host.round_close_face(ws, {
                    "claim": claim, "outcome": "completed",
                    "duration_ms": actual * 60000,
                    "wall_s": actual * 60,
                })
                assert close, f"round close lost {rid}"
                assert close["learned"], f"round close learned none {rid}"
            else:
                deadline = now + timedelta(minutes=budget)
                wake = rollout_timer_host.deadline_wake_face(
                    ws, rid, now=deadline)
                assert wake, f"wake lost {rid}"
                assert wake["stop"]["stop_reason"] == "deadline"
                stop_records.append(wake["stop"])
                outcome = "timeout"
                actual = budget
                late_finish = rng.random() < LATE_FINISH_SHARE
                if late_finish:
                    # the worker finishes during the wrap-up: the round
                    # close sees a FIRED timer and is censored — cancel
                    # only, never a second learn
                    close = rollout_timer_host.round_close_face(ws, {
                        "claim": claim, "outcome": "completed",
                        "duration_ms": (budget + 5.0) * 60000,
                        "wall_s": (budget + 5.0) * 60,
                    })
                    assert close, f"censor lost {rid}"
                    assert close["censored"], f"censor absent {rid}"
            rows.append({
                "i": i, "family": family, "rid": rid,
                "base": float(row["base_min"]),
                "coeff_before": float(row["coeff"]),
                "budget": budget, "actual": round(actual, 3),
                "outcome": outcome, "fired": fired,
                "late_finish": late_finish,
            })
            now += timedelta(minutes=actual + GAP_MIN)

        # the ledger's durable view is what the assertions read
        timer_rows = ledger.read(ws, "telemetry",
                                 schema_prefix=rollout_timer.TIMER_SCHEMA)
        budget_rows = ledger.read(ws, "telemetry",
                                  schema_prefix=rollout_timer.BUDGET_SCHEMA)
        fired_ids = {r["rid"] for r in rows if r["fired"]}
        coeff_by_rid = {}
        for r in budget_rows:
            coeff_by_rid[r.get("rollout_id")] = r.get("coeff_after")
        for r in rows:
            r["coeff_after"] = coeff_by_rid.get(r["rid"])
            r["updated"] = True  # every row here applied a real update

    return {
        "rows": rows, "stop_records": stop_records,
        "timer_rows": timer_rows, "budget_rows": budget_rows,
        "fired_ids": fired_ids,
    }


def _pin_bounds(result: dict, failures: list[str]) -> None:
    """P1 — every coefficient and budget the run ever produced."""
    rows = result["rows"]
    timer_rows = result["timer_rows"]
    missing = [r["rid"] for r in rows if not r.get("coeff_after")]
    if missing:
        failures.append(f"P1 rollouts whose learn wrote no audit row: "
                        f"{missing[:5]}")
    coeffs = ([r["coeff_before"] for r in rows]
              + [float(r["coeff_after"]) for r in rows]
              + [float(t.get("coeff")) for t in timer_rows if t.get("coeff")])
    bad = [c for c in coeffs
           if not (rollout_timer.MIN_COEFF <= c <= rollout_timer.MAX_COEFF)]
    if bad:
        failures.append(f"P1 coeff out of bounds: {bad[:5]}")
    else:
        print(f"P1 PASS coeff bounds: {len(coeffs)} values all inside "
              f"[{rollout_timer.MIN_COEFF}, {rollout_timer.MAX_COEFF}]")
    budgets = ([r["budget"] for r in rows]
               + [float(t.get("budget_min")) for t in timer_rows])
    bad_b = [b for b in budgets
             if not (rollout_timer.MIN_BUDGET_MIN <= b
                     <= rollout_timer.MAX_BUDGET_MIN)]
    if bad_b:
        failures.append(f"P1 budget out of bounds: {bad_b[:5]}")
    else:
        print(f"P1 PASS budget bounds: {len(budgets)} values all inside "
              f"[{rollout_timer.MIN_BUDGET_MIN}, "
              f"{rollout_timer.MAX_BUDGET_MIN}]")


def _pin_censoring(result: dict, failures: list[str]) -> None:
    """P2 — deadline stops never enter the strategic feed, pinned
    against the REAL host faces: the wake face produced the fired rows,
    the round close censored the late finishes, and the ledger rows
    carry the markers."""
    timer_rows = result["timer_rows"]
    budget_rows = result["budget_rows"]
    stop_records = result["stop_records"]
    fired_ids = result["fired_ids"]

    def _strategic_feed(rows: list[dict]) -> list[dict]:
        """The exclusion filter: a row carrying the deadline exclusion
        marker never enters the strategic feed."""
        return [r for r in rows
                if not r.get("excluded_from_strategy_learning")]

    # through the real learn: a fired rollout owns EXACTLY ONE budget
    # row (the wake's timeout) — the late finishes wrote no second row
    per_rollout = {}
    for r in budget_rows:
        per_rollout[r.get("rollout_id")] = per_rollout.get(
            r.get("rollout_id"), 0) + 1
    bad_counts = {rid: n for rid, n in per_rollout.items()
                  if rid in fired_ids and n != 1}
    if bad_counts:
        failures.append(f"P2 censored rollouts with a wrong budget-row "
                        f"count: {dict(list(bad_counts.items())[:5])}")
    else:
        print(f"P2 PASS every fired rollout owns exactly ONE budget row "
              f"(the wake's timeout audit — the late finishes' round "
              f"closes were censored through the real host face)")
    outcome_faces = [r for r in list(timer_rows) + list(stop_records)
                     if r.get("stop_reason") or r.get("state") == "fired"]
    uncensored = [r for r in outcome_faces
                  if r.get("rollout_id") in fired_ids
                  and not r.get("excluded_from_strategy_learning")]
    if uncensored:
        failures.append("P2 fired outcome faces missing the exclusion "
                        f"marker: "
                        f"{[r.get('rollout_id') for r in uncensored][:5]}")
    else:
        print(f"P2 PASS every outcome face of a fired rollout carries "
              f"stop_reason={rollout_timer.STOP_REASON_DEADLINE} + the "
              f"strategic exclusion marker ({len(fired_ids)} fired)")
    leaked = _strategic_feed(outcome_faces)
    if leaked:
        failures.append("P2 deadline-censored rows present in the "
                        "strategic feed after the exclusion filter")
    else:
        print(f"P2 PASS the exclusion filter drops every deadline-stop "
              f"face from the strategic feed "
              f"({len(outcome_faces)} faces filtered)")
    leaky = [s for s in stop_records
             if "disposition" in s
             or s.get("excluded_from_strategy_learning") is not True]
    if leaky:
        failures.append(f"P2 stop record leaked a disposition face: "
                        f"{len(leaky)}")
    else:
        print(f"P2 PASS {len(stop_records)} stop records carry no "
              f"disposition key (the seven-word set untouched)")
    if rollout_timer.STOP_REASON_DEADLINE in rollout_timer.OUTCOMES:
        failures.append("P2 stop reason entered the outcome vocabulary")
    else:
        print("P2 PASS the stop reason rides OUTSIDE the closed outcome "
              f"vocabulary {rollout_timer.OUTCOMES}")


def _pin_global_chain(result: dict, failures: list[str]) -> None:
    """P3 — one global coefficient chain across families (no bucket
    split at/under the sample floor; the split itself is a later
    card)."""
    chain_breaks = []
    prev_after = None
    for r in result["budget_rows"]:
        before = float(r.get("coeff_before"))
        if prev_after is not None and before != prev_after:
            chain_breaks.append(r.get("rollout_id"))
        prev_after = float(r.get("coeff_after"))
    if chain_breaks:
        failures.append(f"P3 coefficient chain broke at {chain_breaks[:5]}")
        return
    buckets = {str(r.get("bucket_key")) for r in result["budget_rows"]}
    ready = [b for b in buckets
             if rollout_timer.bucket_ready(result["budget_rows"], b)]
    print(f"P3 PASS one global coefficient chain across {len(buckets)} "
          f"buckets (split-ready buckets observed: {ready or 'none'} — "
          f"the coefficient stayed global regardless)")


def _pin_sane_trajectory(result: dict, failures: list[str]) -> None:
    """P4 — the final coefficient sits strictly inside the bounds, the
    clamped-update share is small, and the learned base estimates
    separate the families."""
    rows = result["rows"]
    final = rows[-1]["coeff_after"]
    if final is None or not (rollout_timer.MIN_COEFF < final
                             < rollout_timer.MAX_COEFF):
        failures.append(f"P4 final coeff parked at/over a clamp: {final}")
    clamped = sum(1 for r in result["budget_rows"]
                  if "clamped" in str(r.get("reason", "")))
    share = clamped / max(1, len(result["budget_rows"]))
    if share >= 0.2:
        failures.append(f"P4 clamped-update share {share:.0%} >= 20%")
        return
    print(f"P4 PASS final coeff {final} strictly inside the bounds; "
          f"clamped-update share {share:.1%}")
    easy_base = [r["base"] for r in rows if r["family"] == "easy"]
    hard_base = [r["base"] for r in rows if r["family"] == "hard"]
    if statistics.median(hard_base) <= statistics.median(easy_base):
        failures.append("P4 hard family's base did not separate above easy")
    else:
        print(f"P4 PASS base separation: easy median base "
              f"{statistics.median(easy_base):.1f} min vs hard "
              f"{statistics.median(hard_base):.1f} min")


def check_pins(result: dict) -> list[str]:
    failures: list[str] = []
    _pin_bounds(result, failures)
    _pin_censoring(result, failures)
    _pin_global_chain(result, failures)
    _pin_sane_trajectory(result, failures)
    return failures


def print_trajectory(result: dict, head: int = 12, tail: int = 6) -> None:
    rows = result["rows"]
    print("\n=== trajectory (first "
          f"{min(head, len(rows))} of {len(rows)} rollouts) ===")
    print(f"{'i':>4} {'family':>5} {'base':>7} {'coeff0':>7} "
          f"{'budget':>7} {'actual':>8} {'outcome':>8} {'coeff1':>7} "
          f"{'upd':>4}")
    for r in rows[:head] + rows[-tail:]:
        print(f"{r['i']:>4} {r['family']:>5} {r['base']:>7.1f} "
              f"{r['coeff_before']:>7.3f} {r['budget']:>7.1f} "
              f"{r['actual']:>8.1f} {r['outcome']:>8} "
              f"{r['coeff_after']:>7.3f} {str(r['updated']):>4}")
    families = sorted({r["family"] for r in rows})
    print("\n=== per-family summary ===")
    print(f"{'family':>6} {'n':>4} {'med base':>9} {'med actual':>11} "
          f"{'timeouts':>9} {'early':>6} {'on_time':>8} {'updated':>8}")
    for family in families:
        sub = [r for r in rows if r["family"] == family]
        print(f"{family:>6} {len(sub):>4} "
              f"{statistics.median(r['base'] for r in sub):>9.1f} "
              f"{statistics.median(r['actual'] for r in sub):>11.1f} "
              f"{sum(1 for r in sub if r['outcome'] == 'timeout'):>9} "
              f"{sum(1 for r in sub if r['outcome'] == 'early'):>6} "
              f"{sum(1 for r in sub if r['outcome'] == 'on_time'):>8} "
              f"{sum(1 for r in sub if r['updated']):>8}")
    print(f"\nfinal coefficient: {rows[-1]['coeff_after']}  "
          f"fired: {len(result['fired_ids'])}/{len(rows)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rollouts", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1001)
    args = ap.parse_args()
    result = run_sim(rollouts=args.rollouts, seed=args.seed)
    print_trajectory(result)
    failures = check_pins(result)
    if failures:
        print("\n=== FAILURES ===")
        for f in failures:
            print(f"FAIL {f}")
        return 1
    print("\nGATE: sane trajectory — all pins passed; the host wiring "
          "may proceed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
