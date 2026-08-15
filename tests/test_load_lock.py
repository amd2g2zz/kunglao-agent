# -*- coding: utf-8 -*-
"""#369 RED — machine-local serialization of the load-sensitive test region.

The load-flake family (tick-chain mtime windows + static-tools subprocess
spawn storms) only fails when two concurrent pytest runs execute the
sensitive modules at the same time. The fix is mutual exclusion via flock
on a machine-local file; these tests pin the MECHANISM (second acquirer
defers, blocking acquire waits for release) because the flake itself is
statistical and cannot be reproduced deterministically at will.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fcntl", reason="flock serialization is POSIX-only (single-tenant Windows CI is unaffected)")

ROOT = Path(__file__).resolve().parents[1]


# ---------- mutual exclusion: second acquirer defers ----------

def test_lock_second_acquire_defers(load_lock_factory, tmp_path):
    lock = tmp_path / "sensitive.lock"
    with load_lock_factory(path=lock, timeout=0.2):
        # a second open file description must NOT acquire while held
        with pytest.raises(TimeoutError):
            with load_lock_factory(path=lock, timeout=0.2):
                pass


def test_lock_acquire_succeeds_after_release(load_lock_factory, tmp_path):
    lock = tmp_path / "sensitive.lock"
    with load_lock_factory(path=lock, timeout=0.2):
        pass
    with load_lock_factory(path=lock, timeout=0.2):  # re-acquirable
        pass


def test_lock_blocking_acquire_waits_for_holder(load_lock_factory, tmp_path):
    lock = tmp_path / "sensitive.lock"
    hold = threading.Event()
    release = threading.Event()

    def holder():
        with load_lock_factory(path=lock, timeout=1.0):
            hold.set()
            release.wait(timeout=5.0)

    t = threading.Thread(target=holder)
    t.start()
    assert hold.wait(timeout=2.0)
    t0 = time.monotonic()
    release.set()  # holder releases; blocked acquire must then win
    with load_lock_factory(path=lock, timeout=5.0):
        pass
    t.join(timeout=5.0)
    assert not t.is_alive()


def test_lock_contention_observed_cross_process(load_lock_factory, tmp_path):
    """A real second PROCESS holding the lock defers the in-process acquire
    (the exact multi-worktree co-run scenario)."""
    lock = tmp_path / "sensitive.lock"
    child = tmp_path / "child.py"
    child.write_text(
        "import fcntl, os, time\n"
        f"fd = os.open({str(lock)!r}, os.O_CREAT | os.O_RDWR, 0o644)\n"
        "fcntl.flock(fd, fcntl.LOCK_EX)\n"
        "print('held', flush=True)\n"
        "time.sleep(2.0)\n"
        "fcntl.flock(fd, fcntl.LOCK_UN)\n",
        encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(child)], stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "held"   # child holds the lock
        t0 = time.monotonic()
        with load_lock_factory(path=lock, timeout=10.0):
            waited = time.monotonic() - t0
        assert waited >= 1.0   # deferred until the child released (~2s)
    finally:
        p.wait(timeout=10.0)


# ---------- family wiring: marker + module registry ----------

def test_load_sensitive_registry_files_exist(load_sensitive_registry):
    for name in load_sensitive_registry:
        assert (ROOT / "tests" / f"{name}.py").exists(), (
            f"{name}.py missing — LOAD_SENSITIVE_MODULES is stale (renamed file?)")


def test_load_sensitive_marker_covers_family_exactly(load_sensitive_registry):
    """Collecting the family WITH -m load_sensitive yields the same test set
    as collecting it plainly: every family test is marked, and the marker is
    applied through the registry (no hand-marked strays to check)."""
    files = [str(ROOT / "tests" / f"{n}.py") for n in sorted(load_sensitive_registry)]

    def collect(extra):
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", *extra, *files],
            cwd=str(ROOT), capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, r.stdout + r.stderr
        return {ln for ln in r.stdout.splitlines() if "::" in ln}

    marked = collect(["-m", "load_sensitive"])
    plain = collect([])
    assert plain, "no tests collected from the sensitive family"
    assert marked == plain, "marker missing on some family tests"


def test_autouse_fixture_holds_machine_lock_end_to_end(tmp_path):
    """Wiring proof: while an external process holds the REAL machine lock,
    a pytest run of a sensitive module cannot finish until the lock is
    released. Startup-flake-safe: instead of a fixed stall window, we assert
    the nested run is still alive well past its own uncontended duration
    (baseline includes startup), then let the holder go.
    (Lock file name mirrors conftest.LOAD_SENSITIVE_LOCK_NAME deliberately —
    a rename here must fail loudly.)"""
    import os
    import tempfile

    lock = Path(tempfile.gettempdir()) / "kunglao-pytest-load-sensitive.lock"
    release = tmp_path / "release"
    fast_module = ROOT / "tests" / "test_env_ports_wiring.py"

    def run_pytest():
        t0 = time.monotonic()
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(fast_module)],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180)
        assert r.returncode == 0, r.stdout + r.stderr
        return time.monotonic() - t0

    free = run_pytest()  # uncontended baseline (startup + module run)

    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import fcntl, os, time\n"
         f"fd = os.open({str(lock)!r}, os.O_CREAT | os.O_RDWR, 0o644)\n"
         "fcntl.flock(fd, fcntl.LOCK_EX)\n"
         "print('held', flush=True)\n"
         f"for _ in range(1200):\n"
         f"    if os.path.exists({str(release)!r}):\n"
         "        break\n"
         "    time.sleep(0.05)\n"
         "fcntl.flock(fd, fcntl.LOCK_UN)\n"],
        stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"  # external holder owns the lock
        p = subprocess.Popen(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(fast_module)],
            cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # free covers startup + run; 2x + 4s is past ANY plausible startup,
        # so an unfinished process here is blocked at the module lock
        time.sleep(free * 2 + 4.0)
        assert p.poll() is None, (
            "wiring broken: sensitive module finished while the machine lock was held")
        release.write_text("", encoding="utf-8")  # let the holder go
        out, _ = p.communicate(timeout=180)
        assert p.returncode == 0, out
    finally:
        release.write_text("", encoding="utf-8")  # belt-and-braces holder release
        holder.wait(timeout=30)
