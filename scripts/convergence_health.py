#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convergence_health.py - is the loop actually converging, or just spinning? (v1.9.2)

Reads the ledger that convergence_check.py appends each turn and asks the
question convergence_check CANNOT ask: "are the dispatches actually moving
us toward done, or are we churning?"

convergence_check answers  → "should I dispatch right now?" (instantaneous)
convergence_health answers → "is the sequence of dispatches converging?" (trajectory)

Three verdicts:
  HEALTHY  → open_count trending down, or too few rounds to judge
  STALLED  → open_count flat for 5+ rounds, OR a claim stuck 3+ rounds
  SPINNING → flat 8+ rounds, OR facts grew 5+ while open_count held (churn)

Recovery protocol is printed alongside the verdict — this is NOT a "flag and
walk away" tool. STALLED/SPINNING come with a concrete next action.

Why this exists: v1.9.0-1 made convergence-driven dispatch the default, but
a busy loop can fake convergence (DISPATCH every turn, open_count never drops).
Without a trajectory metric + detector, idle-waiting (the "just wait"
pattern) merely changes shape: busy spin instead of idle wait. The user
asked (verbatim, in Chinese): "怎么保证 kunglao-agent 是在收敛而不是再空转呢?"
("how do you guarantee kunglao-agent is converging rather than spinning?")
— honest answer: you can't guarantee it, but you CAN detect it
and force intervention. This script is the detector.

Usage:
  python scripts/convergence_health.py [workspace]          # human-readable
  python scripts/convergence_health.py [workspace] --json   # machine-readable
Workspace defaults to $PWD/malware-analysis-workspace if it has the ledger, else $PWD.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

LEDGER_NAME = ".convergence_ledger.jsonl"

# Thresholds (conservative — hard claims legitimately take time)
STALLED_FLATLINE = 5      # consecutive unchanged open_count snapshots
STALLED_STUCK_CLAIM = 3   # a claim open this many consecutive snapshots
SPINNING_FLATLINE = 8     # longer flatline = spinning, not just hard
SPINNING_CHURN_FACTS = 5  # facts grew this many while open_count held
SAME_TURN_WINDOW_SEC = 30   # snapshots within this gap = same orchestrator turn
# Pressure valve: never collapse more than this many consecutive same-state
# entries, even if they're all within the time window. Without this, an
# orchestrator calling convergence_check every ~20s for 5+ minutes would
# have every entry dedup'd to 1, hiding a real flatline.
MAX_DEDUP_COLLAPSE = 2

EXIT_HEALTHY = 0
EXIT_STALLED = 1
EXIT_SPINNING = 2
EXIT_NO_DATA = 3


def _resolve_ws(arg) -> Path:
    if arg:
        return Path(arg)
    cwd = Path(os.getcwd())
    sub = cwd / "malware-analysis-workspace"
    return sub if (sub / LEDGER_NAME).exists() else cwd


def _read_ledger(workspace: Path):
    p = workspace / LEDGER_NAME
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _parse_ts(s):
    """Parse an ISO-8601 timestamp; return None if unparseable/missing."""
    if not s:
        return None
    try:
        # handle both "...Z" and "+00:00" suffixes, with or without microseconds
        t = s.replace("Z", "+00:00")
        return datetime.fromisoformat(t)
    except (ValueError, TypeError):
        return None


def _dedup_consecutive(ledger: list) -> list:
    """Collapse snapshots taken within the SAME orchestrator turn.

    A turn = close in time (< SAME_TURN_WINDOW_SEC) AND same open_count + open_ids.
    The agent often calls convergence_check 2-3x per turn while thinking; those
    should count as ONE observation, not three.

    CRITICAL: snapshots minutes apart with identical state are NOT collapsed —
    that is the stalled-loop signal we exist to detect. Without the time gate,
    a flatline at open_count=3 across 10 turns would dedup to 1 entry and hide
    the stall entirely.

    M2 fix (pressure valve): even when entries ARE within the time window,
    never collapse more than MAX_DEDUP_COLLAPSE consecutive same-state entries.
    This prevents the edge case where an orchestrator calling convergence_check
    every ~20s for several minutes has ALL entries collapsed, hiding a real
    flatline that should trigger SPINNING detection.
    """
    if not ledger:
        return []
    out = [ledger[0]]
    out_ts = _parse_ts(ledger[0].get("ts"))
    collapse_run = 0  # consecutive collapses for the current out entry
    for e in ledger[1:]:
        same_state = (
            e.get("open_count") == out[-1].get("open_count")
            and e.get("open_ids") == out[-1].get("open_ids")
        )
        e_ts = _parse_ts(e.get("ts"))
        close_in_time = False
        if out_ts and e_ts:
            close_in_time = abs((e_ts - out_ts).total_seconds()) < SAME_TURN_WINDOW_SEC
        # collapse only if ALL THREE conditions hold:
        #   1. same state
        #   2. close in time (< SAME_TURN_WINDOW_SEC)
        #   3. haven't already collapsed MAX_DEDUP_COLLAPSE for this out entry
        # Missing ts → keep (conservative); pressure valve → keep (preserve flatline)
        if same_state and close_in_time and collapse_run < MAX_DEDUP_COLLAPSE:
            collapse_run += 1
            continue
        out.append(e)
        out_ts = e_ts
        collapse_run = 0
    return out


def _flatline_run(ledger: list) -> int:
    """Consecutive trailing snapshots with unchanged open_count."""
    if len(ledger) < 2:
        return 0
    last = ledger[-1]["open_count"]
    run = 0
    for e in reversed(ledger):
        if e["open_count"] == last:
            run += 1
        else:
            break
    return run


def _stuck_claims(ledger: list) -> list:
    """Claims present in open_ids for >= STALLED_STUCK_CLAIM consecutive trailing snapshots."""
    if len(ledger) < STALLED_STUCK_CLAIM:
        return []
    tail = ledger[-STALLED_STUCK_CLAIM:]
    sets = [set(e.get("open_ids") or []) for e in tail]
    if not all(sets):
        return []
    stuck = set.intersection(*sets)
    result = []
    for cid in sorted(stuck):
        run = 0
        for e in reversed(ledger):
            if cid in (e.get("open_ids") or []):
                run += 1
            else:
                break
        result.append({"claim": cid, "open_for_rounds": run})
    return result


def _churn(ledger: list) -> dict:
    """Did facts grow while open_count held? Returns delta over the flatline window."""
    if len(ledger) < 2:
        return {"facts_delta": 0, "open_delta": 0, "is_churning": False}
    first, last = ledger[0], ledger[-1]
    facts_delta = last.get("facts_total", 0) - first.get("facts_total", 0)
    open_delta = last.get("open_count", 0) - first.get("open_count", 0)
    is_churning = facts_delta >= SPINNING_CHURN_FACTS and open_delta >= 0
    return {"facts_delta": facts_delta, "open_delta": open_delta, "is_churning": is_churning}


def assess(ledger: list) -> dict:
    if not ledger:
        return {"verdict": "NO_DATA", "exit_code": EXIT_NO_DATA,
                "action": "No ledger yet. Run convergence_check.py at least once per turn to build history."}

    ledger = _dedup_consecutive(ledger)
    if len(ledger) < 3:
        return {"verdict": "HEALTHY", "exit_code": EXIT_HEALTHY,
                "action": f"Warming up ({len(ledger)} snapshots). Need 3+ to judge a trend.",
                "rounds": len(ledger)}

    flatline = _flatline_run(ledger)
    stuck = _stuck_claims(ledger)
    churn = _churn(ledger)
    first_open = ledger[0]["open_count"]
    last_open = ledger[-1]["open_count"]
    open_delta = last_open - first_open
    rounds = len(ledger)

    # v1.9.29: a converged loop is NOT spinning. SPINNING/STALLED mean open
    # work is flat — the loop finished (open_count=0) and then sat idle across
    # sessions is a completed state, not a stuck one. Without this guard, a
    # finished loop's trailing CONVERGED snapshots trigger flatline >= 8 and
    # block ALL dispatches (including unrelated research agents).
    if last_open == 0:
        verdict, exit_code = "HEALTHY", EXIT_HEALTHY
    elif flatline >= SPINNING_FLATLINE or churn["is_churning"]:
        verdict, exit_code = "SPINNING", EXIT_SPINNING
    elif flatline >= STALLED_FLATLINE or stuck:
        verdict, exit_code = "STALLED", EXIT_STALLED
    else:
        verdict, exit_code = "HEALTHY", EXIT_HEALTHY

    if verdict == "SPINNING":
        stuck_ids = [s["claim"] for s in stuck] or (ledger[-1].get("open_ids") or [])[:3]
        flat_desc = f"{last_open}→{first_open}" if first_open == last_open else f"{first_open}→{last_open}"
        action = (
            f"STOP dispatching. The loop has flatlined {flatline} rounds with "
            f"{churn['facts_delta']} new facts but open_count {flat_desc}. "
            f"For each stuck claim ({', '.join(stuck_ids) or 'none named'}), pick ONE: "
            f"escalate tier (T1→T2→T3) / reformulate the claim / decompose into smaller / "
            f"DEFER with rationale / escalate to user with a specific question. "
            f"Re-dispatching the same claim >3x without a status change is FORBIDDEN."
        )
    elif verdict == "STALLED":
        stuck_ids = [s["claim"] for s in stuck]
        action = (
            f"Diagnose before dispatching again. Flat {flatline} rounds; "
            f"stuck claims: {stuck_ids or 'none named'}. Re-read each stuck claim's definition + "
            f"gathered facts, then ask: 'what evidence would actually close this?' "
            f"If the tier is exhausted, reformulate or decompose. Do NOT re-dispatch unchanged."
        )
    else:
        action = (
            f"Converging: open_count {first_open}→{last_open} over {rounds} rounds "
            f"(D{open_delta:+d}). Keep dispatching via convergence_check.py."
        )

    return {
        "verdict": verdict,
        "exit_code": exit_code,
        "action": action,
        "rounds": rounds,
        "first_open_count": first_open,
        "last_open_count": last_open,
        "open_delta": open_delta,
        "flatline_run": flatline,
        "stuck_claims": stuck,
        "churn": churn,
        "last_snapshot": ledger[-1],
    }


def _human(r: dict) -> str:
    if r["verdict"] == "NO_DATA":
        return f"=== CONVERGENCE HEALTH: NO_DATA ===\n{r['action']}\n"

    lines = [
        f"=== CONVERGENCE HEALTH: {r['verdict']} ===",
        f"rounds tracked: {r.get('rounds', '?')}",
        f"open_count:    {r.get('first_open_count', '?')} -> {r.get('last_open_count', '?')} (D{r.get('open_delta', 0):+d})",
        f"flatline:      {r.get('flatline_run', 0)} consecutive unchanged",
    ]
    if r.get("stuck_claims"):
        lines.append("stuck claims:")
        for s in r["stuck_claims"]:
            lines.append(f"  {s['claim']:>8}  open {s['open_for_rounds']} rounds")
    ch = r.get("churn") or {}
    if ch.get("facts_delta"):
        lines.append(f"facts grown:   +{ch['facts_delta']} (open D{ch.get('open_delta', 0):+d})")
    lines.append("")
    lines.append(f"action: {r['action']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="kunglao-agent convergence health — is it actually converging?")
    parser.add_argument("workspace", nargs="?", default=None, help="workspace root")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    workspace = _resolve_ws(args.workspace)
    ledger = _read_ledger(workspace)
    if not ledger:
        print(f"FAIL: no {LEDGER_NAME} under {workspace} (run convergence_check.py first)", file=sys.stderr)
        return EXIT_NO_DATA

    r = assess(ledger)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False))
    else:
        print(_human(r))
    return r["exit_code"]


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
