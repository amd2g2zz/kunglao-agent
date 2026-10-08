#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_matrix_report.py — the five-arm matrix readout face.

The read side of scripts/eval_matrix_runner.py: per arm x unit matrix
over COMPLETED runs, plus the honest 80/20 gate primitives. Zero model
calls; everything here is read + aggregate over files the runs wrote.

Per cell (one (arm, unit) run):
  final_status    the mechanical checker verdict (PASS / FAIL / SKIP /
                  REFUSED) or the spine's run state (planned / refused /
                  unresolvable / child_error / missing);
  loop_status     the session's terminal class (completed / exhausted /
                  session_error / ...);
  budget_usd      the session's own cost report total (None = unknown —
                  never invented);
  wall_s          the session wall clock the child runner measured;
  transitions     rows in the workspace's transition ledger;
  facts           fact files the workspace banked (facts/F*.md);
  decisions       transition rows that closed with a reward (r_incr);
  learned_decisions  decisions carrying a propensity (policy-sampled,
                  not rule-fired);
  mean_r          mean r_incr over the arm's decisions.

The 80/20 gate — honest primitives, not a verdict: the umbrella target
("80% learned decisions + 20% rules, measured by regret-weighted
decision points") does not pin a per-decision definition, so this face
emits what the ledgers honestly support:
  learned_share   learned_decisions / decisions per arm — the measured
                  share of decisions the POLICY took (the 80 numerator's
                  honest reading);
  regret_vs_best_arm  per unit: the best arm's mean_r minus this arm's
                  mean_r. The post-hoc best arm IS an oracle read (it
                  needs all arms' outcomes to exist) — an upper bound on
                  what the policy left on the table, not an online
                  regret. Summed per arm as regret_total over the cells
                  where the face applies.
Redefining the gate is the owner's call; these primitives do not move.

Reads the progress spine (progress.json from the launcher) when present
and falls back to scanning run dirs — a partially-run matrix reports
what exists and names what does not (missing is a measurement state,
never an invention).

Usage (usually through the launcher):
  eval_matrix_report.py --out runs/ws5-matrix/<run-id>

stdlib + yaml only (the repo's runtime deps).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

SCHEMA_REPORT = "ws5-matrix-report/1"


def newest_results_doc(run_dir: Path) -> dict | None:
    """The child runner's newest kunglao-eval-results doc in a run dir."""
    hits = sorted(Path(run_dir).glob("eval-results-*.json"))
    if not hits:
        return None
    try:
        return json.loads(hits[-1].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def read_transitions(ws: Path) -> list[dict]:
    """The workspace's transition ledger rows (oldest first); absent or
    dirty rows are skipped, never invented (the ledger's own posture)."""
    p = Path(ws) / "runs" / "transitions.jsonl"
    if not p.is_file():
        return []
    rows = []
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
            rows.append(row)
    return rows


def _decision_primitives(ws: Path | None) -> dict:
    """Per-run decision primitives off the workspace's transition ledger:
    decisions (rewarded rows), learned (propensity-bearing), mean r."""
    if not ws:
        return {"decisions": 0, "learned_decisions": 0, "mean_r": None}
    rows = [r for r in read_transitions(ws)
            if r.get("r_incr") is not None]
    if not rows:
        return {"decisions": 0, "learned_decisions": 0, "mean_r": None}
    rs = [float(r["r_incr"]) for r in rows]
    return {"decisions": len(rows),
            "learned_decisions": sum(
                1 for r in rows if r.get("propensity") is not None),
            "mean_r": round(sum(rs) / len(rs), 6)}


def _facts_count(ws: Path | None) -> int:
    if not ws:
        return 0
    return len(list((Path(ws) / "facts").glob("F*.md")))


def _transitions_count(ws: Path | None) -> int:
    return len(read_transitions(ws)) if ws else 0


def _collect_matrix(out: Path, by_cell: dict[tuple[str, str], dict]) \
        -> list[dict]:
    """Per arm x unit cells over the run dirs on disk, enriched from the
    progress spine when it knows the cell."""
    matrix: list[dict] = []
    arm_dirs = sorted(d for d in out.iterdir() if d.is_dir()) \
        if out.is_dir() else []
    for arm_dir in arm_dirs:
        for unit_dir in sorted(d for d in arm_dir.iterdir() if d.is_dir()):
            arm, unit = arm_dir.name, unit_dir.name
            spine = by_cell.get((arm, unit), {})
            doc = newest_results_doc(unit_dir)
            if doc is None and not spine:
                matrix.append({"arm": arm, "unit": unit,
                               "final_status": "missing"})
                continue
            ws = spine.get("workspace")
            if doc and doc.get("rows"):
                child_row = doc["rows"][0]
                loop = child_row.get("loop") or {}
                session = loop.get("session") or {}
                cost = (session.get("session_cost") or {}).get(
                    "total_cost_usd")
                ws = loop.get("workspace") or ws
                matrix.append({
                    "arm": arm, "unit": unit,
                    "final_status": child_row.get("verdict"),
                    "loop_status": loop.get("status"),
                    "budget_usd": cost,
                    "wall_s": session.get("wall_s"),
                    "transitions": _transitions_count(ws),
                    "facts": _facts_count(ws),
                    **_decision_primitives(ws)})
            else:
                status = spine.get("status") or "missing"
                matrix.append({"arm": arm, "unit": unit,
                               "final_status": status,
                               "transitions": _transitions_count(ws),
                               "facts": _facts_count(ws),
                               **_decision_primitives(ws)})
    return matrix


def _aggregate_arms(matrix: list[dict]) -> dict[str, dict]:
    """Per-arm aggregation: verdict counts, decision counts, and the
    regret total over the cells where the face applies."""
    arms: dict[str, dict] = {}
    for cell in matrix:
        acc = arms.setdefault(cell["arm"], {
            "units": 0, "pass": 0, "fail": 0, "other": 0,
            "decisions": 0, "learned_decisions": 0,
            "regret_total": 0.0, "regret_cells": 0})
        acc["units"] += 1
        verdict = cell.get("final_status")
        if verdict == "PASS":
            acc["pass"] += 1
        elif verdict == "FAIL":
            acc["fail"] += 1
        else:
            acc["other"] += 1
        acc["decisions"] += cell.get("decisions", 0) or 0
        acc["learned_decisions"] += (
            cell.get("learned_decisions", 0) or 0)
        regret = cell.get("regret_vs_best_arm")
        if regret is not None:
            acc["regret_total"] = round(acc["regret_total"] + regret, 6)
            acc["regret_cells"] += 1
    for acc in arms.values():
        acc["learned_share"] = (
            round(acc["learned_decisions"] / acc["decisions"], 4)
            if acc["decisions"] else None)
    return arms


def build_report(out: Path, progress: dict | None = None) -> dict:
    """The readout doc: per arm x unit matrix plus arm aggregates, with
    the regret face applied. ``progress`` is the launcher's spine doc;
    when it is not passed, the spine is read from <out>/progress.json
    (absent = the run dirs alone are the truth)."""
    out = Path(out)
    if progress is None:
        spine_path = out / "progress.json"
        if spine_path.is_file():
            try:
                progress = json.loads(
                    spine_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                progress = None
    by_cell: dict[tuple[str, str], dict] = {}
    for row in (progress or {}).get("runs", []):
        by_cell[(row.get("arm"), row.get("unit"))] = row
    matrix = _collect_matrix(out, by_cell)
    # the regret face: per unit, best-arm mean_r anchors the post-hoc
    # upper bound; each arm's regret is what it left on the table
    best: dict[str, float] = {}
    for cell in matrix:
        mr = cell.get("mean_r")
        if mr is None:
            continue
        arm_best = best.get(cell["unit"])
        best[cell["unit"]] = mr if arm_best is None else max(arm_best, mr)
    for cell in matrix:
        mr = cell.get("mean_r")
        cell["regret_vs_best_arm"] = (
            None if mr is None or cell["unit"] not in best
            else round(best[cell["unit"]] - mr, 6))
    report = {"schema": SCHEMA_REPORT,
              "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "out": str(out),
              "note": ("80/20 gate: honest primitives only — regret is "
                       "measured against the post-hoc best arm per unit "
                       "(an oracle read), learned share is the "
                       "propensity-bearing fraction of rewarded "
                       "decisions. The gate definition itself is the "
                       "owner's call."),
              "matrix": matrix,
              "arms": dict(sorted(_aggregate_arms(matrix).items()))}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n",
                                     encoding="utf-8")
    return report


def print_report(report: dict) -> None:
    """The stdout table: one row per arm x unit, arms aggregated after."""
    header = (f"{'ARM':22} {'UNIT':26} {'STATUS':9} {'LOOP':11} "
              f"{'USD':>7} {'TRANS':>5} {'FACTS':>5} {'DEC':>4} "
              f"{'LEARNED':>7} {'MEAN_R':>8} {'REGRET':>8}")
    print(header)
    print("-" * len(header))
    for cell in report["matrix"]:
        if cell.get("final_status") == "missing" and "decisions" not in \
                cell:
            print(f"{cell['arm']:22} {cell['unit']:26} MISSING")
            continue
        print(f"{cell['arm']:22} {cell['unit']:26} "
              f"{str(cell.get('final_status')):9} "
              f"{str(cell.get('loop_status')):11} "
              f"{str(cell.get('budget_usd'))[:7]:>7} "
              f"{cell.get('transitions', 0):>5} "
              f"{cell.get('facts', 0):>5} "
              f"{cell.get('decisions', 0):>4} "
              f"{str(cell.get('learned_decisions')):>7} "
              f"{str(cell.get('mean_r'))[:8]:>8} "
              f"{str(cell.get('regret_vs_best_arm'))[:8]:>8}")
    print("-" * len(header))
    for arm, acc in report["arms"].items():
        print(f"{arm:22} units={acc['units']} pass={acc['pass']} "
              f"fail={acc['fail']} other={acc['other']} "
              f"decisions={acc['decisions']} "
              f"learned={acc['learned_decisions']} "
              f"learned_share={acc['learned_share']} "
              f"regret_total={acc['regret_total']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_matrix_report.py",
        description="the five-arm matrix readout — aggregate completed "
                    "runs into the arm x unit matrix + 80/20 primitives")
    ap.add_argument("--out", required=True,
                    help="matrix output dir (the launcher's --out)")
    args = ap.parse_args(argv)
    report = build_report(Path(args.out))
    print_report(report)
    print(f"REPORT {Path(args.out) / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
