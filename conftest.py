"""Phase 0 shared fixtures: reused by all later phases (SDD contract tests).

- Root-level ONLY (#811 arbitration, B6 CONFIRMED): the 5 shared fixtures
  (tmp / ws_factory / contract_validator / golden_master / isolated_home)
  live in tests/conftest.py — root copies were shadowed twins whose drift
  (golden_master bare text=True) was a live GBK regression trap.
- load_lock_factory / load_sensitive_registry: #369 cross-process serialization
  of the load-sensitive test family (machine-local flock; see bottom section)
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

try:  # POSIX only; Windows dev/CI is single-tenant and unaffected (#369)
    import fcntl
    _HAVE_FLOCK = hasattr(fcntl, "flock")
except ImportError:  # pragma: no cover - Windows
    _HAVE_FLOCK = False

ROOT = Path(__file__).resolve().parents[1]

# tests/ is an import root under pytest's prepend import mode, so the bare
# module name resolves (same convention as tests/conftest.py -> _factories).
# parents[1] above is the pre-existing constant and is NOT the repo root;
# resolve the repo dir from this file's own location instead.
REPO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_DIR / "tests"))
from _tiers import DOCS_MODULES, FAST_MODULES, SLOW_MODULES  # noqa: E402


# ---------- #369: load-sensitive serialization (cross-process file lock) ----------
#
# The tick-chain / static-tools family fails only when concurrent pytest runs
# (multi-agent worktrees on one machine) execute these modules at the same
# time: subprocess spawn storms stretch wall-clock mtime windows (e.g. the
# 5s freshness assert in test_external_kicker) and the nested acceptance
# suite's subprocess timeout. Marked modules hold a machine-local flock for
# their whole duration, so no two sensitive modules ever co-run — within one
# run (tests are sequential) and across concurrent runs/worktrees.

LOAD_SENSITIVE_MODULES = frozenset({
    "test_drift_detection",       # tick-chain: mtime-based lock/worker windows
    "test_external_kicker",       # tick-chain: 5s lock-freshness wall-clock window
    "test_static_tools_1b",       # static-tools: per-test subprocess spawn storm
    "test_env_check",             # tick-chain adjacent (issue #369 audited set)
    "test_env_check_gate",        # real subprocess.run probes (timeout=60 each)
    "test_env_ports_wiring",      # tick-chain adjacent (issue #369 audited set)
    "test_toolchain",             # android stub probes + fixed-port listeners
    "test_acceptance_689",        # nested smoke run wall-tripwire (load window)
    "test_acceptance",            # nested smoke run inside run_acceptance()
})
LOAD_SENSITIVE_LOCK_NAME = "kunglao-pytest-load-sensitive.lock"
LOAD_SENSITIVE_ACQUIRE_TIMEOUT_S = 600.0  # generous: several queued suites under load

# xdist affinity: modules that touch the machine-local lock or hold it
# must land on ONE xdist worker (run with --dist loadgroup), so a lock
# holder, its waiter and the nested-probe in test_load_lock never contend
# against their own run. test_load_lock deliberately stays OUT of
# LOAD_SENSITIVE_MODULES (its module-scoped autouse lock would deadlock the
# external holder its end-to-end test spawns) — it only joins the grouping.
XDIST_AFFINITY_EXTRA_MODULES = frozenset({"test_load_lock"})


@contextmanager
def load_sensitive_lock(path=None, timeout: float = LOAD_SENSITIVE_ACQUIRE_TIMEOUT_S):
    """Cross-process mutual exclusion via flock on a machine-local file.

    The lock file lives in the system temp dir (per-user on macOS, shared
    /tmp per machine on Linux) — NOT in the repo, so concurrent worktrees
    of the same user contend on ONE lock. flock is bound to the open file
    description: the kernel releases it when the holding process dies, so
    there is no stale-lock handling. No-op where flock is unavailable.
    """
    if not _HAVE_FLOCK:  # pragma: no cover - Windows
        yield
        return
    lock_path = Path(path) if path is not None else Path(tempfile.gettempdir()) / LOAD_SENSITIVE_LOCK_NAME
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"load-sensitive lock not acquired within {timeout}s: {lock_path}")
                time.sleep(0.05)
        yield
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def pytest_collection_modifyitems(config, items):
    """Apply the load_sensitive marker via the module registry (single source
    of truth here — no per-file edits needed in the sensitive test modules).

    xdist affinity: the family and the lock-probe module share an
    xdist_group (single-worker execution) — under --dist loadgroup a lock
    holder, its waiter and the nested lock probes never land on different
    workers of the same run; without xdist the marker is inert.

    Tier marking: fast / slow from the tests/_tiers.py registries (docs is
    a routing tag, not a tier). Also records the per-module tier census on
    the config object — tests/test_tier_census.py asserts over it, so the
    gate chain can prove no collected test is left unclassified."""
    census = getattr(config, "_kunglao_tier_census", None)
    if census is None:
        census = {}
        config._kunglao_tier_census = census
    for item in items:
        module = getattr(item, "module", None)
        if module is None:
            continue
        name = module.__name__.rsplit(".", 1)[-1]
        if name in FAST_MODULES:
            item.add_marker(pytest.mark.fast)
            tier = "fast"
        elif name in SLOW_MODULES:
            item.add_marker(pytest.mark.slow)
            tier = "slow"
        else:
            tier = "integration"
        if name in DOCS_MODULES:
            item.add_marker(pytest.mark.docs)
        if name in LOAD_SENSITIVE_MODULES:
            item.add_marker(pytest.mark.load_sensitive)
        if (name in LOAD_SENSITIVE_MODULES
                or name in XDIST_AFFINITY_EXTRA_MODULES):
            item.add_marker(pytest.mark.xdist_group("load_sensitive"))
        entry = census.setdefault(
            name, {"tier": tier, "items": 0, "dual": 0, "path": None})
        entry["items"] += 1
        if (item.get_closest_marker("fast") is not None
                and item.get_closest_marker("slow") is not None):
            entry["dual"] += 1
        if getattr(module, "__file__", None):
            entry["path"] = module.__file__


@pytest.fixture
def load_lock_factory():
    """Raw lock factory for unit-testing the serialization mechanism (#369).
    Pass an explicit `path` (tmp) — the default is the real machine lock."""
    return load_sensitive_lock


@pytest.fixture
def load_sensitive_registry():
    """The frozenset of module names that must never co-run (#369)."""
    return LOAD_SENSITIVE_MODULES


@pytest.fixture(autouse=True, scope="module")
def _serialize_load_sensitive(request):
    """Hold the machine-local lock for the whole sensitive module (#369)."""
    module = getattr(request, "module", None)
    name = module.__name__.rsplit(".", 1)[-1] if module is not None else ""
    if name not in LOAD_SENSITIVE_MODULES or not _HAVE_FLOCK:
        yield
        return
    with load_sensitive_lock():
        yield


# ---------- #770: sys.path mutation guard (session teardown) ----------
#
# Shared-name twins (completion_gate / heartbeat_touch / lib_kunglao) resolve
# by sys.path ORDER, so any test module that inserts scripts/ or hooks/ at
# import time silently re-binds the twins for every LATER suite — CI passes
# while a different local ordering fails (#770's exact shape). Every twin
# consumer now binds by path (#762 convention); the guard enforces that no
# test mutates sys.path at all between session start and teardown.

@pytest.fixture(scope="session", autouse=True)
def _syspath_collision_order_guard():
    def _wins() -> dict:
        out = {}
        for p in sys.path:
            try:
                name = Path(p).name
            except (OSError, ValueError):
                continue
            if name in ("hooks", "scripts") and name not in out:
                out[name] = p
        return out

    baseline = _wins()
    yield
    end = _wins()
    if end != baseline:
        pytest.fail(
            "#770: shared-name twin resolution changed during this pytest "
            f"session (start={baseline}, end={end}). The first "
            "completion_gate / heartbeat_touch / lib_kunglao binding every "
            "later suite sees must be stable — test modules must not insert "
            "scripts/hooks onto sys.path (pytest.ini pythonpath is the only "
            "insertion point); load twin modules by path under an isolated "
            "name instead (see lib_kunglao / completion_gate consumers).",
            pytrace=False,
        )
