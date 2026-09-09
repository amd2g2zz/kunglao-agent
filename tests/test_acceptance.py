# -*- coding: utf-8 -*-
"""tests/test_acceptance.py — end-to-end static acceptance (issue #6, plan §2.3/§9)."""
from __future__ import annotations

import inspect

import pytest

import acceptance_check as ac

# both tests consume the SAME module-scoped report; the xdist group keeps
# them on one worker (--dist loadgroup) so the nested pinned smoke run
# inside executes once per suite, not once per worker
pytestmark = pytest.mark.xdist_group("acceptance")


@pytest.fixture(scope="module")
def acceptance_report() -> dict:
    """run_acceptance() once per module: the report is deterministic and the
    nested pinned smoke run inside it is the expensive part — computing it
    per test re-pays a full nested pytest collection for an identical
    result (both tests only READ the report)."""
    return ac.run_acceptance()


def test_acceptance_overall_passes(acceptance_report):
    report = acceptance_report
    failed = [c["name"] for c in report["checks"] if not c["passed"]]
    assert report["overall_passed"], f"acceptance failures: {failed}"


def test_acceptance_has_five_checks(acceptance_report):
    report = acceptance_report
    names = {c["name"] for c in report["checks"]}
    must = {"oracle_10_10", "cli_surface_8", "priority_voi_formula",
            "digest_builds", "test_suite_green"}
    assert must <= names, f"missing acceptance item(s): {must - names}"


def test_test_suite_green_keeps_quiet_no_cache_pytest_flags():
    """#351/#689: the embedded pytest invocation keeps -q --tb=no -p no:cacheprovider and
    excludes itself (a pinned acceptance nodeid would otherwise recurse; the
    default path is the pinned smoke subset per #689 — full-suite enforcement
    lives in devkit/quality_gates.py Gate 2)."""
    src = inspect.getsource(ac._check_test_suite)
    assert "-q" in src and "--tb=no" in src and "no:cacheprovider" in src
    assert "--ignore=tests/test_acceptance.py" in src
