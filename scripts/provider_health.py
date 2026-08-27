#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""provider_health.py — fail-open runtime provider-failure memory (#692 WP4).

Online learning, NO config edit: a tool failure at worker runtime is
recorded into <ws>/provider_health.json and consumed by route_capability's
selection pass next round (design D3/D4). Failures expire after a window
(default 24h) — memory, not punishment.

Fail-open on every layer (missing/corrupt file = no memory, never raises).

CLI:
  python scripts/provider_health.py record <ws> --provider jadx \
      --outcome fail --reason "timeout"
  python scripts/provider_health.py query <ws> [--json]

Spec: openspec/changes/issue-692-capability-registry (design D4).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DEFAULT_WINDOW_HOURS = 24


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}  # corrupt/missing = no memory (fail-open)


def record(ws: Path | str, provider: str, outcome: str, reason: str = "",
           ts: str | None = None) -> Path:
    """Append one outcome entry for `provider`. Returns the file path.

    A corrupt existing file is replaced (not merged) — fail-open forward.
    """
    ws = Path(ws)
    path = ws / "provider_health.json"
    data = _load(path)
    entries = data.get(provider)
    entries = entries if isinstance(entries, list) else []
    entries.append({"outcome": outcome, "reason": reason,
                    "ts": ts or _utc_now()})
    data[provider] = entries
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def recent_failures(ws: Path | str,
                    window_hours: int = DEFAULT_WINDOW_HOURS) -> dict:
    """Providers with a FAIL entry newer than the window.

    Returns {provider: {"reason", "ts"}} (latest failure). Fail-open:
    missing/corrupt file -> {}.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    out: dict = {}
    for provider, entries in _load(Path(ws) / "provider_health.json").items():
        latest = None
        for e in entries if isinstance(entries, list) else []:
            if not isinstance(e, dict) or e.get("outcome") != "fail":
                continue
            when = _parse_ts(e.get("ts", ""))
            if when and when >= cutoff:
                if latest is None or when > latest[1]:
                    latest = ({"reason": e.get("reason", ""),
                               "ts": e.get("ts", "")}, when)
        if latest:
            out[provider] = latest[0]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="provider-health runtime failure memory (WP4)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="append an outcome entry")
    rec.add_argument("workspace", type=Path)
    rec.add_argument("--provider", required=True)
    rec.add_argument("--outcome", choices=["ok", "fail"], required=True)
    rec.add_argument("--reason", default="")
    qry = sub.add_parser("query", help="print recent failures")
    qry.add_argument("workspace", type=Path)
    qry.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    qry.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "record":
        path = record(args.workspace, args.provider, args.outcome,
                      args.reason)
        print(f"recorded: {args.provider} {args.outcome} -> {path}")
        return 0
    failures = recent_failures(args.workspace, args.window_hours)
    if args.json:
        print(json.dumps(failures, ensure_ascii=False, indent=2))
    else:
        for provider, info in sorted(failures.items()):
            print(f"FAIL(recent): {provider} {info['ts']} {info['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
