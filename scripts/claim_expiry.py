# -*- coding: utf-8 -*-
"""claim_expiry.py - mark long-untouched OPEN claims as STALE (priority demotion).

User pain point (verbatim, in Chinese): "状态管理很差 - 一些任务以及过期了"
("poor state management — some tasks have already expired")

When an OPEN claim hasn't had any activity (no status file update, no
dispatch, no fact written) for > N hours, it's "stale" — the worker may
have given up, or the claim may have been forgotten. STALE is a new
intermediate status (between OPEN and DEFERRED) that:
  - Demotes the claim in priority.py (3x weight penalty)
  - Logs a B1n "claim-stale" warning
  - Does NOT force DEFERRED (preserves user's ability to revive)

This script:
  1. Reads claim-register.yaml
  2. For each claim with status=OPEN, computes time-since-last-activity
  3. "Last activity" = max of:
     - claim's `last_activity_at` field (if set)
     - claim's `dispatched_at` field
     - claim's `created_at` field
  4. If now - last_activity > threshold, mark STALE
  5. Outputs summary: "N stale claims; recommend redispatch or DEFERRED"

Usage:
  python claim_expiry.py <workspace> [--stale-hours 24] [--apply]
"""
from __future__ import annotations
import gate_telemetry as _gt

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from status_defs import ACTIVE_STATUSES


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _load_yaml(p):
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _write_yaml(p, data):
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def last_activity_for(claim: dict) -> datetime | None:
    candidates = []
    for field in ("last_activity_at", "dispatched_at", "created_at", "updated_at"):
        v = claim.get(field)
        if v:
            try:
                if isinstance(v, datetime):
                    # YAML 1.1 resolves unquoted ISO scalars to datetime
                    # objects (#380); normalize tz-naive ones to UTC so they
                    # can participate in age math instead of being skipped.
                    candidates.append(v if v.tzinfo else v.replace(tzinfo=timezone.utc))
                else:
                    candidates.append(parse_iso(v))
            except (ValueError, TypeError):
                continue
    return max(candidates) if candidates else None


@_gt.telemetry('claim_expiry')
def check(workspace: Path, stale_hours: int, apply: bool = False) -> int:
    reg_path = workspace / "claim-register.yaml"
    reg = _load_yaml(reg_path)
    claims = (reg or {}).get("claims", []) or []
    now = utc_now()
    threshold = stale_hours * 3600
    stale = []
    fresh = []

    for c in claims:
        status = (c.get("status") or "").upper()
        if status not in ACTIVE_STATUSES:
            continue
        cid = c.get("id")
        last = last_activity_for(c)
        if last is None:
            fresh.append({"claim_id": cid, "age_hours": 0, "last": "unknown"})
            continue
        age_seconds = (now - last).total_seconds()
        age_hours = age_seconds / 3600
        if age_seconds > threshold:
            stale.append({"claim_id": cid, "age_hours": age_hours, "last": last.isoformat()})
        else:
            fresh.append({"claim_id": cid, "age_hours": age_hours, "last": last.isoformat()})

    if apply and stale:
        for s in stale:
            for c in claims:
                if c.get("id") == s["claim_id"]:
                    c["status"] = "STALE"
                    c["stale_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
                    c["stale_reason"] = f"no activity for {s['age_hours']:.1f}h"
                    break
        _write_yaml(reg_path, reg)
        print(f"APPLIED: marked {len(stale)} claim(s) as STALE")

    print(f"  {len(claims)} total claim(s); {len(fresh)} fresh; {len(stale)} stale (>{stale_hours}h)")
    if stale:
        print(f"STALE claims (recommend redispatch or DEFERRED):")
        for s in stale:
            print(f"  - {s['claim_id']}: {s['age_hours']:.1f}h since last activity (was {s['last']})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark long-untouched OPEN claims as STALE")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--stale-hours", type=int, default=24,
                        help="hours without activity before marking STALE (default 24)")
    parser.add_argument("--apply", action="store_true", help="actually write STALE status to claim-register.yaml")
    args = parser.parse_args()
    return check(Path(args.workspace), stale_hours=args.stale_hours, apply=args.apply)


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())