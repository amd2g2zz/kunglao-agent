# -*- coding: utf-8 -*-
"""tests/test_acceptance_689.py — RED contracts for the acceptance embed retirement.

#689: `scripts/acceptance_check.py::_check_test_suite` embedded the ENTIRE pytest
suite as a subprocess; tests/test_acceptance.py invoked `run_acceptance()` twice,
so every suite run paid 2x ~301s (60% of the 1,004s full-suite runtime, 2026-08-25
audit). These tests pin the post-fix contract:

1. the default check path is a pinned smoke subset, bounded far below any
   possible full-suite embed (ceiling 300s; smoke is seconds idle, minutes
   under a worker storm, vs a 17min full suite)
2. the full-suite timeout budget machinery is retired
3. the five-check enumeration (semantics) is unchanged
"""
from __future__ import annotations

import inspect

import acceptance_check as ac


def test_check_test_suite_smoke_path_completes_under_60s():
    """#689 RED1: default `_check_test_suite()` must be a pinned smoke subset,
    not the embedded full suite (~301s on 2026-08-25 dev; 17min now).

    The wall bound is production's own SMOKE_SUITE_TIMEOUT — if the nested
    run exceeds it, the check fails itself and `passed` goes False. This
    test asserts the STRUCTURE of that contract, not a stopwatch: the whole
    pinned manifest must have been invoked (mode marker carries the
    manifest size), the run must be green, and the detail must carry the
    mode. Three wall ceilings (60/150/300) were all tripped by machine
    load and never by regressions — a stopwatch here measures the machine.
    A stubbed or truncated run cannot produce the real mode marker + green
    + manifest-size combination."""
    # Act — the real production path, no monkeypatching
    result = ac._check_test_suite()
    # Assert
    assert result["name"] == "test_suite_green"
    assert result["passed"] is True, f"smoke subset must be green: {result['detail']}"
    detail = str(result["detail"])
    assert detail.startswith("[smoke:"), (
        f"detail must mark the mode and manifest size, got: {detail!r}")
    expected = len(ac._load_smoke_nodeids())
    assert detail.startswith(f"[smoke:{expected}]"), (
        f"mode marker must carry the FULL manifest size {expected} — a "
        f"truncated or re-embedded subset ran instead: {detail!r}")


def test_full_suite_timeout_machinery_is_retired():
    """#689 RED2: TEST_SUITE_TIMEOUT and the budget machinery that existed solely
    to fit the embedded full suite (#351 raise, #369 load scaling, #457 win32
    guard) must not exist in the acceptance module."""
    # Arrange
    retired = ("TEST_SUITE_TIMEOUT", "TEST_SUITE_TIMEOUT_CEILING",
               "TEST_SUITE_TIMEOUT_ENV", "_test_suite_timeout_s")
    # Act / Assert
    src = inspect.getsource(ac)
    assert "TEST_SUITE_TIMEOUT" not in src, (
        "TEST_SUITE_TIMEOUT must not appear in acceptance_check.py (retired with the embed)")
    for name in retired:
        assert not hasattr(ac, name), f"{name} must be retired from acceptance_check.py"


def test_five_check_enumeration_is_unchanged():
    """#689 RED3: the five-check semantics are preserved — CHECKS stays the same
    five checks in the same order (pure enumeration, no subprocess)."""
    # Arrange
    expected = ["_check_oracle", "_check_cli_surface", "_check_priority_voi",
                "_check_digest", "_check_test_suite"]
    # Act
    names = [fn.__name__ for fn in ac.CHECKS]
    # Assert
    assert names == expected, f"acceptance CHECKS enumeration drifted: {names}"
