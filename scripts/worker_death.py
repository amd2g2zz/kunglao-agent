#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worker_death.py — #11 death event + artifact snapshot: the resume signal.

Pain point (issue #11): a worker that dies mid-claim (API disconnect, crash)
leaves the claim half-done and the loop WITHOUT a structured signal — the
orchestrator had to manually diff the worker's scratch output to figure out
what was produced, then decide how to resume. backtrack_gate (#38) owns
slow/HUNG workers (their status files may still move); this module owns the
GONE case: silence beyond liveness_policy.DEAD_WORKER_MINUTES (2x
STUCK_MINUTES) = no more writes, ever.

This module COMPOSES with the existing stuck machinery instead of running a
parallel detector: detection is the additive ``dead`` flag that
hooks/lib_kunglao.scan_active_workers already puts on stuck entries (#595
scan, #444 canonical protocol), and consumption happens inside
convergence_check._act_stuck_workers (STUCK_WORKERS_PRESENT → BLOCKED), the
same action that writes runs/.stuck-report.md and reopens stuck claims
(#607).

Per dead worker (claim IN_PROGRESS only — a terminal claim is debris, not a
half-done claim) one JSON record is written at

    runs/.worker-death-<worker-stem>.json          (dot-file machine-report
    convention: .stuck-report.md / .env-check.json / .heartbeat.json)

containing: claim id, worker id, last activity ts, the resolved dispatch
anchor, and the SNAPSHOT of files the worker produced (已完成产物清单) —
every product-path file whose mtime falls inside (dispatch_anchor,
detection]. The record is the resume contract: the claim flips back to OPEN
(#607 reopen, death-aware history line) and the orchestrator dispatches a
RESUME claim referencing the artifact list — continue-from, NOT redo-from-
zero (guidance lives in .stuck-report.md, the decide summary, and
heartbeat_loop_prompt.py).

Anchor resolution (window start, best-effort chain — flagged, never silent):
  1. runs/dispatch-context-<claim>.json dispatch_ts   (dispatch_context.py)
  2. claim dispatched_at                              (claim-register.yaml)
  3. claim created_at
  4. none of the above → "approximate": the worker's own final silence
     window (last_activity - DEAD_WORKER_MINUTES) — over-approximates the
     window rather than losing products; the record says so.

Idempotent: the per-worker filename IS the dedup key — an existing record is
never rewritten (two scans, one death event).

CLI:
  python worker_death.py <workspace>                  # scan: report dead workers
  python worker_death.py <workspace> --write          # write death records

Pure stdlib + the repo's own single sources (_hooks_path / liveness_policy /
harness_common). Fail-open posture mirrors _act_stuck_workers: OSError
propagates to the caller's try/except — a read-only filesystem must not
break the convergence verdict.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from _hooks_path import load_hooks_lib  # #863 Family B: loader delegation
from liveness_policy import DEAD_WORKER_MINUTES  # noqa: F401 (re-export)
from harness_common import utc_now

RECORD_NAME = ".worker-death-{stem}.json"
RECORD_SCHEMA = 1

# Worker-product dirs scanned for the artifact snapshot (the issue's
# 已完成产物清单). runs/ is included (plan-<task>.md is the FIRST artifact a
# dispatched worker writes — #239) but its machine surface is excluded below.
# Orchestrator/init-owned top-level files (claim-register.yaml, task_spec.yaml,
# task-oracle.yaml) sit OUTSIDE these dirs and are never scanned.
PRODUCT_DIRS = ("facts", "evidence", "notes", "hypotheses", "runs")


def _parse_ts(value) -> datetime | None:
    """Best-effort ISO parse (Z-form and +00:00 form; datetime passthrough —
    YAML 1.1 resolves unquoted ISO scalars, claim_expiry precedent)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)
            # Z-form strptime is naive — anchor everything to UTC so window
            # comparisons never mix naive and aware datetimes.
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _claim_key(claim_id: str) -> str:
    """dispatch_context._claim_key convention: C-001 -> C001."""
    return str(claim_id).replace("-", "")


def _norm(value: str) -> str:
    """#607 shape-insensitive compare: C400 ≡ C-400 (stems drop the hyphen)."""
    return value.replace("-", "").replace("_", "").lower()


# Public alias — convergence_check._reopen_stuck_claims reuses the SAME
# normalization for its #11 dead-prefix map (one shape-insensitive compare,
# two consumers).
norm_key = _norm


def stem_prefix(stem: str) -> str:
    """Worker stem -> claim-ish prefix (#607 convention, shared semantics):
    strip the ``worker-status-`` role marker and ONE trailing retry/version
    token (C-400v2 -> C-400) — never the id's own digits."""
    stem = stem.removeprefix("worker-status-")
    m = re.search(r"^(.*?)[vV]\d+$", stem) or re.search(r"^(.*)-\d+$", stem)
    return m.group(1) if m and m.group(1) else stem


def claim_for_stem(claims: list[dict], stem: str) -> dict | None:
    """Map a worker-status stem to its claim (same matching as
    convergence_check._reopen_stuck_claims)."""
    prefix = stem_prefix(stem)
    for c in claims:
        cid = c.get("id")
        if not cid:
            continue
        n_cid, n_pfx = _norm(str(cid)), _norm(prefix)
        if n_cid == n_pfx or n_cid.startswith(n_pfx) or n_pfx.startswith(n_cid):
            return c
    return None


def dispatch_anchor(ws: Path, root: Path, claim: dict) -> tuple[datetime | None, str]:
    """(window_start, anchor_kind) — the best-effort chain from the module
    docstring. Reads the dispatch-context JSON (the orchestrator writes it
    into the MAIN workspace's runs/; a worktree worker's own workspace root
    is checked as a fallback), then the claim's own timestamps."""
    nid = _claim_key(claim.get("id", ""))
    for candidate_root in dict.fromkeys((ws, root)):  # dedupe, keep order
        p = candidate_root / "runs" / f"dispatch-context-{nid}.json"
        try:
            if p.exists():
                ts = _parse_ts(json.loads(p.read_text(encoding="utf-8")).get("dispatch_ts"))
                if ts is not None:
                    return ts, "dispatch_context"
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    for field, kind in (("dispatched_at", "claim_dispatched_at"),
                        ("created_at", "claim_created_at")):
        ts = _parse_ts(claim.get(field))
        if ts is not None:
            return ts, kind
    return None, "approximate"


def collect_artifacts(root: Path, start: datetime | None, end: datetime) -> list[dict]:
    """已完成产物清单: product-path files with start < mtime <= end, sorted by
    mtime. Exclusions are the machine/state surface, never products: .git,
    runs/ worker-status protocol files, runs/ dot-file machine reports,
    runs/logs/, orchestrator-owned top-level files."""
    out: list[dict] = []
    for d in PRODUCT_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            parts = p.relative_to(root).parts
            if ".git" in parts:
                continue
            if d == "runs":
                name = p.name
                if name.startswith(".") or name.startswith("worker-status-"):
                    continue
                if "logs" in parts[:-1]:  # runs/logs/** are machine logs
                    continue
            try:
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if start is not None and mtime <= start:
                continue
            if mtime > end:
                continue
            out.append({"path": rel, "mtime_ts": mtime.strftime("%Y-%m-%dT%H:%M:%SZ")})
    out.sort(key=lambda a: a["mtime_ts"])
    return out


def collect_death_records(workspace: Path, stuck: list[dict]) -> list[dict]:
    """Build (not write) death records for the DEAD entries of a stuck list.

    Guards: only entries with dead=True; the mapped claim must exist and be
    IN_PROGRESS (a terminal claim is debris, not a half-done claim — nothing
    to resume). Worker last-activity/root come from the canonical
    iter_worker_states pass (#444).
    """
    ws = Path(workspace)
    dead = [w for w in (stuck or []) if w.get("dead")]
    if not dead:
        return []
    reg_path = ws / "claim-register.yaml"
    claims: list[dict] = []
    if reg_path.exists():
        try:
            claims = (yaml.safe_load(reg_path.read_text(encoding="utf-8"))
                      or {}).get("claims") or []
        except yaml.YAMLError:
            claims = []
    states = {s["file"].stem: s for s in load_hooks_lib().iter_worker_states(ws)}
    now = utc_now()
    records: list[dict] = []
    for w in dead:
        stem = w["worker"]
        claim = claim_for_stem(claims, stem)
        if not claim or str(claim.get("status") or "").upper() != "IN_PROGRESS":
            continue  # nothing resumable — no death event (#11 guards)
        s = states.get(stem)
        last_activity = s["mtime"] if s else now - timedelta(minutes=w["age_min"])
        root = s["root"] if s else ws
        start, anchor_kind = dispatch_anchor(ws, root, claim)
        if start is None:
            # flagged approximation: the worker's own final silence window —
            # over-approximate rather than lose products, and SAY so.
            start = last_activity - timedelta(minutes=DEAD_WORKER_MINUTES)
        records.append({
            "schema": RECORD_SCHEMA,
            "type": "worker_death",
            "worker": stem,
            "claim_id": claim.get("id"),
            "detected_ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "last_activity_ts": last_activity.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "age_min": w["age_min"],
            "threshold_min": DEAD_WORKER_MINUTES,
            "dispatch_ts": (start.strftime("%Y-%m-%dT%H:%M:%SZ")
                            if anchor_kind != "approximate" else None),
            "dispatch_anchor": anchor_kind,
            "artifacts": collect_artifacts(root, start, now),
            "resume": {
                "claim_status_written": "OPEN",
                "instruction": (
                    "Dispatch a RESUME claim referencing this record's "
                    "artifacts list: verify and absorb the existing products "
                    "first, continue from where the worker died — do NOT "
                    "redo from zero."),
            },
        })
    return records


def record_path(ws: Path, stem: str) -> Path:
    return Path(ws) / "runs" / RECORD_NAME.format(stem=stem)


def write_death_records(workspace: Path, stuck: list[dict],
                        force: bool = False) -> list[Path]:
    """Write one death record per resumable dead worker. Idempotent by file
    existence (force=True re-collects for tests/refresh). Returns the paths
    actually written."""
    ws = Path(workspace)
    written: list[Path] = []
    for rec in collect_death_records(ws, stuck):
        p = record_path(ws, str(rec["worker"]))
        if p.exists() and not force:
            continue  # #11 idempotency: two scans, one death event
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        written.append(p)
    return written


def scan(workspace: Path) -> int:
    """Read-only diagnostics: report dead workers without writing."""
    ws = Path(workspace)
    lib = load_hooks_lib()
    states = lib.iter_worker_states(ws)
    _active, stuck = lib.scan_active_workers(ws, states)
    dead = [w for w in stuck if w.get("dead")]
    if not dead:
        print("OK: no dead workers")
        return 0
    reg_path = ws / "claim-register.yaml"
    claims = ((yaml.safe_load(reg_path.read_text(encoding="utf-8"))
               or {}).get("claims") or []) if reg_path.exists() else []
    print(f"DEAD: {len(dead)} worker(s) silent > {DEAD_WORKER_MINUTES}m:")
    for w in dead:
        claim = claim_for_stem(claims, w["worker"])
        status = (claim or {}).get("status", "?")
        resumable = str(status).upper() == "IN_PROGRESS"
        print(f"  - {w['worker']} (age {w['age_min']}m, claim "
              f"{(claim or {}).get('id', '?')} {status}"
              f"{', resumable' if resumable else ', not resumable'})")
    print(f"Records land at runs/{RECORD_NAME.format(stem='<worker>')}")
    return 1


def main(argv: list[str] | None = None) -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {Path(sys.argv[0]).name} <workspace> [--write]",
              file=sys.stderr)
        return 2
    ws = Path(sys.argv[1])
    if "--write" in sys.argv[2:]:
        paths = write_death_records(ws, [
            w for w in load_hooks_lib().scan_active_workers(ws)[1]
            if w.get("dead")])
        for p in paths:
            print(f"wrote {p}")
        return 0
    return scan(ws)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
