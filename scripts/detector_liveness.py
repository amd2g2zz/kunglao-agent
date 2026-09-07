#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""detector_liveness.py — #127 detector utilization evidence: eval/fire
counters read back from the unified log, DORMANT flag (the #600 sentinel
generalized).

Mechanism existence is not mechanism effectiveness (#127). #600 proved the
pattern once, by hand: a gate whose arming field is absent evaluates every
dispatch and fires NEVER — a wired detector that cannot fire is worse than
none (false confidence). This module makes that property QUERYABLE for
every detector that emits the #127 telemetry pair:

  detector_eval   one evaluation pass (detail JSON carries `detector` name)
  detector_fired  the detector flagged the pathology it exists for

liveness_report(ws) reduces the unified log (kunglao_log._all_rows, the
same tolerant read backtrack_loop uses) to per-detector counters:

  {"ts": <iso>, "log_rows": <n scanned>,
   "detectors": {"<name>": {"evaluations": n, "fires": m,
                            "status": "DORMANT" | "ACTIVE"}},
   "dormant": [<names>]}

  DORMANT = evaluations > 0 and fires == 0   (runs, never fires — the
                                             mission_stall blindness class)
  ACTIVE  = fires > 0                        (has fired; liveness evidenced)
Detectors with no rows at all are absent — absence is NO_DATA, not
DORMANT (a detector that never ran says nothing about utilization).

dormant_warn(ws) is the heartbeat_tick face: ONE-TIME WARN when any
detector is DORMANT (the #600 DORMANT_SENTINEL shape — stderr nag line +
sentinel file, so the operator sees it once and fixes the detector, not
every tick). Fail-open everywhere: liveness is evidence, never a gate.

CLI: python detector_liveness.py <workspace> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness_common import utc_now_z as utc_now  # #863 Family F single source
from kunglao_log import _all_rows  # same tolerant read backtrack_loop uses

# One-time WARN sentinel (the #600 DORMANT_SENTINEL generalized): present
# in runs/ = the WARN already fired for this workspace.
DORMANT_SENTINEL = Path("runs") / ".detector-liveness-sentinel"

DETECTOR_EVAL = "detector_eval"
DETECTOR_FIRED = "detector_fired"


def liveness_report(ws) -> dict:
    """Per-detector eval/fire counters + DORMANT/ACTIVE status, read back
    from the unified log. DORMANT = evaluated, never fired."""
    ws = Path(ws)
    rows = _all_rows(ws)
    counters: dict[str, dict[str, int]] = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("action") not in (
                DETECTOR_EVAL, DETECTOR_FIRED):
            continue
        name = None
        try:
            d = json.loads(str(r.get("detail") or "{}"))
            if isinstance(d, dict):
                name = str(d.get("detector") or "").strip() or None
        except ValueError:
            name = None
        if not name:
            continue  # unparseable detail — never guess a detector name
        c = counters.setdefault(name, {"evaluations": 0, "fires": 0})
        if r.get("action") == DETECTOR_EVAL:
            c["evaluations"] += 1
        else:
            c["fires"] += 1
    detectors: dict[str, dict] = {}
    for name, c in counters.items():
        status = "ACTIVE" if c["fires"] > 0 else "DORMANT"
        detectors[name] = {**c, "status": status}
    dormant = sorted(n for n, c in detectors.items()
                     if c["status"] == "DORMANT")
    return {"ts": utc_now(), "log_rows": len(rows),
            "detectors": detectors, "dormant": dormant}


def dormant_warn(ws) -> list[str]:
    """ONE-TIME WARN for DORMANT detectors (#600 sentinel shape).

    Prints the nag line + writes runs/.detector-liveness-sentinel on first
    observation; quiet afterwards (the operator fixes the detector, the
    tick does not re-nag). Returns the dormant list ([] = nothing to say /
    already nagged). Fail-open by contract: any error degrades to no WARN.
    """
    ws = Path(ws)
    report = liveness_report(ws)
    dormant = report["dormant"]
    if not dormant:
        return []
    sentinel = ws / DORMANT_SENTINEL
    if sentinel.exists():
        return []
    detail = ", ".join(
        f"{n} ({report['detectors'][n]['evaluations']} evals, 0 fires)"
        for n in dormant)
    print(f"[detector] DORMANT: {detail} — evaluated but never fired; a "
          f"wired detector that cannot fire is false confidence. Check "
          f"its injection trip-tests / thresholds (#127)", flush=True)
    try:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text(
            datetime.now(tz=timezone.utc).isoformat(timespec="seconds")
            .replace("+00:00", "Z")
            + " #127 detector-liveness DORMANT WARN emitted once\n",
            encoding="utf-8")
    except OSError as exc:
        print(f"detector_liveness: sentinel write failed ({exc!r})",
              file=sys.stderr, flush=True)
    return dormant


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="detector_liveness.py",
        description="#127 detector utilization — eval/fire counters + "
                    "DORMANT flag from the unified log")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true", help="machine-readable")
    args = ap.parse_args()
    report = liveness_report(args.workspace)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        if not report["detectors"]:
            print("detector-liveness: no detector_eval rows yet (NO_DATA)")
            return 0
        print(f"=== DETECTOR LIVENESS ({report['log_rows']} log rows) ===")
        for name, c in sorted(report["detectors"].items()):
            print(f"  {name:<24} eval={c['evaluations']:<6} "
                  f"fires={c['fires']:<6} {c['status']}")
        if report["dormant"]:
            print(f"DORMANT: {', '.join(report['dormant'])}")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
