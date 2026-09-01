#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_shim.py — device-side deployment + one-off shim records (#477 ③).

Issue #477 evidence 3: the device-side deployments (frida-server push +
RENAME + custom port; android_server push + run) existed only as FIX_TEXT
guidance in toolchain.py — no executable, no idempotency, no probe
closure. This script is that executable, plus the #462 normalization of
"一次性垫片须标注即弃" (one-off shims must be annotated and discarded):

  deploy face — idempotent adb deployment for the two device services:
      frida-server   -> adb push to a RENAMED on-device name (default
                        `sysmon`; the #304 F3 convention — default name/
                        port 27042 is detected by samples) + background
                        start on the custom port (default toolchain.
                        FRIDA_PORT, env KUNGLAO_FRIDA_PORT)
      android-server -> adb push + background start on the IDA
                        android_server port (toolchain.ANDROID_SERVER_PORT)
    Idempotent by construction: the port pre-probe (toolchain's
    adb-forward probe, reused — single source) PASSes on an
    already-deployed device and the run becomes a no-op with ZERO
    DEVICE-SIDE mutations — the probe itself still runs `adb forward`
    on the HOST (probe semantics, not a deployment mutation);
    after a real deploy the port re-probe must PASS before success is
    claimed (#474 posture: never claim an unverified deployment). The
    outcome lands in <ws>/env-facts.yaml's installed ledger (#450 face).

  new face — materialize an annotated one-off shim record under
      scripts/shims/<name>.md (target/purpose/expiry + a discard-after-use
      contract line); the directory README (created on first use)
      declares the discard semantics. A shim that earns permanence goes
      upstream via an issue into scripts/ — never silently promoted.

Device scope: ADB only (the android dynamic contract; #455). VM-side
deployment stays on the #451 vm-* verbs. Multi-device serial targeting
is deliberately out of v1 — toolchain's own probes use bare adb; same
caliber.

CLI:
  deploy_shim.py deploy --tool frida-server --local <path>
      [--port N] [--alias NAME] [--workspace <ws>]
  deploy_shim.py deploy --tool android-server --local <path>
      [--workspace <ws>]
  deploy_shim.py new --name N --purpose P --expiry E
      [--target T] [--root DIR]

Exit codes: 0 = ok; 1 = deploy or re-probe failed; 3 = validation
refusal (bad name / missing fields / overwrite). (2 = argparse usage.)
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import env_manifest  # noqa: E402  (#450 facts file — installed ledger)
import toolchain  # noqa: E402  (ports + the adb-forward probe, single source)

# UTF-8 stdout/stderr unification (same pattern as toolchain.py).
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        try:
            _reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

RC_OK = 0
RC_DEPLOY_FAILED = 1
RC_VALIDATION = 3

# Seams (repo pattern): tests inject deterministic which/subprocess/probe.
_subprocess_run = subprocess.run
_shutil_which = shutil.which


def _probe_port(adb: str, port: int) -> tuple[bool, str]:
    """Device-side service probe — toolchain's adb-forward probe reused
    (single source; liveness tier per #474)."""
    return toolchain._adb_forward_probe(adb, port)


# ---------- deploy face ----------

DEFAULT_FRIDA_ALIAS = "sysmon"          # non-default on-device name (#304 F3)
_DEVICE_BIN_DIR = "/data/local/tmp"
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def _frida_alias(alias: str | None) -> str:
    """--alias > KUNGLAO_FRIDA_ALIAS > the default renamed name."""
    import os
    if alias:
        return alias
    env = os.environ.get("KUNGLAO_FRIDA_ALIAS", "").strip()
    return env or DEFAULT_FRIDA_ALIAS


def _adb_run(adb: str, args: list[str], timeout: int = 60) -> int:
    """One adb invocation through the seam; fail-open rc on crash."""
    try:
        r = _subprocess_run([adb, *args], capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8",
                            errors="replace")
        return r.returncode
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError) as exc:
        print(f"deploy-shim: adb {args[:2]} failed: {exc}", file=sys.stderr)
        return 1


def _record(ws: Path | None, item: str, reprobe: str) -> None:
    """installed-ledger write (fail-open bookkeeping — #477 ④ family).
    record_installed raises ValueError (non-string field) or OSError
    (unwritable workspace) — both fail open, same posture as
    toolchain_install._record_installed."""
    if ws is None:
        return
    try:
        env_manifest.record_installed(ws, item, "device-adb", reprobe)
    except (ValueError, OSError) as exc:
        print(f"deploy-shim: WARNING installed-ledger write failed "
              f"({exc})", file=sys.stderr)


def deploy(tool: str, local: Path, port: int | None = None,
           alias: str | None = None, ws: Path | None = None,
           adb: str | None = None) -> int:
    """Idempotent device-side deployment; RC 0 only on a verified port.

    tool: "frida-server" (renamed binary + custom port) or
    "android-server" (default name + the IDA port).
    """
    if tool == "frida-server":
        item, on_device = "frida_server", _frida_alias(alias)
        use_port = port if port is not None else toolchain.FRIDA_PORT
        start_cmd = f"{_DEVICE_BIN_DIR}/{on_device} -l 127.0.0.1:{use_port}"
    elif tool == "android-server":
        item, on_device = "android_server", "android_server"
        use_port = (port if port is not None
                    else toolchain.ANDROID_SERVER_PORT)
        start_cmd = f"{_DEVICE_BIN_DIR}/{on_device}"
    else:
        print(f"deploy-shim: unknown tool {tool!r} (frida-server | "
              f"android-server)", file=sys.stderr)
        return RC_VALIDATION

    adb = adb or _shutil_which("adb")
    if not adb:
        print(f"deploy-shim: adb not found in PATH — fix first: "
              f"{toolchain.fix_text('adb') or 'install platform-tools'}",
              file=sys.stderr)
        return RC_DEPLOY_FAILED

    # Idempotency pre-probe: an already-deployed service is a no-op
    # (issue acceptance: run twice -> identical state). No-op = ZERO
    # device-side mutations; the probe itself still runs `adb forward`
    # on the host (part of probing, not a deployment step).
    ok, detail = _probe_port(adb, use_port)
    if ok:
        print(f"deploy-shim: {tool} already deployed — port {use_port} "
              f"verified ({detail}); no-op (idempotent): zero device-side "
              f"changes, host-side adb forward (probe) still ran")
        _record(ws, item, "PASS")
        return RC_OK

    local = Path(local)
    if not local.is_file():
        print(f"deploy-shim: local binary missing: {local}", file=sys.stderr)
        return RC_DEPLOY_FAILED

    target = f"{_DEVICE_BIN_DIR}/{on_device}"
    print(f"deploy-shim: deploying {tool}: {local} -> {target} "
          f"(port {use_port})")
    if _adb_run(adb, ["push", str(local), target]) != 0:
        print("deploy-shim: adb push failed", file=sys.stderr)
        return RC_DEPLOY_FAILED
    if _adb_run(adb, ["shell", "chmod", "755", target]) != 0:
        print("deploy-shim: adb shell chmod failed", file=sys.stderr)
        return RC_DEPLOY_FAILED
    if _adb_run(adb, ["shell", f"{start_cmd} >/dev/null 2>&1 &"]) != 0:
        print(f"deploy-shim: background start failed ({start_cmd})",
              file=sys.stderr)
        return RC_DEPLOY_FAILED

    # Re-probe gate: PASS is required before success is claimed.
    ok, detail = _probe_port(adb, use_port)
    if not ok:
        print(f"deploy-shim: {tool} deployed but port {use_port} NOT "
              f"verified ({detail}) — fix: "
              f"{toolchain.fix_text(item) or ''}", file=sys.stderr)
        return RC_DEPLOY_FAILED
    print(f"deploy-shim: {tool} deployed and verified on port {use_port}")
    _record(ws, item, "PASS")
    return RC_OK


# ---------- new face: #462 shim records ----------

_SHIMS_DIRNAME = "shims"
_README_TEXT = """# scripts/shims/ — one-off shim records (discard after use)

Every file here is an ANNOTATED ONE-OFF (#462 contract): a shim created
for a single engagement, carrying its target / purpose / expiry in-file.

Rules:
- a shim is DISCARDED after its engagement ends (delete the file; the
  record of it lives in git history if it was ever committed);
- a shim that earns permanence is promoted UPSTREAM via an issue into
  scripts/ (mechanism registration: code + reference + index row), never
  silently renamed/moved;
- create records with `python scripts/deploy_shim.py new --name ...
  --purpose ... --expiry ...` so the annotation shape stays uniform.
"""


def make_shim(name: str, purpose: str, expiry: str,
              target: str | None = None,
              root: Path | None = None) -> int:
    """Materialize scripts/shims/<name>.md with the discard annotation."""
    if not _NAME_RE.match(name or ""):
        print(f"deploy-shim: invalid shim name {name!r} (slug: "
              f"[a-z0-9][a-z0-9._-]*)", file=sys.stderr)
        return RC_VALIDATION
    for label, value in (("purpose", purpose), ("expiry", expiry)):
        if not (isinstance(value, str) and value.strip()):
            print(f"deploy-shim: --{label} is required (one-off shims "
                  f"are annotated)", file=sys.stderr)
            return RC_VALIDATION
    shim_root = root if root is not None else _SCRIPT_DIR / _SHIMS_DIRNAME
    shim_root.mkdir(parents=True, exist_ok=True)
    readme = shim_root / "README.md"
    if not readme.exists():
        readme.write_text(_README_TEXT, encoding="utf-8")
    note = shim_root / f"{name}.md"
    if note.exists():
        print(f"deploy-shim: refusing to overwrite existing shim record "
              f"{note} (annotate a NEW engagement with a new name)",
              file=sys.stderr)
        return RC_VALIDATION
    from datetime import datetime, timezone
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    note.write_text(
        f"# shim: {name} (DISCARD AFTER USE)\n\n"
        f"- target: {target or '(not recorded)'}\n"
        f"- purpose: {purpose}\n"
        f"- expiry: {expiry}\n"
        f"- created: {created}\n"
        f"- contract: one-off deployment shim (#462) — annotated at\n"
        f"  creation, discarded after its engagement; promotion to\n"
        f"  scripts/ requires an upstream issue.\n",
        encoding="utf-8")
    print(f"deploy-shim: wrote {note} (discard semantics in-file + "
          f"{readme.name})")
    return RC_OK


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="deploy-shim",
        description="device-side deployment + one-off shim records",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dep = sub.add_parser("deploy", help="idempotent device-side deploy")
    p_dep.add_argument("--tool", required=True,
                       choices=("frida-server", "android-server"))
    p_dep.add_argument("--local", required=True,
                       help="local binary path to push")
    p_dep.add_argument("--port", type=int, default=None,
                       help="custom port (default: FRIDA_PORT / "
                            "ANDROID_SERVER_PORT)")
    p_dep.add_argument("--alias", default=None,
                       help="renamed on-device name for frida-server "
                            f"(default {DEFAULT_FRIDA_ALIAS})")
    p_dep.add_argument("--workspace", default=None,
                       help="workspace root for the env-facts ledger")

    p_new = sub.add_parser("new", help="annotate a one-off shim")
    p_new.add_argument("--name", required=True)
    p_new.add_argument("--purpose", required=True)
    p_new.add_argument("--expiry", required=True)
    p_new.add_argument("--target", default=None)
    p_new.add_argument("--root", default=None,
                       help="shims dir (default scripts/shims)")

    args = parser.parse_args(argv)
    if args.cmd == "deploy":
        ws = Path(args.workspace).resolve() if args.workspace else None
        return deploy(args.tool, Path(args.local), port=args.port,
                      alias=args.alias, ws=ws)
    root = Path(args.root) if args.root else None
    return make_shim(args.name, args.purpose, args.expiry,
                     target=args.target, root=root)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
