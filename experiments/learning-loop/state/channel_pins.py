# -*- coding: utf-8 -*-
"""state/channel_pins.py — the two P reward-channel safety pins (#904).

The Dark-Room paper ("The Dark Room in the Reward Channel", 2026) shows
dense per-step supervision under group-normalized RL can collapse the
policy: the paper's criterion is a signal's VARIANCE PROFILE — signals
whose variance DECAYS BY MASTERY become unbounded pressure under
z-scoring, and its shuffled-gold placebo matched the true-gold arm (the
gap survives without correct labels). #898's merged P(s) face consumes
ΔP through Beta-fold banking + terminal calibration, structurally
different from GRPO z-scoring — so these pins adopt the paper's caution
as TEST-LEVEL guards beside that face, with NO semantic change to ΔP.

Pin 1 — the variance-profile watch: ``variance_profile`` reads a P
trajectory (one P per lap/segment) and reports its spread profile. The
watch threshold ``DARK_ROOM_DECAY_RATIO`` is a DOCUMENTED constant, not
fitted (the same governance class as ``terminator.LOSS_CUT_N`` /
``stagnation.STAGNATION_FLOOR`` — changing one follows the
replay-evidence-plus-pins procedure): 0.25, an a-priori conservative
reading of the paper's qualitative criterion — the second half's
variance below a quarter of the first half's WHILE the mean still
rises is the mastery-decay precondition worth surfacing. The flag is a
watch, not a terminator: like the stagnation receipt it mutates no
posterior and ends no rollout.

Pin 2 — placebo-before-channel-change: ``APPROVED_CHANNELS`` is the
registry of ΔP consumption channels; ``beta-fold`` (#898) is the only
registered one. Any channel NOT in the registry is refused by
``placebo_gate`` with the documented rule in the reason (``PLACEBO_RULE``):
"a channel change re-runs the shuffled-P placebo control (the #887
scrambled-control pattern applied to P) before banking." The gate is
fail-closed: an unregistered channel banks nothing until its placebo
control has PASSED and the registry row is added by a reviewed change.

Fail-closed at the boundary (the progress/stagnation posture): a
non-numeric, non-finite, bool or too-short P series, and a garbage
channel name, raise ValueError.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

#: the Dark-Room watch threshold (see module docstring): second-half
#: variance / first-half variance must stay ABOVE this while the mean
#: rises; below it the mastery-decay precondition is flagged.
DARK_ROOM_DECAY_RATIO = 0.25

#: the ΔP consumption-channel registry — the closed list of channels
#: allowed to consume the merged ΔP face. ``beta-fold`` is #898's
#: banking path; every other channel must first pass the placebo rule.
APPROVED_CHANNELS: Mapping[str, bool] = {"beta-fold": True}

#: the documented channel-change rule — the named face a future card
#: cannot skip (issue #904 pin 2; the #887 scrambled-control pattern
#: applied to P).
PLACEBO_RULE = (
    "a channel change re-runs the shuffled-P placebo control (the #887 "
    "scrambled-control pattern applied to P) before banking")


def _fail(field: str, why: str) -> ValueError:
    return ValueError(f"state.channel_pins.{field}: {why}")


def _checked_series(series: Any) -> list[float]:
    """Fail-closed boundary for a P trajectory (the stagnation face's
    ``_checked_deltas`` posture): a sequence of >= 2 finite numbers —
    bools, strings, NaN/inf and short series never profile."""
    if series is None or isinstance(series, (str, bytes)) \
            or not isinstance(series, Sequence):
        raise _fail("P_series", "must be a sequence of finite numbers")
    if len(series) < 2:
        raise _fail("P_series",
                    f"needs >= 2 points (one per half), got {len(series)}")
    out: list[float] = []
    for i, v in enumerate(series):
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(v):
            raise _fail("P_series",
                        f"[{i}] must be a finite number, got {v!r}")
        out.append(float(v))
    return out


def _variance(values: Sequence[float]) -> float:
    """Population variance over the half (ddof=0 — the descriptive
    spread of the observed laps, not an estimator of a population)."""
    n = len(values)
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / n


def variance_profile(P_series: Sequence[float]) -> dict:
    """The Pin-1 watch over a P trajectory (one P per lap/segment).

    Splits the series into halves (first ``len // 2`` points, remainder
    in the second half — both halves non-empty by the >= 2 boundary)
    and returns the profile::

        {mean, variance,
         first_half_mean, first_half_var,
         second_half_mean, second_half_var,
         decay_ratio, threshold, dark_room_flag}

    ``decay_ratio`` is ``second_half_var / first_half_var``, 0-safe by
    documented branches: both halves flat -> 1.0 (no decay PROFILE is
    observable on a constant signal — the watch stays silent and defers
    to the stagnation face); a flat first half under a spread second
    half -> ``inf`` (variance GREW from the zero floor — maximal
    non-decay). ``dark_room_flag`` is True only when the decay ratio is
    BELOW ``DARK_ROOM_DECAY_RATIO`` while the mean still rises (the
    Dark-Room mastery-decay precondition). Pure function — no clock, no
    ledger write, no posterior mutation.
    """
    values = _checked_series(P_series)
    half = len(values) // 2
    first, second = values[:half], values[half:]
    first_mean = sum(first) / len(first)
    second_mean = sum(second) / len(second)
    first_var = _variance(first)
    second_var = _variance(second)
    if first_var > 0.0:
        decay = second_var / first_var
    elif second_var == 0.0:
        decay = 1.0   # constant signal: no decay profile observable
    else:
        decay = math.inf   # variance grew from the zero floor
    rises = second_mean > first_mean
    return {
        "mean": sum(values) / len(values),
        "variance": _variance(values),
        "first_half_mean": first_mean,
        "first_half_var": first_var,
        "second_half_mean": second_mean,
        "second_half_var": second_var,
        "decay_ratio": decay,
        "threshold": DARK_ROOM_DECAY_RATIO,
        "dark_room_flag": bool(decay < DARK_ROOM_DECAY_RATIO and rises),
    }


def placebo_gate(channel: str) -> dict:
    """The Pin-2 CHANNEL-CHANGE GATE: is this ΔP consumption channel
    allowed to bank?

    ``beta-fold`` (the registered #898 path) is approved. Any other
    well-formed channel name is REFUSED with ``PLACEBO_RULE`` verbatim
    in the reason — a channel change must first re-run the shuffled-P
    placebo control and add its registry row by a reviewed change.
    Garbage names (non-string, blank) are boundary garbage and raise
    (the fail-closed posture — they must never read as a refusal of a
    real proposal)."""
    if not isinstance(channel, str) or not channel.strip():
        raise _fail("channel", "must be a non-empty string")
    if APPROVED_CHANNELS.get(channel) is True:
        return {"channel": channel, "approved": True,
                "reason": "registered ΔP consumption channel "
                          "(the #898 Beta-fold banking face)"}
    return {"channel": channel, "approved": False,
            "reason": f"unregistered ΔP consumption channel — "
                      f"{PLACEBO_RULE}"}
