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


def _mem_posix() -> float:
    """Avail physical memory on POSIX in bytes (sysconf)."""
    pagesize = os.sysconf("SC_PAGESIZE")
    avail_pages = os.sysconf("SC_AVPHYS_PAGES")
    if pagesize <= 0 or avail_pages <= 0:
        raise OSError(f"sysconf returned non-positive (pagesize={pagesize}, avail={avail_pages})")
    return float(pagesize * avail_pages)


def _avail_gb() -> float:
    """Total avail physical memory in GB. Falls back to 4 GB on failure."""
    try:
        if sys.platform.startswith("win"):
            return _mem_windows() / GB
        return _mem_posix() / GB
    except Exception:  # noqa: BLE001 - detection is best-effort
        return DEFAULTS["apk_mem_floor_gb"]


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
              override: str | None, avail_gb: float) -> dict[str, Any]:
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

    return {
        "target": str(target_path),
        "target_ext": target_ext,
        "apk_size": apk_size,
        "dex_count": dex_count,
        "dex_bytes_total": dex_bytes,
        "est_heap_gb": round(est_gb, 3),
        "avail_gb": round(avail_gb, 3),
        "budget_gb": round(budget_gb, 3),
        "verdict": verdict,
        "reason": reason,
        "calibration_basis": (CALIBRATION_BASIS + (" | override applied" if override else "")),
        "evaluated_at": _utc_now(),
    }


def _write_evidence(workspace: Path, data: dict) -> Path:
    out_dir = workspace / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "apk_mem_gate.json"
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


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
    avail_gb = _avail_gb()

    data = _evaluate(target_path, params, override, avail_gb)
    _write_evidence(workspace, data)
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
             "budget_gb": data["budget_gb"]},
            ensure_ascii=False,
        ))
    except Exception:  # noqa: BLE001 - best-effort audit line
        pass
    return rc


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())