#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""platform_matrix.py — the host support matrix (Windows face included).

The production lesson this module answers: memory consolidation never
succeeded on Windows hosts because the platform was UNDECLARED — a
top-level fcntl import, a POSIX-only chmod-on-fd call, and children
inheriting the GBK console code page each killed the closure path
silently (78 consecutive failures, zero successes, nobody paged).

The module is the single platform seam:

  SUPPORTED_OS_NAMES   the declared host classes (posix, nt)
  host_report()        the machine-readable matrix row for this host
  fd_lock/fd_unlock    feature-detected advisory lock: POSIX flock,
                       msvcrt.locking, or a declared unlocked no-op
  chmod_checked        os.chmod with the nt skip guard (Windows chmod
                       honors only the read-only bit and an int fd
                       raises TypeError — the production signature)
  utf8_env             subprocess env with UTF-8 forced (PYTHONUTF8 /
                       PYTHONIOENCODING) so children never inherit the
                       GBK default code page
  assert_run_start     the run-start platform assertion: declared hosts
                       are recorded in the ledger; undeclared host
                       classes are refused LOUDLY (stderr + ledger row,
                       one bounded refusal per invocation — never a
                       silent wipeout)

Every function takes ``os_name`` (default: the live ``os.name``) so the
Windows faces are testable with injected platform semantics; feature
detection (fcntl / msvcrt availability) reads the running interpreter.

Stdlib only; workspace-relative like its engine sibling.
"""
from __future__ import annotations

import importlib
import json
import os
import sys

SCHEMA = "platform-matrix/1"

#: the declared host classes. posix = macOS/Linux (flock face); nt =
#: Windows (msvcrt/no-op lock, chmod skipped, UTF-8 forced). Anything
#: else is UNDECLARED: run start records it and closure duties refuse.
SUPPORTED_OS_NAMES = ("posix", "nt")

#: forced into every subprocess environment (the GBK curse: zh-CN
#: Windows children default to code page 936 unless told otherwise).
UTF8_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}

#: the controlled-vocabulary action word for the run-start row.
RUN_START_ACTION = "platform_run_start"


def _feature(name: str):
    """Module or None — the feature-detection primitive."""
    try:
        return importlib.import_module(name)
    except ImportError:
        return None


#: the live host class, captured at import. THE INJECTION SEAM: tests
#: flip this attribute (never the global os.name — pathlib reads it too
#: and WindowsPath construction would explode on a POSIX host).
_OS_NAME = os.name


def _os_of(os_name: str | None) -> str:
    return os_name if os_name is not None else _OS_NAME


def lock_strategy(os_name: str | None = None) -> str:
    """The advisory-lock face this host would use. Reflects FEATURE
    availability, not the name alone: a posix-named host without fcntl
    degrades exactly like the production Windows host did."""
    if _os_of(os_name) == "posix" and _feature("fcntl") is not None:
        return "posix-flock"
    if _feature("msvcrt") is not None:
        return "msvcrt-locking"
    return "unlocked-noop"


def fd_lock(fd: int, *, os_name: str | None = None) -> str:
    """Advisory exclusive lock on an open fd. Returns the strategy
    applied ("posix-flock" | "msvcrt-locking" | "unlocked-noop");
    never raises for the degraded faces (O_APPEND single-writer stays
    correct; the no-op is declared, not silent)."""
    if _os_of(os_name) == "posix":
        fcntl = _feature("fcntl")
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return "posix-flock"
    msvcrt = _feature("msvcrt")
    if msvcrt is not None:
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        return "msvcrt-locking"
    return "unlocked-noop"


def fd_unlock(fd: int, *, os_name: str | None = None) -> str:
    """Release the lock taken by fd_lock (same strategy selection;
    the no-op face returns its name unchanged)."""
    if _os_of(os_name) == "posix":
        fcntl = _feature("fcntl")
        if fcntl is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            return "posix-flock"
    msvcrt = _feature("msvcrt")
    if msvcrt is not None:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return "msvcrt-locking"
    return "unlocked-noop"


def chmod_checked(target, mode: int, *, os_name: str | None = None) -> bool:
    """os.chmod with the platform guard. Unix-only semantics are
    SKIPPED on nt (an int fd raises TypeError there, and the mode bits
    do not map to Windows ACLs) — the skip is the declared equivalent,
    and this returns False so callers can see the branch taken.
    Returns True when the chmod was applied."""
    if _os_of(os_name) == "nt":
        return False
    os.chmod(target, mode)
    return True


def utf8_env(base: dict | None = None) -> dict:
    """A NEW env dict (the base is never mutated) with UTF-8 forced for
    the child process tree. Pass {} for a bare env, None to inherit."""
    env = dict(os.environ if base is None else base)
    env.update(UTF8_ENV)
    return env


def host_report(os_name: str | None = None) -> dict:
    """The support-matrix row for this host (schema platform-matrix/1):
    declared-ness, the concrete lock/chmod strategies, and the UTF-8
    env contract. This dict is what the run-start row carries."""
    name = _os_of(os_name)
    return {
        "schema": SCHEMA,
        "os_name": name,
        "declared": name in SUPPORTED_OS_NAMES,
        "lock_strategy": lock_strategy(name),
        "chmod": "skipped-on-nt" if name == "nt" else "posix-chmod",
        "utf8_env": dict(UTF8_ENV),
    }


def _emit_row(ws, report: dict) -> bool:
    """The ledger face of the assertion. kunglao_log is import-guarded
    (the engine's partial-deploy lifeline): a missing logger degrades
    to False while the stderr face below stays loud."""
    try:
        import kunglao_log
    except ImportError:
        return False
    return kunglao_log.emit(
        ws, "orchestrator", RUN_START_ACTION,
        detail=json.dumps(report, sort_keys=True, ensure_ascii=False))


def assert_run_start(ws, *, os_name: str | None = None,
                     emit_row: bool = True) -> dict:
    """Record the platform at run start and refuse undeclared host
    classes LOUDLY. Declared hosts: one ledger row with the matrix
    report, duties proceed. Undeclared: the row still lands AND a
    stderr line names the refusal ("platform-undeclared") — the caller
    (the engine's main) then refuses closure duties with a nonzero
    exit. The refusal is bounded: once per invocation, no retry loop,
    no silent degradation."""
    report = host_report(os_name)
    report["duty"] = "closure"
    report["row_emitted"] = bool(emit_row and _emit_row(ws, report))
    if not report["declared"]:
        print(json.dumps({"refused": "platform-undeclared",
                          "os_name": report["os_name"],
                          "duty": "closure"}, sort_keys=True),
              file=sys.stderr)
    return report
