#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rlvr/censored_review.py — the censored-outcome fairness review
(issue #548): is "timeout = failure" punishing slow-but-correct arms?

The expert-adjudicated policy banks a TIMEOUT as failure in the arm
posterior ("time is cost"). That is only fair if the punishment tracks
wall time ALONE — if timed-out acts had already moved the state forward
(Φ movement on the transition row), the posterior is punishing exactly
the slow-but-correct routes the hard tasks need.

The review face over one or more run directories (each scanned
recursively for `runs/transitions.jsonl`):

  per method family (the row's `a` field), settlement rows
  (`r_settle` present) fall into:

    censored_with_facts   the settlement was censored (producer rule:
                          o.status == TIMEOUT, unless the row carries
                          its own explicit `censored` flag) AND
                          o.facts > 0 — work done, posterior still
                          banked the failure floor;
    censored_no_facts     censored with zero facts (reported, not
                          judged — nothing was produced);
    clean_failure         NOT censored and not a success (o.status !=
                          DISPATCHED) — the fully-observed failure
                          baseline;
    success               o.status == DISPATCHED (context only).

  For each bucket: count, mean r_incr, mean Φ delta (s_prime_phi −
  phi_before — the pure movement; r_incr additionally carries the cost
  term) and mean credit.

  Verdict per family, on the Φ delta (not r_incr — cost must not
  masquerade as signal):

    underpowered  either judged bucket below MIN_BUCKET_ROWS rows
                  (small-sample honesty, the policy_compare gate);
    fair          censored-bucket Φ delta below PHI_SIGNAL_FLOOR (≈0 —
                  no state movement, punishment tracks time only), or
                  the gap to the clean-failure baseline stays under
                  PHI_MARGIN;
    unfair        Φ moved meaningfully above the clean-failure
                  baseline while the posterior still banked the
                  failure floor (mean credit < full success credit).

  Kaplan-Meier face: the sibling `runs/logs/e2e-audit.jsonl` stream's
  `posterior_updated` rows carry the explicit `censored` flag + credit
  the settle face emitted. Those rows omit the claim id (the producer
  documents the omission), so the join is per family, not per dispatch.

An "unfair" verdict does NOT flip any sampling behavior here — the
credit-tiebreaker adoption is a consumption-only follow-up riding the
offline comparison (issue #548 deliverable 2).

Usage:
    python scripts/rlvr/censored_review.py <run-dir> [<run-dir> ...]
    python scripts/rlvr/censored_review.py <run-dir> ... --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    # direct-path execution: the package parent (scripts/) is NOT on
    # sys.path (path[0] is scripts/rlvr/) — insert it before the sibling
    # imports (the q_cells direct-execution pattern)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kunglao_log import warn

SCHEMA = "censored-review/1"
SCOPE = "rlvr.censored_review"

TRANSITIONS_NAME = "transitions.jsonl"   # matched only inside a runs/ dir
AUDIT_REL = ("logs", "e2e-audit.jsonl")  # sibling of the transitions file

SUCCESS_STATUS = "DISPATCHED"   # the producer's binary-success word
CENSORED_STATUS = "TIMEOUT"     # the producer's censoring word

# ---- verdict policy constants (issue-scoped, NOT fitted) ------------------
PHI_SIGNAL_FLOOR = 0.05   # below: censored-bucket Φ movement ≈ 0 → fair
PHI_MARGIN = 0.05         # min gap over the clean-failure baseline
MIN_BUCKET_ROWS = 3       # below: underpowered, no verdict (small-N)

BUCKETS = ("censored_with_facts", "censored_no_facts",
           "clean_failure", "success")


# ---- row classification ----------------------------------------------------

def _num(value: object) -> float | None:
    """A finite float or None — never a guess, never a raise."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _facts(row: dict) -> int | None:
    facts = (row.get("o") or {}).get("facts", 0)
    if isinstance(facts, bool) or not isinstance(facts, int):
        return None
    return facts


def _is_censored(row: dict) -> bool:
    """The settlement's censoring flag. An explicit row-level `censored`
    field is authoritative (schema evolution headroom); otherwise the
    producer rule applies: censored := o.status == TIMEOUT."""
    explicit = row.get("censored")
    if isinstance(explicit, bool):
        return explicit
    return (row.get("o") or {}).get("status") == CENSORED_STATUS


def _phi_delta(row: dict) -> float | None:
    after = _num(row.get("s_prime_phi"))
    before = _num(row.get("phi_before"))
    if after is None or before is None:
        return None
    return after - before


def _classify(row: object) -> str | None:
    """'settlement' | 'pending' | None — None means the line does not
    carry a usable transition row (skipped AND counted upstream)."""
    if not isinstance(row, dict):
        return None
    o = row.get("o")
    if not isinstance(o, dict):
        return None
    for key in ("dispatch_id", "a"):
        value = row.get(key)
        if not isinstance(value, str) or not value:
            return None
    if not isinstance(o.get("status"), str) or not o["status"]:
        return None
    if _facts(row) is None:
        return None
    if row.get("r_settle") is None:
        return "pending"
    if _num(row.get("r_settle")) is None:
        return None
    return "settlement"


# ---- aggregation ------------------------------------------------------------

def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _bucket_stats(rows: list[dict]) -> dict:
    r_incrs = [v for v in (_num(r.get("r_incr")) for r in rows)
               if v is not None]
    deltas = [v for v in (_phi_delta(r) for r in rows) if v is not None]
    credits = [v for v in (_num(r.get("r_settle")) for r in rows)
               if v is not None]
    return {
        "count": len(rows),
        "mean_r_incr": _mean(r_incrs),
        "mean_phi_delta": _mean(deltas),
        "mean_credit": _mean(credits),
    }


def _verdict(cens: dict, clean: dict) -> tuple[str, dict]:
    """The per-family verdict + the numbers it rests on. Judged on the
    Φ delta: cost lives in r_incr and must not masquerade as signal."""
    basis = {
        "censored_mean_phi_delta": cens["mean_phi_delta"],
        "clean_failure_mean_phi_delta": clean["mean_phi_delta"],
        "censored_mean_credit": cens["mean_credit"],
        "phi_signal_floor": PHI_SIGNAL_FLOOR,
        "phi_margin": PHI_MARGIN,
    }
    if cens["count"] < MIN_BUCKET_ROWS or clean["count"] < MIN_BUCKET_ROWS:
        return "underpowered", basis
    c = cens["mean_phi_delta"]
    f = clean["mean_phi_delta"]
    if c is None or c < PHI_SIGNAL_FLOOR:
        return "fair", basis
    if f is not None and c - f >= PHI_MARGIN:
        return "unfair", basis
    return "fair", basis


def _families(settlements: list[dict]) -> dict[str, dict]:
    """Per-family bucket table over settlement rows (family = the `a`
    field the launch stash recorded — the method family, or
    'unattributed')."""
    grouped: dict[str, dict[str, list[dict]]] = {}
    for row in settlements:
        fam = str(row["a"])
        b = grouped.setdefault(fam, {name: [] for name in BUCKETS})
        if _is_censored(row):
            key = ("censored_with_facts" if (_facts(row) or 0) > 0
                   else "censored_no_facts")
        elif (row.get("o") or {}).get("status") == SUCCESS_STATUS:
            key = "success"
        else:
            key = "clean_failure"
        b[key].append(row)
    out: dict[str, dict] = {}
    for fam in sorted(grouped):
        b = grouped[fam]
        entry = {name: _bucket_stats(b[name]) for name in BUCKETS}
        entry["verdict"], entry["verdict_basis"] = _verdict(
            entry["censored_with_facts"], entry["clean_failure"])
        out[fam] = entry
    return out


# ---- the Kaplan-Meier posterior join ----------------------------------------

def _audit_detail(row: dict) -> dict | None:
    det = row.get("detail")
    if isinstance(det, str):
        try:
            det = json.loads(det)
        except json.JSONDecodeError:
            return None
    return det if isinstance(det, dict) else None


def _km_absorb(acc: dict[str, dict], row: dict) -> None:
    """Fold one audit row into the per-family KM accumulator (skip
    anything that is not a well-formed posterior_updated row)."""
    if (row.get("action") or row.get("event")) != "posterior_updated":
        return
    det = _audit_detail(row)
    if det is None:
        return
    cell = str(det.get("cell") or "")
    counts = det.get("counts")
    if not cell or not isinstance(counts, dict):
        return
    slot = acc.setdefault(cell, {
        "rows": 0, "censored_true": 0, "censored_false": 0,
        "_credit_cens": [], "_credit_obs": []})
    slot["rows"] += 1
    credit = _num(counts.get("credit"))
    if counts.get("censored") is True:
        slot["censored_true"] += 1
        if credit is not None:
            slot["_credit_cens"].append(credit)
    elif counts.get("censored") is False:
        slot["censored_false"] += 1
        if credit is not None:
            slot["_credit_obs"].append(credit)


def _km_face(audit_paths: list[Path]) -> dict[str, dict]:
    """posterior_updated rows per family (cell): the explicit censored
    flag + credit the settle face emitted into the audit stream."""
    acc: dict[str, dict] = {}
    for path in audit_paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warn(SCOPE, f"audit stream unreadable {path}: "
                        f"{type(exc).__name__}: {exc}")
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                _km_absorb(acc, row)
    return {cell: {
        "rows": slot["rows"],
        "censored_true": slot["censored_true"],
        "censored_false": slot["censored_false"],
        "mean_credit_censored": _mean(slot["_credit_cens"]),
        "mean_credit_observed": _mean(slot["_credit_obs"]),
    } for cell, slot in sorted(acc.items())}


# ---- the ledger scan ---------------------------------------------------------

def find_transition_files(run_dirs: list[str | Path]) -> list[Path]:
    """Every transitions.jsonl under a `runs` path component within the
    given run directories (the `find <dirs> -name transitions.jsonl
    -path '*/runs/*'` face, stdlib-only). Deterministic order; a missing
    run dir warns loudly and contributes nothing."""
    found: list[Path] = []
    for raw in run_dirs:
        root = Path(raw)
        if not root.is_dir():
            warn(SCOPE, f"run dir missing: {root}")
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                if name != TRANSITIONS_NAME:
                    continue
                candidate = Path(dirpath) / name
                # the -path '*/runs/*' contract: only under a runs dir
                if "runs" in candidate.parent.parts:
                    found.append(candidate)
    return sorted(found, key=str)


def read_ledger(paths: list[Path]) -> tuple[list[dict], dict]:
    """Read every transitions.jsonl into (settlement + pending rows,
    stats). Malformed lines are skipped AND counted — never silently
    dropped."""
    rows: list[dict] = []
    stats = {"files_scanned": len(paths), "rows_total": 0,
             "rows_settlement": 0, "rows_non_settlement": 0,
             "skipped_malformed": 0}
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            warn(SCOPE, f"ledger unreadable {path}: "
                        f"{type(exc).__name__}: {exc}")
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                stats["skipped_malformed"] += 1
                continue
            kind = _classify(row)
            if kind is None:
                stats["skipped_malformed"] += 1
                continue
            stats["rows_total"] += 1
            rows.append(row)
            if kind == "settlement":
                stats["rows_settlement"] += 1
            else:
                stats["rows_non_settlement"] += 1
    return rows, stats


# ---- the review face ---------------------------------------------------------

def review(run_dirs: list[str | Path]) -> dict:
    """The censored-review/1 report over the given run directories."""
    files = find_transition_files(run_dirs)
    rows, stats = read_ledger(files)
    settlements = [r for r in rows if _classify(r) == "settlement"]
    km = _km_face([f.parent.joinpath(*AUDIT_REL) for f in files])
    families = _families(settlements)
    for fam, entry in families.items():
        entry["km_posterior"] = km.get(fam, {
            "rows": 0, "censored_true": 0, "censored_false": 0,
            "mean_credit_censored": None, "mean_credit_observed": None})
    return {
        "schema": SCHEMA,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "run_dirs": [str(d) for d in run_dirs],
        "files_scanned": stats["files_scanned"],
        "rows_total": stats["rows_total"],
        "rows_settlement": stats["rows_settlement"],
        "rows_non_settlement": stats["rows_non_settlement"],
        "skipped_malformed": stats["skipped_malformed"],
        "constants": {
            "phi_signal_floor": PHI_SIGNAL_FLOOR,
            "phi_margin": PHI_MARGIN,
            "min_bucket_rows": MIN_BUCKET_ROWS,
        },
        "families": families,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="censored_review.py",
        description="censored-outcome fairness review: does 'timeout = "
                    "failure' punish slow-but-correct arms? Per-family "
                    "censored-with-facts vs clean-failure comparison "
                    "over runs/transitions.jsonl ledgers")
    ap.add_argument("run_dirs", nargs="+",
                    help="run directories to scan for transitions.jsonl "
                         "under a runs/ path component")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="also write the report to this file")
    args = ap.parse_args(argv)
    report = review(args.run_dirs)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
