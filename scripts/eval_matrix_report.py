#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_matrix_report.py — the capability-matrix readout face
(pass@k aggregation + the B-ladder decompositions).

The read side of scripts/eval_matrix_runner.py: per arm x unit matrix
over COMPLETED runs, the honest 80/20 gate primitives, the B2
pass@k-at-equal-cost aggregation, and the B-ladder decompositions.
Zero model calls; everything here is read + aggregate over files the
runs wrote.

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

Multi-sample cells (the B2 same-cost face): a multi-sample arm's run
dirs live one level deeper (…/<arm>/<unit>/s0..s{N-1}, one child run per
sample). The cell aggregates them — final_status is pass@k (any PASS
passes), pass_at_k is the 0/1 face of that, budget_usd is the samples'
SUMMED spend (equal cost by the same-cost contract), and the decision
primitives pool across samples. samples names the child-run count.

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

The B-ladder decompositions (report["decompositions"]): three named
rows that split WHERE the value comes from —
  learning_value      B4 - B3   (kunglao-warm vs kunglao-uniform: the
                      LEARNED scheduler's worth on the same harness);
  architecture_value  B3 - B0   (kunglao-uniform vs cc-bare: the static
                      harness's worth without any learning);
  sampling_check      B4 vs B2@equal-cost  (the "is it just more
                      sampling?" rebuttal: warm DTS vs same-cost
                      multi-sample pass@k).
Each row pairs the arms per unit (mean_r deltas), reports the mean
delta with a seeded bootstrap CI over unit resamples, and carries the
honest-stats note. An arm with no data is named missing — a one-sided
matrix renders NO number rather than a fabricated delta.

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
import random
import time
from pathlib import Path

SCHEMA_REPORT = "ws5-matrix-report/1"

# the B-ladder roles: the lettered arms the decompositions read. Fixed
# by the matrix design — the registry is the declaration, this is the
# reading.
DECOMPOSITION_ARMS = {
    "learning_value": {
        "label": ("learning value — the warm DTS scheduler vs the "
                  "frozen uniform one on the same harness"),
        "formula": "B4 - B3",
        "arm_a": "kunglao-warm",
        "arm_b": "kunglao-uniform",
        # readout-only tier slice: the B4-B3 delta decomposed by unit
        # tier (the over-reasoning alarm reads the simple-unit slice —
        # evidence sliced for reading, never a dispatch flag)
        "tier_slice": True},
    "architecture_value": {
        "label": ("architecture value — the static harness vs bare CC "
                  "with learning frozen"),
        "formula": "B3 - B0",
        "arm_a": "kunglao-uniform",
        "arm_b": "cc-bare"},
    "sampling_check": {
        "label": ("sampling rebuttal — warm DTS vs bare-CC multi-sample "
                  "at the same total budget"),
        "formula": "B4 vs B2@equal-cost",
        "arm_a": "kunglao-warm",
        "arm_b": "cc-multisample"},
}
# the bootstrap is seeded: the same matrix renders the same CI twice
# (determinism wall — no lucky intervals)
BOOTSTRAP_DRAWS = 1000
BOOTSTRAP_SEED = 569
HONEST_STATS_NOTE = ("paired across units (mean_r deltas), multi-seed "
                     "by construction (one seed per arm run), 95% "
                     "bootstrap CI over unit resamples — discipline, "
                     "not verdict: small-N intervals are wide and say "
                     "so")


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


def _rewarded_rows(ws: Path | None) -> list[dict]:
    """Reward-carrying transition rows (the decision primitives' raw
    material); absent or dirty rows are skipped, never invented."""
    if not ws:
        return []
    return [r for r in read_transitions(ws)
            if r.get("r_incr") is not None]


def _decision_primitives(ws: Path | None) -> dict:
    """Per-run decision primitives off the workspace's transition ledger:
    decisions (rewarded rows), learned (propensity-bearing), mean r."""
    rows = _rewarded_rows(ws)
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


def _sample_dirs(unit_dir: Path) -> list[Path]:
    """The B2 sample run dirs (…/<unit>/s0, s1, …) under a unit dir,
    in index order; empty when the cell is a single-run face."""
    if not unit_dir.is_dir():
        return []
    out = []
    for d in unit_dir.iterdir():
        if d.is_dir() and len(d.name) > 1 and d.name.startswith("s") \
                and d.name[1:].isdigit():
            out.append(d)
    return sorted(out, key=lambda p: int(p.name[1:]))


def _aggregate_samples(unit_dir: Path, samples: list[Path],
                       spine_rows: list[dict]) -> dict:
    """The B2 cell: pass@k over the sample runs at summed (equal) cost.
    Each sample is read on its own; the aggregation invents nothing —
    a sample with no results doc rides its spine row's state, or
    counts as missing."""
    spine_by_sample = {}
    for row in spine_rows:
        try:
            spine_by_sample[int(row.get("sample") or 0)] = row
        except (TypeError, ValueError):
            continue
    statuses: list[str] = []
    verdicts: list[str] = []
    costs: list[float] = []
    wall = None
    transitions = 0
    facts = 0
    rows_all: list[dict] = []
    for i, sample_dir in enumerate(samples):
        doc = newest_results_doc(sample_dir)
        if doc and doc.get("rows"):
            child_row = doc["rows"][0]
            loop = child_row.get("loop") or {}
            session = loop.get("session") or {}
            verdict = child_row.get("verdict")
            if verdict:
                verdicts.append(str(verdict))
            statuses.append(str(verdict))
            cost = (session.get("session_cost") or {}).get(
                "total_cost_usd")
            if cost is not None:
                costs.append(float(cost))
            s_wall = session.get("wall_s")
            if s_wall is not None:
                wall = max(wall or 0.0, float(s_wall))
            ws = loop.get("workspace")
        else:
            spine = spine_by_sample.get(i) or {}
            statuses.append(str(spine.get("status") or "missing"))
            ws = spine.get("workspace")
        transitions += _transitions_count(ws)
        facts += _facts_count(ws)
        rows_all.extend(_rewarded_rows(ws))
    cell: dict = {
        "arm": unit_dir.parent.name, "unit": unit_dir.name,
        "samples": len(samples)}
    if not verdicts:
        cell["final_status"] = statuses[0] if statuses else "missing"
    elif "PASS" in verdicts:
        cell["final_status"] = "PASS"  # pass@k: any PASS passes
    elif "FAIL" in verdicts:
        cell["final_status"] = "FAIL"
    else:
        cell["final_status"] = statuses[0]
    cell["pass_at_k"] = (1.0 if "PASS" in verdicts
                         else (0.0 if verdicts else None))
    cell["budget_usd"] = round(sum(costs), 6) if costs else None
    cell["wall_s"] = wall
    cell["transitions"] = transitions
    cell["facts"] = facts
    if rows_all:
        rs = [float(r["r_incr"]) for r in rows_all]
        cell["decisions"] = len(rows_all)
        cell["learned_decisions"] = sum(
            1 for r in rows_all if r.get("propensity") is not None)
        cell["mean_r"] = round(sum(rs) / len(rs), 6)
    else:
        cell.update({"decisions": 0, "learned_decisions": 0,
                     "mean_r": None})
    return cell


def _attach_tier(cell: dict, spine_row: dict) -> dict:
    """A cell's unit tier, when the spine row knows it (the launcher
    declares tiers; the report only reads them — the readout-only tier
    slice's raw material). Cells without tier knowledge carry no tier
    field at all (absence is a state, never an invented label)."""
    tier = spine_row.get("tier")
    if isinstance(tier, str) and tier:
        cell["tier"] = tier
    return cell


def _collect_matrix(out: Path, by_cell: dict[tuple[str, str],
                                             list[dict]]) -> list[dict]:
    """Per arm x unit cells over the run dirs on disk, enriched from the
    progress spine when it knows the cell. Multi-sample cells (the B2
    face) aggregate their sample dirs; cells that never created a run
    dir still surface from the spine (a refusal is a state, not an
    absence)."""
    matrix: list[dict] = []
    seen: set[tuple[str, str]] = set()
    arm_dirs = sorted(d for d in out.iterdir() if d.is_dir()) \
        if out.is_dir() else []
    for arm_dir in arm_dirs:
        for unit_dir in sorted(d for d in arm_dir.iterdir() if d.is_dir()):
            arm, unit = arm_dir.name, unit_dir.name
            seen.add((arm, unit))
            spine_rows = by_cell.get((arm, unit)) or []
            spine = spine_rows[0] if spine_rows else {}
            samples = _sample_dirs(unit_dir)
            if samples:
                matrix.append(_aggregate_samples(
                    unit_dir, samples, spine_rows))
                continue
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
                matrix.append(_attach_tier({
                    "arm": arm, "unit": unit,
                    "final_status": child_row.get("verdict"),
                    "loop_status": loop.get("status"),
                    "budget_usd": cost,
                    "wall_s": session.get("wall_s"),
                    "transitions": _transitions_count(ws),
                    "facts": _facts_count(ws),
                    **_decision_primitives(ws)}, spine))
            else:
                status = spine.get("status") or "missing"
                matrix.append(_attach_tier(
                    {"arm": arm, "unit": unit,
                     "final_status": status,
                     "transitions": _transitions_count(ws),
                     "facts": _facts_count(ws),
                     **_decision_primitives(ws)}, spine))
    # spine-only cells: the launcher refused/planned them before any run
    # dir existed — reported states, never silent absences
    for (arm, unit), rows in sorted(by_cell.items()):
        if (arm, unit) in seen:
            continue
        sample_count = max(
            [int(r["sample_count"]) for r in rows
             if isinstance(r.get("sample_count"), int)] or [1])
        cell = _attach_tier({"arm": arm, "unit": unit,
                             "final_status": rows[0].get("status")
                             or "missing",
                             "transitions": 0, "facts": 0,
                             "decisions": 0, "learned_decisions": 0,
                             "mean_r": None}, rows[0])
        if sample_count > 1:
            cell["samples"] = sample_count
        if rows[0].get("detail"):
            cell["detail"] = rows[0]["detail"]
        matrix.append(cell)
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


def _pass_rate(arm_cells: dict[str, dict], units: list[str]) -> float | None:
    """The arm's PASS share over the paired units (a B2 arm's cell
    verdicts ARE pass@k by the aggregation)."""
    if not units:
        return None
    hits = sum(1 for u in units
               if arm_cells[u].get("final_status") == "PASS")
    return round(hits / len(units), 4)


def _bootstrap_ci(values: list[float]) -> list[float]:
    """The seeded 95% bootstrap CI over unit resamples (percentile
    face): same matrix in, same interval out — no lucky intervals."""
    n = len(values)
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_DRAWS):
        sample = [values[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * (BOOTSTRAP_DRAWS - 1))]
    hi = means[int(0.975 * (BOOTSTRAP_DRAWS - 1))]
    return [round(lo, 6), round(hi, 6)]


def _decompositions(matrix: list[dict]) -> dict:
    """The three named B-ladder rows. Each pairs its arms per unit on
    mean_r, reports the mean delta with the seeded bootstrap CI and the
    pass-rate face, and names any arm with no data — a one-sided matrix
    renders NO number rather than a fabricated delta. The learning_value
    row additionally slices its paired deltas by unit tier (when the
    spine knows the unit's tier) — read-only aggregation; units without
    tier knowledge are excluded from the slice (never an invented
    label)."""
    cells_by_arm: dict[str, dict[str, dict]] = {}
    for cell in matrix:
        cells_by_arm.setdefault(cell["arm"], {})[cell["unit"]] = cell
    out: dict[str, dict] = {}
    for name, spec in DECOMPOSITION_ARMS.items():
        missing = [arm for arm in (spec["arm_a"], spec["arm_b"])
                   if arm not in cells_by_arm]
        if missing:
            out[name] = {**spec, "missing_arms": missing}
            continue
        arm_a = cells_by_arm[spec["arm_a"]]
        arm_b = cells_by_arm[spec["arm_b"]]
        units = sorted(set(arm_a) & set(arm_b))
        deltas: dict[str, float] = {}
        for u in units:
            ra = arm_a[u].get("mean_r")
            rb = arm_b[u].get("mean_r")
            if ra is None or rb is None:
                continue
            deltas[u] = round(float(ra) - float(rb), 6)
        row = {**spec, "units": units,
               "pass_rate_a": _pass_rate(arm_a, units),
               "pass_rate_b": _pass_rate(arm_b, units)}
        if deltas:
            vals = list(deltas.values())
            row["per_unit"] = deltas
            row["mean_delta"] = round(sum(vals) / len(vals), 6)
            row["ci95"] = _bootstrap_ci(vals)
            if spec.get("tier_slice"):
                tiers = _tier_slice(arm_a, arm_b, deltas)
                if tiers:
                    row["tiers"] = tiers
        row["note"] = (HONEST_STATS_NOTE if deltas else
                       "no paired units with measurable reward yet — "
                       "the decomposition waits for data")
        out[name] = row
    return out


def _tier_or_none(cell_a: dict, cell_b: dict):
    """A paired unit's tier: the spine's declaration when either cell
    knows it; None when no face knows — never an invented label."""
    for cell in (cell_a, cell_b):
        tier = cell.get("tier")
        if isinstance(tier, str) and tier:
            return tier
    return None


def _tier_slice(arm_a: dict, arm_b: dict, deltas: dict) -> dict:
    """The learning_value delta sliced by unit tier: per-tier paired
    units, mean delta, and the same seeded bootstrap CI discipline as
    the whole-matrix row. Tiers render in sorted order (determinism);
    the slice is readout-only — no dispatch face consumes it."""
    by_tier: dict[str, list] = {}
    for u in sorted(deltas):
        tier = _tier_or_none(arm_a.get(u) or {}, arm_b.get(u) or {})
        if tier is None:
            continue
        acc = by_tier.setdefault(tier, [[], {}])
        acc[0].append(u)
        acc[1][u] = deltas[u]
    out: dict[str, dict] = {}
    for tier in sorted(by_tier):
        units, per_unit = by_tier[tier]
        vals = [per_unit[u] for u in units]
        out[tier] = {"units": units,
                     "per_unit": per_unit,
                     "mean_delta": round(sum(vals) / len(vals), 6),
                     "ci95": _bootstrap_ci(vals)}
    return out


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
    by_cell: dict[tuple[str, str], list[dict]] = {}
    for row in (progress or {}).get("runs", []):
        by_cell.setdefault(
            (row.get("arm"), row.get("unit")), []).append(row)
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
              "arms": dict(sorted(_aggregate_arms(matrix).items())),
              "decompositions": _decompositions(matrix)}
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
    # the B-ladder decompositions: the three named rows beneath the arm
    # aggregates — a missing arm renders WAITING, never a fabricated
    # number
    dec = report.get("decompositions") or {}
    if dec:
        print("=" * len(header))
        for name, row in dec.items():
            if "missing_arms" in row:
                print(f"{name}: {row['formula']} — WAITING (missing: "
                      f"{', '.join(row['missing_arms'])})")
            elif "per_unit" not in row:
                print(f"{name}: {row['formula']} — WAITING "
                      f"({row['note']})")
            else:
                print(f"{name}: {row['formula']} = {row['mean_delta']} "
                      f"ci95={row['ci95']} "
                      f"(pass {row['pass_rate_a']} vs "
                      f"{row['pass_rate_b']})")
                for tier in sorted(row.get("tiers") or {}):
                    face = row["tiers"][tier]
                    print(f"  tier {tier}: mean_delta={face['mean_delta']} "
                          f"ci95={face['ci95']} n={len(face['units'])}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_matrix_report.py",
        description="the seven-arm matrix readout — aggregate completed "
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
