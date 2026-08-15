# -*- coding: utf-8 -*-
"""tests/test_acceptance.py — end-to-end static acceptance (issue #6, plan §2.3/§9)."""
from __future__ import annotations

import inspect

import acceptance_check as ac


def test_acceptance_overall_passes():
    report = ac.run_acceptance()
    failed = [c["name"] for c in report["checks"] if not c["passed"]]
    assert report["overall_passed"], f"acceptance failures: {failed}"


def test_acceptance_has_five_checks():
    report = ac.run_acceptance()
    names = {c["name"] for c in report["checks"]}
    must = {"oracle_10_10", "cli_surface_8", "priority_voi_formula",
            "digest_builds", "test_suite_green"}
    assert must <= names, f"missing acceptance item(s): {must - names}"


def test_test_suite_green_timeout_fits_full_suite():
    """#351: _check_test_suite embeds the full suite as a subprocess; the timeout must accommodate the suite's real duration
    (CI measured ~2.5 min). 60s constantly times out → acceptance always red."""
    assert ac.TEST_SUITE_TIMEOUT >= 300, (
        f"TEST_SUITE_TIMEOUT={ac.TEST_SUITE_TIMEOUT} — full suite CI actually runs ~150s, "
        "an overly short timeout makes test_suite_green always fail on timeout")


def test_test_suite_green_keeps_quiet_no_cache_pytest_flags():
    """#351: the embedded pytest invocation keeps -q --tb=no -p no:cacheprovider and
    excludes itself (otherwise recursive embedding)."""
    src = inspect.getsource(ac._check_test_suite)
    assert "-q" in src and "--tb=no" in src and "no:cacheprovider" in src
    assert "--ignore=tests/test_acceptance.py" in src
