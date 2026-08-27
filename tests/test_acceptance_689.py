# -*- coding: utf-8 -*-
"""tests/test_acceptance_689.py — RED contracts for the acceptance embed retirement.

#689: `scripts/acceptance_check.py::_check_test_suite` embedded the ENTIRE pytest
suite as a subprocess; tests/test_acceptance.py invoked `run_acceptance()` twice,
so every suite run paid 2x ~301s (60% of the 1,004s full-suite runtime, 2026-08-25
audit). These tests pin the post-fix contract:

1. the default check path is a pinned smoke subset, end-to-end < 60s
2. the full-suite timeout budget machinery is retired
3. the five-check enumeration (semantics) is unchanged
"""
from __future__ import annotations

import inspect
import time

import acceptance_check as ac


def test_check_test_suite_smoke_path_completes_under_60s():
    """#689 RED1: default `_check_test_suite()` must be a pinned smoke subset
    (seconds), not the embedded full suite (~301s on 2026-08-25 dev)."""
    # Arrange — nothing; the contract is about the real production path
    start = time.perf_counter()
    # Act
    result = ac._check_test_suite()
    elapsed = time.perf_counter() - start
    # Assert
    assert result["name"] == "test_suite_green"
    assert result["passed"] is True, f"smoke subset must be green: {result['detail']}"
    assert str(result["detail"]).startswith("[smoke:"), (
        f"detail must mark the mode and manifest size, got: {result['detail']!r}")
    assert elapsed < 60.0, (
        f"default check took {elapsed:.1f}s — the full-suite embed is back "
        "(the whole point of #689 is that this stays seconds)")


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
