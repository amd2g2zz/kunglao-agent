#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""consolidate_ledgers.py — the #1004 ledger retirement CLI + liveness.

Issue #721 consolidated the 12+ JSONL ledgers into 4 by lifecycle; its
compat window (dual read + the runs/archive/ migration) is retired by
#1004 — every family has switched whole. This CLI is the ONE-TIME
retirement face plus the per-schema liveness readout:

    python scripts/consolidate_ledgers.py <ws> --retire-legacy
    python scripts/consolidate_ledgers.py <ws> --retire-legacy --dry-run
    python scripts/consolidate_ledgers.py <ws> --liveness

--retire-legacy, per family then per rel (registry order — the order the
old dual-read produced its legacy rows in): every legacy row is APPENDED
into the family's consolidated file (values preserved; a missing stamp
added ONLY where the rel registers exactly one schema — never guessed),
the appended rows are VERIFIED (count + stamps against the consolidated
file), and only then is the legacy rel DELETED together with its
``.<stem>.lock`` file. Idempotent: rows the target already carries
(canonical-JSON multiset) are not re-appended, so a re-run appends
nothing and the absent rels are no-ops. ``--dry-run`` reports without
writing or deleting anything. ``runs/archive/`` is NEVER created — the
consolidated file is the single home; the legacy rel is deleted, not
archived.

Exit: 0 ok; 2 bad args; 3 a rel failed to append or failed verification
(nothing was deleted for that rel — fix and re-run; idempotent).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rlvr import consolidated_ledger as cl  # noqa: E402

# --------------------------------------------------------------------------
# the retire registry — the retired rels' ONLY sanctioned home (#1004):
# family -> {rel: (registered stamps, scope)}. scope "ws" resolves the
# rel under the workspace, "guard" under the guarded cross-task root
# (strategy_store.store_root). A rel registering exactly ONE stamp gets
# that stamp inferred onto its unstamped rows (the pre-stamp cost /
# strategy-log archives); a multi-stamp rel's unstamped rows are copied
# VERBATIM (never guessed) and count under ``(no-schema)`` in liveness.
RETIRE_LEGACY: dict[str, dict[str, tuple[tuple[str, ...], str]]] = {
    "experience": {
        "runs/transitions.jsonl": (("transition/1",), "ws"),
        "runs/q-cell-log.jsonl": (("q-cell-obs/1",), "ws"),
        "runs/step-ledger.jsonl": (("step-record/1", "step-record/2"),
                                   "ws"),
        "runs/evidence-credit.jsonl": (("evidence-item/1",
                                        "credit-amendment/1"), "ws"),
    },
    "settlement": {
        "runs/rollout-ledger.jsonl": (("rollout-ledger/1",), "ws"),
        "runs/attributed-waste.jsonl": (("attributed-waste/1",), "ws"),
        "cost_events.jsonl": (("cost-event/1",), "ws"),
    },
    "telemetry": {
        "runs/interventions.jsonl": (("intervention/1",), "ws"),
        "runs/predictions.jsonl": (("prediction-ledger/1",), "ws"),
        "runs/situation-stream.jsonl": (("situation/1",), "ws"),
        "runs/strategy-log.jsonl": (("strategy-log/1",), "ws"),
    },
    # the knowledge rels under the guarded root; the two ws-scoped
    # historical files (the mined feature table and the workspace-local
    # credit series) resolve under the workspace — where their writers
    # actually wrote them
    "knowledge": {
        "posterior-store.jsonl": (("posterior-store/1",), "guard"),
        "marl-negative.jsonl": (("marl-negative/1",), "guard"),
        "runs/feature-table.jsonl": (("feature-table/1",), "ws"),
        "runs/posterior-store.jsonl": (("posterior-store/1",), "ws"),
    },
}

NO_SCHEMA = "(no-schema)"


def _rel_path(ws: Path, family: str, rel: str, scope: str) -> Path:
    if scope == "guard":
        return cl._knowledge_root() / rel
    return ws / rel


def _read_rows(p: Path) -> list[dict]:
    """Tolerant JSONL read (absent -> [])."""
    if not p.is_file():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8",
                            errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, ensure_ascii=False)


def _existing_counts(target: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in _read_rows(target):
        key = _canonical(row)
        counts[key] = counts.get(key, 0) + 1
    return counts


def _stamp_row(row: dict, schemas: tuple[str, ...]) -> dict:
    """Retirement stamping, deliberately timid (the #721 contract): a
    row that already carries a schema copies verbatim; an unstamped row
    gets a stamp ONLY when its rel registers exactly ONE schema — a
    zero- or two-schema rel's unstamped row is copied verbatim, never
    guessed."""
    if str(row.get("schema") or "").strip():
        return row
    if len(schemas) == 1:
        return {**row, "schema": schemas[0]}
    return row


def _retire_rel(ws: Path, family: str, rel: str,
                schemas: tuple[str, ...], scope: str,
                dry_run: bool) -> dict:
    """One rel's retirement: stamp-infer, dedupe against the target
    (idempotent), append, verify, then delete the rel + its lock file.
    NEVER archives: the delete happens only after every row verified in
    the consolidated file."""
    src = _rel_path(ws, family, rel, scope)
    if not src.is_file():
        return {"status": "absent", "rows": 0, "appended": 0,
                "deleted": False}
    legacy_rows = _read_rows(src)
    stamped = [_stamp_row(row, schemas) for row in legacy_rows]
    existing = _existing_counts(cl.family_path(ws, family))
    to_append: list[dict] = []
    for row in stamped:
        key = _canonical(row)
        if existing.get(key, 0) > 0:
            existing[key] -= 1  # an already-copied row (re-run)
        else:
            to_append.append(row)
    if dry_run:
        return {"status": "dry-run", "rows": len(legacy_rows),
                "appended": len(to_append), "deleted": False}
    results = []
    for row in to_append:
        if str(row.get("schema") or "").strip():
            results.append(cl.append(ws, family, row))
        else:  # a stampless row: append() refuses such rows, so this
              #  path keeps the bytes unchanged; the row stays visible
              #  under the no-schema liveness key
            results.append(cl._locked_append(
                cl.family_path(ws, family),
                (json.dumps(row, ensure_ascii=False) + "\n")
                .encode("utf-8")))
    if not all(results):
        return {"status": "partial", "rows": len(legacy_rows),
                "appended": sum(1 for r in results if r),
                "deleted": False}
    # verify: every stamped row present in the target (canonical
    # multiset), then delete the rel and its lock file
    verify = _existing_counts(cl.family_path(ws, family))
    for row in stamped:
        key = _canonical(row)
        if verify.get(key, 0) <= 0:
            return {"status": "verify-failed", "rows": len(legacy_rows),
                    "appended": len(to_append), "deleted": False}
        verify[key] -= 1
    lock = src.parent / f".{src.stem}.lock"
    try:
        src.unlink()
        lock.unlink(missing_ok=True)
    except OSError as exc:
        print(f"[{family}] {rel}: delete failed ({exc!r}) — the rows "
              f"are verified in the consolidated file; delete the rel "
              f"by hand and re-run (idempotent)", file=sys.stderr)
        return {"status": "delete-failed", "rows": len(legacy_rows),
                "appended": len(to_append), "deleted": False}
    return {"status": "retired", "rows": len(legacy_rows),
            "appended": len(to_append), "deleted": True}


def _retire(ws: Path, families: tuple[str, ...] | None,
            dry_run: bool) -> tuple[dict, int]:
    """The retirement pass; returns (report, failed-rel count)."""
    report: dict[str, dict] = {}
    failed = 0
    for family in (families or tuple(RETIRE_LEGACY)):
        fam: dict[str, dict] = {}
        for rel, (schemas, scope) in RETIRE_LEGACY[family].items():
            entry = _retire_rel(ws, family, rel, schemas, scope, dry_run)
            fam[rel] = entry
            if entry["status"] not in ("absent", "dry-run", "retired"):
                failed += 1
        report[family] = fam
    return report, failed


def _print_retire(report: dict) -> None:
    for family, fam in report.items():
        for rel, entry in fam.items():
            print(f"[{family}] {rel}: {entry['status']} "
                  f"(rows={entry['rows']} appended={entry['appended']})"
                  + (" DELETED" if entry.get("deleted") else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="consolidate_ledgers.py",
        description="the one-time #1004 ledger retirement (append, "
                    "verify, DELETE the legacy rel — never archive) + "
                    "the per-schema liveness readout")
    ap.add_argument("workspace", help="the analysis workspace root")
    ap.add_argument("--retire-legacy", action="store_true",
                    help="append every legacy rel's rows into its "
                         "family's consolidated file (dual-read order), "
                         "verify, then DELETE the rel + its lock file "
                         "(idempotent; never creates runs/archive/)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --retire-legacy: report what would move; "
                         "write and delete nothing")
    ap.add_argument("--families", default=None,
                    help="comma-separated families to retire "
                         "(default: all four)")
    ap.add_argument("--liveness", action="store_true",
                    help="print per-schema row counts (family:schema) "
                         "and exit — includes registered-but-dead "
                         "schemas at 0 (consolidated files only)")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the report (or liveness counts) "
                         "here")
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

    if not args.retire_legacy:
        print("error: nothing to do — pass --retire-legacy (the "
              "one-time retirement) or --liveness (the readout)",
              file=sys.stderr)
        return 2

    families = None
    if args.families:
        families = tuple(f.strip() for f in args.families.split(",")
                         if f.strip())
        unknown = [f for f in families if f not in cl.FAMILIES]
        if unknown:
            print(f"error: unknown families {sorted(unknown)} — known: "
                  f"{list(cl.FAMILIES)}", file=sys.stderr)
            return 2
    report, failed = _retire(ws, families, args.dry_run)
    _print_retire(report)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if failed:
        print(f"INCOMPLETE: {failed} rel(s) failed append, verification "
              f"or deletion — nothing was deleted for them; fix and "
              f"re-run (idempotent)", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
