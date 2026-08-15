# -*- coding: utf-8 -*-
"""#369 RED — load-adaptive budget for the nested acceptance test suite.

scripts/acceptance_check.py runs the full suite as a subprocess with a flat
300s timeout. Under parallel machine load (multi-agent dev, load16-31
observed 2026-08-15 in #377's DEV run) the same suite stretches past 300s
and test_suite_green fails on a subprocess timeout — not a test failure.
The budget must scale with load, honor an env override, and stay capped.
"""
import acceptance_check as ac


# ---------- pure budget computation ----------

def test_budget_floor_at_idle_load():
    assert ac._test_suite_timeout_s(loadavg=0.5, cpu_count=16) == ac.TEST_SUITE_TIMEOUT


def test_budget_scales_with_load_per_core():
    # load 48 on 16 cores -> factor 3 -> 900s
    assert ac._test_suite_timeout_s(loadavg=48.0, cpu_count=16) == 900


def test_budget_partial_load_is_proportional():
    # load 24 on 16 cores -> factor 1.5 -> 450s
    assert ac._test_suite_timeout_s(loadavg=24.0, cpu_count=16) == 450


def test_budget_capped_under_extreme_load():
    v = ac._test_suite_timeout_s(loadavg=1000.0, cpu_count=1)
    assert v <= ac.TEST_SUITE_TIMEOUT_CEILING


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv(ac.TEST_SUITE_TIMEOUT_ENV, "777")
    assert ac._test_suite_timeout_s(loadavg=1000.0, cpu_count=1) == 777


def test_env_override_floored_at_300(monkeypatch):
    monkeypatch.setenv(ac.TEST_SUITE_TIMEOUT_ENV, "10")
    assert ac._test_suite_timeout_s(loadavg=0.0, cpu_count=16) == ac.TEST_SUITE_TIMEOUT


def test_env_override_garbage_falls_back_to_load(monkeypatch):
    monkeypatch.setenv(ac.TEST_SUITE_TIMEOUT_ENV, "not-a-number")
    assert ac._test_suite_timeout_s(loadavg=48.0, cpu_count=16) == 900


def test_ceiling_allows_operators_headroom(monkeypatch):
    """Env override is the operator escape hatch: it may exceed the load
    ceiling (e.g. a deliberately over-subscribed machine) but is still sane."""
    monkeypatch.setenv(ac.TEST_SUITE_TIMEOUT_ENV, "3000")
    assert ac._test_suite_timeout_s(loadavg=0.0, cpu_count=16) == 3000


# ---------- wiring: _check_test_suite actually uses the budget ----------

def test_check_test_suite_uses_adaptive_budget(monkeypatch):
    captured = {}

    class FakeProc:
        returncode = 0
        stdout = "129 passed in 20.0s\n"
        stderr = ""

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(ac.subprocess, "run", fake_run)
    monkeypatch.setenv(ac.TEST_SUITE_TIMEOUT_ENV, "480")
    result = ac._check_test_suite()
    assert result["passed"] is True
    assert captured["timeout"] == 480
