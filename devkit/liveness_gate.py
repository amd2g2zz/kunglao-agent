#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""devkit/liveness_gate.py — the loop-liveness gate (issue #772, Gate 10).

Development mechanism's feedback edge: for every system face that
claims to decide, learn, or gate, check the LEDGER EVIDENCE that it
fired in a real run (devkit/liveness_fingerprints.json). Repo-internal
checks (types, unit, review) validate consistency; this gate validates
LIVENESS — a fingerprint that cannot pass means the face is decorative.

Two modes:

  --ledger <ws>   evaluate the fingerprints against an existing
                  workspace's ledgers (free; per-PR tier when a live
                  workspace is available)
  --smoke         drive the headless smoke workspace first
                  (scripts/eval_loop_runner.py, smoke tier), then run
                  --ledger on the produced workspace (per-release and
                  nightly tier; spends real budget)

Exit codes: 0 all fingerprints pass; 1 any fingerprint FAIL (the face
is decorative or the wiring is missing); 2 configuration/usage error.
A missing ledger is a FAIL, never a silent skip — absence of evidence
is the failure mode this gate exists to catch.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEVKIT_ROOT = Path(__file__).resolve().parent
FINGERPRINTS_PATH = DEVKIT_ROOT / "liveness_fingerprints.json"
SCRIPTS = DEVKIT_ROOT.parent / "scripts"


def load_fingerprints(path: Path = FINGERPRINTS_PATH) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != "liveness-fingerprints/1":
        raise ValueError(f"unknown fingerprints schema: {data.get('schema')!r}")
    return data


def _latest_log(ws: Path) -> Path | None:
    logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    return logs[-1] if logs else None


def _resolve_ledger(ws: Path, ledger: str) -> Path | None:
    if ledger == "runs/logs/latest":
        return _latest_log(ws)
    return ws / ledger


def _rows(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8",
                               errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _count_jsonl(path: Path, check: dict) -> tuple[int, str]:
    rows = _rows(path)
    all_of = check.get("all_of") or {}
    contains = check.get("contains")
    nonempty = check.get("field_nonempty")
    # any_nonempty: the row qualifies when ANY named field is non-empty —
    # a row family with several historically-equivalent key spellings
    # (posterior-store/1 rows carry `arm` from the cross-task writer and
    # `arm_key` from the workspace credit writer). #807: lets the
    # rl-posterior-moved sentinel require a REAL arm attribution instead
    # of passing on case-level (key-less) posterior rows.
    any_nonempty = check.get("any_nonempty")
    hits = 0
    for rec in rows:
        if any(rec.get(k) != v for k, v in all_of.items()):
            continue
        if contains is not None and contains not in json.dumps(
                rec, ensure_ascii=False):
            continue
        if nonempty is not None and not rec.get(nonempty):
            continue
        if any_nonempty is not None and not any(
                rec.get(f) for f in any_nonempty):
            continue
        hits += 1
    return hits, f"{hits} matching row(s) of {len(rows)}"


def _glob_min(ws: Path, ledger: str, check: dict) -> tuple[int, str]:
    matches = [p for p in ws.glob(ledger) if p.is_file()]
    need_any = check.get("content_any") or []
    qualified = 0
    for p in matches:
        text = p.read_text(encoding="utf-8", errors="replace")
        if not need_any or any(s in text for s in need_any):
            qualified += 1
    return qualified, f"{qualified} qualified file(s) of {len(matches)}"


def evaluate_fingerprint(ws: Path, fp: dict) -> tuple[bool, str]:
    ledger = fp["ledger"]
    check = fp["check"]
    if check["kind"] == "file_glob_min":
        hits, detail = _glob_min(ws, ledger, check)
    else:
        path = _resolve_ledger(ws, ledger)
        if path is None or not path.is_file():
            return False, (f"ledger missing: {ledger} "
                           f"(absence of evidence is the failure)")
        hits, detail = _count_jsonl(path, check)
    minimum = int(check.get("min", 1))
    return hits >= minimum, detail


def run_ledger(ws: Path, fingerprints_path: Path = FINGERPRINTS_PATH,
               as_json: bool = False) -> int:
    ws = Path(ws).resolve()
    if not ws.is_dir():
        print(f"liveness: workspace not found: {ws}", file=sys.stderr)
        return 2
    fps = load_fingerprints(fingerprints_path)["fingerprints"]
    results = []
    failed = 0
    for fp in fps:
        ok, detail = evaluate_fingerprint(ws, fp)
        failed += 0 if ok else 1
        results.append({"id": fp["id"], "pass": ok, "detail": detail})
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {fp['id']}: {detail}")
    verdict = ("LIVE" if failed == 0 else
               f"DECORATIVE ({failed}/{len(fps)} fingerprints dead)")
    print(f"liveness --ledger {ws.name}: {verdict}")
    if as_json:
        print(json.dumps({"workspace": str(ws), "verdict": verdict,
                          "results": results}, ensure_ascii=False))
    return 1 if failed else 0


def run_smoke(out: Path, unit: str, budget_usd: float, wall_cap_s: float,
              fingerprints_path: Path) -> int:
    runner = SCRIPTS / "eval_loop_runner.py"
    if not runner.is_file():
        print(f"liveness: smoke runner missing: {runner}", file=sys.stderr)
        return 2
    cmd = [sys.executable, str(runner), "--tier", "smoke", "--tasks", unit,
           "--budget-usd", str(budget_usd), "--wall-cap-s", str(wall_cap_s),
           "--out", str(out)]
    print(f"liveness --smoke: launching the smoke run ({unit}), "
          f"budget ${budget_usd} / wall {wall_cap_s}s ...")
    rc = subprocess.run(cmd).returncode
    if rc != 0:
        print(f"liveness: smoke runner exited rc={rc} — harvesting what "
              f"exists, but the run did not complete cleanly",
              file=sys.stderr)
    workspaces = sorted((Path(out) / "workspaces").glob("*"))
    if not workspaces:
        print("liveness: no workspace produced — cannot evaluate "
              "fingerprints", file=sys.stderr)
        return 2
    return run_ledger(workspaces[-1], fingerprints_path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ledger", metavar="WS",
                      help="evaluate fingerprints on an existing workspace")
    mode.add_argument("--smoke", action="store_true",
                      help="run the smoke workspace first, then --ledger it")
    ap.add_argument("--fingerprints", default=str(FINGERPRINTS_PATH))
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--unit", default="web-token-v1",
                    help="smoke unit (default: web-token-v1)")
    ap.add_argument("--budget-usd", type=float, default=8.0)
    ap.add_argument("--wall-cap-s", type=float, default=1800.0)
    ap.add_argument("--out", default="kunglao-liveness-smoke")
    args = ap.parse_args(argv)
    if args.ledger:
        return run_ledger(Path(args.ledger), Path(args.fingerprints),
                          args.as_json)
    return run_smoke(Path(args.out), args.unit, args.budget_usd,
                     args.wall_cap_s, Path(args.fingerprints))


if __name__ == "__main__":
    raise SystemExit(main())
