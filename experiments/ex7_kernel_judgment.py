#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EX-7 — the kernel capability judgment experiment (pre-registered).

Owner doubt: does the landed DTS/q_cells kernel beat uniform arm
selection once fed data? Real kernel code paths over a simulated
world; paired seeds; pre-registered discriminators (design.md) written
BEFORE any run. Deterministic: fixed seeds, byte-identical reruns.

Each (class, seed, policy) runs ONE 100-step episode; metrics are
checkpoints at n=5/10/25/50/100 (cumulative regret, waste-acts,
first-success index). Paired sign tests from the same episodes.

Usage: python experiments/ex7_kernel_judgment.py [--seeds N]
Writes: experiments/ex7-results.json (+ prints the verdict table).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from rlvr import q_cells  # noqa: E402  the REAL kernel under judgment

WORLD_SEED = 20261001
N_CLASSES = 6
N_FAMILIES = 8
FAMILIES = [f"fam-{i}" for i in range(N_FAMILIES)]
NS = (5, 10, 25, 50, 100)
N_MAX = max(NS)
TS_FMT = "2026-10-01T00:%02d:%02dZ"

REGIMES = {
    "R1-sparse-strong": {"strong": 2, "p_strong": (0.75, 0.9),
                         "p_weak": (0.08, 0.22)},
    "R2-degenerate": {"strong": 0, "p_strong": None,
                      "p_weak": (0.45, 0.55)},
    "R3-one-dominant": {"strong": 1, "p_strong": (0.85, 0.95),
                        "p_weak": (0.05, 0.15)},
}


def build_world(regime: str, seed: int) -> dict:
    rng = random.Random(seed)
    cfg = REGIMES[regime]
    world = {}
    for s in range(N_CLASSES):
        probs = [rng.uniform(*cfg["p_weak"]) for _ in FAMILIES]
        for i in (rng.sample(range(N_FAMILIES), cfg["strong"])
                  if cfg["strong"] else []):
            probs[i] = rng.uniform(*cfg["p_strong"])
        world[f"{s:012x}"] = dict(zip(FAMILIES, probs))
    return world


def llm_prior(seed: int) -> dict:
    """Weak informative P_LLM: uniform + a random (NOT true-strong) tilt
    per class — the kernel must earn discovery, not read the answer."""
    rng = random.Random(seed + 777)
    return {s: {f: 1.0 / N_FAMILIES +
                (0.1 / N_FAMILIES if f == rng.choice(FAMILIES) else 0.0)
                for f in FAMILIES}
            for s in [f"{i:012x}" for i in range(N_CLASSES)]}


def _episode(pick, world_row: dict, seed: int) -> dict:
    """One 100-step episode; pick(t)->family. Checkpoints at NS."""
    sim = random.Random(seed + 1)
    regret = 0.0
    fails = 0
    first_success_at = None
    snap = {}
    p_star = max(world_row.values())
    for t in range(N_MAX):
        fam = pick(t)
        ok = sim.random() < world_row[fam]
        regret += p_star - world_row[fam]
        if ok:
            if first_success_at is None:
                first_success_at = t
        else:
            fails += 1
        if (t + 1) in NS:
            snap[t + 1] = {
                "regret": regret,
                "waste": (first_success_at if first_success_at is None
                          else fails - 0) if False else (
                              fails if first_success_at is None
                              else None),
                "first": (first_success_at if first_success_at
                          is not None else t + 1),
            }
    return snap


def episode_kernel(sig, prior, world_row, seed):
    rng = random.Random(seed)
    store = q_cells.InMemoryStore([])
    state = {"store": store}

    def pick(t: int) -> str:
        receipt = q_cells.sample_method_family(
            sig, prior[sig], state["store"], rng=rng)
        fam = receipt["family"]
        state["store"]._rows.append({
            "schema": q_cells.OBS_SCHEMA,
            "ts": TS_FMT % (t // 60, t % 60), "source": "settlement",
            "signature_hash": sig, "method_family": fam,
            "claim": None, "agent": None, "credit": None})
        state["last"] = fam
        return fam

    # outcome feedback must land BEFORE the next pick: wrap the episode
    sim = random.Random(seed + 1)
    regret = 0.0
    fails = 0
    first_success_at = None
    snap = {}
    p_star = max(world_row.values())
    for t in range(N_MAX):
        fam = pick(t)
        ok = sim.random() < world_row[fam]
        regret += p_star - world_row[fam]
        if ok:
            if first_success_at is None:
                first_success_at = t
            state["store"]._rows[-1]["credit"] = 1.0
        else:
            fails += 1
            state["store"]._rows[-1]["credit"] = 0.0
        if (t + 1) in NS:
            snap[t + 1] = {
                "regret": regret,
                "waste": fails if first_success_at is None else None,
                "first": (first_success_at if first_success_at
                          is not None else t + 1)}
    return snap


def episode_uniform(world_row, seed):
    rng = random.Random(seed)
    fams = list(world_row)
    return _episode(lambda _t: rng.choice(fams), world_row, seed)


def episode_eps(world_row, seed, eps=0.1):
    rng = random.Random(seed)
    fams = list(world_row)
    stats = {f: [0, 0] for f in fams}

    def pick(t: int) -> str:
        if rng.random() < eps or t == 0:
            return rng.choice(fams)
        return max(fams, key=lambda f: (stats[f][0] / stats[f][1]
                                        if stats[f][1] else 0.0))

    sim = random.Random(seed + 1)
    regret = 0.0
    fails = 0
    first_success_at = None
    snap = {}
    p_star = max(world_row.values())
    for t in range(N_MAX):
        fam = pick(t)
        ok = sim.random() < world_row[fam]
        stats[fam][0] += 1 if ok else 0
        stats[fam][1] += 1
        regret += p_star - world_row[fam]
        if ok:
            if first_success_at is None:
                first_success_at = t
        else:
            fails += 1
        if (t + 1) in NS:
            snap[t + 1] = {
                "regret": regret,
                "waste": fails if first_success_at is None else None,
                "first": (first_success_at if first_success_at
                          is not None else t + 1)}
    return snap


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--out", default=str(Path(__file__).parent
                                         / "ex7-results.json"))
    args = ap.parse_args(argv)
    prior = llm_prior(WORLD_SEED)
    results = {"seeds": args.seeds, "worlds": {}, "verdicts": {}}
    for regime in REGIMES:
        world = build_world(regime, WORLD_SEED)
        results["worlds"][regime] = {
            s: {f: round(p, 4) for f, p in row.items()}
            for s, row in world.items()}
        # episodes per policy: {policy: {(class, seed): snap}}
        eps = {}
        for seed in range(args.seeds):
            for sig, row in world.items():
                cell = (sig, seed)
                eps.setdefault("kernel", {})[cell] = episode_kernel(
                    sig, prior, row, seed)
                eps.setdefault("uniform", {})[cell] = episode_uniform(
                    row, seed)
                eps.setdefault("eps-greedy", {})[cell] = episode_eps(
                    row, seed)
        for n in NS:
            agg = {}
            for pol, table in eps.items():
                agg[pol] = {
                    m: round(sum(snap[n][m] for snap in table.values()
                                 if snap[n][m] is not None)
                             / max(1, sum(1 for snap in table.values()
                                          if snap[n][m] is not None)), 4)
                    for m in ("regret", "first")}
            pairs = [(eps["kernel"][(sig, seed)][n]["regret"],
                      eps["uniform"][(sig, seed)][n]["regret"])
                     for sig in world for seed in range(args.seeds)]
            agg["kernel_vs_uniform_sign"] = round(
                sum(1 for k, u in pairs if k < u) / len(pairs), 4)
            results["verdicts"][f"{regime}@n={n}"] = agg
    Path(args.out).write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps(results["verdicts"], indent=1)[:1600])
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
