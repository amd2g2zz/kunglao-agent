#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""slot_monitor.py - #636: subagent slot monitor (the decision table).

The watchdog's stuck-worker face narrated ONE condition (silence); the
slot question needs the full picture (owner directive 2026-10-10): per
active worker, {age, silence, progress delta} -> a mechanical verdict in
{keep | ping | terminate_review | gone}, plus the slot ledger
(cap / active / free) so adding or pausing workers is a visible decision.

Policy (constants from liveness_policy, never hand-rolled):
  silence >= DEAD_WORKER_MINUTES   -> "gone" (worker_death.py owns the
                                      record + resume signal; this face
                                      only reports it)
  silence >= STUCK_MINUTES         -> "ping" (the smart-ping protocol)
  age >= 3800s AND progress frozen -> "terminate_review" (owner trigger,
    ruling 2026-10-10: > 3800s runtime with no new "] step:" lines since
    the previous report; the orchestrator decides TaskStop)
  else                             -> "keep"

Frozen detection is report-to-report (progress_lines compared against the
previous runs/.slot-report.json); the first report establishes the
baseline and never flags. Wrong-direction calls stay orchestrator
judgment - surfaced by the status tail in the report, never guessed
mechanically. Zero active workers -> a quiet report.

The monitor RECOMMENDS; it never kills (constitutional isolation - the
orchestrator executes SendMessage/TaskStop). Each non-keep verdict also
lands an RL signal row (kind=slot; #637 coupling).

Usage: slot_monitor.py <workspace> [--json]
Exit codes: 0 ok / 2 usage / 3 not a workspace.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from _hooks_path import load_hooks_lib  # #444: the ONE worker-status parser

REPORT_REL = Path("runs") / ".slot-report.json"
# Owner ruling 2026-10-10 (raised from 1800): the long-run review trigger.
# A subagent may legitimately run 30-60 min on a deep task; the review fires
# only past 3800s AND frozen progress.
OWNER_AGE_S = 3800
_TS_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})Z?\]")
_CLAIM_RE = re.compile(r"C(\d+)")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _worker_cap() -> int | None:
    """The 3-slot contract's single-source read (mirror kept by workguard)."""
    try:
        import convergence_check as cc  # noqa: PLC0415 - lazy, one read

        return int(cc.WORKER_CAP)
    except Exception:  # noqa: BLE001 - degraded read, second source
        try:
            import workguard as wg  # noqa: PLC0415

            return int(wg.WORKER_CAP)
        except Exception:  # noqa: BLE001 - no source: report cap=null
            return None


def _age_s(text: str, mtime: float, now: datetime) -> float:
    m = _TS_RE.search(text)
    if m:
        try:
            t = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M").replace(
                tzinfo=timezone.utc)
            return max(0.0, (now - t).total_seconds())
        except ValueError as exc:
            from kunglao_log import warn
            warn("slot_age_parse", f"{type(exc).__name__}: {exc}")
    return max(0.0, now.timestamp() - mtime)


def scan(ws: Path, *, now: datetime | None = None) -> dict:
    """One monitor pass: verdict per active worker + the slot ledger."""
    import liveness_policy as lp
    lib = load_hooks_lib()
    now = now or _now()
    prior = _read_json(ws / REPORT_REL) or {}
    prior_progress = {w.get("worker"): w.get("progress_lines")
                      for w in prior.get("workers") or []
                      if isinstance(w, dict)}
    workers: list[dict] = []
    for f in sorted((ws / "runs").glob("worker-status-*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            mtime = f.stat().st_mtime
        except OSError:
            continue
        last = next((ln.strip() for ln in reversed(text.splitlines())
                     if ln.strip()), "")
        if lib.parse_worker_status(text) != "in-progress":
            continue  # waiting/done files are not active slots (#444 parser)
        wid = f.stem.replace("worker-status-", "")
        age_s = _age_s(text, mtime, now)
        silence_s = max(0.0, now.timestamp() - mtime)
        progress = sum(1 for ln in text.splitlines() if "] step:" in ln)
        frozen = wid in prior_progress and prior_progress.get(wid) == progress
        if silence_s >= lp.DEAD_WORKER_MINUTES * 60:
            verdict = "gone"
        elif silence_s >= lp.STUCK_MINUTES * 60:
            verdict = "ping"
        elif age_s >= OWNER_AGE_S and frozen:
            verdict = "terminate_review"
        else:
            verdict = "keep"
        cm = _CLAIM_RE.search(f.name)
        workers.append({"worker": wid,
                        "claim": f"C-{cm.group(1)}" if cm else None,
                        "age_s": int(age_s), "silence_s": int(silence_s),
                        "progress_lines": progress, "frozen": frozen,
                        "verdict": verdict, "status_tail": last[:160]})
    cap = _worker_cap()
    return {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "cap": cap, "active": len(workers),
            "free": None if cap is None else max(0, cap - len(workers)),
            "workers": workers}


def _emit_signals(ws: Path, out: dict) -> None:
    """#637: non-keep verdicts are learning data (kind=slot)."""
    rows = [{"ts": out["ts"], "kind": "slot", "worker": w["worker"],
             "verdict": w["verdict"], "age_s": w["age_s"],
             "silence_s": w["silence_s"]}
            for w in out["workers"] if w["verdict"] != "keep"]
    if not rows:
        return
    try:
        p = ws / "runs" / "signals.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as exc:
        from kunglao_log import warn
        warn("slot_monitor_signal", f"{type(exc).__name__}: {exc}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="#636 subagent slot monitor")
    ap.add_argument("workspace")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").is_file():
        print(f"slot_monitor: not a kunglao workspace: {ws}",
              file=sys.stderr)
        return 3
    out = scan(ws)
    try:
        p = ws / REPORT_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    except OSError as exc:
        from kunglao_log import warn
        warn("slot_monitor_write", f"{type(exc).__name__}: {exc}")
    _emit_signals(ws, out)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        verdicts = ", ".join(f"{w['worker']}={w['verdict']}"
                             for w in out["workers"]) or "no active workers"
        print(f"slot: active={out['active']} free={out['free']} [{verdicts}]")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    sys.exit(main())
