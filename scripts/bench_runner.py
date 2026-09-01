#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench_runner.py — lane runner (B4, #823 AB-VALUE).

Schedules paired two-arm runs from the bench manifest:

  lanes         A = the N arm, SERIAL in stratum order (priors update
                only from receipted runs — parallel N is contamination);
                B/C = the O pool, parallel.
  budgets       max-turns is the PRIMARY budget; the wall cap exists
                only to catch hangs (S3 ceiling = the user-ruled 8h).
                task_spec.time_budget = the stratum budget (the agent
                must know its real budget — #823 ETA input).
  arm switch    env KUNGLAO_VALUE_ALGO for N; O runs with the flag
                absent (byte-identical dev behavior).
  terminal      done / timeout (LEGAL terminal, z=0, workspace FROZEN
                for grading) / crashed (infrastructure — rerun, not a
                sample failure, not contamination).

Deterministic: same manifest seed → same plan (arm order, workspace
names). --dry-run prints the plan and executes nothing.

The default executor shells out to `claude -p` with
--permission-mode acceptEdits and NEVER --dangerously-skip-permissions;
tests inject a stub instead.

Usage: bench_runner.py <manifest.yaml> --stratum S3 --lane A
                      [--dry-run] [--out-dir runs/]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

RECEIPT_SCHEMA = "kunglao-bench-run/1"

# user-ruled final budget table (plan B4): max-turns primary, wall hard
# caps only against hangs, task_spec budget = stratum cap
BUDGETS = {
    "S1": {"max_turns": 700, "wall_h": 6, "budget_min": 360},
    "S2": {"max_turns": 800, "wall_h": 6, "budget_min": 360},
    "S3": {"max_turns": 900, "wall_h": 8, "budget_min": 480},
    "S4": {"max_turns": 500, "wall_h": 4, "budget_min": 240},
}

LANE_ARMS = {"A": "N", "B": "O", "C": "O"}


def arm_env(arm: str) -> dict:
    """The ONLY difference between arms (AB-DESIGN §3)."""
    return {"KUNGLAO_VALUE_ALGO": "1"} if arm == "N" else {}


def _load_manifest(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
        raise SystemExit(f"FAIL: bad manifest: {path}")
    return data


def build_plan(manifest_path: Path, stratum: str, lane: str) -> list[dict]:
    """Deterministic run specs for one stratum × lane. Same seed → same
    plan (workspace names, order)."""
    data = _load_manifest(manifest_path)
    arm = LANE_ARMS[lane]
    budget = BUDGETS[stratum]
    samples = sorted(s["id"] for s in data["samples"]
                     if s.get("stratum") == stratum)
    rng = random.Random(data.get("seed", 0))
    # one draw per sample fixes the pair-order stream; both lanes of a
    # pair read the same stream so the bookkeeping stays comparable
    pair_order = {s: rng.choice(("O", "N")) for s in samples}
    plan = []
    for sid in samples:
        plan.append({
            "sample": sid,
            "stratum": stratum,
            "arm": arm,
            "serial": lane == "A",
            "pair_order": pair_order[sid],
            "workspace": f"bench-{stratum.lower()}-{sid}-{arm.lower()}",
            "env": arm_env(arm),
            "max_turns": budget["max_turns"],
            "wall_cap_s": budget["wall_h"] * 3600,
            "budget_min": budget["budget_min"],
        })
    return plan


def _default_executor(spec: dict) -> dict:
    """Real run seam. The bench entry prompt + workspace bootstrap land
    with Stage C1/C2 (sample vault wiring); the contract — outcome ∈
    {done, timeout}, compaction_count, transcript path — is fixed here."""
    env = dict(os.environ)
    env.update(spec["env"])
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            ["claude", "-p", f"kunglao-bench entry for {spec['sample']}",
             "--permission-mode", "acceptEdits",
             "--max-turns", str(spec["max_turns"])],
            timeout=spec["wall_cap_s"], env=env,
            capture_output=True, text=True, check=False, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"outcome": "timeout", "transcript": None,
                "compaction_count": None,
                "started": started.isoformat(),
                "finished": datetime.now(timezone.utc).isoformat()}
    outcome = "done" if proc.returncode == 0 else "crashed"
    return {"outcome": outcome, "transcript": None,
            "compaction_count": None,
            "started": started.isoformat(),
            "finished": datetime.now(timezone.utc).isoformat()}


def run_plan(plan: list[dict], executor=None,
             out_dir: Path | None = None) -> list[dict]:
    """Execute specs (or a stub through tests), one receipt per run.
    Crashes NEVER abort the lane: the receipt records crashed and the
    loop continues (single-run failure stays single)."""
    executor = executor or _default_executor
    receipts = []
    for spec in plan:
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "sample": spec["sample"],
            "arm": spec["arm"],
            "stratum": spec["stratum"],
            "workspace": spec["workspace"],
            "max_turns": spec["max_turns"],
            "wall_cap_s": spec["wall_cap_s"],
            "budget_min": spec["budget_min"],
            "pair_order": spec.get("pair_order"),
        }
        try:
            receipt.update(executor(spec))
        except Exception as exc:  # noqa: BLE001 — infra failure ≠ lane abort
            receipt.update({"outcome": "crashed", "transcript": None,
                            "compaction_count": None, "error": str(exc),
                            "finished": datetime.now(timezone.utc).isoformat()})
        receipts.append(receipt)
        if out_dir is not None:
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            (out / f"receipt-{receipt['sample']}-{receipt['arm']}-{stamp}.json") \
                .write_text(json.dumps(receipt, ensure_ascii=False, indent=2,
                                       sort_keys=True), encoding="utf-8")
    return receipts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench_runner.py",
                                 description="kunglao-bench lane runner")
    ap.add_argument("manifest", help="kunglao-bench/manifest.yaml")
    ap.add_argument("--stratum", required=True, choices=tuple(BUDGETS))
    ap.add_argument("--lane", default="A", choices=tuple(LANE_ARMS))
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan; execute nothing")
    ap.add_argument("--out-dir", default="runs")
    args = ap.parse_args(argv)
    plan = build_plan(Path(args.manifest), args.stratum, args.lane)
    if args.dry_run:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    receipts = run_plan(plan, out_dir=Path(args.out_dir))
    outcomes: dict[str, int] = {}
    for r in receipts:
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    print(json.dumps(outcomes, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
