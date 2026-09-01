#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/static/die_probe.py — Detect-It-Easy probe wrapper CLI (issue #278 PR-1c).

Absorbed from D:/works/samples/2026-07-01/scripts/die_probe.py (the "DIE
5-call merge v8" driver that replaced the Windows-mangling bash wrapper),
de-hardcoded (the source had the diec.exe path as a literal): runs diec.exe
with five flag sets and merges the results into one deterministic JSON report.

  diec -j <path>                detects[]
  diec -j -e <path>             records[] (per-section entropy)
  diec -j -b <path>             verbose detects (language / os / packer depth)
  diec -j -S Hash <path>        full hash set
  diec -j -S Resource <path>    VERSION_INFO / MANIFEST / ICON / STRINGTABLE

#277 contract: parameterized (--binary + --die), deterministic (no timestamps
in the output — idempotent re-runs emit identical JSON), three-state exit
codes, --json (default single JSON object), --reproduce field=value lines
(kunglao L1 gate), errors carry guidance.

Exit codes:
  0 = merged report produced from at least one successful DIE call;
  1 = negative finding (DIE ran but no call produced usable data);
  2 = operational error (DIE not found / binary missing / bad args).
      The DIE-missing message carries install guidance.

Usage:
  python die_probe.py --binary sample.exe
  python die_probe.py --binary sample.exe --die D:/tools/die/diec.exe
  python die_probe.py --binary sample.exe --reproduce
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
import os
import shutil
import subprocess
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

# issue #319 dedup: the {"error","exit_code"} stderr emitter has a single
# source — tools/static/common.error. Reuse it instead of a local _error().
from common import error  # noqa: E402

# r2-278-1c H1 (die_probe gap): this tool does NOT import common (byte-scan
# helpers); it imports common only for the single error emitter (issue #319
# dedup). The shared UTF-8 stdout guard therefore still lives here — an
# emoji/non-ASCII --out filename crashes on GBK consoles without it.
# Same unified UTF-8 policy as tools/static/common.py.

FLAG_CALLS: tuple[tuple[str, list[str]], ...] = (
    ("diec -j <path>", []),
    ("diec -j -e <path>", ["-e"]),
    ("diec -j -b <path>", ["-b"]),
    ("diec -j -S Hash <path>", ["-S", "Hash"]),
    ("diec -j -S Resource <path>", ["-S", "Resource"]),
)

PACKER_NAMES = (
    "upx", "vmprotect", "themida", "aspack", "mpress",
    "pecompact", "pelock", "winupack", "kkrunchy", "exestealth",
    "nspack", "pepack", "rlpack", "yzpack", "petite",
)


def resolve_die(die_arg: str | None, env: dict | None = None) -> Path | None:
    """Locate the diec executable: --die, then $KUNGLAO_DIE, then PATH."""
    if die_arg:
        return Path(die_arg)
    environ = env if env is not None else os.environ
    if environ.get("KUNGLAO_DIE"):
        return Path(environ["KUNGLAO_DIE"])
    for name in ("diec", "diec.exe"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def run_diec(die: Path, target: Path, flags: list[str], timeout: int) -> dict:
    cmd = [str(die), "-j"] + flags + [str(target)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        return {"_error": f"timeout after {timeout}s: {exc}", "flags": flags}
    except OSError as exc:
        return {"_error": f"cannot run {die}: {exc}", "flags": flags}
    if p.returncode != 0 or not p.stdout.strip():
        return {"_error": p.stderr.strip() or "no output", "flags": flags}
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        return {"_error": f"json: {exc}", "raw_first_200": p.stdout[:200], "flags": flags}


def _first(*types, values, name=None):
    for v in values:
        if v.get("type") in types:
            if name and v.get("name") != name:
                continue
            return v
    return None


def merge(detects: dict, verbose: dict, entropy: dict,
          hashes: dict, resources: dict) -> dict:
    """Merge the five DIE call results (source die_probe.py merge logic)."""
    all_values = []
    for d in detects.get("detects", []) or []:
        all_values.extend(v for v in d.get("values", []) or [])
    basic_keys = {(v.get("type"), v.get("name"), v.get("version")) for v in all_values}
    for d in verbose.get("detects", []) or []:
        for v in d.get("values", []) or []:
            if (v.get("type"), v.get("name"), v.get("version")) not in basic_keys:
                all_values.append(v)

    language = _first("language", values=all_values) or _first("compiler", values=all_values)
    compiler_v = _first("compiler", values=all_values)
    sign_tool = _first("sign tool", values=all_values)
    op_system = _first("operation system", "operationSystem", "os", values=all_values)

    detected_packer = None
    for v in all_values:
        text = (str(v.get("name", "")) + " " + str(v.get("string", ""))).lower()
        for pn in PACKER_NAMES:
            if pn in text:
                detected_packer = pn
                break
        if detected_packer:
            break

    section_table, high_entropy = [], []
    for r in entropy.get("records", []) or []:
        name = str(r.get("name", ""))
        if name.startswith("Section") and "[" in name and "]" in name:
            sec = name.split("[")[1].split("]")[0].strip('"')
        else:
            sec = name
        ent = r.get("entropy", 0.0) or 0.0
        section_table.append({
            "name": sec, "offset": r.get("offset"), "size": r.get("size"),
            "entropy": ent, "status": r.get("status"),
        })
        if ent > 7.0:
            high_entropy.append(sec)

    res = (resources.get("data", {}) or {}).get("Resource", {}) or resources.get("Resource", {})
    return {
        "detects": detects.get("detects", []),
        "records": entropy.get("records", []),
        "overall_status": entropy.get("status"),
        "total_entropy": entropy.get("total"),
        "hashes": (hashes.get("data", {}) or {}).get("Hash", {}) or hashes.get("Hash", {}),
        "resources": res,
        "version_info": res.get("VERSION_INFO", {}),
        "manifest": res.get("MANIFEST", ""),
        "derived": {
            "language": language.get("name") if language else None,
            "compiler_version": compiler_v.get("version") if compiler_v else None,
            "compiler_string": compiler_v.get("string") if compiler_v else None,
            "sign_tool": sign_tool.get("string") if sign_tool else None,
            "operation_system": op_system.get("string") if op_system else None,
            "detected_packer": detected_packer,
            "section_table": section_table,
            "high_entropy_sections": high_entropy,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Detect-It-Easy 5-call merge probe — issue #278 PR-1c")
    ap.add_argument("--binary", required=True, help="PE to probe")
    ap.add_argument("--die", metavar="PATH",
                    help="diec executable (default: $KUNGLAO_DIE, then diec on PATH)")
    ap.add_argument("--timeout", type=int, default=120, metavar="N",
                    help="per-call timeout seconds (default 120)")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout (default)")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines (kunglao L1 mechanical gate)")
    ap.add_argument("--out", metavar="FILE", help="write the JSON result to FILE")
    args = ap.parse_args(argv)

    target = Path(args.binary)
    if not target.is_file():
        error(f"target missing: {target}. "
              f"Check the path and re-run: python die_probe.py --binary {target}",
              2)

    die = resolve_die(args.die)
    if die is None:
        error("DIE (diec) not found. Install Detect-It-Easy and pass the "
              "executable explicitly, e.g. "
              "python die_probe.py --binary <pe> --die D:/tools/die/diec.exe "
              "— or set KUNGLAO_DIE=<path-to-diec.exe> in the environment.",
              2)
    if not Path(die).is_file():
        error(f"--die {die} does not exist. Install Detect-It-Easy and pass "
              f"the diec executable: --die <path-to-diec.exe>",
              2)

    calls = {label: run_diec(die, target, flags, args.timeout) for label, flags in FLAG_CALLS}
    detects, entropy = calls["diec -j <path>"], calls["diec -j -e <path>"]
    verbose = calls["diec -j -b <path>"]
    hashes, resources = calls["diec -j -S Hash <path>"], calls["diec -j -S Resource <path>"]

    payload = {
        "_meta": {
            "source": "die",
            "tool": "DIE diec.exe (5-call merge)",
            "die_path": str(die),
            "binary": str(target),
            "flag_calls": [label for label, _ in FLAG_CALLS],
        },
        **merge(detects, verbose, entropy, hashes, resources),
        "call_errors": {label: c["_error"] for label, c in calls.items() if "_error" in c},
    }

    if args.reproduce:
        derived = payload["derived"]
        rows = {
            "tool": "die-probe",
            "binary": str(target),
            "die": str(die),
            "calls_ok": len(FLAG_CALLS) - len(payload["call_errors"]),
            "language": derived["language"] or "none",
            "packer": derived["detected_packer"] or "none",
            "high_entropy_sections": len(derived["high_entropy_sections"]),
            "detects": len(payload["detects"]),
        }
        for k, v in rows.items():
            print(f"{k}={v}")
    else:
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if args.out:
            try:
                Path(args.out).write_text(text, encoding="utf-8")
            except OSError as exc:
                error(f"cannot write --out {args.out}: {exc}. "
                      f"Check the directory and re-run with a writable --out path.",
                      2)
        else:
            print(text)

    if len(payload["call_errors"]) == len(FLAG_CALLS):
        print(json.dumps({"error": "all 5 DIE calls failed (see call_errors in the report). "
                                   "Check that diec runs: %s -j <path-to-pe>" % die,
                          "exit_code": 1}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
