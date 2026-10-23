#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""key_freeze.py — issue-797 acceptance (a)+(b): the task-open learning-key
freeze and the fingerprint churn measurement.

## The production pathology (logs panel 2026-10-23)

Trigger fingerprints are task-unique BY CONSTRUCTION: the dispatch
observation recomputed the state signature per dispatch, and every
settled fact moved the snapshot — case pq-01 cycled 3 distinct
fingerprints in 35 minutes. Signature-keyed Q cells therefore never
recurred, cross-run accumulation was structurally zero (the web run
re-derived C-001..C-007 from scratch ~26h after android's same-version
experience), and 21 settlements spread over 17 cells = 1.2 obs/cell.

## Face (a) — the freeze

``runs/learning-key.json`` (schema ``learning-key/1``) is the mint-once
task doc:

    {"schema": "learning-key/1", "ts": ..., "task_signature": <12-hex>,
     "keys": {"<family>": {"key": "<fam|recipe|verif|tier[|agent]>",
                           "opened_ts": ...}}}

- ``task_signature`` — the TASK ANCHOR: snapped once at task open
  (mint-on-read: the first consumer opens the task) and immutable for
  the task's life. The dispatch recording face
  (``q_cells.record_dispatch_observation``) consumes it through
  ``task_signature`` so every row in a task carries ONE signature —
  intra-task accumulation by construction, the churn source dead.
  Absent/corrupt doc -> ``None`` -> the fresh per-dispatch signature
  (the bit-identical legacy face; fail-open, telemetry never breaks the
  ALLOW tail).
- ``keys[family].key`` — the FAMILY-GRAIN learning key:
  ``q_cells.arm_key`` over STRUCTURAL dispatch dims only (recipe/verif/
  tier/agent — zero state-derived material), so two runs of the
  same-family task freeze the SAME key and their evidence accumulates
  in one fold (the RED pin: family-repeatable across runs). Re-freeze
  returns the mint-once entry unchanged — frozen means frozen.
- ``other(...)`` free-text escapes are REFUSED at the boundary (the
  panel quarantine: they fragment cells without learning value).
- Alignment: issue-800's dispatch-ledger owns the rollout identity (the
  dispatch id); this doc owns the CELL key and duplicates nothing the
  ledger already keys. issue-807's INV-003 made the family the live
  posterior grain — the frozen key is family-grain by construction.

## Face (b) — the churn measurement

``churn_rate(runs)`` is the pure metric over per-run fingerprint
sequences (a fingerprint is NEW when never seen in any earlier run or
earlier in the same run; REUSED otherwise):

    churn = new / (new + reused)      verdict:
      reused == 0        -> "all-new"       (churn 1.0 — the production
                                             shape, structurally zero
                                             accumulation: LOUD)
      new == 0           -> "frozen"        (churn 0.0 — every
                                             fingerprint already known)
      0 < churn < 1      -> "accumulating"
      no fingerprint     -> "no-data"

``churn_report(ws)`` reads the dispatch rows of the live consolidated
experience ledger as ONE run (the workspace IS the run) and reports the
same shape. Loudness is STRUCTURAL (the verdict field + report rows):
this module adds ZERO warn() telemetry points (Standard 11 — pinned by
test); an unreadable ledger is the honest gap (``reason`` set — an
unreadable read is a different fact from an empty one).

## CLI

  python scripts/rlvr/key_freeze.py --churn <ws>
  python scripts/rlvr/key_freeze.py --freeze <ws> --family f
        [--recipe r] [--verif v] [--tier n] [--agent a]
  python scripts/rlvr/key_freeze.py --key <ws> --family f
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

FROZEN_REL = "runs/learning-key.json"
FROZEN_SCHEMA = "learning-key/1"
CHURN_SCHEMA = "fingerprint-churn/1"

#: the issue-797 quarantine (the panel scope addition): other(...) free-text
#: escapes fragment cells without learning value — refused at the freeze
#: boundary. Dependency-light mirror of method_families.OTHER (lazy
#: single-source below; the local fallback keeps partial deployments
#: honest — the declared_family precedent).
_OTHER_TOKEN = "other"


# ---------------------------------------------------------------------------
# the frozen doc (mint-once, immutable)
# ---------------------------------------------------------------------------

def _doc_path(ws) -> Path:
    return Path(ws) / FROZEN_REL


def _load(ws) -> dict | None:
    """The parsed frozen doc, or None (absent/corrupt — the honest
    not-frozen fact; readers degrade to the legacy face)."""
    p = _doc_path(ws)
    try:
        if not p.is_file():
            return None
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _save(ws, doc: dict) -> bool:
    """Persist the frozen doc (tiny JSON, fail-open)."""
    p = _doc_path(ws)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8")
        return True
    except OSError:
        return False


def _mint_doc(ws) -> dict | None:
    """Mint the task doc: the anchor snaps at THIS moment (task open).
    None = the snap or the write failed — stay not-frozen, never lie."""
    from rlvr import state as ssig  # noqa: PLC0415 — lazy, import-clean
    try:
        anchor = ssig.signature_hash(ssig.snapshot(ws))
    except Exception:  # noqa: BLE001 — fail-open telemetry
        return None
    doc = {"schema": FROZEN_SCHEMA, "task_signature": anchor,
           "keys": {}}
    from harness_common import utc_now_z  # noqa: PLC0415
    try:
        doc["ts"] = utc_now_z()
    except Exception:  # noqa: BLE001 — clock-source outage: no ts
        pass
    return doc if _save(ws, doc) else None


def task_signature(ws) -> str | None:
    """The task-open frozen signature — mint-on-read. The first consumer
    of the learning channel opens the task; every later read (including
    the dispatch recording face) returns the SAME anchor for the task's
    life. None = not frozen (the legacy fresh-computation face)."""
    doc = _load(ws)
    if doc is None:
        doc = _mint_doc(ws)
    if doc is None:
        return None
    anchor = doc.get("task_signature")
    return str(anchor) if anchor else None


def frozen_key(ws, method_family: str) -> str | None:
    """The family's frozen learning key, or None when the task never
    froze it (a pure read — never mints, never fabricates)."""
    doc = _load(ws)
    if doc is None:
        return None
    entry = (doc.get("keys") or {}).get(str(method_family)) or {}
    key = entry.get("key")
    return str(key) if key else None


def _refuse_other_escape(family: str) -> None:
    """The issue-797 quarantine boundary: bare ``other`` and the free-text
    ``other(...)`` escape never freeze a learning key (they fragment
    cells without learning value — method_families quarantines the
    dispatch rows; the freeze face refuses the key)."""
    token = _OTHER_TOKEN
    try:  # single-source the token when the sibling is importable
        from method_families import OTHER  # noqa: PLC0415
        token = OTHER
    except ImportError:
        pass
    if family == token or family.startswith(token):
        raise ValueError(
            f"other(...) escapes never freeze a learning key (the #797 "
            f"quarantine — they fragment cells without learning value): "
            f"{family!r}")


def freeze_task_key(ws, method_family: str, *,
                    context_recipe: str = "facts_snapshot",
                    verification_mode: str = "none",
                    tier=0, agent_type: str | None = None,
                    ts: str | None = None) -> dict | None:
    """Freeze the family-grain learning key for THIS task (mint-once per
    (task, family); the freeze is immutable — a re-freeze with different
    dims or after state drift returns the ORIGINAL entry unchanged).

    The key is ``q_cells.arm_key`` over structural dims only (family |
    recipe | verif | tier [| agent]) — zero state-derived material — so
    the same-family task in ANY run freezes the SAME key (the
    family-repeatable RED pin; cross-run accumulation follows in the
    fold). The first freeze of a task also snaps the task anchor (task
    open). Boundary: an empty family or an ``other(...)`` escape is
    refused (ValueError, nothing written). None = the doc could not be
    persisted (the honest gap — never a key that would not stick)."""
    family = str(method_family or "").strip()
    if not family:
        raise ValueError("method_family must be a non-empty token")
    _refuse_other_escape(family)
    doc = _load(ws)
    if doc is None:
        doc = _mint_doc(ws)
    if doc is None:
        return None
    keys = doc.setdefault("keys", {})
    existing = keys.get(family)
    if existing:
        return {"created": False, "key": str(existing.get("key")),
                "opened_ts": str(existing.get("opened_ts") or ""),
                "signature_hash": str(doc.get("task_signature") or "")}
    from rlvr import q_cells  # noqa: PLC0415 — the arm-key single source
    key = q_cells.arm_key(family, context_recipe, verification_mode,
                          tier, agent_type)
    if not ts:
        from harness_common import utc_now_z  # noqa: PLC0415
        try:
            ts = utc_now_z()
        except Exception:  # noqa: BLE001 — clock outage: ts optional
            ts = ""
    keys[family] = {"key": key, "opened_ts": str(ts)}
    if not _save(ws, doc):
        return None
    return {"created": True, "key": key, "opened_ts": str(ts),
            "signature_hash": str(doc.get("task_signature") or "")}


# ---------------------------------------------------------------------------
# face (b) — the fingerprint churn measurement
# ---------------------------------------------------------------------------

def churn_rate(runs) -> dict:
    """The pure churn metric over per-run fingerprint sequences.

    ``runs`` is an ordered list of runs, each an ordered list of the
    fingerprints observed at dispatch in that run (None/blank = the row
    carried no fingerprint — counted as ``missing``, never fabricated
    into reuse). A fingerprint is NEW when it was never seen in any
    earlier run or earlier in the same run; REUSED otherwise.
    churn = new / (new + reused); verdict per the module docstring.
    Pure: no filesystem, no clock, no telemetry."""
    seen: set[str] = {}
    new = reused = missing = 0
    runs = list(runs or [])
    for run in runs:
        run_new = 0
        for fp in (run or []):
            if fp is None or not str(fp).strip():
                missing += 1
                continue
            token = str(fp).strip()
            if token in seen:
                reused += 1
            else:
                seen[token] = True
                new += 1
                run_new += 1
        last_run_new = run_new
    total = new + reused
    churn: float | None = (new / total) if total else None
    if total == 0:
        verdict = "no-data"
    elif reused == 0:
        verdict = "all-new"
    elif new == 0 or last_run_new == 0:
        verdict = "frozen"
    else:
        verdict = "accumulating"
    return {"schema": CHURN_SCHEMA, "n_runs": len(runs),
            "dispatches": total, "missing": missing,
            "distinct": len(seen), "new": new, "reused": reused,
            "last_run_new": last_run_new if total else 0,
            "churn": None if churn is None else round(churn, 6),
            "verdict": verdict}


def churn_report(ws) -> dict:
    """The measurement surface over the LIVE ledger: the consolidated
    experience file's dispatch rows (the fingerprint churn source) read
    as ONE run — the workspace IS the run. Diagnostic read: rows were
    sealed at write (the recording face), this face never banks mass,
    so the tolerant ledger read applies (an unreadable ledger is the
    honest gap — ``reason`` set; an empty one is ``no-data`` — different
    facts, never conflated)."""
    from rlvr import consolidated_ledger as _cl  # noqa: PLC0415
    ws = Path(ws)
    rel = _cl.CONSOLIDATED["experience"]
    exp = ws / rel
    reason = None
    if exp.exists() and not exp.is_file():
        reason = f"read-failed: not-a-file: {rel}"
        rows: list[dict] = []
    else:
        rows = [r for r in _cl.read(ws, "experience",
                                    schema_prefix="q-cell-obs")
                if isinstance(r, dict)
                and str(r.get("source") or "") == "dispatch"]
    fps = [r.get("fingerprint") for r in rows]
    out = churn_rate([fps])
    out["workspace"] = str(ws)
    if reason:
        out["reason"] = reason
    return out


# ---------------------------------------------------------------------------
# CLI (offline measurement faces only)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="rlvr.key_freeze",
        description="#797: task-open learning-key freeze + fingerprint "
                    "churn measurement (library faces consumed by the "
                    "q_cells recording face)")
    ap.add_argument("--churn", metavar="WS",
                    help="fingerprint churn report over one workspace's "
                         "experience ledger")
    ap.add_argument("--freeze", metavar="WS",
                    help="freeze the learning key for --family in WS")
    ap.add_argument("--key", metavar="WS",
                    help="read the frozen key for --family in WS")
    ap.add_argument("--family", metavar="FAM",
                    help="the method family (with --freeze/--key)")
    ap.add_argument("--recipe", default="facts_snapshot")
    ap.add_argument("--verif", default="none")
    ap.add_argument("--tier", default=0)
    ap.add_argument("--agent", default=None)
    args = ap.parse_args(argv)
    if args.churn:
        print(json.dumps(churn_report(args.churn), ensure_ascii=False,
                         indent=2))
        return 0
    if args.freeze:
        if not args.family:
            ap.error("--freeze requires --family")
        out = freeze_task_key(args.freeze, args.family,
                              context_recipe=args.recipe,
                              verification_mode=args.verif,
                              tier=args.tier, agent_type=args.agent)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out is not None else 1
    if args.key:
        if not args.family:
            ap.error("--key requires --family")
        print(json.dumps({"key": frozen_key(args.key, args.family)},
                         ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
