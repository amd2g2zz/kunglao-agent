# -*- coding: utf-8 -*-
"""tests/test_heartbeat_window_4.py - issue #4 heartbeat continuity window.

RED contract: the #754 continuity evaluator scanned the ENTIRE durable tick
sidecar, so ONE mid-life stall (laptop asleep over a weekend) re-rejected
the workspace forever - every later evaluation re-read the same historical
gap and no sanctioned recovery path existed. The verdict now reads a
SLIDING WINDOW (recent N ticks OR recent M hours); older ticks stay on disk
(append-only sidecar, nothing deleted) but stop participating in the
verdict, and aged-out stalls are surfaced in the detail text.

  W1  early-history stall + recent continuous ticks -> PASS (was REJECT)
  W2  stall INSIDE the window -> still REJECT (fix must not weaken
      in-window detection: a recent cadence hole, and a too-recent stall
      with too few resumed ticks, both keep rejecting)
  W3  brand-new workspace (2 clean ticks, both branches) -> PASS as before
  W4  aged-out stalls counted and surfaced in the verdict detail
  W5  window knobs are policy constants + function parameters; an override
      that widens the window to everything restores the legacy full-history
      verdict
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import heartbeat as hb_mod  # noqa: E402

NOW = datetime.now(timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def _write_sidecar(ws: Path, stamps: list[datetime]) -> Path:
    log = ws / "runs" / ".heartbeat.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        for dt in stamps:
            fh.write(json.dumps({"ts": _ts(dt), "actor": "test"}) + "\n")
    return log


def _cache_state(history: list[str]) -> dict:
    return {"started_ts": _ts(NOW - timedelta(days=7)),
            "interval_min": 5,
            "loop_registered": True,
            "last_tick_ts": history[-1] if history else _ts(NOW),
            "tick_history": list(history)}


def _recent_block(ticks: int = 12, newest_ago_min: int = 5,
                  cadence_min: int = 5) -> list[datetime]:
    """A clean continuous block ending newest_ago_min before NOW."""
    return [NOW - timedelta(minutes=newest_ago_min + cadence_min * i)
            for i in range(ticks - 1, -1, -1)]


# ===========================================================================
# W1 - the issue itself: a mid-life stall must age out
# ===========================================================================

class TestMidlifeStallAgesOut:
    def test_durable_branch_old_stall_plus_recent_continuity_passes(
            self, tmp_path):
        """THE incident: a weekend stall 3 days back + a clean recent block
        must be ALIVE - the historical gap no longer participates."""
        ws = _mk_ws(tmp_path)
        old = [NOW - timedelta(days=3, minutes=5), NOW - timedelta(days=3)]
        log = _write_sidecar(ws, old + _recent_block())
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state([]), log_path=log, now=NOW)
        assert alive is True, detail
        assert "aged out" in detail, detail

    def test_cache_history_branch_windows_too(self, tmp_path):
        """The window applies to the .heartbeat.json tick_history branch as
        well (no log_path) - same verdict, same aged-out surfacing."""
        hist = [_ts(NOW - timedelta(days=3, minutes=5)),
                _ts(NOW - timedelta(days=3))]
        hist += [_ts(t) for t in _recent_block()]
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state(hist), now=NOW)
        assert alive is True, detail
        assert "aged out" in detail, detail


# ===========================================================================
# W2 - the fix must not weaken in-window detection
# ===========================================================================

class TestInWindowStillRejects:
    def test_recent_cadence_hole_inside_window_rejects(self, tmp_path):
        ws = _mk_ws(tmp_path)
        stamps = [NOW - timedelta(minutes=m) for m in (60, 55, 25, 20, 5)]
        log = _write_sidecar(ws, stamps)  # 30-min hole between -55 and -25
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state([]), log_path=log, now=NOW)
        assert alive is False, detail
        assert "gap" in detail.lower() or "cadence" in detail.lower(), detail
        assert "aged out" not in detail, detail

    def test_stall_with_too_few_resumed_ticks_still_rejects(self, tmp_path):
        """Recovery needs a full window: a 3h-old stall with only 4 resumed
        ticks is still inside the window (last-12 and 24h both reach it)."""
        ws = _mk_ws(tmp_path)
        pre = [NOW - timedelta(hours=3), NOW - timedelta(hours=3) +
               timedelta(minutes=5)]
        log = _write_sidecar(ws, pre + _recent_block(ticks=4))
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state([]), log_path=log, now=NOW)
        assert alive is False, detail

    def test_brand_new_two_tick_durable_passes(self, tmp_path):
        """W3: a brand-new workspace keeps passing (no regression)."""
        ws = _mk_ws(tmp_path)
        log = _write_sidecar(ws, [NOW - timedelta(minutes=6),
                                  NOW - timedelta(minutes=1)])
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state([]), log_path=log, now=NOW)
        assert alive is True, detail
        assert "aged out" not in detail, detail

    def test_brand_new_two_tick_cache_passes(self):
        hist = [_ts(NOW - timedelta(minutes=6)), _ts(NOW - timedelta(minutes=1))]
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state(hist), now=NOW)
        assert alive is True, detail


# ===========================================================================
# W4 - aged-out stalls are counted and surfaced (no silent rewriting)
# ===========================================================================

class TestAgedOutSurfacing:
    def test_two_aged_out_stalls_counted(self, tmp_path):
        ws = _mk_ws(tmp_path)
        d3 = NOW - timedelta(days=3)
        old = [d3, d3 + timedelta(minutes=30), d3 + timedelta(minutes=35)]
        log = _write_sidecar(ws, old + _recent_block())
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state([]), log_path=log, now=NOW)
        assert alive is True, detail
        m = re.search(r"older history excluded: (\d+) stall", detail)
        assert m, f"aged-out count missing from detail: {detail}"
        assert m.group(1) == "2", detail

    def test_clean_long_history_no_aged_out_note(self, tmp_path):
        """Old out-of-window ticks with NO stall anywhere: verdict stays
        clean - no spurious aged-out claim. Uninterrupted ~25h of 5-min
        ticking: ticks older than the 24h bound drop out of the window, but
        no gap in the raw history ever exceeds 2x the interval."""
        ws = _mk_ws(tmp_path)
        stamps = [NOW - timedelta(minutes=5 * i) for i in range(307, 0, -1)]
        log = _write_sidecar(ws, stamps)
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state([]), log_path=log, now=NOW)
        assert alive is True, detail
        assert "aged out" not in detail, detail


# ===========================================================================
# W5 - window knobs: policy constants + overridable parameters
# ===========================================================================

class TestWindowKnobs:
    def test_defaults_are_policy_module_constants(self):
        from liveness_policy import (CONTINUITY_WINDOW_HOURS,
                                     CONTINUITY_WINDOW_TICKS)
        assert hb_mod.CONTINUITY_WINDOW_TICKS == CONTINUITY_WINDOW_TICKS
        assert hb_mod.CONTINUITY_WINDOW_HOURS == CONTINUITY_WINDOW_HOURS
        assert CONTINUITY_WINDOW_TICKS >= 1 and CONTINUITY_WINDOW_HOURS >= 1

    def test_widened_window_restores_legacy_full_history_verdict(
            self, tmp_path):
        """Operator escape hatch: a window wide enough to hold everything
        re-judges the historical gap (pre-#4 behavior, opt-in)."""
        ws = _mk_ws(tmp_path)
        old = [NOW - timedelta(days=3, minutes=5), NOW - timedelta(days=3)]
        log = _write_sidecar(ws, old + _recent_block())
        alive, detail = hb_mod.evaluate_tick_continuity(
            _cache_state([]), log_path=log, now=NOW,
            window_ticks=10 ** 6, window_hours=10 ** 6)
        assert alive is False, detail
