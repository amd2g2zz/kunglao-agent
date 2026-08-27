# -*- coding: utf-8 -*-
"""Tests for #477 ① — package-manager detection (scripts/pkg_detect.py).

Contract (openspec/changes/issue-477-deploy-completion design.md D1):
  * closed manager vocabulary MANAGERS (winget/choco/scoop — win32;
    brew — darwin; apt/dnf/apk/pacman — linux; pip/uv/npm — any) with
    needs_sudo + which_names + known_paths;
  * detect_managers(platform=None): which-first, known-path fallback,
    read-only, "any"-family managers probed on every platform, win32
    order winget > choco > scoop;
  * find_ghidra_install(): the "unpacked but unconfigured" half-state —
    a directory containing support/analyzeHeadless(.bat) under the #451
    tool dirs -> the GHIDRA_HOME recommendation, not a reinstall.

TDD RED phase: written BEFORE pkg_detect.py exists (function-level
imports so RED is test failure, not collection error).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def _load_pkg_detect():
    import pkg_detect
    return pkg_detect


def _hit(pkg_detect, name, path=None):
    return pkg_detect.ManagerHit(name=name, path=path or f"/fake/{name}",
                                 source="PATH")


# ---------- closed vocabulary ----------

def test_managers_vocabulary_closed():
    """MANAGERS is exactly the closed vocabulary — a new manager cannot
    appear without this pin noticing (structural declaration)."""
    pkg_detect = _load_pkg_detect()
    assert set(pkg_detect.MANAGERS) == {
        "winget", "choco", "scoop",            # win32
        "brew",                                  # darwin
        "apt", "dnf", "apk", "pacman",          # linux
        "pip", "uv", "npm",                     # any-OS
    }, sorted(pkg_detect.MANAGERS)


def test_every_manager_carries_family_sudo_and_probes():
    pkg_detect = _load_pkg_detect()
    for name, m in pkg_detect.MANAGERS.items():
        assert m.name == name
        assert m.os_family in ("win32", "darwin", "linux", "any"), m
        assert isinstance(m.needs_sudo, bool), m
        assert m.which_names or m.known_paths, (
            f"{name} must be findable via which or a known path")


def test_linux_family_managers_need_sudo_windows_do_not():
    """#304 parity: system-wide Linux managers are never auto-run; the
    user-scope Windows managers and language managers are not."""
    pkg_detect = _load_pkg_detect()
    for name in ("apt", "dnf", "apk", "pacman"):
        assert pkg_detect.MANAGERS[name].needs_sudo, name
    for name in ("winget", "choco", "scoop", "brew", "pip", "uv", "npm"):
        assert not pkg_detect.MANAGERS[name].needs_sudo, name


# ---------- detection: which-first, known-path fallback ----------

def test_detect_which_takes_priority(monkeypatch):
    pkg_detect = _load_pkg_detect()

    def fake_which(name):
        return f"/from-path/{name}" if name == "winget" else None

    hits = pkg_detect.detect_managers(
        "win32", which=fake_which,
        exists=lambda p: False)  # known paths all miss anyway
    winget = [h for h in hits if h.name == "winget"]
    assert winget and winget[0].path == "/from-path/winget"
    assert winget[0].source == "PATH"


def test_detect_known_path_fallback(monkeypatch, tmp_path):
    """winget is inbox but often NOT on PATH in service contexts — the
    known-path fallback is what makes win32 detection honest."""
    pkg_detect = _load_pkg_detect()
    import os

    known = {"KUNGLAO_TEST_WINGET": ""}
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "fake-localappdata"))
    winget_known = pkg_detect.MANAGERS["winget"].known_paths[0]
    target = os.path.expandvars(winget_known)

    def fake_exists(p):
        return str(p) == str(Path(target))

    hits = pkg_detect.detect_managers(
        "win32", which=lambda name: None, exists=fake_exists)
    winget = [h for h in hits if h.name == "winget"]
    assert winget, "known-path winget must be detected when the file exists"
    assert winget[0].source == "known-path"
    assert str(winget[0].path) == str(Path(target))


def test_detect_which_beats_known_path_when_both_hit():
    """FAULT-INJECT M1 pin (survivor 1): when BOTH channels hit the same
    manager — `which` resolves it AND its known path exists — the PATH
    evidence must win (source='PATH', path = the which result). The
    other tests pin the two channels in isolation (which-only:
    exists=False; known-path-only: which=None) — nothing made them hit
    the same manager at once, so a reversed fallback chain (stale
    known-path masking a live PATH hit — the half-installed misreport
    direction) survived. This closes that gap."""
    pkg_detect = _load_pkg_detect()

    def _both_channels_hit(name):
        def fake_which(n):
            return f"/from-path/{name}" if n == name else None

        return pkg_detect.detect_managers(
            "win32", which=fake_which,
            exists=lambda p: True)  # every known path exists too

    for name in ("winget", "choco"):
        hit = [h for h in _both_channels_hit(name) if h.name == name]
        assert hit, f"{name} must be reported when both channels hit"
        assert hit[0].source == "PATH", f"{name}: {hit[0]}"
        assert hit[0].path == f"/from-path/{name}", f"{name}: {hit[0]}"


def test_detect_apt_via_known_path_linux():
    pkg_detect = _load_pkg_detect()
    hits = pkg_detect.detect_managers(
        "linux", which=lambda name: None,
        exists=lambda p: Path(p).as_posix() == "/usr/bin/apt-get")
    names = [h.name for h in hits]
    assert "apt" in names, names


def test_detect_win32_order_winget_choco_scoop():
    """Issue acceptance 2 precondition: on win32 the detection order is
    winget > choco > scoop (inbox-first), so a machine with BOTH winget
    and choco reports winget first."""
    pkg_detect = _load_pkg_detect()
    hits = pkg_detect.detect_managers(
        "win32", which=lambda name: f"/x/{name}", exists=lambda p: False)
    win32_names = [h.name for h in hits
                   if pkg_detect.MANAGERS[h.name].os_family == "win32"]
    assert win32_names[:3] == ["winget", "choco", "scoop"], win32_names


def test_detect_excludes_wrong_family():
    pkg_detect = _load_pkg_detect()
    hits = pkg_detect.detect_managers(
        "win32", which=lambda name: f"/x/{name}", exists=lambda p: False)
    names = [h.name for h in hits]
    assert "brew" not in names and "apt" not in names, names
    # ... but the any-family is probed everywhere
    assert "pip" in names and "npm" in names, names


def test_detect_darwin_brew():
    pkg_detect = _load_pkg_detect()
    hits = pkg_detect.detect_managers(
        "darwin", which=lambda name: f"/opt/homebrew/bin/{name}"
        if name == "brew" else None,
        exists=lambda p: False)
    assert [h.name for h in hits] == ["brew"], hits


def test_detect_absent_manager_not_reported():
    pkg_detect = _load_pkg_detect()
    hits = pkg_detect.detect_managers(
        "win32", which=lambda name: None, exists=lambda p: False)
    assert hits == [], hits


# ---------- install-plans referential integrity (D3) ----------

def test_plan_specs_reference_real_managers():
    """Every PkgSpec.manager in INSTALL_PLANS must be a MANAGERS key —
    a typo'd manager name would silently never resolve."""
    pkg_detect = _load_pkg_detect()
    import toolchain_install as ti
    for item, plan in ti.INSTALL_PLANS.items():
        for spec in plan.packages:
            assert spec.manager in pkg_detect.MANAGERS, (
                f"{item}: unknown manager {spec.manager!r}")
            assert spec.argv, f"{item}/{spec.manager}: empty argv"


# ---------- ghidra half-state (D1, issue acceptance 3) ----------

def test_find_ghidra_install_hits_unpacked_dir(tmp_path, monkeypatch):
    """An unpacked ghidra (support/analyzeHeadless present) under a tool
    dir is discoverable -> the set-GHIDRA_HOME recommendation has data."""
    pkg_detect = _load_pkg_detect()
    ghidra = tmp_path / "tools" / "ghidra_11.3_PUBLIC"
    (ghidra / "support").mkdir(parents=True)
    ah = ghidra / "support" / ("analyzeHeadless.bat"
                               if sys.platform == "win32"
                               else "analyzeHeadless")
    ah.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_TOOL_DIRS", str(tmp_path / "tools"))
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    found = pkg_detect.find_ghidra_install()
    assert found is not None
    assert Path(found) == ghidra


def test_find_ghidra_install_requires_analyze_headless(
        tmp_path, monkeypatch):
    """A dir NAMED ghidra* without support/analyzeHeadless is not an
    install (honest half-state detection — no false set-env advice)."""
    pkg_detect = _load_pkg_detect()
    (tmp_path / "tools" / "ghidra_empty").mkdir(parents=True)
    monkeypatch.setenv("KUNGLAO_TOOL_DIRS", str(tmp_path / "tools"))
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    assert pkg_detect.find_ghidra_install() is None


def test_find_ghidra_install_none_when_no_dirs(monkeypatch):
    pkg_detect = _load_pkg_detect()
    monkeypatch.setenv("KUNGLAO_TOOL_DIRS", "")
    monkeypatch.delenv("GHIDRA_HOME", raising=False)
    # the default tool roots may exist on this host — the
    # seam must be injectable; pass explicit empty roots for determinism
    assert pkg_detect.find_ghidra_install(tool_dirs=()) is None
