#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""intake_battery.py — #460 intake probe battery (the instrument face).

Owner ruling: a 2-3 probe battery at intake is a legitimate INSTRUMENT,
not a behavior rule — it reads the environment ONCE before the first
claim dispatch so die/apkid features exist from run #1 (feeding the
feature-conditioned prior and the mined feature table instead of
waiting for learned ordering). Instruments degrade, they never gate:

  - die-probe    — CLI face (tools/static/die_probe.py --binary … --out
                   evidence/die.json). Subprocess isolation on purpose:
                   importing that module inserts tools/static into
                   sys.path (the #863 shadow risk). The CLI's own
                   three-state exit IS the semantics: 0 produced,
                   1 negative finding (evidence still written), 2
                   operational error (no file).
  - apkid-prescan — library face (apkid_scanner.run): the documented
                   never-raise entry; its fail-open contract always
                   writes evidence/apkid.json (status ok/unavailable/
                   error — unavailable/error count as absent).

Applicability lives in the probes' own contracts, not here: both run
over the workspace's analysis target (the aligned bins/ sample, or the
staged workspace entry on the e2e face) and self-classify anything
they cannot identify.

Outputs land exactly where the probe contracts expect (evidence/die.json,
evidence/apkid.json) plus the battery ledger evidence/intake-battery.json
(schema intake-battery/1) — one fact row per probe (ran / outcome /
evidence / detail), the #813 "never skip silently" discipline applied to
the instrument. No sample (non-malware lanes) → explicit absent rows.

NOT behind KUNGLAO_PREDICT_BEFORE_TRY: the flag gates prior-informed
SELECTION (a behavior); this is evidence PRODUCTION. Battery-fed data
is the prerequisite for the EX-5 re-evaluation that could flip it.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import apkid_scanner  # the apkid library face (scripts/ sibling)
from _hooks_path import load_module_by_path  # noqa: E402  (#863 authority)
from harness_common import utc_now_z as _utc_now  # single time source
from kunglao_log import warn  # canonical warn (dedupe + ledger face)

# #863 Family J: the ONE evidence writer (tools/static/common.py), reached
# through the #891 by-path loader authority — same idiom as apkid_scanner.
_COMMON = load_module_by_path(
    "tools_static_common",
    Path(__file__).resolve().parent.parent / "tools" / "static" / "common.py")
write_evidence = _COMMON.write_evidence

SCHEMA = "intake-battery/1"
LEDGER_NAME = "intake-battery.json"
DIE_PROBE_CLI = (Path(__file__).resolve().parent.parent / "tools"
                 / "static" / "die_probe.py")

# Intake budget: the die CLI default (120 s × 5 calls) is an agent-run
# budget; intake must stay snappy, so the battery caps per-call time and
# carries a subprocess backstop for the whole 5-call sweep. Operators
# re-running the CLI face adjust with --die-timeout.
DIE_TIMEOUT_S = 30
DIE_SPAWN_TIMEOUT_S = DIE_TIMEOUT_S * len(
    ("j", "e", "b", "hash", "resource")) + 30

PROBES = ("die-probe", "apkid-prescan")


def _row(probe: str, ran: bool, outcome: str, evidence: str | None,
         detail: str) -> dict:
    """One ledger fact row (enumerated vocabulary)."""
    return {"probe": probe, "ran": ran, "outcome": outcome,
            "evidence": evidence, "detail": detail}


def _tail(text: str, limit: int = 200) -> str:
    return " ".join((text or "").split())[:limit]


def _resolve_sample(ws: Path, target: str | None) -> tuple[Path | None,
                                                           str]:
    """The probe subject: ``target`` resolved against the workspace (a
    staged entry like ``target/beacon.apk`` or a ``bins/`` reference);
    a bare bins/ file name also resolves. Returns (path-or-None, note).

    An unreadable/missing reference degrades to None (an instrument
    records why, it does not refuse)."""
    if not target:
        return None, ""
    cand = Path(target)
    if not cand.is_absolute():
        cand = ws / cand
    if cand.is_file():
        return cand, ""
    bare = ws / "bins" / target
    if bare.is_file():
        return bare, ""
    return None, f"sample reference not found: {target}"


def _run_die(ws: Path, sample: Path) -> dict:
    """die-probe via its CLI (isolated; three-state exit semantics)."""
    out = ws / "evidence" / "die.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(DIE_PROBE_CLI), "--binary", str(sample),
            "--out", str(out), "--timeout", str(DIE_TIMEOUT_S)]
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=DIE_SPAWN_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        return _row("die-probe", True, "absent", None,
                    f"probe timed out after {exc.timeout}s")
    except OSError as exc:
        return _row("die-probe", True, "absent", None,
                    f"probe invocation failed: {exc}")
    if proc.returncode == 2:
        return _row("die-probe", True, "absent", None,
                    f"probe operational error (exit 2): "
                    f"{_tail(proc.stderr)}")
    if out.is_file():
        detail = ("probe ran (exit 0)" if proc.returncode == 0
                  else f"negative finding (exit 1): {_tail(proc.stderr)}")
        return _row("die-probe", True, "produced", "evidence/die.json",
                    detail)
    return _row("die-probe", True, "absent", None,
                f"probe exit {proc.returncode} wrote no report: "
                f"{_tail(proc.stderr)}")


def _run_apkid(ws: Path, sample: Path) -> dict:
    """apkid-prescan via the library face (never raises; fail-open
    contract always writes evidence/apkid.json)."""
    try:
        rc = apkid_scanner.run(ws, str(sample))
    except Exception as exc:  # noqa: BLE001 — instrument, never raises
        return _row("apkid-prescan", True, "absent", None,
                    f"probe invocation failed: {type(exc).__name__}: {exc}")
    path = ws / "evidence" / "apkid.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        status = str(doc.get("status") or "")
    except (OSError, ValueError):
        return _row("apkid-prescan", True, "absent", None,
                    f"probe exit {rc} left no readable report")
    if status == "ok":
        return _row("apkid-prescan", True, "produced", "evidence/apkid.json",
                    f"probe ran (status ok, exit {rc})")
    return _row("apkid-prescan", True, "absent", "evidence/apkid.json",
                f"probe status {status or 'missing'}: "
                f"{_tail(str(doc.get('reason') or ''))}")


def run_battery(ws, target: str | None, lane: str | None = None) -> dict:
    """Run the battery once; write the ledger; return the report.

    NEVER raises — every probe failure (and every internal defect)
    degrades to an absent fact row. This is the init-facing entry."""
    ws = Path(ws)
    sample, note = _resolve_sample(ws, target)
    rows: list[dict] = []
    if sample is None:
        why = note or f"no aligned sample (lane={lane or 'unknown'})"
        rows = [_row(probe, False, "absent", None, why) for probe in PROBES]
    else:
        for runner in (_run_die, _run_apkid):
            try:
                rows.append(runner(ws, sample))
            except Exception as exc:  # noqa: BLE001 — degrade, never gate
                rows.append(_row(
                    "die-probe" if runner is _run_die else "apkid-prescan",
                    True, "absent", None,
                    f"battery defect: {type(exc).__name__}: {exc}"))
    try:
        rel = str(sample.relative_to(ws)) if sample is not None else None
    except ValueError:
        rel = str(sample)
    report = {"schema": SCHEMA, "generated_at": _utc_now(),
              "sample": rel, "lane": lane, "probes": rows}
    try:
        write_evidence(ws, LEDGER_NAME, report)
    except OSError as exc:
        warn("intake_battery", f"ledger write failed: {exc}")
    return report


def _cli_default_target(ws: Path) -> str | None:
    """The unique bins/ file when unambiguous, else None (explicit)."""
    bins = ws / "bins"
    try:
        files = sorted(p for p in bins.iterdir() if p.is_file())
    except OSError:
        return None
    if len(files) == 1:
        return f"bins/{files[0].name}"
    return None


def main(argv: list[str] | None = None) -> int:
    """CLI face: run the battery on a workspace (re-run after installing
    a probe tool). The instrument never fails the invocation."""
    global DIE_TIMEOUT_S  # --die-timeout override (operators, one-offs)
    ap = argparse.ArgumentParser(
        prog="intake_battery.py",
        description="#460 intake probe battery — die-probe + apkid-prescan "
                    "over the workspace analysis target (instrument: "
                    "failures record absence, never block)")
    ap.add_argument("workspace", type=Path, help="workspace root")
    ap.add_argument("target", nargs="?", default=None,
                    help="sample reference relative to the workspace "
                         "(default: the unique bins/ file, else none)")
    ap.add_argument("--die-timeout", type=int, default=None, metavar="N",
                    help=f"die per-call timeout seconds "
                         f"(default {DIE_TIMEOUT_S})")
    args = ap.parse_args(argv)
    if args.die_timeout is not None:
        DIE_TIMEOUT_S = max(1, args.die_timeout)
    target = args.target or _cli_default_target(args.workspace)
    lane = None
    try:
        import yaml  # noqa: PLC0415 — lazy (flavor only)

        spec = yaml.safe_load(
            (args.workspace / "task_spec.yaml").read_text(encoding="utf-8"))
        lane = str(spec.get("lane")) if isinstance(spec, dict) else None
    except (OSError, ValueError, yaml.YAMLError):
        lane = None
    report = run_battery(args.workspace, target, lane)
    summary = ", ".join(f"{r['probe']}={r['outcome']}" for r in
                        report["probes"])
    print(f"intake-battery: {summary} "
          f"(ledger: evidence/{LEDGER_NAME})")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
