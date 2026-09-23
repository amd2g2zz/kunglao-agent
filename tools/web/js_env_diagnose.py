#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""js_env_diagnose.py — Node-VM sandbox diagnosis for obfuscated web JS.

Runs a target JS file inside a fresh Node `vm` sandbox whose global object
is proxy-monitored, and reports which browser-environment globals the code
reads but the sandbox does not provide (the "undefined paths"), plus a
truncated error, access counters, and captured console output. This is the
mechanical first step of the env-patching loop: patch what is reported,
re-run, repeat until the bundle executes or the residue is stable.

The sandbox ships with deliberately ZERO browser environment: every missing
global it reports is a real requirement of the target. Stub objects can be
injected as --prelude files (plain JS assigning onto globalThis) to verify
a patch suppresses the miss.

Input: --target <file.js> (+ optional --prelude files, --timeout-ms,
  --node binary, --max-console lines). Output: stdout JSON {success,
  error, undefined_paths, access_stats, console_tail}. Exit 0 = diagnosis
  produced (a target crash or sandbox timeout is a RESULT, not an error);
  exit 2 = tool-level failure (node binary missing, target missing/empty,
  harness crashed, wall-clock budget exhausted).

Usage:
  python tools/web/js_env_diagnose.py --target bundle.js
  python tools/web/js_env_diagnose.py --target bundle.js --prelude stub.js

Examples:
  # first diagnosis: no env at all — collect the missing-globals list
  python tools/web/js_env_diagnose.py --target obfuscated_bundle.js

  # verify a navigator stub removes its miss from the report
  python tools/web/js_env_diagnose.py --target obfuscated_bundle.js \
      --prelude stub_navigator.js

  # bounded run for bundles that may loop forever
  python tools/web/js_env_diagnose.py --target bundle.js --timeout-ms 3000
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# UTF-8 stdout guard via the shared tools/ _lib; the guard itself fires in
# __main__ only.
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents
                  if _p.name == "tools")
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402

HARNESS = r"""
"use strict";
const vm = require("vm");
const fs = require("fs");
const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

const missing = new Set();
const stats = { get: 0, set: 0, has: 0, construct: 0 };
const consoleOut = [];

function fmt(v) {
  if (typeof v === "string") return v;
  try { return JSON.stringify(v); } catch (_) { return String(v); }
}
function cap(...a) { return a.map(fmt).join(" "); }

const base = {
  console: {
    log: (...a) => consoleOut.push(["log", cap(...a)]),
    error: (...a) => consoleOut.push(["error", cap(...a)]),
    warn: (...a) => consoleOut.push(["warn", cap(...a)]),
    info: (...a) => consoleOut.push(["info", cap(...a)]),
    debug: (...a) => consoleOut.push(["debug", cap(...a)]),
    trace: (...a) => consoleOut.push(["trace", cap(...a)]),
  },
  setTimeout: () => 0,
  setInterval: () => 0,
  clearTimeout: () => {},
  clearInterval: () => {},
  atob: (s) => Buffer.from(s, "base64").toString("binary"),
  btoa: (s) => Buffer.from(s, "binary").toString("base64"),
};

const handler = {
  get(target, prop, recv) {
    stats.get++;
    if (typeof prop === "string" && !(prop in target)) missing.add(prop);
    return Reflect.get(target, prop, recv);
  },
  has(target, prop) { stats.has++; return Reflect.has(target, prop); },
  set(target, prop, value) { stats.set++; return Reflect.set(target, prop, value); },
  construct(target, args) { stats.construct++; return Reflect.construct(target, args); },
};

const sandbox = new Proxy(base, handler);
sandbox.globalThis = sandbox;
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.global = sandbox;

const context = vm.createContext(sandbox);
const runOpts = { timeout: cfg.timeout_ms, filename: cfg.filename,
                  displayErrors: true };

let ok = true;
let err = null;
for (const p of cfg.preludes) {
  try {
    vm.runInContext(fs.readFileSync(p, "utf8"), context, runOpts);
  } catch (e) {
    ok = false;
    err = "prelude failed: " + String((e && (e.name + ": " + e.message)) || e).slice(0, 500);
    break;
  }
}
if (ok) {
  try {
    vm.runInContext(fs.readFileSync(cfg.target, "utf8"), context, runOpts);
  } catch (e) {
    ok = false;
    err = String((e && (e.name + ": " + e.message)) || e).slice(0, 500);
  }
}

process.stdout.write(JSON.stringify({
  success: ok,
  error: err,
  undefined_paths: Array.from(missing).sort(),
  access_stats: stats,
  console_tail: consoleOut.slice(-cfg.max_console),
}));
"""


def _resolve_node(node: str) -> str:
    if Path(node).is_file() or Path(node).is_absolute():
        return node
    found = shutil.which(node)
    if not found:
        print(f"js_env_diagnose: node binary not found: {node!r} "
              f"(install Node.js or pass --node)", file=sys.stderr)
        raise SystemExit(2)
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="run a JS bundle in a bare Node-VM sandbox and report "
                    "missing browser globals (the env-patch list)",
        epilog=(
            "exit codes: 0 = diagnosis produced (target crash/timeout is a "
            "result); 2 = tool-level failure\n"
            "\n"
            "Examples:\n"
            "  # first diagnosis: no env at all — collect missing globals\n"
            "  python tools/web/js_env_diagnose.py --target "
            "obfuscated_bundle.js\n"
            "\n"
            "  # verify a stub suppresses its miss\n"
            "  python tools/web/js_env_diagnose.py --target bundle.js "
            "--prelude stub_navigator.js\n"
            "\n"
            "  # bounded run for bundles that may loop forever\n"
            "  python tools/web/js_env_diagnose.py --target bundle.js "
            "--timeout-ms 3000"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True, help="JS file to execute")
    ap.add_argument("--prelude", action="append", default=[],
                    help="stub JS file loaded before the target "
                         "(repeatable; assigns onto globalThis)")
    ap.add_argument("--timeout-ms", type=int, default=60000,
                    help="sandbox execution budget per script (default 60000)")
    ap.add_argument("--node", default="node",
                    help="node binary name or path (default: PATH lookup)")
    ap.add_argument("--max-console", type=int, default=100,
                    help="console entries kept in the report tail "
                         "(default 100)")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if not target.is_file():
        print(f"js_env_diagnose: target not found: {target}",
              file=sys.stderr)
        return 2
    if not target.read_bytes().strip():
        print(f"js_env_diagnose: target is empty: {target}", file=sys.stderr)
        return 2
    for pre in args.prelude:
        if not Path(pre).is_file():
            print(f"js_env_diagnose: prelude not found: {pre}",
                  file=sys.stderr)
            return 2
    if args.timeout_ms <= 0:
        print("js_env_diagnose: --timeout-ms must be positive",
              file=sys.stderr)
        return 2

    node = _resolve_node(args.node)
    cfg = {
        "target": str(target.resolve()),
        "preludes": [str(Path(p).resolve()) for p in args.prelude],
        "timeout_ms": args.timeout_ms,
        "filename": target.name,
        "max_console": max(1, args.max_console),
    }
    with tempfile.TemporaryDirectory(prefix="jsenvdiag_") as td:
        cfg_path = Path(td) / "cfg.json"
        harness_path = Path(td) / "harness.cjs"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        harness_path.write_text(HARNESS, encoding="utf-8")
        try:
            proc = subprocess.run(
                [node, str(harness_path), str(cfg_path)],
                capture_output=True, text=True,
                timeout=args.timeout_ms / 1000 + 15)
        except subprocess.TimeoutExpired:
            print("js_env_diagnose: harness exceeded its wall-clock budget",
                  file=sys.stderr)
            return 2
        except OSError as exc:
            print(f"js_env_diagnose: cannot execute node: {exc}",
                  file=sys.stderr)
            return 2

    if proc.returncode != 0 or not proc.stdout.strip():
        print(f"js_env_diagnose: harness crashed (rc={proc.returncode}): "
              f"{proc.stderr.strip()[:500]}", file=sys.stderr)
        return 2
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"js_env_diagnose: harness produced unparsable output: {exc}",
              file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
