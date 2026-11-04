#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watchdog_interval.py — #770: the reap/keep window derived from observed
liveness.

Pain point (owner feedback, rc2 testing 2026-10-18): the watchdog interval
was a fixed 5-minute wall clock — blind for a slow-but-progressing worker,
lax for a wedged one. Owner refinement (card comment 2026-10-19):
CONDITION-TRIGGERED + LONG-BASELINE — the long calm period is the NORM;
observed stall/poor-progress evidence TIGHTENS the window; the wall-clock
constant demotes to a bound (the floor) / cold-start fallback, and the
PRIMARY liveness signal is the progress ledger.

Scope vs #801 (card comment): the economics half (a fixed wake interval
burning tokens) is #801 Face 1's delivered pre-LLM wake gate; THIS module is
the decision half — the reap/keep decision derived from the worker's own
progress signal, with the two bidirectional pins:
  - an actively-writing worker is NEVER reaped on this face;
  - a wedged worker (fast cadence, silent past its own tolerance) is reaped
    well before the old fixed window.

THE FORMULA (documented per the acceptance; every bound single-sourced in
the liveness_policy #770 family, computed from STUCK_MINUTES /
TICK_INTERVAL_DEFAULT_MIN / DEAD_WORKER_MINUTES — never copied):

  inputs (WatchdogObservation — all mechanical, all optional):
    cadence_min         median gap between the worker's own progress-ledger
                        writes (worker-status step-line timestamps; None =
                        no cadence observed);
    last_write_age_min  minutes since the newest progress write (None = no
                        write ever observed);
    rounds_failed       consecutive failed rounds (poor-progress evidence);
    burn_rate           budget consumed / wall-time budget share
                        (None = unknown).

  derivation (long-baseline, condition-tightened; Standard 11: every
  result clamped into [MIN, MAX]):
    1. nothing observed                      -> BASELINE      "cold_start"
       (no evidence, no tightening — the wall-clock fallback)
    2. active writer: last_write <= cadence  -> MAX           "active_writer"
       (extend; the reap face never fires on an active writer)
    3. stall evidence -> tighten to 2 x cadence (BASELINE / TOLERANCE when
       the cadence is unknown), clamped into [MIN, BASELINE]  "stalled"
       evidence = silence past TOLERANCE x cadence
                  OR rounds_failed >= ROUNDS_FAIL_TRIGGER
                  OR burn_rate >= BURN_RATE_TIGHTEN while the newest write
                     is stale (> BASELINE / TOLERANCE)
    4. cadence known, calm                   -> TOLERANCE x cadence,
                                                clamped [MIN, BASELINE]
                                                                  "cadence"

  reap_verdict fires only when the observed silence exceeds the derived
  window AND the basis is not the active-writer extension.

Fail-safe posture: garbage inputs (negative, non-finite) read as ABSENT —
the derivation falls back toward the long baseline instead of inventing a
window from noise. Library module (no CLI): consumers are loop_watchdog.py
(the additive reap-window reason face) and tests. Pure stdlib +
liveness_policy — safe for hooks-side import (no sibling-module cycle).
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone

import liveness_policy as lp

#: The progress ledger's mechanical face: worker-status step lines carry ISO
#: stamps ("[2026-10-25T12:30:00Z] step: ..."). Legacy "[HH:MM]" lines carry
#: no date and are skipped — a missing sample never fabricates a cadence
#: (fail-safe to the mtime age / baseline arms instead).
_STEP_TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)Z?\]")


@dataclass(frozen=True)
class WatchdogObservation:
    """One worker's observed liveness snapshot (all fields optional)."""

    cadence_min: float | None = None
    last_write_age_min: float | None = None
    rounds_failed: int = 0
    burn_rate: float | None = None


@dataclass(frozen=True)
class DerivedInterval:
    """The derived reap/keep window plus its basis and echoed bounds
    (Standard 11: the clamp is part of the result, not an afterthought)."""

    minutes: float
    basis: str  # cold_start | active_writer | stalled | cadence
    lo: float
    hi: float


def _sane(value) -> float | None:
    """Negative / non-finite noise reads as absent (fail-safe)."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f < 0:
        return None
    return f


def derive_watchdog_interval(obs: WatchdogObservation) -> DerivedInterval:
    """The documented formula — see the module docstring for the contract."""
    lo = float(lp.WATCHDOG_MIN_MINUTES)
    hi = float(lp.WATCHDOG_MAX_MINUTES)
    baseline = float(lp.WATCHDOG_BASELINE_MINUTES)
    tol = float(lp.WATCHDOG_CADENCE_TOLERANCE)
    cadence = _sane(obs.cadence_min)
    last = _sane(obs.last_write_age_min)
    rounds = int(obs.rounds_failed or 0)
    burn = _sane(obs.burn_rate)

    if cadence is None and last is None and rounds <= 0 and burn is None:
        return DerivedInterval(baseline, "cold_start", lo, hi)
    if cadence is not None and last is not None and last <= cadence:
        return DerivedInterval(hi, "active_writer", lo, hi)

    def clamp_calm(target: float, basis: str) -> DerivedInterval:
        return DerivedInterval(min(max(target, lo), baseline), basis, lo, hi)

    stale_line = baseline / tol
    stalled = (
        (cadence is not None and last is not None and last > tol * cadence)
        or rounds >= lp.WATCHDOG_ROUNDS_FAIL_TRIGGER
        or (burn is not None and burn >= lp.WATCHDOG_BURN_RATE_TIGHTEN
            and last is not None and last > stale_line)
    )
    if stalled:
        target = (lp.WATCHDOG_TIGHTEN_FACTOR * cadence if cadence is not None
                  else stale_line)
        return clamp_calm(float(target), "stalled")
    if cadence is not None:
        return clamp_calm(tol * cadence, "cadence")
    # A write was seen but no cadence samples exist (single write, legacy
    # stamps): no evidence to tighten on — the long baseline applies.
    return DerivedInterval(baseline, "cold_start", lo, hi)


def reap_verdict(obs: WatchdogObservation) -> dict:
    """The decision half: {"reap": bool, "window_min", "basis", "reason"}.

    Reap iff the observed silence exceeds the derived window AND the basis
    is not the active-writer extension (pin: an actively-writing worker is
    never reaped). The reason token follows the watchdog's stable-token
    convention (heartbeat-gap:<n>min family)."""
    d = derive_watchdog_interval(obs)
    last = _sane(obs.last_write_age_min)
    reap = bool(last is not None and d.basis != "active_writer"
                and last > d.minutes)
    return {"reap": reap, "window_min": d.minutes, "basis": d.basis,
            "reason": (f"reap-window:{d.basis}:{d.minutes:.1f}min"
                       if reap else None)}


def observation_from_status(text: str, mtime: float, *,
                            now: datetime | None = None) -> WatchdogObservation:
    """Build the observation from one worker-status file's progress ledger.

    `text` is the file content, `mtime` its epoch stamp. Cadence = the
    median gap between consecutive ISO step-line timestamps; the last-write
    age is the fresher of the newest step stamp and the file mtime (a bare
    status-line rewrite counts as the write). Files without ISO stamps
    (legacy [HH:MM] lines) derive no cadence and fall back to the mtime
    age — absence of signal tightens nothing (the #597 posture: the policy
    is over observables, not guesses)."""
    now = now or datetime.now(timezone.utc)
    stamps: list[datetime] = []
    for m in _STEP_TS_RE.finditer(text or ""):
        try:
            ts = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
        except ValueError:
            continue
        stamps.append(ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc))
    stamps.sort()
    mtime_age = max(0.0, (now.timestamp() - float(mtime)) / 60.0)
    if not stamps:
        return WatchdogObservation(last_write_age_min=mtime_age)
    gaps = [(b - a).total_seconds() / 60.0
            for a, b in zip(stamps, stamps[1:])]
    gaps = [g for g in gaps if g > 0]
    cadence = statistics.median(gaps) if gaps else None
    last_age = max(0.0, (now - stamps[-1]).total_seconds() / 60.0)
    return WatchdogObservation(
        cadence_min=cadence,
        last_write_age_min=min(last_age, mtime_age))
