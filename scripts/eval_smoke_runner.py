#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_smoke_runner.py — smoke-tier runner (the eval-dataset card) (release-train gate face).

Runs the whole smoke tier (constructed targets, minutes-scale) through the
mechanical checker and aggregates evidence-bar-shaped results rows:

  - default arm is self-check: the tier's own reference candidates (the
    constructed targets) must green their oracles — oracle liveness is
    part of the gate (a checker that greens anything is a stamp);
  - --candidate-for <task_id>=<path> plugs an external arm's artifacts in
    (the bare-LLM control arm executes on the smoke tier through
    exactly this surface); label the rows with --arm <name>;
  - --baselines appends the 1/k-guessing baseline rows (p = 2^-space_bits,
    arithmetic — no run) — the bare-LLM comparison floor; the historical-
    self arm is the historical-replay lane, not this lane;
  - --tasks <id,id> scopes a run (unknown id = refusal, exit 2).

A run writes one results JSON (kunglao-eval-results/1: eval_version, tier,
arm, rows, summary) under --out (default runs/eval-smoke/), and appends
METRIC/VERDICT lines from the per-task checkers to stdout. Any task FAIL
is a nonzero exit; toolchain SKIPs are structured, never silent holes.

Usage: eval_smoke_runner.py [--tier smoke] [--tasks id,id] [--arm NAME]
                            [--candidate-for task=path ...] [--baselines]
                            [--out DIR]
stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import eval_dataset as ds

TIERS = {"smoke": {"desc": "3-5 constructed targets, minutes-scale, "
                           "runnable per release train"}}

RC_OK, RC_FAIL, RC_REFUSED = 0, 1, 2


def _parse_candidates(items: list[str]) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for item in items:
        task_id, sep, path = item.partition("=")
        if not sep or not task_id or not path:
            raise SystemExit(f"FAIL: --candidate-for wants task_id=path, "
                             f"got {item!r}")
        mapping[task_id] = Path(path)
    return mapping


def _parse_output(proc_text: str) -> dict:
    """Parse the checker stream: METRIC / FAILURE / EVIDENCE / VERDICT."""
    out: dict[str, object] = {"metrics": {}, "failures": []}
    for line in proc_text.splitlines():
        if line.startswith("METRIC "):
            _key, _, val = line[len("METRIC "):].partition("=")
            try:
                out["metrics"][_key] = json.loads(val)
            except json.JSONDecodeError:
                out["metrics"][_key] = val
        elif line.startswith("FAILURE "):
            # detail may contain spaces: split on the detail= marker only,
            # never on the detail's own words (the aggregated row must not
            # truncate the evidence)
            rest = line[len("FAILURE "):]
            head, marker, detail = rest.partition("detail=")
            code = head.strip()
            if code.startswith("code="):
                code = code[len("code="):]
            out["failures"].append({
                "code": code.strip(),
                "detail": detail if marker else "",
            })
        elif line.startswith("EVIDENCE "):
            out["evidence"] = line[len("EVIDENCE "):].strip()
        elif line.startswith("VERDICT "):
            out["verdict"] = line[len("VERDICT "):].strip()
    return out


def _load_unit_meta(task_dir: Path) -> dict:
    return ds.load_task(task_dir)


def run_task(task_dir: Path, candidate: Path, out: Path) -> dict:
    """One checker subprocess per task (runner-style: a run emits METRIC
    lines; the runner parses the stream)."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "eval_checker.py"),
         "--task", str(task_dir), "--candidate", str(candidate),
         "--out", str(out)],
        capture_output=True, text=True, timeout=240)
    meta = _load_unit_meta(task_dir)
    parsed = _parse_output(proc.stdout)
    verdict = parsed.get("verdict") or {
        0: "PASS", 1: "FAIL", 2: "REFUSED", 3: "SKIP"}.get(proc.returncode, "FAIL")
    return {
        "task_id": task_dir.name,
        "family": meta["family"],
        "checker_kind": meta["checker"]["kind"],
        "metrics": parsed["metrics"],
        "verdict": verdict,
        "failures": parsed["failures"],
        "evidence": parsed.get("evidence", ""),
        "checker_rc": proc.returncode,
    }


def run_tier(tasks: list[str], tier: str, arm: str, candidates: dict[str, Path],
             baselines: bool, out: Path) -> tuple[int, dict]:
    """Run the tier; returns (exit_code, results_doc)."""
    started = time.time()
    out.mkdir(parents=True, exist_ok=True)
    all_dirs = ds.iter_task_dirs(tier=tier)
    known = {d.name for d in all_dirs}
    unknown = [t for t in tasks if t not in known]
    if unknown:
        print(f"FAILURE code=BAD_TASK detail=unknown task(s): {unknown}")
        print("VERDICT REFUSED")
        return RC_REFUSED, {}
    selected = [d for d in all_dirs if not tasks or d.name in tasks]

    rows: list[dict] = []
    for tdir in selected:
        task = _load_unit_meta(tdir)
        if arm == "self-check" or tdir.name in candidates:
            candidate = candidates.get(tdir.name) or (tdir / task["workspace_scaffold"]["entry"])
            res = run_task(tdir, candidate, out)
            row = ds.results_row(
                task_id=res["task_id"], family=res["family"],
                checker_kind=res["checker_kind"], metrics=res["metrics"],
                verdict=res["verdict"], failures=res["failures"],
                evidence_ref=res["evidence"], arm=arm)
            rows.append(row)
            for name, value in res["metrics"].items():
                print(ds.metric_line(f"{tdir.name}.{name}", value))
            print(f"VERDICT {tdir.name} {res['verdict']}")
        else:
            rows.append(ds.results_row(
                task_id=tdir.name, family=task["family"],
                checker_kind=task["checker"]["kind"],
                metrics={m: 0 for m in ds.REQUIRED_METRICS},
                verdict="SKIP", failures=[{
                    "code": "BAD_CANDIDATE",
                    "detail": f"arm {arm!r} provides no candidate for "
                              f"{tdir.name} (pass --candidate-for)"}],
                evidence_ref="", arm=arm))
            print(f"VERDICT {tdir.name} SKIP")
        if baselines:
            gt = json.loads((tdir / task["ground_truth"]["file"])
                            .read_text(encoding="utf-8"))
            p_guess = ds.guess_pass_p(gt["space_bits"])
            rows.append({
                "task_id": tdir.name, "family": task["family"],
                "checker_kind": task["checker"]["kind"],
                "metrics": {m: 0 for m in ds.REQUIRED_METRICS},
                "verdict": "EXPECTED-FAIL",
                "failures": [], "evidence_ref": "", "arm": "guess-1ofk",
                "guess_pass_p": p_guess,
            })
            print(f"VERDICT {tdir.name} guess-1ofk EXPECTED-FAIL "
                  f"(p={p_guess:.2e})")

    summary = {
        "pass": sum(1 for r in rows if r["arm"] == arm and r["verdict"] == "PASS"),
        "fail": sum(1 for r in rows if r["arm"] == arm and r["verdict"] == "FAIL"),
        "skip": sum(1 for r in rows if r["arm"] == arm and r["verdict"] == "SKIP"),
        "refused": sum(1 for r in rows if r["arm"] == arm and r["verdict"] == "REFUSED"),
        "baselines": sum(1 for r in rows if r["arm"] == "guess-1ofk"),
        "wall_seconds": round(time.time() - started, 2),
        # skip reasons travel in the summary: a skipped task is NOT an
        # executed one, and consumers must see why without opening evidence
        "skips": [
            {"task_id": r["task_id"],
             "reason": (r["failures"][0].get("detail")
                        if r["failures"] else "checker reported SKIP")}
            for r in rows
            if r["arm"] == arm and r["verdict"] == "SKIP"],
    }
    doc = {
        "schema": ds.RESULTS_SCHEMA,
        "eval_version": ds.EVAL_VERSION,
        "tier": tier,
        "arm": arm,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rows": rows,
        "summary": summary,
    }
    results_path = out / (
        f"eval-results-{time.strftime('%Y%m%dT%H%M%SZ')}-{os.getpid() % 100000}.json")
    results_path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"RESULTS {results_path}")
    print(f"SUMMARY pass={summary['pass']} fail={summary['fail']} "
          f"skip={summary['skip']} wall_seconds={summary['wall_seconds']}")
    rc = RC_FAIL if summary["fail"] or summary["refused"] else RC_OK
    # a skip must never read as a clean PASS: with skip>0 the tier verdict
    # is PARTIAL (rc stays 0 — a SKIP is legal, not a failure — but the
    # token is distinct so no consumer mistakes it for full execution)
    verdict_token = ("FAIL" if rc != RC_OK
                     else "PASS" if summary["skip"] == 0 else "PARTIAL")
    print(f"VERDICT {verdict_token}")
    return rc, doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_smoke_runner.py",
        description="#299 smoke-tier runner: mechanical oracles, METRIC "
                    "emission, evidence archive, #295-shaped results.")
    ap.add_argument("--tier", default="smoke", choices=sorted(TIERS))
    ap.add_argument("--tasks", default="",
                    help="comma-separated task ids (default: whole tier)")
    ap.add_argument("--arm", default="self-check",
                    help="row label: self-check | bare-llm | guess-1ofk | ...")
    ap.add_argument("--candidate-for", action="append", default=[],
                    help="task_id=path to an external arm's candidate "
                         "(repeatable; enables the #236 control arm)")
    ap.add_argument("--baselines", action="store_true",
                    help="append 1/k-guessing baseline rows (p=2^-space_bits)")
    ap.add_argument("--out", default=str(ds.EVAL_ROOT.parent / "runs" / "eval-smoke"),
                    help="output dir (default: runs/eval-smoke/)")
    args = ap.parse_args(argv)

    candidates = _parse_candidates(args.candidate_for)
    tasks = [t for t in args.tasks.split(",") if t]
    rc, _ = run_tier(tasks, args.tier, args.arm, candidates,
                     args.baselines, Path(args.out))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
