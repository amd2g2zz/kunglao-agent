#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""apk_mem_gate.py - memory-aware jadx dispatch estimator (#670).

Predicts the heap cost of `jadx` against the resolved target (APK or JAR)
and emits a verdict that selects the downstream dispatch path:
  - jadx-ok:        budget >= 1.5*est -> full decompile
  - targeted-jadx:  est <= budget < 1.5*est -> baksmali xref + per-class jadx
  - smali-only:     budget < est -> baksmali + smali semantic, no jadx
  - refuse:         JAR target (no smali fallback) | operator override

Calibration (single data point, declared in output per #54 numeric-fidelity):
  est = max(apk_mem_floor_gb, apk_mem_dex_factor * dex_bytes_total)
  budget = apk_mem_budget_ratio * avail_gb

avail_gb comes from a platform probe (win: GlobalMemoryStatusEx; darwin:
Mach host_statistics64; else: sysconf SC_AVPHYS_PAGES). A probe failure
keeps the floor, and `avail_probe` records that it happened so a dead
probe is never read as a genuinely-4GB host (issue 223).

Fail-open: every error path writes evidence/apk_mem_gate.json with reason;
never raises. Operators can audit / retry with apk_mem_override.

Spec: openspec/changes/issue-670-mem-gated-jadx/specs/mem-gated-jadx/spec.md
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402

# #863 Family F: the harness-wide time-stamp util lives in scripts/;
# add scripts/ beside the tools/ bridge above (no second def).
_SCRIPTS_DIR = _TOOLS_DIR.parent / "scripts"
if str(_SCRIPTS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_SCRIPTS_DIR))
from harness_common import utc_now_z as _utc_now  # noqa: E402


import argparse
import json
import os
import sys
import zipfile
from pathlib import Path


from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))
from common import write_evidence  # noqa: E402  (#863 Family J: single source)

GB = 1024 ** 3

DEFAULTS = {
    "apk_mem_dex_factor": 50.0,
    "apk_mem_floor_gb": 4.0,
    "apk_mem_budget_ratio": 0.65,
}

CALIBRATION_BASIS = (
    "single data point (395MB APK / 12GB heap / ~10h GC-thrashed completion) - "
    "refine with more samples"
)

# Available-memory probe provenance (issue 223): recorded in the verdict as
# `avail_probe`, and echoed into the reason when the floor fallback is in
# force, so a dead probe is distinguishable from a genuinely-4GB host.
AVAIL_PROBE_OK = "ok"
AVAIL_PROBE_FLOOR_FALLBACK = "floor-fallback"
PROBE_DETAIL_MAX = 200

# Mach host_statistics64(HOST_VM_INFO64) constants for the darwin probe.
_HOST_VM_INFO64 = 4
_KERN_SUCCESS = 0


def _mem_windows() -> float:
    """Avail physical memory on Windows in bytes (ctypes GlobalMemoryStatusEx)."""
    import ctypes
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(stat)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
        return float(stat.ullAvailPhys)
    raise OSError("GlobalMemoryStatusEx failed")


def _darwin_vm_page_counts() -> tuple[int, int, int]:
    """(free, inactive, speculative) VM page counts via Mach host_statistics64.

    `SC_AVPHYS_PAGES` is a Linux-only sysconf key — darwin raises
    `ValueError: unrecognized configuration name` — so macOS reads the Mach
    VM statistics instead (the source vm_stat / Activity Monitor use).
    """
    import ctypes

    class VmStatistics64(ctypes.Structure):
        # vm_statistics64_data_t (xnu vm_statistics.h), declaration order.
        _fields_ = [
            ("free_count", ctypes.c_uint32),
            ("active_count", ctypes.c_uint32),
            ("inactive_count", ctypes.c_uint32),
            ("wire_count", ctypes.c_uint32),
            ("zero_fill_count", ctypes.c_uint64),
            ("reactivations", ctypes.c_uint64),
            ("pageins", ctypes.c_uint64),
            ("pageouts", ctypes.c_uint64),
            ("faults", ctypes.c_uint64),
            ("cow_faults", ctypes.c_uint64),
            ("lookups", ctypes.c_uint64),
            ("hits", ctypes.c_uint64),
            ("purges", ctypes.c_uint64),
            ("purgeable_count", ctypes.c_uint32),
            ("speculative_count", ctypes.c_uint32),
            ("decompressions", ctypes.c_uint64),
            ("compressions", ctypes.c_uint64),
            ("swapins", ctypes.c_uint64),
            ("swapouts", ctypes.c_uint64),
            ("compressor_page_count", ctypes.c_uint32),
            ("throttled_count", ctypes.c_uint32),
            ("external_page_count", ctypes.c_uint32),
            ("internal_page_count", ctypes.c_uint32),
            ("total_uncompressed_pages_in_compressor", ctypes.c_uint64),
        ]

    # dlopen(NULL): libSystem is already linked into this process — no
    # subprocess, no dylib path guessing.
    libsystem = ctypes.CDLL(None, use_errno=True)
    libsystem.mach_host_self.restype = ctypes.c_uint32
    libsystem.host_statistics64.restype = ctypes.c_int
    libsystem.host_statistics64.argtypes = [
        ctypes.c_uint32, ctypes.c_int, ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
    ]
    stats = VmStatistics64()
    # host_statistics64's count is in natural_t WORDS (HOST_VM_INFO64_COUNT),
    # not bytes — the struct's own word count is the exact value.
    count = ctypes.c_uint32(
        ctypes.sizeof(stats) // ctypes.sizeof(ctypes.c_uint32))
    kern_return = libsystem.host_statistics64(
        libsystem.mach_host_self(), _HOST_VM_INFO64,
        ctypes.byref(stats), ctypes.byref(count))
    if kern_return != _KERN_SUCCESS:
        raise OSError(f"host_statistics64 failed (kern_return {kern_return})")
    return (int(stats.free_count), int(stats.inactive_count),
            int(stats.speculative_count))


def _mem_darwin() -> float:
    """Avail physical memory on macOS in bytes (Mach VM counters).

    available ~= (free + inactive + speculative) pages x page size — the
    reclaimable pool Activity Monitor-style tooling reports. xnu counts
    speculative pages inside free_count, so the third term re-includes a
    pool already in the free list (bounded by the speculative pool, well
    under 1% in the field); it is kept because this sum is the
    availability definition this gate documents (issue 223).
    """
    free, inactive, speculative = _darwin_vm_page_counts()
    page_size = int(os.sysconf("SC_PAGESIZE"))
    if page_size <= 0:
        raise OSError(f"sysconf returned non-positive (pagesize={page_size})")
    return float((free + inactive + speculative) * page_size)


def _mem_posix() -> float:
    """Avail physical memory on POSIX (non-darwin) in bytes (sysconf)."""
    pagesize = os.sysconf("SC_PAGESIZE")
    avail_pages = os.sysconf("SC_AVPHYS_PAGES")
    if pagesize <= 0 or avail_pages <= 0:
        raise OSError(f"sysconf returned non-positive (pagesize={pagesize}, avail={avail_pages})")
    return float(pagesize * avail_pages)


def _probe_avail_bytes() -> float:
    """Platform dispatch: available physical memory in bytes (raises on
    failure, so the caller decides between the floor fallback and the
    provenance marker)."""
    if sys.platform.startswith("win"):
        return _mem_windows()
    if sys.platform == "darwin":
        return _mem_darwin()
    return _mem_posix()


def _avail_probe() -> tuple[float, str, str]:
    """(avail_gb, avail_probe, detail) — one measurement, plus provenance.

    `avail_probe` is "ok" when the platform probe measured real memory, or
    "floor-fallback" when it failed and the floor constant is in force —
    fail-safe, but never silent.
    """
    try:
        return _probe_avail_bytes() / GB, AVAIL_PROBE_OK, ""
    except Exception as exc:  # noqa: BLE001 - detection is best-effort
        detail = f"{type(exc).__name__}: {exc}"[:PROBE_DETAIL_MAX]
        return (DEFAULTS["apk_mem_floor_gb"], AVAIL_PROBE_FLOOR_FALLBACK,
                detail)


def _avail_gb() -> float:
    """Total avail physical memory in GB. Falls back to the floor on
    failure; `_avail_probe` carries the same reading with its provenance."""
    return _avail_probe()[0]


def _probe_note(reason: str, avail_probe: str, detail: str) -> str:
    """Append the provenance note to the verdict reason when the floor
    fallback is in force (no-op for a measured reading)."""
    if avail_probe == AVAIL_PROBE_OK:
        return reason
    note = f"avail_probe: {avail_probe}"
    if detail:
        note += f" ({detail})"
    return f"{reason} | {note}" if reason else note


def _read_overrides(workspace: Path) -> dict[str, str]:
    """Read analysis_state.txt for operator overrides (key=value per line)."""
    state = workspace / "analysis_state.txt"
    if not state.exists():
        return {}
    out: dict[str, str] = {}
    try:
        for line in state.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    except OSError:
        return {}
    return out


def _sum_dex_bytes(apk_path: Path) -> tuple[int, int]:
    """Return (dex_count, dex_bytes_total) for an APK. Reads each .dex entry's
    uncompressed size from the central directory (no full unzip needed)."""
    dex_count = 0
    dex_bytes_total = 0
    try:
        with zipfile.ZipFile(apk_path, "r") as zf:
            for info in zf.infolist():
                name = info.filename.lower()
                if name.endswith(".dex"):
                    dex_count += 1
                    dex_bytes_total += info.file_size
    except (zipfile.BadZipFile, OSError):
        return 0, 0
    return dex_count, dex_bytes_total


def _verdict(est_gb: float, budget_gb: float, target_ext: str,
             override: str | None) -> tuple[str, str]:
    """Compute the verdict + reason string. override wins if set."""
    if override in ("jadx", "jadx-ok"):
        return "jadx-ok", "operator override apk_mem_override=jadx"
    if override in ("baksmali", "smali-only"):
        return "smali-only", "operator override apk_mem_override=baksmali"
    if override in ("refuse",):
        return "refuse", "operator override apk_mem_override=refuse"

    if target_ext == ".jar":
        return "refuse", ("jadx-infeasible: pure Java has no smali fallback; "
                           "analysis cannot proceed at this memory budget")

    if budget_gb >= 1.5 * est_gb:
        return "jadx-ok", ""
    if est_gb <= budget_gb:
        return "targeted-jadx", ""
    return "smali-only", ""


def _evaluate(target_path: Path, params: dict[str, Any],
              override: str | None, avail_gb: float,
              avail_probe: str = AVAIL_PROBE_OK,
              probe_detail: str = "") -> dict[str, Any]:
    """Build the evidence dict (no I/O)."""
    target_ext = target_path.suffix.lower()
    apk_size = target_path.stat().st_size if target_path.exists() else 0

    if target_ext == ".apk":
        dex_count, dex_bytes = _sum_dex_bytes(target_path)
    else:
        dex_count, dex_bytes = 0, apk_size

    est_gb = max(params["floor_gb"], params["dex_factor"] * dex_bytes / GB)
    budget_gb = params["budget_ratio"] * avail_gb
    verdict, reason = _verdict(est_gb, budget_gb, target_ext, override)
    reason = _probe_note(reason, avail_probe, probe_detail)

    return {
        "target": str(target_path),
        "target_ext": target_ext,
        "apk_size": apk_size,
        "dex_count": dex_count,
        "dex_bytes_total": dex_bytes,
        "est_heap_gb": round(est_gb, 3),
        "avail_gb": round(avail_gb, 3),
        "avail_probe": avail_probe,
        "budget_gb": round(budget_gb, 3),
        "verdict": verdict,
        "reason": reason,
        "calibration_basis": (CALIBRATION_BASIS + (" | override applied" if override else "")),
        "evaluated_at": _utc_now(),
    }


def run(workspace: Path | str, target: str) -> int:
    """Top-level entry: estimate + write evidence. Always exits 0
    (REFUSE is an expected outcome, not an error)."""
    workspace = Path(workspace)
    target_path = Path(target)
    overrides = _read_overrides(workspace)
    override = overrides.get("apk_mem_override")

    params = {
        "dex_factor": float(overrides.get("apk_mem_dex_factor", DEFAULTS["apk_mem_dex_factor"])),
        "floor_gb": float(overrides.get("apk_mem_floor_gb", DEFAULTS["apk_mem_floor_gb"])),
        "budget_ratio": float(overrides.get("apk_mem_budget_ratio",
                                            DEFAULTS["apk_mem_budget_ratio"])),
    }
    avail_gb, avail_probe, probe_detail = _avail_probe()

    data = _evaluate(target_path, params, override, avail_gb, avail_probe,
                     probe_detail)
    write_evidence(workspace, "apk_mem_gate.json", data)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="apk_mem_gate - memory-aware jadx dispatch estimator (#670).",
    )
    parser.add_argument("workspace", type=Path, help="workspace root")
    parser.add_argument("target", help="APK or JAR path")
    args = parser.parse_args(argv)
    rc = run(args.workspace, args.target)
    try:
        data = json.loads((args.workspace / "evidence" / "apk_mem_gate.json")
                          .read_text(encoding="utf-8"))
        print(json.dumps(
            {"verdict": data["verdict"],
             "est_heap_gb": data["est_heap_gb"],
             "budget_gb": data["budget_gb"],
             # issue 215's recorder mirrors this line into env-facts: the
             # probe provenance must travel with it (issue 223).
             "reason": data.get("reason", ""),
             "avail_probe": data.get("avail_probe", AVAIL_PROBE_OK)},
            ensure_ascii=False,
        ))
    except Exception:  # noqa: BLE001 - best-effort audit line
        pass
    return rc


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())