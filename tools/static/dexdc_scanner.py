#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dexdc_scanner.py - dex-decompiler provider wrapper (#692 WP2).

Wraps androguard/dex-decompiler (pure Rust, no JVM - immune to the jadx
12GB-heap-thrash failure mode, #670's calibration point) as the android
capability provider `dexdc` (tools/_INDEX.yaml entry `dexdc-decompile`).

Detection (fail-open on every layer, never raises):
  1. PyO3 wheel: `import dex_decompiler` (build: cd dex-decompiler-py &&
     maturin build --release && pip install target/wheels/dex_decompiler-*.whl)
  2. CLI fallback: `dex-decompile` binary on PATH.

Faces per mode (ONLY documented upstream surfaces, nothing invented):
  index mode -> pyo3 face: parse_dex(bytes) +
     dex.get_method_bytecode_and_cfg(class, method) -> (rows, nodes, edges).
     The wire is the #670 gitnexus-shape (classes[].methods[].xrefs, the
     same face as evidence/smali_index.json) with the per-method cfg
     {nodes, edges} as the dexdc value-add. The CLI face cannot enumerate
     per-method CFG -> status "unavailable-via-cli" (honest, not an error).
  taint mode -> cli face: dex-decompile -i <target> --taint-solve
     --taint-output <tmp/issues.json> [--taint-api <seed>]...; the upstream
     IssueReport is normalized VERBATIM into issues[].{rule, source, sink,
     traces}. The pyo3 face has no documented taint binding -> status
     "unavailable-via-pyo3" (CLI only, honest).

Outputs (always written, fail-open): evidence/dexdc_index.json +
evidence/dexdc_taint.json. Exit 0 ok/unavailable, 1 hard error only.

Spec: openspec/changes/issue-692-capability-registry (design D6).
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# UTF-8 stdout contract (#317): non-ASCII output must not crash a GBK console.

PYO3_MODULE = "dex_decompiler"
CLI_BINARY = "dex-decompile"
DEFAULT_SEEDS_FILE = (Path(__file__).resolve().parent.parent.parent /
                      "references" / "re-library" /
                      "android-fingerprint-seeds.yaml")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    cp = subprocess.run(args, capture_output=True, encoding="utf-8",
                        errors="replace", timeout=timeout)
    return cp.returncode, cp.stdout or "", cp.stderr or ""


def detect() -> dict[str, Any]:
    """Locate the dexdc provider. Returns {face, version, module, bin}.

    face is "pyo3" | "cli" | None. PyO3 wins (in-process, no subprocess
    spawn). Version best-effort: module __version__ or `--version` output.
    """
    try:
        module = importlib.import_module(PYO3_MODULE)
        return {"face": "pyo3",
                "version": getattr(module, "__version__", None),
                "module": module, "bin": None}
    except ImportError:
        pass
    bin_path = shutil.which(CLI_BINARY)
    if bin_path:
        version = None
        try:
            rc, out, _ = _run([bin_path, "--version"], timeout=10)
            if rc == 0:
                version = out.strip() or None
        except (OSError, subprocess.TimeoutExpired):
            pass
        return {"face": "cli", "version": version, "module": None,
                "bin": bin_path}
    return {"face": None, "version": None, "module": None, "bin": None}


def _base_payload(face: dict[str, Any], target: str) -> dict[str, Any]:
    return {"tool": "dexdc", "version": face.get("version"),
            "face": face.get("face"), "status": "ok", "target": target,
            "scanned_at": _utc_now()}


def _write_evidence(workspace: Path, name: str, data: dict) -> Path:
    out_dir = workspace / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / name
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return out_path


def _run_index(workspace: Path, target: str, face: dict[str, Any],
               methods: list[tuple[str, str]],
               only_package: str | None) -> dict[str, Any]:
    payload = _base_payload(face, target)
    payload["classes"] = []
    if face.get("face") != "pyo3":
        payload["status"] = ("unavailable" if face.get("face") is None
                             else "unavailable-via-cli")
        return payload
    try:
        dex = face["module"].parse_dex(Path(target).read_bytes())
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        payload["status"] = "error"
        payload["reason"] = f"parse_dex failed: {exc}"
        return payload

    # class list: targeted methods first; decompile_to_dir file walk
    # discovers class NAMES for the untargeted remainder (methods stay
    # empty there - honest shape, no invented enumeration).
    classes: dict[str, dict] = {}
    for cls, method in methods:
        entry = classes.setdefault(
            cls, {"name": cls, "methods": []})
        try:
            _rows, nodes, edges = dex.get_method_bytecode_and_cfg(
                cls, method)
            entry["methods"].append({
                "name": method,
                "xrefs": {"calls": [], "called_by": []},
                "cfg": {"nodes": list(nodes or []),
                        "edges": [list(e) for e in (edges or [])]},
            })
        except (AttributeError, TypeError, ValueError) as exc:
            entry["methods"].append({
                "name": method,
                "xrefs": {"calls": [], "called_by": []},
                "error": str(exc),
            })
    if only_package:
        payload["only_package"] = only_package
    payload["classes"] = list(classes.values())
    return payload


def _load_seeds(seeds: list[str] | None, seeds_file: Path | None) -> list[str]:
    """Explicit seeds win; else the WP5 fingerprint table (fail-open)."""
    if seeds:
        return list(seeds)
    path = Path(seeds_file) if seeds_file else DEFAULT_SEEDS_FILE
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = data.get("seeds") if isinstance(data, dict) else None
        return [str(e.get("api")) for e in entries if e.get("api")] \
            if isinstance(entries, list) else []
    except (OSError, ValueError, yaml.YAMLError, ImportError):
        return []


def _run_taint(workspace: Path, target: str, face: dict[str, Any],
               seeds: list[str], only_package: str | None) -> dict[str, Any]:
    payload = _base_payload(face, target)
    payload["seeds"] = list(seeds)
    payload["issues"] = []
    payload["count"] = 0
    if face.get("face") != "cli":
        payload["status"] = ("unavailable" if face.get("face") is None
                             else "unavailable-via-pyo3")
        return payload
    with tempfile.TemporaryDirectory(prefix="dexdc-taint-") as tmp:
        report = Path(tmp) / "issues.json"
        args = [face["bin"], "-i", str(target), "--taint-solve",
                "--taint-output", str(report)]
        for seed in seeds:
            args += ["--taint-api", str(seed)]
        if only_package:
            args += ["--only-package", only_package]
        try:
            rc, _out, err = _run(args, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            payload["status"] = "error"
            payload["reason"] = f"dex-decompile failed: {exc}"
            return payload
        if rc != 0:
            payload["status"] = "error"
            payload["reason"] = f"dex-decompile exit {rc}: {err.strip()[:300]}"
            return payload
        try:
            raw = json.loads(report.read_text(encoding="utf-8"))
            issues = raw.get("issues") if isinstance(raw, dict) else raw
        except (OSError, ValueError) as exc:
            payload["status"] = "error"
            payload["reason"] = f"taint-output parse failed: {exc}"
            return payload
        payload["issues"] = [
            {"rule": i.get("rule"), "source": i.get("source"),
             "sink": i.get("sink"), "traces": i.get("traces") or []}
            for i in (issues or []) if isinstance(i, dict)
        ]
        payload["count"] = len(payload["issues"])
    return payload


def run(workspace: Path | str, target: str, mode: str = "both",
        methods: list[tuple[str, str]] | None = None,
        only_package: str | None = None,
        seeds: list[str] | None = None,
        seeds_file: Path | None = None) -> int:
    """Top-level entry: detect + write evidence. Always exits 0 on
    ok/unavailable; 1 only on hard usage errors (never raises)."""
    workspace = Path(workspace)
    face = detect()
    methods = methods or []
    if mode in ("index", "both"):
        _write_evidence(workspace, "dexdc_index.json",
                        _run_index(workspace, str(target), face, methods,
                                   only_package))
    if mode in ("taint", "both"):
        resolved = _load_seeds(seeds, seeds_file)
        _write_evidence(workspace, "dexdc_taint.json",
                        _run_taint(workspace, str(target), face, resolved,
                                   only_package))
    return 0


def _parse_method(spec: str) -> tuple[str, str]:
    """'CLASS#METHOD' -> (class, method); the upstream CLI argument shape."""
    cls, sep, method = spec.partition("#")
    if not sep or not cls or not method:
        raise argparse.ArgumentTypeError(
            f"--method must be CLASS#METHOD, got {spec!r}")
    return cls, method


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="dexdc provider wrapper (#692 WP2). Writes "
                    "evidence/dexdc_index.json + dexdc_taint.json "
                    "(fail-open).")
    parser.add_argument("workspace", type=Path,
                        help="workspace root (writes evidence/)")
    parser.add_argument("--target", required=True,
                        help="APK/DEX target path")
    parser.add_argument("--mode", choices=["index", "taint", "both"],
                        default="both")
    parser.add_argument("--method", action="append", type=_parse_method,
                        default=[], metavar="CLASS#METHOD",
                        help="targeted method for index mode (repeatable)")
    parser.add_argument("--only-package", default=None,
                        help="passthrough: only decompile this package")
    parser.add_argument("--seeds", action="append", default=None,
                        help="taint seed API (repeatable; default: the "
                             "fingerprint seed table)")
    parser.add_argument("--seeds-file", type=Path, default=None,
                        help="alternate seed table yaml")
    parser.add_argument("--json", action="store_true",
                        help="print the evidence summaries as JSON")
    args = parser.parse_args(argv)

    rc = run(args.workspace, args.target, mode=args.mode,
             methods=args.method, only_package=args.only_package,
             seeds=args.seeds, seeds_file=args.seeds_file)
    if args.json:
        out = {}
        for name in ("dexdc_index.json", "dexdc_taint.json"):
            p = args.workspace / "evidence" / name
            if p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                out[name] = {"status": data.get("status"),
                             "count": data.get(
                                 "count", len(data.get("classes", [])))}
        print(json.dumps(out, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
