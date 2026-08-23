#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pkg_detect.py — package-manager detection + half-state discovery (#477 ①).

WHY: INSTALL_PLANS keyed install commands by sys.platform (win32=choco /
darwin=brew / linux=apt-get) — a static table that dies on the first real
machine (issue #477 evidence 2: a win32 host without choco gets a
`choco install ghidra` suggestion that can never run; winget ships inbox
and is never consulted; an unpacked ghidra directory gets a reinstall
suggestion instead of a GHIDRA_HOME pointer).

This module is the DETECTION half of the fix (the DATA half is
toolchain_install.INSTALL_PLANS, now (manager, argv) pairs):

  * closed manager vocabulary MANAGERS with per-manager needs_sudo +
    which_names + known_paths;
  * detect_managers(): which-first, known-path fallback — strictly
    READ-ONLY (no manager is installed, no state written);
  * find_ghidra_install(): the "unpacked but unconfigured" half-state —
    a directory carrying support/analyzeHeadless(.bat) under the #451
    tool-dir roots, so the resolution layer can recommend
    `set GHIDRA_HOME=<dir>` instead of a reinstall.

#304 discipline lives in the data consumers: a needs_sudo manager is
never auto-executed (toolchain_install prints the sudo-prefixed command
for the human). Detection only reports what exists.

CLI: pkg_detect.py [--json] — print the detected managers (operator /
diagnostics face; tests inject the which/exists seams).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# platform-correct analyzeHeadless name (#409) — single source, imported
# (leaf module, no cycle).
import platform_paths  # noqa: E402

# Seams (repo pattern, toolchain_install._subprocess_run): tests inject
# deterministic lookups; production uses shutil.which / Path.exists.
_shutil_which = shutil.which


def _default_exists(p: Path) -> bool:
    return Path(p).exists()


@dataclass(frozen=True)
class Manager:
    """One package manager: where it can live and how it must be run.

    needs_sudo: system-wide installs on Linux need elevation — such a
    manager is NEVER auto-executed (#304); the exact sudo-prefixed
    command is printed for the human instead. User-scope Windows
    managers (winget/scoop), choco, brew and language managers
    (pip/uv/npm) run in-place.
    which_names: PATH lookup names (apt runs via apt-get).
    known_paths: fallback locations when not on PATH (env-vars expanded
    at detect time) — winget is inbox but often missing from PATH in
    service contexts; brew installs outside /usr/local on Apple Silicon.
    """

    name: str
    os_family: str                     # "win32" | "darwin" | "linux" | "any"
    needs_sudo: bool
    which_names: tuple[str, ...] = ()
    known_paths: tuple[str, ...] = ()


# Closed vocabulary (regression-pinned by tests/test_pkg_detect.py):
# adding a manager is a deliberate data change, never an accident.
MANAGERS: dict[str, Manager] = {
    # --- Windows family (preference order: inbox first) ---
    "winget": Manager(
        "winget", "win32", needs_sudo=False,
        which_names=("winget", "winget.exe"),
        known_paths=(r"%LOCALAPPDATA%\Microsoft\WindowsApps\winget.exe",),
    ),
    "choco": Manager(
        "choco", "win32", needs_sudo=False,
        which_names=("choco", "choco.exe"),
        known_paths=(r"C:\ProgramData\chocolatey\bin\choco.exe",),
    ),
    "scoop": Manager(
        "scoop", "win32", needs_sudo=False,
        which_names=("scoop", "scoop.cmd"),
    ),
    # --- macOS family ---
    "brew": Manager(
        "brew", "darwin", needs_sudo=False,
        which_names=("brew",),
        known_paths=("/opt/homebrew/bin/brew", "/usr/local/bin/brew"),
    ),
    # --- Linux family (system-wide -> needs_sudo, #304) ---
    "apt": Manager(
        "apt", "linux", needs_sudo=True,
        which_names=("apt-get",),
        known_paths=("/usr/bin/apt-get",),
    ),
    "dnf": Manager(
        "dnf", "linux", needs_sudo=True,
        which_names=("dnf",),
        known_paths=("/usr/bin/dnf",),
    ),
    "apk": Manager(
        "apk", "linux", needs_sudo=True,
        which_names=("apk",),
        known_paths=("/sbin/apk", "/bin/apk"),
    ),
    "pacman": Manager(
        "pacman", "linux", needs_sudo=True,
        which_names=("pacman",),
        known_paths=("/usr/bin/pacman",),
    ),
    # --- cross-platform language managers ---
    "pip": Manager("pip", "any", needs_sudo=False, which_names=("pip",)),
    "uv": Manager("uv", "any", needs_sudo=False, which_names=("uv",)),
    "npm": Manager("npm", "any", needs_sudo=False, which_names=("npm",)),
}

# Detection order: family-specific managers in declaration order, then
# the any-family (language managers) — the order of the dict IS the
# report order; per-item preference is the PkgSpec order in
# toolchain_install.INSTALL_PLANS (data is preference, design.md D2).
_ORDER: tuple[str, ...] = ("winget", "choco", "scoop", "brew", "apt", "dnf",
                           "apk", "pacman", "pip", "uv", "npm")


@dataclass(frozen=True)
class ManagerHit:
    """One detected manager — `source` says HOW it was found (honest
    reporting: a known-path hit and a PATH hit are different evidence)."""

    name: str
    path: str
    source: str  # "PATH" | "known-path"


def _os_family(platform: str | None) -> str:
    p = platform or sys.platform
    if p == "win32":
        return "win32"
    if p == "darwin":
        return "darwin"
    return "linux"


def _expand(raw: str) -> Path:
    """Expand %VAR%/... and ~/... in a known path spec."""
    return Path(os.path.expanduser(os.path.expandvars(raw)))


def detect_managers(platform: str | None = None, *,
                    which=_shutil_which,
                    exists=_default_exists) -> list[ManagerHit]:
    """Detect the managers present on this host, in _ORDER order.

    which-first, known-path fallback, strictly read-only. "any"-family
    managers are probed on every platform; family-specific ones only on
    their own family. Absent managers are simply absent from the result
    (never invented, never installed here).
    """
    family = _os_family(platform)
    hits: list[ManagerHit] = []
    for name in _ORDER:
        m = MANAGERS[name]
        if m.os_family not in (family, "any"):
            continue
        found = None
        for wn in m.which_names:
            path = which(wn)
            if path:
                found = (path, "PATH")
                break
        if found is None:
            for kp in m.known_paths:
                cand = _expand(kp)
                if exists(cand):
                    found = (str(cand), "known-path")
                    break
        if found is not None:
            hits.append(ManagerHit(name=name, path=found[0],
                                   source=found[1]))
    return hits


# ---------- ghidra half-state (issue acceptance 3) ----------

# Bounded search (triage, not a disk walk — same posture as the #451
# disk enumeration): depth 2 below each root, first hit wins.
_GHIDRA_MAX_DEPTH = 2
_GHIDRA_DIR_PREFIX = "ghidra"


def _tool_dirs() -> tuple[Path, ...]:
    """#451 enumeration roots: KUNGLAO_TOOL_DIRS (os.pathsep-separated) >
    the defaults C:/tools + D:/tools (same literals toolchain_negotiation
    uses — kept local to avoid the import cycle
    toolchain_install -> toolchain_negotiation)."""
    raw = os.environ.get("KUNGLAO_TOOL_DIRS", "")
    if raw.strip():
        return tuple(Path(p) for p in raw.split(os.pathsep) if p.strip())
    return (Path("C:/tools"), Path("D:/tools"))


def _is_ghidra_root(d: Path) -> bool:
    """A ghidra*-named directory carrying the platform-correct
    analyzeHeadless under support/ (#409 single source for the name)."""
    if not d.name.lower().startswith(_GHIDRA_DIR_PREFIX):
        return False
    return platform_paths.analyze_headless(d).exists()


def find_ghidra_install(
        tool_dirs: tuple[Path, ...] | None = None) -> str | None:
    """Locate an UNPACKED ghidra install (support/analyzeHeadless present)
    — the 'already downloaded, GHIDRA_HOME never set' half-state.

    Search roots: GHIDRA_HOME (defensive — a valid one means the check
    did not FAIL, kept for direct-call symmetry) > tool_dirs param >
    #451 roots. Bounded depth, first hit wins, read-only, fail-open
    (None) — a miss just means the resolution layer falls through to
    package installs.
    """
    env_home = os.environ.get("GHIDRA_HOME")
    if env_home and _is_ghidra_root(Path(env_home)):
        return env_home
    roots = tuple(tool_dirs) if tool_dirs is not None else _tool_dirs()
    for root in roots:
        stack: list[tuple[Path, int]] = [(root, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                entries = list(d.iterdir())
            except OSError:
                continue
            for e in entries:
                if e.is_dir():
                    if _is_ghidra_root(e):
                        return str(e)
                    if depth < _GHIDRA_MAX_DEPTH:
                        stack.append((e, depth + 1))
    return None


def main(argv: list[str] | None = None) -> int:
    """Diagnostics CLI: print detected managers (human or --json)."""
    import json

    parser = argparse.ArgumentParser(
        prog="pkg-detect",
        description="package-manager detection (#477)",
    )
    parser.add_argument("--json", action="store_true",
                        help="emit detected managers as JSON")
    parser.add_argument("--ghidra", action="store_true",
                        help="also probe the unpacked-ghidra half-state")
    args = parser.parse_args(argv)

    hits = detect_managers()
    payload: dict = {"managers": [
        {"name": h.name, "path": h.path, "source": h.source}
        for h in hits]}
    if args.ghidra:
        payload["ghidra_unpacked"] = find_ghidra_install()
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for h in hits:
            print(f"{h.name}: {h.path} ({h.source})")
        if not hits:
            print("(no package manager detected)")
        if args.ghidra:
            print(f"ghidra unpacked at: {find_ghidra_install() or '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
