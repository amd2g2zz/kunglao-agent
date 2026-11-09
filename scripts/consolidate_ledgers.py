#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""consolidate_ledgers.py — the one-time #721 ledger migration + liveness CLI.

Issue #721 consolidates the 12+ JSONL ledgers into 4 by lifecycle
(runs/experience.jsonl, runs/settlement.jsonl, runs/telemetry.jsonl —
and knowledge-store.jsonl under the guarded cross-task root). This CLI
is the ONE-TIME migration face plus the per-schema liveness readout:

    python scripts/consolidate_ledgers.py <ws>              # migrate (report)
    python scripts/consolidate_ledgers.py <ws> --dry-run    # report only
    python scripts/consolidate_ledgers.py <ws> --liveness   # per-schema counts
    python scripts/consolidate_ledgers.py <ws> --families experience

Migration APPENDS (never rewrites): every source row is appended into
the family's consolidated file (values preserved; a missing stamp added
only where a single schema is registered), then the source file is
MOVED to <ws>/runs/archive/ — bytes intact, never deleted. Idempotent:
re-running appends nothing already copied. Since the issue-1004 R3
schema cutover every family's writers live on the consolidated files,
so all four families migrate by default (``--families`` narrows); the
migration SOURCE LIST below is this CLI's own registry (the in-core
compat registry was deleted by R3) and is what the R4 retire slice
consumes to verify + delete the legacy rels.

Exit: 0 ok; 2 bad args; 3 a rel ended partial/copied-unarchived
(append refusal or archive conflict — nothing was rewritten or deleted;
fix and re-run).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rlvr import consolidated_ledger as cl  # noqa: E402

#: family -> {legacy rel: the schema stamps rows in that rel may carry}.
#: THE migration source list (issue-1004 R3 moved it here from the
#: consolidated core — the R4 retire slice consumes the same registry).
#: Knowledge rels resolve under the guarded root EXCEPT the ws-scoped
#: ``runs/`` rels (the historical ws-local posterior series and the
#: mined feature table — see rlvr.consolidated_ledger.legacy_path).
LEGACY_SOURCES: dict[str, dict[str, tuple[str, ...]]] = {
    "experience": {
        "runs/transitions.jsonl": ("transition/1",),
        "runs/q-cell-log.jsonl": ("q-cell-obs/1",),
        "runs/step-ledger.jsonl": ("step-record/1", "step-record/2"),
        "runs/evidence-credit.jsonl": ("evidence-item/1",
                                       "credit-amendment/1"),
    },
    "settlement": {
        "runs/rollout-ledger.jsonl": ("rollout-ledger/1",),
        "runs/attributed-waste.jsonl": ("attributed-waste/1",),
        # historical rows are UNSTAMPED {"ts","amount","source"}; the
        # registration gives the migration its one-schema stamp
        "cost_events.jsonl": ("cost-event/1",),
    },
    "telemetry": {
        "runs/interventions.jsonl": ("intervention/1",),
        "runs/predictions.jsonl": ("prediction-ledger/1",),
        "runs/situation-stream.jsonl": ("situation/1",),
        # historical rows are UNSTAMPED event=dispatch rows; the
        # registration gives the migration its one-schema stamp
        # (issue-1004 R2b: the writer moved to the family, new rows
        # carry the stamp at write)
        "runs/strategy-log.jsonl": ("strategy-log/1",),
    },
    "knowledge": {
        "posterior-store.jsonl": ("posterior-store/1",),
        "marl-negative.jsonl": ("marl-negative/1",),
        "runs/feature-table.jsonl": ("feature-table/1",),
        # issue-1004 R2c: the ws-local credit/DTS series' pre-move
        # file — the writer moved to the family file
        "runs/posterior-store.jsonl": ("posterior-store/1",),
    },
}


def _print_migration(report: dict) -> int:
    """The per-rel report lines; returns the refused-rel count."""
    refused = 0
    for family, fam in report.items():
        for rel, entry in fam.items():
            print(f"[{family}] {rel}: {entry['status']} "
                  f"(rows={entry['rows']} appended={entry['appended']})")
            if entry.get("archived"):
                print(f"[{family}] {rel}: archived -> {entry['archived']}")
            if entry["status"] in ("partial", "copied-unarchived"):
                refused += 1
    return refused


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="consolidate_ledgers.py",
        description="the one-time #721 ledger migration (append-only, "
                    "bytes-archived) + the per-schema liveness readout")
    ap.add_argument("workspace", help="the analysis workspace root")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would migrate; write nothing")
    ap.add_argument("--liveness", action="store_true",
                    help="print per-schema row counts (family:schema) and "
                         "exit — includes registered-but-dead schemas at 0")
    ap.add_argument("--families", default=None,
                    help="comma-separated families to migrate "
                         "(default: every family with registered sources)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the report (or liveness counts) here")
    args = ap.parse_args(argv)

    ws = Path(args.workspace)
    if not ws.is_dir():
        print(f"error: workspace not found: {ws}", file=sys.stderr)
        return 2

    if args.liveness:
        counts = cl.liveness(ws)
        for key in sorted(counts):
            print(f"{key}\t{counts[key]}")
        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps(counts, indent=2, sort_keys=True),
                encoding="utf-8")
        return 0

    families = None
    if args.families:
        families = tuple(f.strip() for f in args.families.split(",")
                         if f.strip())
        unknown = [f for f in families if f not in cl.FAMILIES]
        if unknown:
            print(f"error: unknown families {sorted(unknown)} — known: "
                  f"{list(cl.FAMILIES)}", file=sys.stderr)
            return 2
    report = cl.migrate(ws, families, sources=LEGACY_SOURCES,
                        dry_run=args.dry_run)
    refused = _print_migration(report)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if refused:
        print(f"INCOMPLETE: {refused} rel(s) ended partial or "
              f"copied-unarchived — nothing was rewritten or deleted; "
              f"fix and re-run (idempotent)", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
