# -*- coding: utf-8 -*-
"""tests/test_gate4_syspath_guard_663.py — the sys.path guard
stands down under mutmut's runner.

The session guard (conftest._syspath_collision_order_guard) polices
TEST modules mutating sys.path. mutmut's runner legitimately puts the
mutants/ tree on sys.path for Gate 4 baseline runs, so the guard must
stand down while MUTANT_UNDER_TEST is present in the environment —
presence, not truthiness (mutmut marks its validation phase with the
empty string).

conftest is loaded by path (the repo's by-path convention) so this
suite never re-binds the shared-name twins for later modules."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_conftest():
    spec = importlib.util.spec_from_file_location(
        "conftest_663_by_path", ROOT / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drive(monkeypatch, env_present: bool) -> None:
    """Run the guard's start→mutate→teardown cycle with a path change."""
    conftest = _load_conftest()
    if env_present:
        monkeypatch.setenv("MUTANT_UNDER_TEST", "")
    fn = getattr(conftest._syspath_collision_order_guard, "__wrapped__",
                 conftest._syspath_collision_order_guard)
    gen = fn()
    next(gen)  # session start: captures the baseline
    probe = str(ROOT / "mutants" / "scripts")
    sys.path.insert(0, probe)
    try:
        next(gen)  # teardown: compares
    except StopIteration:
        pass  # early-return path: generator completes normally
    finally:
        sys.path.remove(probe)


def test_guard_stands_down_under_mutmut(monkeypatch) -> None:
    """MUTANT_UNDER_TEST present (even empty) -> teardown never fails."""
    _drive(monkeypatch, env_present=True)


def test_guard_still_fails_on_test_mutation(monkeypatch) -> None:
    """No mutmut env -> a mid-session scripts-path flip is still a failure."""
    monkeypatch.delenv("MUTANT_UNDER_TEST", raising=False)
    with pytest.raises(BaseException) as ei:
        _drive(monkeypatch, env_present=False)
    assert "#770" in str(ei.value)
