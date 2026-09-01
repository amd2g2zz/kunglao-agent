#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""baksmali_index.py - DEX enumeration + xref (#670).

gitnexus is Java-only. For DEX we need baksmali. The output schema MUST be
shape-compatible with gitnexus so downstream consumers (anomaly detector
#663, hypothesis seeder #662) don't branch on tool identity - the
"system optimum" wire.

Spec: openspec/changes/issue-670-mem-gated-jadx/specs/mem-gated-jadx/spec.md
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _discover_baksmali() -> str | None:
    """Locate baksmali binary. Returns path or None."""
    return shutil.which("baksmali")


def _run(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run subprocess; return (rc, stdout, stderr)."""
    cp = subprocess.run(
        args, capture_output=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return cp.returncode, cp.stdout, cp.stderr


def _list_classes(baksmali: str, apk: str, timeout: int = 120) -> list[dict]:
    """`baksmali list --format json <apk>` -> list of class dicts."""
    rc, stdout, stderr = _run(
        [baksmali, "list", "--format", "json", apk], timeout=timeout,
    )
    if rc != 0:
        return []
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict] = []
    for cls in data:
        if not isinstance(cls, dict):
            continue
        out.append({
            "name": str(cls.get("name", "")),
            "methods": cls.get("methods") if isinstance(cls.get("methods"), list) else [],
        })
    return out


def _xref_class(baksmali: str, cls: dict, timeout: int = 30) -> None:
    """`baksmali xref <class>` -> populate cls['methods'][*]['xrefs'].
    Fail-open: a per-class error leaves xrefs empty for that class; others OK."""
    name = cls.get("name", "")
    if not name:
        return
    try:
        rc, stdout, stderr = _run(
            [baksmali, "xref", name], timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        for m in cls.get("methods", []):
            m["xrefs"] = {"calls": [], "called_by": []}
        return
    if rc != 0:
        for m in cls.get("methods", []):
            m["xrefs"] = {"calls": [], "called_by": []}
        return
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError:
        doc = {}
    calls = doc.get("calls") if isinstance(doc.get("calls"), list) else []
    called_by = doc.get("called_by") if isinstance(doc.get("called_by"), list) else []
    for m in cls.get("methods", []):
        m["xrefs"] = {"calls": list(calls), "called_by": list(called_by)}


def _write_evidence(workspace: Path, data: dict) -> Path:
    out_dir = workspace / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "smali_index.json"
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def _base_payload() -> dict[str, Any]:
    return {
        "tool": "baksmali",
        "version": None,
        "target": None,
        "classes": [],
        "scanned_at": _utc_now(),
    }


def run(workspace: Path | str, apk: str) -> int:
    """Top-level entry: enumerate + xref + write evidence. Always exits 0
    on ok/unavailable; 1 only on hard errors (never raises)."""
    workspace = Path(workspace)
    apk_path = apk
    payload = _base_payload()
    payload["target"] = apk_path

    baksmali = _discover_baksmali()
    if baksmali is None:
        print("warning: baksmali binary not found; smali_index.json will have "
              "empty classes (downstream consumers skip on empty)",
              file=sys.stderr)
        _write_evidence(workspace, payload)
        return 0

    try:
        rc, stdout, _ = _run([baksmali, "--version"], timeout=10)
        if rc == 0:
            # strip a leading "baksmali " prefix (real baksmali prints it)
            v = stdout.strip()
            if v.lower().startswith("baksmali"):
                v = v[len("baksmali"):].lstrip()
            payload["version"] = v or None
    except (OSError, subprocess.TimeoutExpired):
        _write_evidence(workspace, payload)
        return 0

    classes = _list_classes(baksmali, apk_path)
    for cls in classes:
        _xref_class(baksmali, cls)
    payload["classes"] = classes

    _write_evidence(workspace, payload)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="baksmali_index - DEX enumeration + xref (#670).",
    )
    parser.add_argument("workspace", type=Path, help="workspace root")
    parser.add_argument("apk", help="absolute path to the APK")
    args = parser.parse_args(argv)
    return run(args.workspace, args.apk)


if __name__ == "__main__":
    sys.exit(main())