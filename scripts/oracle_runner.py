#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""oracle_runner.py — the oracle's mechanical face (issue #108, design card #97 part 3).

Runs the workspace's oracle case set (`<ws>/oracle/cases/*.yaml`) against a
client implementation (a Python module exposing ``compute(params: dict) ->
dict``), and writes the verdict file the convergence DRAIN probes consume:

    <ws>/runs/oracle-status.json
      {"schema": "oracle-status/1",
       "cases": {"<case_id>": {"status": "pass|fail|pending",
                               "pending_entries": N, "instrumented": bool}},
       "low_discriminativity": [...], "counts": {"red": N, "green": N, "pending": N}}

Half B — mutation must fail (the oracle's own red-team, no LLM). The oracle
is LLM-built: it catches a wrong client (wrong values -> red) but not its
own design errors (a mis-pinned case passes a wrong implementation too).
What is mechanical: a deliberately-mutated client — ONE declared field
swapped / omitted / changed per the case's ``mutations:`` block — MUST turn
the case red. A case that stays green under all its declared mutations
observes nothing its author claims distinguishes it: flagged
``low_discriminativity`` (the strengthening to-do; the convergence gate
blocks on red/pending — the flag is reported, not a verdict branch).

Half C — byte anchors, made mechanical (the doubao convention): every
expected entry carries ``evidence_refs`` to the fact that pins it, or an
explicit ``pending-observation: true`` marker. An entry with neither is
REFUSED with a lint-style OracleCaseError — no silent invented values. On
refusal the runner exits 2 and writes NO status file (a refusal must never
degenerate into a green status).

No client runnable -> every case reports ``pending`` with
``instrumented=false`` — pending is the honest unknown; it is never green.
A client that CRASHES is recorded as pending too, but with
``instrumented=true``: the wiring exists, the observation is still owed
(the DRAIN probe blocks pendings on live instrumentation — "unknown" is
not "pass", #108 A).

#106 reuse: a REAL verdict (pass/fail) is a Bernoulli observation — each run
updates the case's CasePosterior in the ``runs/posteriors.yaml`` ledger via
record_posteriors() ("runner red/green is the only reward signal"). Pending
is not an observation and never touches the posterior.

Case YAML shape::

    id: auth-fields            # required (file stem as fallback)
    params: {user: alice, nonce: 10}
    expected:                  # required, non-empty
      - field: auth_algo       # required per entry
        value: hmac-sha256     # required per entry
        evidence_refs: [F001]  # byte anchor (fact id(s)) — OR the marker below
        pending-observation: true   # scaffold entry: owed, not compared
    mutations:                 # optional; what distinguishes this case from
      - field: auth_algo       #   near-miss implementations (half B)
        kind: swap             #   swap | omit | change (default change)

Exit codes: 0 = no red case; 1 = at least one red case; 2 = lint refusal.
Usage:
  python scripts/oracle_runner.py <ws> [--client <path>] [--mutation] [--json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

import yaml

SCHEMA_ID = "oracle-status/1"
STATUS_REL = ("runs", "oracle-status.json")
CASES_REL = ("oracle", "cases")
DEFAULT_CLIENT_REL = ("oracle", "client.py")
MUTATION_KINDS = ("swap", "omit", "change")

Compute = Callable[[dict], dict]


class OracleCaseError(ValueError):
    """Case-set lint refusal (#108 half C) — loud, never silently blessed."""


# ------------------------------------------------------------ case loading

def _parse_expected(case_path: Path, cid: str, raw) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r} needs a non-empty `expected` list")
    out: list[dict] = []
    for i, e in enumerate(raw):
        if not isinstance(e, dict):
            raise OracleCaseError(
                f"{case_path.name}: expected entry #{i} is "
                f"{type(e).__name__}; expected a mapping")
        field = e.get("field")
        if not isinstance(field, str) or not field:
            raise OracleCaseError(
                f"{case_path.name}: expected entry #{i} lacks a `field` name")
        if "value" not in e:
            raise OracleCaseError(
                f"{case_path.name}: expected entry {field!r} lacks a `value`")
        refs = e.get("evidence_refs")
        pending = bool(e.get("pending-observation"))
        if pending:
            out.append({"field": field, "value": e["value"],
                        "evidence_refs": [str(r) for r in (refs or [])],
                        "pending": True})
            continue
        # #108 half C: no byte-anchored fact reference and no pending marker
        # -> the value is invented. Refuse (lint-style), never bless.
        if not isinstance(refs, list) or not refs:
            raise OracleCaseError(
                f"{case_path.name}: expected entry {field!r} lacks "
                f"evidence_refs and a pending-observation marker — refusing "
                f"to bless an invented value (#108 half C: every expected "
                f"entry carries a byte-anchored fact reference or an "
                f"explicit pending-observation marker)")
        out.append({"field": field, "value": e["value"],
                    "evidence_refs": [str(r) for r in refs], "pending": False})
    return out


def _parse_mutations(case_path: Path, cid: str, raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise OracleCaseError(
            f"{case_path.name}: case {cid!r}: `mutations` must be a list")
    out: list[dict] = []
    for i, m in enumerate(raw):
        if isinstance(m, str):  # shorthand: - auth_algo  (kind defaults change)
            m = {"field": m}
        if not isinstance(m, dict) or not isinstance(m.get("field"), str) \
                or not m["field"]:
            raise OracleCaseError(
                f"{case_path.name}: case {cid!r}: mutation #{i} needs a "
                f"`field` name")
        kind = m.get("kind") or "change"
        if kind not in MUTATION_KINDS:
            raise OracleCaseError(
                f"{case_path.name}: case {cid!r}: mutation {m['field']!r} has "
                f"unknown kind {kind!r} (have {MUTATION_KINDS})")
        out.append({"field": m["field"], "kind": kind})
    return out


def load_cases(cases_dir) -> list[dict]:
    """Load + lint every ``*.yaml`` case. Raises OracleCaseError on the first
    refusal (#108 half C) — the case set is blessed as a whole or not at all."""
    cases: list[dict] = []
    for p in sorted(Path(cases_dir).glob("*.yaml")):
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise OracleCaseError(f"{p.name}: case file is not a mapping")
        cid = str(doc.get("id") or p.stem).strip()
        if not cid:
            raise OracleCaseError(f"{p.name}: case id is empty")
        cases.append({
            "id": cid,
            "params": doc.get("params") or {},
            "expected": _parse_expected(p, cid, doc.get("expected")),
            "mutations": _parse_mutations(p, cid, doc.get("mutations")),
        })
    return cases


# ------------------------------------------------------------ client loader

def load_client(client_path) -> Compute | None:
    """Load a client module (``compute(params) -> dict``). Missing path ->
    None (all cases pending, never green). A PRESENT but broken client is a
    hard error: silently treating broken instrumentation as "no client"
    would dress a red face in pending clothes.

    Imported through a content-hashed snapshot copy under a digest-bearing
    module name, NOT the file itself: the source-file bytecode cache
    validates on (mtime_seconds, size), so a rewritten SAME-LENGTH client
    re-served the stale module (observed: equal-length good/bad clients ->
    the bad run silently judged the good one). Different bytes -> different
    snapshot name -> different cache file; identical bytes reuse the
    identical module (same behavior). #863 Family B: the by-path load
    itself delegates to hooks/_path_hygiene.load_module_by_path (the ONE
    importlib by-path load site in the repo)."""
    if client_path is None or not Path(client_path).exists():
        return None
    path = Path(client_path)
    source = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    snap_dir = Path(tempfile.gettempdir()) / "kunglao-oracle-clients"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / f"{path.stem}-{digest}.py"
    if not snap.exists():
        snap.write_text(source, encoding="utf-8")
    from _hooks_path import load_module_by_path  # (#863 Family B delegation)
    mod = load_module_by_path(
        "kunglao_oracle_client_" + snap.stem.replace("-", "_"), snap)
    compute = getattr(mod, "compute", None)
    if not callable(compute):
        raise OracleCaseError(
            f"client {path} exposes no callable compute(params) -> dict")
    return compute


# ---------------------------------------------------------------- checking

def check_case(case: dict, compute: Compute | None) -> dict:
    """One case -> {"status", "pending_entries", "instrumented", "failures"}.

    status: fail (observed entry mismatched) > pending (no client / client
    crash / nothing observed / scaffold entries owed) > pass (every observed
    entry matches and nothing is owed). "Unknown" is never "pass" (#108 A)."""
    expected = case["expected"]
    pending_entries = sum(1 for e in expected if e["pending"])
    observed = [e for e in expected if not e["pending"]]
    row = {"status": "pending", "pending_entries": pending_entries,
           "instrumented": False, "failures": [], "error": None}
    if compute is None:
        return row
    row["instrumented"] = True
    try:
        out = compute(dict(case["params"]))
    except Exception as exc:  # noqa: BLE001 — a crash is a verdict of "unknown"
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    if not isinstance(out, dict):
        row["error"] = f"client returned {type(out).__name__}, expected dict"
        return row
    for e in observed:
        if out.get(e["field"]) != e["value"]:
            row["failures"].append(
                f"{e['field']}: expected {e['value']!r}, got "
                f"{out.get(e['field'])!r}")
    if row["failures"]:
        row["status"] = "fail"
    elif not observed or pending_entries:
        row["status"] = "pending"  # observations still owed — not pass
    else:
        row["status"] = "pass"
    return row


# ---------------------------------------------------------------- mutation

def _perturb(value):
    """A value GUARANTEED different from the input (deterministic)."""
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, str):
        return value + "#mutated"
    if isinstance(value, list):
        return list(reversed(value))
    if isinstance(value, dict):
        return dict(value, mutated=True)
    if value is None:
        return "mutated"
    return f"{value!r}#mutated"


def _mutated_client(compute: Compute, mut: dict,
                    swap_partner: str | None) -> Compute:
    """A reference-BAD client: compute(), then perturb ONE declared field of
    its output (swap = transpose with the partner field, falling back to a
    changed value when no partner is available; omit = drop the field;
    change = _perturb). Output-only mutation, fixed case params: any verdict
    change is attributable to the declared field (#108 half B)."""
    field, kind = mut["field"], mut["kind"]

    def bad(params: dict) -> dict:
        out = dict(compute(params))
        if field not in out:
            return out  # nothing to mutate -> the case judges as-is
        if kind == "omit":
            out.pop(field)
        elif kind == "swap" and swap_partner and swap_partner in out \
                and out[swap_partner] != out[field]:
            out[field], out[swap_partner] = out[swap_partner], out[field]
        else:
            out[field] = _perturb(out[field])
        return out
    return bad


def mutation_pass(cases: list[dict], compute: Compute | None) -> dict:
    """--mutation: every declared mutation MUST turn its case red. A case
    that stays green under ALL its declared mutations observes nothing its
    author claims distinguishes it -> ``low_discriminativity`` (#108 B)."""
    result: dict = {"mutations": {}, "low_discriminativity": []}
    if compute is None:
        return result  # no live instrumentation -> nothing to discriminate
    for case in cases:
        decls = case["mutations"]
        if not decls:
            continue
        observed = [e["field"] for e in case["expected"] if not e["pending"]]
        rows = []
        for m in decls:
            partner = next((f for f in observed if f != m["field"]), None)
            row = check_case(case, _mutated_client(compute, m, partner))
            rows.append({"field": m["field"], "kind": m["kind"],
                         "red": row["status"] == "fail"})
        result["mutations"][case["id"]] = rows
        if rows and all(not r["red"] for r in rows) \
                and check_case(case, compute)["status"] == "pass":
            result["low_discriminativity"].append(case["id"])
    return result


# ------------------------------------------------------------------ report

def run(cases_dir, client_path, *, mutation: bool = False) -> dict:
    """Run the whole case set. No client -> ALL pending (never green)."""
    cases = load_cases(Path(cases_dir))
    compute = load_client(client_path)
    rows = {c["id"]: check_case(c, compute) for c in cases}
    counts = {"red": 0, "green": 0, "pending": 0}
    for row in rows.values():
        counts[{"fail": "red", "pass": "green",
                "pending": "pending"}[row["status"]]] += 1
    return {
        "schema": SCHEMA_ID,
        "cases_dir": str(cases_dir),
        "client": str(client_path) if compute is not None else None,
        "cases": rows,
        "counts": counts,
        "mutation": mutation_pass(cases, compute)
        if (compute is not None and mutation) else None,
    }


def write_status(ws, report: dict) -> Path:
    """Atomic write of the convergence-convention verdict file. `cases` rows
    are narrowed to the three fields the DRAIN probe reads."""
    path = Path(ws).joinpath(*STATUS_REL)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": SCHEMA_ID,
        "cases": {cid: {"status": r["status"],
                        "pending_entries": r["pending_entries"],
                        "instrumented": r["instrumented"]}
                  for cid, r in report["cases"].items()},
        "low_discriminativity": list(
            (report.get("mutation") or {}).get("low_discriminativity") or []),
        "counts": report["counts"],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return path


def record_posteriors(ws, report: dict) -> Path | None:
    """#106 reuse: a REAL verdict (pass/fail) is one Bernoulli observation on
    the case's CasePosterior (green -> alpha+1 / red -> beta+1). Pending is
    not an observation — no update, no ledger touch. Missing/unreadable
    ledger degrades per posteriors.py's fail-open load contract."""
    import posteriors as po
    updates = {cid: row["status"] == "pass"
               for cid, row in report["cases"].items()
               if row["status"] in ("pass", "fail")}
    if not updates:
        return None
    led = po.PosteriorLedger.load(ws)
    for cid, passed in updates.items():
        cp = led.cases.get(cid) or po.CasePosterior(cid)
        cp.update(passed)
        led.cases[cid] = cp
    return led.save(ws)


# --------------------------------------------------------------------- CLI

def _human(report: dict) -> str:
    lines = [f"=== ORACLE RUN: {report['counts']['green']} green / "
             f"{report['counts']['red']} red / "
             f"{report['counts']['pending']} pending "
             f"(client: {report['client'] or 'NONE — all pending'}) ==="]
    for cid, row in report["cases"].items():
        mark = {"pass": "PASS", "fail": "FAIL",
                "pending": "PEND"}[row["status"]]
        lines.append(f"  [{mark}] {cid} "
                     f"(pending_entries={row['pending_entries']})")
        for f in row["failures"]:
            lines.append(f"         {f}")
        if row["error"]:
            lines.append(f"         error: {row['error']}")
    mut = report.get("mutation") or {}
    for cid, rows in (mut.get("mutations") or {}).items():
        for r in rows:
            lines.append(f"  [MUT] {cid}: {r['field']} {r['kind']} -> "
                         f"{'RED (discriminates)' if r['red'] else 'STAYED GREEN'}")
    for cid in (mut.get("low_discriminativity") or []):
        lines.append(f"  [LOW-DISCRIMINATIVITY] {cid}: green under every "
                     f"declared mutation — the case observes nothing its "
                     f"author claims distinguishes it; strengthen the case "
                     f"or revise its mutation set")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="oracle_runner.py",
        description="kunglao-agent oracle runner — red/green verdicts + "
                    "mutation-must-fail self-test (#108)")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--client", default=None,
                    help="client module path (default: <ws>/oracle/client.py "
                         "when present; without a client every case is pending)")
    ap.add_argument("--mutation", action="store_true",
                    help="run the mutation-must-fail pass over each case's "
                         "declared mutations (flag low_discriminativity)")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable report on stdout")
    args = ap.parse_args(argv)

    ws = Path(args.workspace)
    cases_dir = ws.joinpath(*CASES_REL)
    if not cases_dir.is_dir():
        print(f"oracle_runner: no {cases_dir} — nothing to bless "
              f"(no status written)", file=sys.stderr)
        return 0
    try:
        load_cases(cases_dir)  # lint refusal: loud, before any IO
    except OracleCaseError as exc:
        print(f"oracle_runner: REFUSED — {exc}", file=sys.stderr)
        return 2
    client = args.client
    if client is None:
        default_client = ws.joinpath(*DEFAULT_CLIENT_REL)
        client = str(default_client) if default_client.exists() else None
    report = run(cases_dir, client, mutation=args.mutation)
    write_status(ws, report)
    record_posteriors(ws, report)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
          else _human(report))
    return 1 if report["counts"]["red"] else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
