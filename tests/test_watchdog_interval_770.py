#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_watchdog_interval_770.py — the reap/keep window derived from
observed liveness (issue #770).

Pain point (owner feedback, rc2 testing 2026-10-18): the watchdog interval
was a fixed 5-minute wall clock — blind for a slow-but-progressing worker,
lax for a wedged one. Owner refinement (card comment 2026-10-19):
CONDITION-TRIGGERED + LONG-BASELINE — the long calm period is the NORM,
observed stall/poor-progress evidence TIGHTENS it, and the wall-clock
constant demotes to a bound / cold-start fallback. The primary liveness
signal is the progress ledger.

Scope vs #801 (card comment): the economics half (wake tokens) is #801
Face 1's delivered work; this file pins the DECISION half:
  - the documented derivation formula (watchdog_interval.py);
  - the bidirectional pins: an actively-writing worker is NEVER reaped,
    a wedged worker is reaped well before the old fixed window;
  - the bounds (Standard 11): every derived value clamps to [MIN, MAX];
  - the #597 single-source discipline: the bound family lives in
    liveness_policy, COMPUTED from the existing constants (STUCK_MINUTES /
    TICK_INTERVAL_DEFAULT_MIN / DEAD_WORKER_MINUTES) — never copied;
  - the loop watchdog's additive reap-window reason face.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from _factories import write_claims_register, write_hook_state, \
    write_worker_status  # noqa: E402

NOW = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)


def _obs(**kw):
    import watchdog_interval as wi
    return wi.WatchdogObservation(**kw)


def _derive(**kw):
    import watchdog_interval as wi
    return wi.derive_watchdog_interval(_obs(**kw))


# ---------------------------------------------------------------------------
# (a) the bound family is single-sourced in liveness_policy, COMPUTED from
#     the existing constants — the #597 discipline (extend, don't copy).
# ---------------------------------------------------------------------------

def test_watchdog_bounds_family_is_parameterized_not_copied() -> None:
    """MIN/BASELINE/MAX must be expressions over the existing single-source
    constants — a bare int literal would silently fork the value."""
    import liveness_policy as lp
    src = SCRIPTS.joinpath("liveness_policy.py").read_text(encoding="utf-8")
    for name in ("WATCHDOG_MIN_MINUTES", "WATCHDOG_BASELINE_MINUTES",
                 "WATCHDOG_MAX_MINUTES"):
        m = re.search(rf"^{name}\s*=\s*(.+)$", src, re.MULTILINE)
        assert m, f"{name} missing from liveness_policy"
        rhs = m.group(1).strip()
        assert not re.fullmatch(r"\d+(\.\d+)?", rhs), (
            f"{name} = {rhs} is a copied literal — #597/#770 discipline: "
            f"compute it from STUCK_MINUTES / TICK_INTERVAL_DEFAULT_MIN / "
            f"DEAD_WORKER_MINUTES so a future adjudication moves the family.")
    # the values line up with the parameterization (1 / 25 / 35)
    assert lp.WATCHDOG_MIN_MINUTES == lp.TICK_INTERVAL_DEFAULT_MIN / 5
    assert (lp.WATCHDOG_BASELINE_MINUTES
            == lp.STUCK_MINUTES + lp.TICK_INTERVAL_DEFAULT_MIN)
    assert (lp.WATCHDOG_MAX_MINUTES
            == lp.DEAD_WORKER_MINUTES - lp.TICK_INTERVAL_DEFAULT_MIN)
    assert 0 < lp.WATCHDOG_MIN_MINUTES < 5.0 \
        < lp.WATCHDOG_BASELINE_MINUTES < lp.WATCHDOG_MAX_MINUTES


# ---------------------------------------------------------------------------
# (b) the documented formula — long-baseline, condition-tightened.
# ---------------------------------------------------------------------------

class TestDeriveFormula:
    def test_cold_start_falls_back_to_baseline(self):
        """Nothing observed: the wall-clock constant is demoted to the
        cold-start fallback — the long calm baseline, not the fixed 5."""
        d = _derive()
        assert d.basis == "cold_start"
        assert d.minutes == 25.0
        assert d.lo == 1.0 and d.hi == 35.0

    def test_active_writer_extends_to_max(self):
        """A worker writing inside its own cadence is ACTIVE: the window
        extends to the cap and the reap face never fires on it."""
        d = _derive(cadence_min=1.0, last_write_age_min=0.5)
        assert d.basis == "active_writer"
        assert d.minutes == 35.0

    def test_wedged_fast_cadence_tightens_below_old_fixed_window(self):
        """THE bidirectional pin (wedge direction): a worker that wrote
        every 0.5 min and went silent 4 min ago (8x its cadence) gets a
        window of 2 x 0.5 = 1 min — well below the old fixed 5."""
        d = _derive(cadence_min=0.5, last_write_age_min=4.0)
        assert d.basis == "stalled"
        assert d.minutes == pytest.approx(1.0)
        assert d.minutes < 5.0

    def test_calm_known_cadence_widens_with_tolerance(self):
        """Calm, cadence known, silence within tolerance: the window is the
        tolerance multiple of the cadence (4 x 3 = 12), still <= baseline."""
        d = _derive(cadence_min=3.0, last_write_age_min=6.0)
        assert d.basis == "cadence"
        assert d.minutes == pytest.approx(12.0)

    def test_stall_target_clamps_to_floor(self):
        """Standard 11 lower bound: a hyperactive cadence must not derive a
        sub-minute window — the floor catches it."""
        d = _derive(cadence_min=0.1, last_write_age_min=100.0)
        assert d.basis == "stalled"
        assert d.minutes == 1.0

    def test_cadence_target_clamps_to_baseline(self):
        """Standard 11 upper side of the tighten/cadence arms: a glacial
        cadence must not exceed the long baseline (only the ACTIVE
        extension reaches the cap)."""
        d = _derive(cadence_min=100.0, last_write_age_min=200.0)
        assert d.minutes == 25.0
        d2 = _derive(cadence_min=100.0, last_write_age_min=150.0)
        assert d2.basis == "cadence"
        assert d2.minutes == 25.0

    def test_failed_rounds_tighten_without_cadence(self):
        """Poor-progress evidence (rounds failing) tightens even when the
        write cadence is unknown: BASELINE / TOLERANCE = 6.25."""
        d = _derive(last_write_age_min=10.0, rounds_failed=2)
        assert d.basis == "stalled"
        assert d.minutes == pytest.approx(25.0 / 4.0)
        # one failed round is below the trigger — no tightening
        d2 = _derive(last_write_age_min=10.0, rounds_failed=1)
        assert d2.basis == "cold_start"

    def test_budget_burn_with_stale_writes_is_stall_evidence(self):
        """Budget burning >= 2x its wall share while the newest write is
        already stale (> BASELINE/TOLERANCE) = stall evidence; fresh
        writes plus fast burn is NOT (a worker may legitimately burn)."""
        d = _derive(burn_rate=2.5, last_write_age_min=7.0)
        assert d.basis == "stalled"
        d2 = _derive(burn_rate=2.5, last_write_age_min=1.0)
        assert d2.basis == "cold_start"
        d3 = _derive(burn_rate=1.9, last_write_age_min=100.0)
        assert d3.basis == "cold_start"

    def test_garbage_inputs_read_as_absent(self):
        """Fail-safe: negative / non-finite inputs are noise, not signal —
        they read as absent and the derivation falls back to baseline."""
        assert _derive(cadence_min=-1.0).basis == "cold_start"
        assert _derive(cadence_min=math.nan).basis == "cold_start"
        assert _derive(cadence_min=math.inf).basis == "cold_start"
        assert _derive(last_write_age_min=-5.0).basis == "cold_start"

    def test_every_derivation_stays_bounded(self):
        """Standard 11 sweep: no input combination may derive a window
        outside [MIN, MAX]."""
        for cadence in (0.01, 0.1, 0.5, 1.0, 4.0, 6.0, 20.0, 100.0, 1e6):
            for last in (0.0, 0.5, 3.0, 10.0, 30.0, 1000.0):
                d = _derive(cadence_min=cadence, last_write_age_min=last,
                            rounds_failed=3, burn_rate=9.9)
                assert 1.0 <= d.minutes <= 35.0, (cadence, last, d)


# ---------------------------------------------------------------------------
# (c) the decision half — reap_verdict bidirectional pins.
# ---------------------------------------------------------------------------

class TestReapVerdict:
    def test_active_writer_is_never_reaped(self):
        """THE bidirectional pin (active direction): a worker writing
        inside its own cadence is never reaped, no matter how tight its
        cadence would make any fixed window."""
        import watchdog_interval as wi
        v = wi.reap_verdict(_obs(cadence_min=0.2, last_write_age_min=0.15))
        assert v["reap"] is False
        assert v["basis"] == "active_writer"

    def test_wedged_worker_reaps_before_old_fixed_window(self):
        import watchdog_interval as wi
        v = wi.reap_verdict(_obs(cadence_min=0.5, last_write_age_min=4.0))
        assert v["reap"] is True
        assert v["window_min"] < 5.0
        assert v["reason"] == "reap-window:stalled:1.0min"

    def test_reap_boundary_is_strict(self):
        """Silence exactly at the window is not a reap (strict >)."""
        import watchdog_interval as wi
        v = wi.reap_verdict(_obs(last_write_age_min=25.0))
        assert v["reap"] is False
        v2 = wi.reap_verdict(_obs(last_write_age_min=25.5))
        assert v2["reap"] is True

    def test_silent_single_write_worker_reaps_at_baseline(self):
        """A worker that wrote once and never again has no cadence
        evidence: the long baseline applies — reaped past 25, not before,
        and strictly inside the death line (40)."""
        import watchdog_interval as wi
        assert wi.reap_verdict(
            _obs(last_write_age_min=10.0))["reap"] is False
        v = wi.reap_verdict(_obs(last_write_age_min=30.0))
        assert v["reap"] is True and v["window_min"] == 25.0


# ---------------------------------------------------------------------------
# (d) observation building — the progress ledger IS the worker-status
#     step-line timestamps (mechanical, no new state).
# ---------------------------------------------------------------------------

class TestObservationFromStatus:
    def _stamp(self, minutes_ago: float) -> str:
        ts = NOW - timedelta(minutes=minutes_ago)
        return ts.strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    def _status(self, ages_min: list[float], status: str = "in-progress",
                mtime_age: float | None = None) -> tuple[str, float]:
        lines = [f"[{self._stamp(a)}] step: s{i} | status: in-progress"
                 for i, a in enumerate(ages_min)]
        lines.append(f"[{self._stamp(ages_min[-1])}] wait: x | status: {status}")
        mtime = (NOW - timedelta(
            minutes=len(ages_min) if mtime_age is None else mtime_age
        )).timestamp()
        return "\n".join(lines) + "\n", mtime

    def test_iso_step_lines_derive_cadence_and_freshness(self):
        import watchdog_interval as wi
        text, mtime = self._status([3.0, 2.5, 2.0, 1.5])
        obs = wi.observation_from_status(text, mtime, now=NOW)
        assert obs.cadence_min == pytest.approx(0.5)
        assert obs.last_write_age_min == pytest.approx(1.5, abs=1 / 60)

    def test_legacy_hhmm_lines_derive_no_cadence(self):
        """Legacy `[HH:MM]` stamps carry no date: skipping them must not
        fabricate a cadence (fallback = mtime age, baseline applies)."""
        import watchdog_interval as wi
        text = ("[12:00] step: started | status: in-progress\n"
                "[12:30] wait: x | status: in-progress\n")
        mtime = (NOW - timedelta(minutes=10)).timestamp()
        obs = wi.observation_from_status(text, mtime, now=NOW)
        assert obs.cadence_min is None
        assert obs.last_write_age_min == pytest.approx(10.0)

    def test_unreadable_text_falls_back_to_mtime(self):
        import watchdog_interval as wi
        mtime = (NOW - timedelta(minutes=7)).timestamp()
        obs = wi.observation_from_status("", mtime, now=NOW)
        assert obs.cadence_min is None
        assert obs.last_write_age_min == pytest.approx(7.0)

    def test_status_only_rewrite_counts_as_the_write(self):
        """An mtime NEWER than the newest step stamp (a bare status-line
        rewrite) is the true last write — the fresher of the two wins."""
        import watchdog_interval as wi
        text, _ = self._status([30.0, 20.0])
        mtime = (NOW - timedelta(minutes=2)).timestamp()
        obs = wi.observation_from_status(text, mtime, now=NOW)
        assert obs.last_write_age_min == pytest.approx(2.0, abs=1 / 60)


# ---------------------------------------------------------------------------
# (e) the loop watchdog's additive reap-window face.
# ---------------------------------------------------------------------------

def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [])
    write_hook_state(ws, active_hooks=["cost_gate"])
    return ws


def _activity_row(ws: Path, minutes_ago: float) -> None:
    log = ws / "runs" / ".heartbeat.log"
    ts = _iso(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": ts, "actor": "tick"}) + "\n")


def _iso_worker(ws: Path, name: str, ages_min: list[float],
                status: str = "in-progress") -> Path:
    """A status file whose step lines carry ISO stamps (the mechanical
    progress ledger the derivation reads)."""
    now = datetime.now(timezone.utc)

    def st(m: float) -> str:
        return (now - timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S") + "Z"

    lines = [f"[{st(a)}] step: s{i} | status: in-progress"
             for i, a in enumerate(ages_min)]
    lines.append(f"[{st(ages_min[-1])}] wait: x | status: {status}")
    p = ws / "runs" / f"worker-status-{name}.md"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    old = time.time() - ages_min[-1] * 60
    os.utime(p, (old, old))
    return p


class TestLoopWatchdogReapWindow:
    def test_wedged_worker_fires_reap_window_before_stuck_line(self, tmp_path):
        """A fast-cadence worker silent past its derived window fires the
        reap-window reason NOW — minutes before the canonical 20-min stuck
        line and before the old fixed 5-min cron wake would act."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=1)
        _iso_worker(ws, "w1", [4.5, 4.0, 3.5, 4.0])  # cadence .5, silence 4
        res = loop_watchdog.evaluate(ws)
        assert res["fired"] is True, res
        assert any(r.startswith("reap-window:") for r in res["reasons"]), res
        assert not any("stuck-worker" in r for r in res["reasons"]), res

    def test_active_writer_does_not_fire(self, tmp_path):
        """THE bidirectional pin, end to end: a worker writing inside its
        cadence never trips the reap-window face."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=1)
        _iso_worker(ws, "w1", [1.0, 0.6, 0.2])
        res = loop_watchdog.evaluate(ws)
        assert res["fired"] is False, res

    def test_canonically_stuck_worker_stays_on_the_stuck_face(self, tmp_path):
        """No double narration: a worker already past STUCK_MINUTES is
        reported by the stuck face; the reap window does not duplicate."""
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=1)
        write_worker_status(ws, "w1", "in-progress", age_min=45)
        res = loop_watchdog.evaluate(ws)
        assert any("stuck-worker" in r for r in res["reasons"]), res
        assert not any(r.startswith("reap-window:") for r in res["reasons"])

    def test_done_worker_is_silent(self, tmp_path):
        import loop_watchdog
        ws = _mk_ws(tmp_path)
        _activity_row(ws, minutes_ago=1)
        _iso_worker(ws, "w1", [30.0, 29.5], status="done")
        res = loop_watchdog.evaluate(ws)
        assert res["fired"] is False, res
