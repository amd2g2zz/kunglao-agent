#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cadence_advisor.py - #635: adaptive heartbeat registration advisor.

The loop registration is NOT fixed at 5m (owner directive 2026-10-10):
the interval is a state function, evaluated EVERY 3 tick passes, moving
within [5, 25] minutes (step 5) by environment observation:

  busy   - an active worker, a watchdog that FIRED (a missed event), or a
           recent RL signal -> step DOWN toward the floor (observe faster)
  quiet  - none of the above -> step UP toward the ceiling (stop paying
           idle ticks)
  mixed  -> hold

The advisor is a registry mechanism (channel: tick, gate: always): each
pass increments ``ticks_since_eval``; at 3 (or --force-eval) it evaluates
and resets. It writes runs/.cadence-advice.json carrying the
recommendation, the reason, the cycle counter and a state_hash over the
observed inputs - the orchestrator reads it at each firing and
re-registers (CronDelete + CronCreate + loop_scheduler upsert) when
``evaluation_due`` or the armed registration's state_hash drifts (the
real-time edge; see heartbeat_loop_prompt's Registration-duty block).

RL coupling (#637): the advisor consumes the RL signal bus (a recent
runs/signals.jsonl row counts as activity) and EMITS one kind=cadence
signal row per evaluation - the scheduling decision itself is learning
data. The coupling is wired; it learns nothing until #634's feed lands
credits - the signal row is written regardless (honest timeline).

Usage: cadence_advisor.py <workspace> [--json] [--force-eval]
Exit codes: 0 ok / 2 usage / 3 not a workspace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _hooks_path import load_hooks_lib  # #444: the ONE worker-status parser

FLOOR_MIN = 5
CEIL_MIN = 25
STEP_MIN = 5
EVAL_EVERY_TICKS = 3
RECENT_SIGNAL_MIN = 30  # a signal row younger than this = activity
ADVICE_REL = Path("runs") / ".cadence-advice.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(p: Path) -> dict | list | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def current_interval_min(ws: Path) -> int:
    """The armed interval: heartbeat state wins, else the policy default."""
    hb = _read_json(ws / "runs" / ".heartbeat.json") or {}
    try:
        val = int(hb.get("interval_min") or 0)
    except (TypeError, ValueError, AttributeError):
        val = 0
    if val > 0:
        return val
    from liveness_policy import TICK_INTERVAL_DEFAULT_MIN
    return int(TICK_INTERVAL_DEFAULT_MIN)


def active_workers(ws: Path) -> list[str]:
    """Fresh in-progress worker ids — the canonical #444 parser (last
    ``status:`` token wins; never a hand-rolled scan)."""
    lib = load_hooks_lib()
    out: list[str] = []
    for f in sorted((ws / "runs").glob("worker-status-*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if lib.parse_worker_status(text) == "in-progress":
            out.append(f.stem.replace("worker-status-", ""))
    return out


def recent_signal(ws: Path, *, now: datetime | None = None) -> bool:
    """A machine signal row younger than RECENT_SIGNAL_MIN (RL activity)."""
    now = now or _now()
    try:
        lines = (ws / "runs" / "signals.jsonl").read_text(
            encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return False
    for ln in lines[-3:]:
        try:
            row = json.loads(ln)
            if str(row.get("kind") or "") == "cadence":
                continue  # our own emission is not external activity
            ts = datetime.strptime(
                str(row.get("ts")), "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
        if (now - ts).total_seconds() <= RECENT_SIGNAL_MIN * 60:
            return True
    return False


def read_advice(ws: Path) -> dict:
    """The persisted advice (the read-only seam the brief composer uses —
    never advances the cycle counter)."""
    doc = _read_json(Path(ws) / ADVICE_REL)
    return doc if isinstance(doc, dict) else {}


def holds(ws: Path) -> list[str]:
    doc = _read_json(ws / "runs" / ".loop-holds.json") or []
    if not isinstance(doc, list):
        return []
    return [str(e.get("text")) for e in doc
            if isinstance(e, dict) and e.get("text")]


def watchdog_state(ws: Path) -> dict:
    """The latest persisted tick report's watchdog verdict (one-pass lag by
    construction - the report file is written at the END of a tick pass)."""
    rep = _read_json(ws / "runs" / ".heartbeat-tick.json") or {}
    wd = rep.get("watchdog") if isinstance(rep, dict) else None
    wd = wd if isinstance(wd, dict) else {}
    return {"fired": bool(wd.get("fired")),
            "reasons": [str(r) for r in (wd.get("reasons") or [])]}


def state_hash(ws: Path) -> str:
    """Deterministic hash over the brief-relevant state - the registration
    staleness signal, shared with heartbeat_loop_prompt's situation brief."""
    parts = [f"interval={current_interval_min(ws)}",
             "workers=" + ",".join(active_workers(ws)),
             "holds=" + "|".join(holds(ws))]
    wd = watchdog_state(ws)
    parts.append("watchdog=" + str(wd["fired"]) + ":" + ";".join(wd["reasons"]))
    try:
        import yaml

        from status_defs import TERMINAL
        doc = yaml.safe_load(
            (ws / "claim-register.yaml").read_text(encoding="utf-8"))
        rows = [f"{c.get('id')}:{c.get('status')}"
                for c in (doc or {}).get("claims") or []
                if isinstance(c, dict)]
        parts.append("claims=" + ",".join(sorted(rows)))
        parts.append("terminal=" + str(sum(
            1 for r in rows if r.split(":", 1)[-1].upper() in TERMINAL)))
    except Exception:  # noqa: BLE001 - hash degrades, never blocks
        pass
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _emit_signal(ws: Path, out: dict) -> None:
    """#637: the scheduling decision is learning data (kind=cadence)."""
    try:
        p = ws / "runs" / "signals.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(
                {"ts": out["ts"], "kind": "cadence",
                 "interval": out["recommended_interval_min"],
                 "current": out["current_interval_min"],
                 "reason_class": out["reason"].split(":", 1)[0]},
                ensure_ascii=False) + "\n")
    except OSError as exc:
        from kunglao_log import warn
        warn("cadence_advisor_signal", f"{type(exc).__name__}: {exc}")


def advise(ws: Path, *, force_eval: bool = False,
           now: datetime | None = None) -> dict:
    """One advisor pass: tick the cycle counter, evaluate when due, persist
    the advice. Raises nothing for read troubles (all reads are tolerant)."""
    now = now or _now()
    cur = current_interval_min(ws)
    prior = _read_json(ws / ADVICE_REL)
    prior = prior if isinstance(prior, dict) else {}
    try:
        ticks = int(prior.get("ticks_since_eval") or 0) + 1
    except (TypeError, ValueError):
        ticks = 1
    workers = active_workers(ws)
    wd = watchdog_state(ws)
    sign = recent_signal(ws, now=now)
    busy = bool(workers) or wd["fired"] or sign
    quiet = not workers and not wd["fired"] and not sign
    due = force_eval or ticks >= EVAL_EVERY_TICKS
    try:
        rec = int(prior.get("recommended_interval_min") or cur)
    except (TypeError, ValueError):
        rec = cur
    if due:
        if busy:
            rec = max(FLOOR_MIN, cur - STEP_MIN)
            reason = ("busy: worker(s) " + ",".join(workers) if workers else
                      ("busy: watchdog " + ";".join(wd["reasons"])
                       if wd["fired"] else "busy: recent RL signal"))
        elif quiet:
            rec = min(CEIL_MIN, cur + STEP_MIN)
            reason = "quiet: no workers, no missed events, no recent signal"
        else:
            rec = cur
            reason = "mixed: hold"
        ticks = 0
    else:
        reason = f"hold: evaluation in {EVAL_EVERY_TICKS - ticks} tick(s)"
    out = {"ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "current_interval_min": cur,
           "recommended_interval_min": rec,
           "reason": reason,
           "ticks_since_eval": ticks,
           "evaluation_due": rec != cur,
           "state_hash": state_hash(ws),
           "sources": {"workers": workers, "watchdog": wd,
                       "recent_signal": sign, "holds": holds(ws)}}
    try:
        p = ws / ADVICE_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                     encoding="utf-8")
    except OSError as exc:
        from kunglao_log import warn
        warn("cadence_advisor_write", f"{type(exc).__name__}: {exc}")
    if due and rec != cur:
        _emit_signal(ws, out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="#635 adaptive cadence advisor")
    ap.add_argument("workspace")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force-eval", action="store_true",
                    help="evaluate now regardless of the 3-tick cycle")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").is_file():
        print(f"cadence_advisor: not a kunglao workspace: {ws}",
              file=sys.stderr)
        return 3
    out = advise(ws, force_eval=args.force_eval)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"cadence: current={out['current_interval_min']}m "
              f"advice={out['recommended_interval_min']}m "
              f"due={out['evaluation_due']} ({out['reason']})")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)

    force_utf8()
    sys.exit(main())
