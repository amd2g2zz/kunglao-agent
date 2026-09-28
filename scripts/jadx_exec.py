#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jadx_exec.py — the jadx EXECUTION contract (issue 426).

apk_mem_gate.py (#670) makes the memory-budget DECISION (verdict:
jadx-ok / targeted-jadx / smali-only / refuse, persisted as key ``verdict``
in evidence/apk_mem_gate.json). THIS module is the execution face: it turns
each verdict into a concrete, memory-bounded jadx invocation plan.

Rung ladder (#426):

  rung-1  jadx-ok (budget >= 1.5x est):
      whole-APK ``jadx --no-res`` with a bounded JVM heap (JAVA_OPTS -Xmx)
      and a thread cap (--threads-count).
  rung-2  targeted-jadx (est <= budget < 1.5x est):
      per-DEX spec — extract classes*.dex from the APK via zip entries (NO
      full unpack), byte-scan each dex for relevance markers (class-name
      fragments are plain ASCII in the dex string table — substring match
      is sufficient, no dex parser dependency), then an ISOLATED
      ``jadx --no-res`` run per matched dex: one bad dex never kills the
      batch.
  OOM fallback ladder:
      a rung-1 OOM (non-zero exit OR OutOfMemoryError/OOM in captured
      output) automatically drops to the per-dex rung. The transition is
      RECORDED on both faces (canonical warn() + the summary JSON) —
      silent degradation is forbidden — and rung-1 partial output is
      DISCARDED, never merged with per-dex output.
  smali-only / refuse:
      unchanged — no jadx runs at all (summary status: noop).

Resources are NEVER decompiled: every invocation carries ``--no-res``.

Output contract: unified ``-d OUT`` layout regardless of rung — rung-1
decompiles into OUT itself, per-dex outputs land under OUT/<dex-stem>/ —
so downstream faces see one source tree. The structured summary JSON is
written NEXT TO OUT (OUT.parent / jadx_exec_summary.json); OUT itself
stays a pure source tree. Deterministic ordering: dexes are processed in
sorted entry-name order and the summary is serialized with sort_keys.

Exit codes (tools/static convention): 0 = ok or no-op verdict, 1 = jadx
ran but produced nothing (negative), 2 = usage/input error (structured
error JSON on stderr, never a traceback).

Single chokepoint: this wrapper is THE way jadx runs from the framework
going forward. Call sites that should migrate to it (deliberately NOT
migrated in #426 — scope discipline):
  - scripts/tool_tiers.yaml android-dex-static tier rows (``tools:
    ["jadx"]`` / ``jadx --classes-to-decompile <prefixes>``) — the tier
    table's own header note reserves the execution wrapper for a follow-up
    PR; the tier rows should name this script as the executor.
  - scripts/route_capability.py android:java-source lanes, whose prose
    says "jadx-decompile ... apk_mem_gate 过闸" — the decompile step
    should dispatch through this wrapper so the #670 verdict is consumed
    instead of re-derived.
  - Agent playbooks that shell out raw ``jadx -d ...`` (kunglao-worker
    android lanes) — replace direct invocations with
    ``python scripts/jadx_exec.py <ws> <apk> [--verdict ...]``.

Spec: issue #426 (execution contract) layered on issue #670 (decision
gate, tools/static/apk_mem_gate.py).
"""
from __future__ import annotations

# Canonical warning channel (#419): ONE implementation — rung transitions,
# per-dex failures, discard failures and verdict errors all trace here
# (silent degradation forbidden). The ledger face is pinned to the
# workspace via set_warn_workspace (kunglao_log public API).
from kunglao_log import set_warn_workspace, warn

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

from harness_common import utc_now_z as _utc_now  # #863 Family F: single source

# ---- named constants (no magic numbers) ------------------------------------
SCHEMA = "jadx_exec/1"
FLAG_NO_RES = "--no-res"            # resources are NEVER decompiled (#426 rule 1)
FLAG_THREADS = "--threads-count"    # jadx processing thread cap
FLAG_OUT = "-d"                     # unified output layout flag
DEFAULT_JADX_BIN = "jadx"
DEFAULT_HEAP_GB = 4                 # JVM -Xmx bound (GB) absent an operator value
DEFAULT_THREADS = 4
DEFAULT_TIMEOUT_SECS = 3600         # mirrors tool_tiers android-dex-static full cap
ENV_JAVA_OPTS = "JAVA_OPTS"         # the jadx launcher's standard JVM-opts channel
SUMMARY_NAME = "jadx_exec_summary.json"   # the record surface, NEXT TO OUT
DEX_WORKDIR_NAME = "jadx_exec_dex"        # extracted dexes live beside OUT, never inside
DEFAULT_OUT_SUBPATH = ("out", "jadx-src")
GATE_EVIDENCE_RELPATH = ("evidence", "apk_mem_gate.json")  # the #670 decision file
VERDICTS = ("jadx-ok", "targeted-jadx", "smali-only", "refuse")  # #670 vocabulary
NO_JADX_VERDICTS = ("smali-only", "refuse")
OOM_MARKERS = ("OutOfMemoryError", "GC overhead limit exceeded")
# bare "OOM" matches only at word boundaries: a substring match would flag
# benign class paths like com/zoom/... ("zoom" contains "oom") and discard a
# healthy rung-1 pass (reviewer F1 probe).
_OOM_WORD_RE = re.compile(r"(?<![a-z0-9_])oom(?![a-z0-9_])")
OUTPUT_SNIPPET_MAX = 2000           # bounded stdout/stderr tails kept in the summary
WARN_SNIPPET_MAX = 200              # bounded stderr excerpt inside warn() reasons
RC_OK, RC_NEGATIVE, RC_ERROR = 0, 1, 2


def _structured_error(msg: str) -> None:
    """Canonical warn (ledger face) FIRST, then the structured error JSON as
    the terminal stderr line (tools/static convention: the last stderr line
    is the machine-readable payload). Failure is recorded, never silent."""
    warn("jadx_exec_error", msg)
    print(json.dumps({"error": msg, "exit_code": RC_ERROR},
                     ensure_ascii=False), file=sys.stderr)


def _resolve_verdict(workspace: Path, explicit: str | None) -> tuple[str, str]:
    """(verdict, source): --verdict wins; else the #670 gate evidence file
    (key ``verdict``); else ("", reason) — the caller turns that into a
    structured usage error, never a guessed verdict."""
    if explicit:
        return explicit.strip(), "cli --verdict"
    path = workspace.joinpath(*GATE_EVIDENCE_RELPATH)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        verdict = str(data.get("verdict") or "")
    except (OSError, ValueError):
        verdict = ""
    if verdict:
        return verdict, "evidence/apk_mem_gate.json"
    return "", f"--verdict absent and {path} missing/unreadable"


def _dex_stem(entry_name: str) -> str:
    """Zip entry name -> the per-dex output dir name under OUT (the dex
    file's stem; entries are flattened, so a hostile zip cannot escape)."""
    name = Path(entry_name).name
    return name[:-4] if name.lower().endswith(".dex") else name


def _extract_dexes(apk_path: Path, dest: Path) -> list[tuple[str, Path]]:
    """Extract *.dex ZIP entries ONLY (no full unpack, #426 rule 3a).
    Deterministic: sorted by entry name. Entry names are flattened via
    Path(name).name so a path-traversal entry name cannot escape dest."""
    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[tuple[str, Path]] = []
    with zipfile.ZipFile(apk_path, "r") as zf:
        for info in zf.infolist():
            if not info.filename.lower().endswith(".dex"):
                continue
            target = dest / Path(info.filename).name
            target.write_bytes(zf.read(info))
            extracted.append((info.filename, target))
    return sorted(extracted, key=lambda item: item[0])


def _match_markers(data: bytes, markers: tuple[str, ...]) -> list[str]:
    """Markers whose case-insensitive bytes occur in the dex. Class-name
    fragments live as plain ASCII in the dex string table — substring
    match is the contract (#426 rule 3b, no dex parser dependency)."""
    lowered = data.lower()
    return [m for m in markers if m.lower().encode("utf-8", "ignore") in lowered]


def _has_oom(text: str) -> list[str]:
    """Which OOM markers appear in captured output (#426 rule 4: non-zero
    exit OR the OOM string in output both count; bare "OOM" is
    word-boundary anchored — see _OOM_WORD_RE)."""
    lowered = (text or "").lower()
    hits = [m for m in OOM_MARKERS if m.lower() in lowered]
    if _OOM_WORD_RE.search(lowered):
        hits.append("OOM")
    return hits


def _snip(text: str) -> str:
    return (text or "")[-OUTPUT_SNIPPET_MAX:]


def _run_jadx(jadx_bin: str, input_path: Path, out_dir: Path, *, threads: int,
              heap_gb: int, timeout_secs: int) -> dict[str, Any]:
    """One isolated jadx invocation. ``--no-res`` and the thread cap are
    NON-OPTIONAL argv; the heap bound rides JAVA_OPTS (the jadx launcher's
    standard channel), overriding any inherited value — the bound IS the
    contract, operator overrides go through --heap-gb, not the env."""
    out_dir.mkdir(parents=True, exist_ok=True)
    argv = [str(jadx_bin), FLAG_NO_RES, FLAG_THREADS, str(int(threads)),
            FLAG_OUT, str(out_dir), str(input_path)]
    env = dict(os.environ)
    env[ENV_JAVA_OPTS] = f"-Xmx{int(heap_gb)}g"
    try:
        cp = subprocess.run(argv, capture_output=True, encoding="utf-8",
                            errors="replace", timeout=timeout_secs, env=env)
    except subprocess.TimeoutExpired as exc:
        return {"argv": argv, "exit": None, "stdout": _snip(str(exc.stdout or "")),
                "stderr": _snip(f"timeout after {timeout_secs}s"),
                "oom": [], "timed_out": True}
    except OSError as exc:
        return {"argv": argv, "exit": None, "stdout": "",
                "stderr": _snip(f"{type(exc).__name__}: {exc}"),
                "oom": [], "timed_out": False}
    oom = _has_oom((cp.stdout or "") + (cp.stderr or ""))
    return {"argv": argv, "exit": cp.returncode, "stdout": _snip(cp.stdout or ""),
            "stderr": _snip(cp.stderr or ""), "oom": oom, "timed_out": False}


def _discard(path: Path) -> bool:
    """rm -rf a failed run's partial output (never merged downstream).
    Returns False — and warns — when removal failed; never silent."""
    if not path.exists():
        return True
    try:
        shutil.rmtree(path)
        return True
    except OSError as exc:
        warn("jadx_exec_discard", f"{path}: {type(exc).__name__}: {exc}")
        return False


def _run_status(res: dict[str, Any]) -> str:
    """ok | oom | failed for one jadx invocation result. OOM wins over the
    exit code (exit 0 + OOM text is still an OOM, #426 rule 4)."""
    if res["oom"]:
        return "oom"
    if res["timed_out"] or res["exit"] != 0:
        return "failed"
    return "ok"


def _run_rung1(target: Path, out_root: Path, *, jadx_bin: str, heap_gb: int,
               threads: int, timeout_secs: int) -> tuple[dict[str, Any], dict[str, Any]]:
    """Rung-1: whole-APK jadx into OUT itself. Returns (summary entry, raw result)."""
    res = _run_jadx(jadx_bin, target, out_root, threads=threads,
                    heap_gb=heap_gb, timeout_secs=timeout_secs)
    entry = {"kind": "whole-apk", "rung": 1, "input": str(target),
             "output_dir": str(out_root), "exit": res["exit"],
             "status": _run_status(res), "oom_markers": res["oom"],
             "discarded": False, "stderr_tail": res["stderr"]}
    return entry, res


def _run_dex_batch(apk_path: Path, dex_dir: Path, out_root: Path,
                   markers: tuple[str, ...], *, jadx_bin: str, heap_gb: int,
                   threads: int, timeout_secs: int) -> dict[str, Any]:
    """Isolated per-dex jadx runs over ALL extracted dexes in sorted entry
    order (relevance markers narrow the selection when provided; no markers
    = every dex individually). One bad dex never kills the batch: failures
    are recorded (warn + dex_plans) and the failed run's partial output is
    discarded with the failure documented in the plan entry."""
    extracted = _extract_dexes(apk_path, dex_dir)
    plans: list[dict[str, Any]] = []
    matched: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    produced = False
    for entry_name, dex_path in extracted:
        hits = _match_markers(dex_path.read_bytes(), markers) if markers else []
        plan: dict[str, Any] = {"dex": entry_name, "matched_markers": hits,
                                "output_dir": str(out_root / _dex_stem(entry_name))}
        if markers and not hits:
            plan["status"], plan["exit"] = "skipped", None
            skipped.append(entry_name)
        else:
            matched.append(entry_name)
            res = _run_jadx(jadx_bin, dex_path, out_root / _dex_stem(entry_name),
                            threads=threads, heap_gb=heap_gb,
                            timeout_secs=timeout_secs)
            status = _run_status(res)
            plan["status"], plan["exit"] = status, res["exit"]
            if status == "ok":
                produced = True
            else:
                failed.append(entry_name)
                warn("jadx_exec_dex_failed",
                     f"{entry_name}: exit={res['exit']} oom={res['oom'] or 'none'} "
                     f"stderr={res['stderr'][-WARN_SNIPPET_MAX:]!r}")
                plan["discarded"] = _discard(out_root / _dex_stem(entry_name))
        plans.append(plan)
    return {"plans": plans, "matched": matched, "skipped": skipped,
            "failed": failed, "produced": produced}


def _execute(target: Path, out_root: Path, verdict: str,
             markers: tuple[str, ...], *, jadx_bin: str, heap_gb: int,
             threads: int, timeout_secs: int) -> dict[str, Any]:
    """The rung ladder (#426). Returns the summary fragments (rungs,
    rung_fallback, dex_plans, matched/skipped/failed, produced)."""
    rungs: list[dict[str, Any]] = []
    fallback: dict[str, Any] | None = None
    batch: dict[str, Any] = {"plans": [], "matched": [], "skipped": [],
                             "failed": [], "produced": False}
    kw = dict(jadx_bin=jadx_bin, heap_gb=heap_gb, threads=threads,
              timeout_secs=timeout_secs)
    dex_dir = out_root.parent / DEX_WORKDIR_NAME
    if verdict == "jadx-ok":
        entry, res = _run_rung1(target, out_root, **kw)
        rungs.append(entry)
        if entry["status"] == "ok":
            return {"rungs": rungs, "rung_fallback": None, "dex_plans": [],
                    "matched_dexes": [], "skipped_dexes": [],
                    "per_dex_failures": [], "produced": True}
        if entry["status"] == "oom":
            # OOM fallback ladder: recorded on both faces, never silent; the
            # rung-1 partial output is discarded, never merged with per-dex
            # output (#426 rule 4).
            entry["discarded"] = _discard(out_root)
            warn("jadx_exec_rung_fallback",
                 f"whole-APK jadx OOM (exit={res['exit']}, "
                 f"oom={res['oom'] or 'string-only'}); dropping to the per-dex "
                 f"rung; rung-1 partial output discarded")
            fallback = {"from": "whole-apk", "to": "per-dex", "reason": "oom",
                        "rung1_exit": res["exit"], "oom_markers": res["oom"]}
            batch = _run_dex_batch(target, dex_dir, out_root, (), **kw)
            rungs.append({"kind": "per-dex", "rung": 2,
                          "trigger": "oom-fallback",
                          "dex_count": len(batch["matched"]),
                          "output_root": str(out_root)})
    elif verdict == "targeted-jadx":
        batch = _run_dex_batch(target, dex_dir, out_root, tuple(markers), **kw)
        rungs.append({"kind": "per-dex", "rung": 2,
                      "trigger": "targeted-jadx verdict",
                      "dex_count": len(batch["matched"]),
                      "output_root": str(out_root)})
    # smali-only / refuse never reach here (handled as noop in run()).
    return {"rungs": rungs, "rung_fallback": fallback,
            "dex_plans": batch["plans"], "matched_dexes": batch["matched"],
            "skipped_dexes": batch["skipped"],
            "per_dex_failures": batch["failed"], "produced": batch["produced"]}


def _write_summary(out_root: Path, summary: dict[str, Any]) -> Path:
    """The record surface: NEXT TO OUT (OUT itself stays a pure source
    tree). sort_keys -> stable key order; indented for operator audit."""
    out_root.parent.mkdir(parents=True, exist_ok=True)
    path = out_root.parent / SUMMARY_NAME
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return path


def _noop_summary(summary: dict[str, Any], verdict: str) -> dict[str, Any]:
    """smali-only / refuse face: no jadx runs (#426 rule 5) — recorded, not
    silent."""
    summary.update({
        "status": "noop",
        "reason": (f"verdict {verdict}: no jadx runs "
                   "(#426: smali-only/refuse unchanged)"),
        "rungs": [], "rung_fallback": None, "dex_plans": [],
        "matched_dexes": [], "skipped_dexes": [], "per_dex_failures": [],
    })
    return summary


def _validate(target_path: Path, verdict: str, jadx_bin: str,
              heap_gb: int, threads: int, timeout_secs: int) -> str:
    """System-boundary validation; returns "" when usable, else the error."""
    if not verdict:
        return "jadx_exec: unresolvable verdict"
    if verdict not in VERDICTS:
        return (f"jadx_exec: unknown verdict {verdict!r} "
                f"(#670 vocabulary: {', '.join(VERDICTS)})")
    if heap_gb < 1 or threads < 1 or timeout_secs < 1:
        return (f"jadx_exec: --heap-gb/--threads/--timeout-secs must be >= 1 "
                f"(got {heap_gb}/{threads}/{timeout_secs})")
    if not target_path.is_file():
        return f"jadx_exec: target not found: {target_path}"
    if verdict not in NO_JADX_VERDICTS and shutil.which(jadx_bin) is None:
        return f"jadx_exec: jadx binary not found: {jadx_bin!r} (not on PATH)"
    return ""


def _base_summary(target_path: Path, resolved: str, source: str, markers,
                  binary: str, heap_gb: int, threads: int, timeout_secs: int,
                  out_root: Path) -> dict[str, Any]:
    """The stable summary scaffold every status face starts from."""
    return {
        "schema": SCHEMA, "executed_at": _utc_now(),
        "target": str(target_path), "verdict": resolved,
        "verdict_source": source, "markers": list(markers),
        "jadx_bin": binary, "heap_opts": f"-Xmx{int(heap_gb)}g",
        "threads": int(threads), "timeout_secs": int(timeout_secs),
        "output_root": str(out_root),
    }


def run(workspace: Path | str, target: str | Path, *, verdict: str | None = None,
        markers: tuple[str, ...] | list[str] = (), jadx_bin: str | None = None,
        out: Path | str | None = None, heap_gb: int = DEFAULT_HEAP_GB,
        threads: int = DEFAULT_THREADS,
        timeout_secs: int = DEFAULT_TIMEOUT_SECS) -> int:
    """Top-level entry: resolve the verdict -> execute the rung plan ->
    write the summary NEXT TO OUT. 0 ok/no-op, 1 ran-but-nothing-produced,
    2 input error (structured stderr + canonical warn)."""
    workspace = Path(workspace)
    set_warn_workspace(workspace)  # pin the canonical-warn ledger face HERE
    target_path = Path(target)
    binary = jadx_bin or DEFAULT_JADX_BIN
    resolved, source = _resolve_verdict(workspace, verdict)
    out_root = Path(out) if out else workspace.joinpath(*DEFAULT_OUT_SUBPATH)
    summary = _base_summary(target_path, resolved, source, markers, binary,
                            heap_gb, threads, timeout_secs, out_root)
    error = _validate(target_path, resolved, binary, heap_gb, threads,
                      timeout_secs)
    if error:
        _structured_error(error)
        return RC_ERROR
    if resolved in NO_JADX_VERDICTS:
        _write_summary(out_root, _noop_summary(summary, resolved))
        return RC_OK
    try:
        result = _execute(target_path, out_root, resolved, tuple(markers),
                          jadx_bin=binary, heap_gb=heap_gb, threads=threads,
                          timeout_secs=timeout_secs)
    except (zipfile.BadZipFile, OSError) as exc:
        reason = f"jadx_exec: cannot process {target_path}: " \
                 f"{type(exc).__name__}: {exc}"
        summary.update({"status": "error", "reason": reason, "rungs": [],
                        "rung_fallback": None, "dex_plans": [],
                        "matched_dexes": [], "skipped_dexes": [],
                        "per_dex_failures": []})
        _write_summary(out_root, summary)
        _structured_error(reason)
        return RC_ERROR
    summary.update(result)
    summary.pop("produced", None)
    produced = bool(result["produced"])
    summary["status"] = "ok" if produced else "empty"
    summary["reason"] = "" if produced else (
        "jadx ran but produced no output (all runs failed or no dex matched)")
    _write_summary(out_root, summary)
    return RC_OK if produced else RC_NEGATIVE


def _split_markers(raw: str | None) -> tuple[str, ...]:
    """Comma-separated --markers -> tuple (empty parts dropped)."""
    if not raw:
        return ()
    return tuple(m.strip() for m in raw.split(",") if m.strip())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="jadx_exec.py",
        description="jadx execution contract (#426): the memory-bounded rung "
                    "ladder consuming the #670 apk_mem_gate verdict.")
    parser.add_argument("workspace", type=Path,
                        help="workspace root (reads evidence/apk_mem_gate.json "
                             "for the verdict)")
    parser.add_argument("target", help="APK path")
    parser.add_argument("--verdict", default=None,
                        help="override the verdict (jadx-ok | targeted-jadx | "
                             "smali-only | refuse); default: the #670 gate "
                             "evidence file")
    parser.add_argument("--markers", default=None,
                        help="comma-separated relevance markers (class-name "
                             "fragments / distinctive strings); targeted-jadx only")
    parser.add_argument("--jadx-bin", default=DEFAULT_JADX_BIN,
                        help=f"jadx binary (default: {DEFAULT_JADX_BIN})")
    parser.add_argument("--out", type=Path, default=None,
                        help="output root (default: "
                             f"<workspace>/{'/'.join(DEFAULT_OUT_SUBPATH)})")
    parser.add_argument("--heap-gb", type=int, default=DEFAULT_HEAP_GB,
                        help=f"JVM -Xmx bound in GB (default: {DEFAULT_HEAP_GB})")
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS,
                        help=f"jadx {FLAG_THREADS} (default: {DEFAULT_THREADS})")
    parser.add_argument("--timeout-secs", type=int, default=DEFAULT_TIMEOUT_SECS,
                        help="per-invocation timeout "
                             f"(default: {DEFAULT_TIMEOUT_SECS})")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI face: parse args, execute the plan, return the process exit code."""
    args = _parse_args(argv)
    return run(args.workspace, args.target, verdict=args.verdict,
               markers=_split_markers(args.markers), jadx_bin=args.jadx_bin,
               out=str(args.out) if args.out else None,
               heap_gb=args.heap_gb, threads=args.threads,
               timeout_secs=args.timeout_secs)


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
