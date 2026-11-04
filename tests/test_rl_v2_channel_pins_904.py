# -*- coding: utf-8 -*-
"""tests/test_rl_v2_channel_pins_904.py — the P reward-channel pins (904).

RED-first pins for the two TEST-LEVEL safety pins on the merged P(s)
face (#898) — the Dark-Room paper's caution made testable, with NO
semantic change to ΔP:

  1. variance-profile watch — the P trajectory across laps/segments
     carries its VARIANCE PROFILE (mean, total variance, per-half
     variance, decay ratio); the Dark-Room precondition (variance
     decays by mastery while the mean still rises) raises a
     ``dark_room_flag``; a healthy mastery series does not; the
     constant series is 0-safe (no division by a zero floor, no flag);
     fail-closed rejects (empty, non-numeric, NaN/inf, bools);
  2. placebo-before-channel-change — ``beta-fold`` (#898's Beta-fold
     banking) is the only registered ΔP consumption channel; any other
     channel is refused with the documented rule IN THE REASON: a
     channel change re-runs the shuffled-P placebo control (the #887
     scrambled-control pattern applied to P) before banking; garbage
     channel names raise (fail-closed boundary).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from state import channel_pins  # noqa: E402

# ---------------------------------------------------------------- pin 1


def test_dark_room_flags_rising_mean_decaying_variance():
    """Mastery with a collapsing variance profile: the first half swings
    widely around a lower mean, the second half is nearly constant
    around a higher mean — the Dark-Room precondition."""
    series = [0.0, 4.0, 1.0, 5.0, 8.0, 8.1, 8.0, 8.1]
    profile = channel_pins.variance_profile(series)
    assert profile["first_half_var"] > profile["second_half_var"] * 4
    assert profile["second_half_mean"] > profile["first_half_mean"]
    assert profile["decay_ratio"] < channel_pins.DARK_ROOM_DECAY_RATIO
    assert profile["dark_room_flag"] is True


def test_healthy_series_does_not_flag():
    """A linear mastery ramp holds its spread: the decay ratio sits at
    ~1.0 (no collapse) even though the mean rises — no flag."""
    series = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    profile = channel_pins.variance_profile(series)
    assert profile["dark_room_flag"] is False
    assert profile["decay_ratio"] >= channel_pins.DARK_ROOM_DECAY_RATIO


def test_constant_series_is_zero_safe():
    """The 0-safe pin: a constant series drives both half variances to
    0 — no ZeroDivisionError, a finite documented decay ratio, no flag
    (a flat signal is the stagnation face's business, not a fake
    dark-room reading)."""
    profile = channel_pins.variance_profile([2.0] * 8)
    assert profile["first_half_var"] == 0.0
    assert profile["second_half_var"] == 0.0
    assert math.isfinite(profile["decay_ratio"])
    assert profile["decay_ratio"] == 1.0
    assert profile["dark_room_flag"] is False


def test_variance_growing_from_zero_floor_does_not_flag():
    """first half constant, second half spread out: variance GREW —
    maximal non-decay, never a flag (documented 0-safe branch)."""
    profile = channel_pins.variance_profile([1.0, 1.0, 1.0, 1.0,
                                             0.0, 2.0, 0.5, 1.5])
    assert profile["first_half_var"] == 0.0
    assert profile["second_half_var"] > 0.0
    assert math.isinf(profile["decay_ratio"])
    assert profile["dark_room_flag"] is False


def test_profile_keys_present_and_finite():
    """The acceptance pin: the profile carries the documented variance
    series fields, all finite, plus the threshold it was judged
    against (the threshold rides the output — never a hidden fit)."""
    profile = channel_pins.variance_profile([0.5, 1.5, 2.5, 3.5])
    for key in ("mean", "variance", "first_half_mean", "first_half_var",
                "second_half_mean", "second_half_var", "decay_ratio",
                "threshold", "dark_room_flag"):
        assert key in profile, f"missing profile key {key}"
    for key in ("mean", "variance", "first_half_mean", "first_half_var",
                "second_half_mean", "second_half_var", "decay_ratio"):
        assert math.isfinite(profile[key]), f"non-finite {key}"
    assert profile["threshold"] == channel_pins.DARK_ROOM_DECAY_RATIO


def test_threshold_is_a_documented_constant():
    """The watch threshold is policy, not fitted: 0.25, the documented
    a-priori reading of the Dark-Room criterion (second-half variance
    at or under a quarter of the first half's, while the mean still
    rises)."""
    assert channel_pins.DARK_ROOM_DECAY_RATIO == 0.25


@pytest.mark.parametrize("bad", [
    [],
    ["a", 1.0, 2.0],
    [1.0, float("nan"), 2.0],
    [1.0, float("inf"), 2.0],
    [True, False, True, False],
    "01234567",
    None,
])
def test_fail_closed_rejects(bad):
    """Garbage in the P series never produces a profile — the
    fail-closed boundary posture of the state faces."""
    with pytest.raises(ValueError):
        channel_pins.variance_profile(bad)


def test_short_series_rejected():
    """A single P value has no halves: the profile needs >= 2 points."""
    with pytest.raises(ValueError):
        channel_pins.variance_profile([1.0])


# ---------------------------------------------------------------- pin 2


def test_beta_fold_is_the_registered_channel():
    """The registry pins beta-fold (#898's ΔP -> Beta-fold banking) as
    the approved consumption channel."""
    assert dict(channel_pins.APPROVED_CHANNELS) == {"beta-fold": True}
    gate = channel_pins.placebo_gate("beta-fold")
    assert gate["channel"] == "beta-fold"
    assert gate["approved"] is True


def test_unknown_channel_refused_with_placebo_rule():
    """A channel NOT in the registry is refused, and the reason carries
    the documented rule verbatim: re-run the shuffled-P placebo control
    (the #887 scrambled-control pattern applied to P) before banking."""
    gate = channel_pins.placebo_gate("gradient")
    assert gate["channel"] == "gradient"
    assert gate["approved"] is False
    assert channel_pins.PLACEBO_RULE in gate["reason"]


def test_placebo_rule_names_the_scrambled_control():
    """The documented rule is a NAMED face a future card cannot skip:
    it must reference the placebo control and its #887 pattern."""
    rule = channel_pins.PLACEBO_RULE
    assert "placebo" in rule.lower()
    assert "#887" in rule
    assert "P" in rule


@pytest.mark.parametrize("bad", ["", "   ", None, 7, ["beta-fold"]])
def test_garbage_channel_raises(bad):
    """Non-string or empty channel names are boundary garbage — raise,
    never a silent refusal dict (the state faces' posture)."""
    with pytest.raises(ValueError):
        channel_pins.placebo_gate(bad)


def test_dark_room_requires_rising_mean_not_decay_alone():
    """The falling-mean conjunct branch (review M1): variance decays
    below the threshold while the mean FALLS — growth, not the
    mastery-decay precondition; no flag. Deleting the `and rises`
    conjunct flips this pin red."""
    series = [10.0, 2.0, 9.0, 1.0, 3.0, 2.5, 3.5, 2.0]
    out = channel_pins.variance_profile(series)
    assert out["decay_ratio"] < channel_pins.DARK_ROOM_DECAY_RATIO
    assert out["dark_room_flag"] is False