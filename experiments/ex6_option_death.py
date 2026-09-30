#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ex6_option_death.py — EX-6: the option-death MC replay A/B
(issue 461 Phase 2 acceptance: attribution-in-state + learned
termination vs current decay-only, on the owner's five-step trap
trajectory).

**DECLARED SYNTHETIC** — the environment is EX-4's truth table (the
owner-authored trap: frida-detected -> unidbg-env-error ->
static-tool-limit -> encrypted-layer -> breakthrough-at-decryptor),
replayed through the REAL faces (obstacles.record with probe
artifacts, q_cells dispatch + settlement observation rows,
q_cells.sample_method_family, the termination verdicts) on persistent
per-arm workspaces. Nothing here is campaign data.

Arms (one persistent workspace each — the registry + q-cell log
persist across episodes WITHIN an arm; that persistence IS the
learning):

  A decay-only        — the current kernel: the sampler with no death
                        kwarg (failures demote only through the
                        ordinary DTS posterior);
  B attribution+death — failures record obstacle rows (the Phase-1
                        worker protocol followed); the sampler consults
                        the termination verdicts (dead -> ARM_FLOOR);
  C cause-free        — termination consulted, but failures record NO
                        obstacle rows (the worker skipped attribution):
                        the zero-registry rule threads no kwarg at all,
                        so C replays A exactly — the negative control
                        proving cause-free failures never terminate.

NON-REAL FACES (declared): P_LLM is a uniform prior over the five
families (both production hosts measure the proposal channel from
dispatch rows; the replay pins the prior so arm deltas attribute to
termination, not to prior-measurement noise — the EX-5 declared-prior
choice); the act environment is a deterministic truth table (no
Bernoulli draws); episodes are independent except through the
persistent registries.

DISCLOSED FRAGMENTATION ASYMMETRY: arm B's obstacle recording advances
ob= at every failure, so B's failure evidence fragments across
CHANGING signature cells while arm A concentrates local evidence in
one cell (the family anchor is SHRINK_CAPped at 8 pseudo-observations)
— attribution makes B's ORDINARY DTS demotion weaker than A's for the
same failure count. B's advantage comes from the termination floor
(fires at 2 attributed same-cause failures), measured on a slightly
weakened baseline: the conservative direction.

Determinism: fixed ts on every recorded row (obstacles via the ts
override; q-cell rows via append_observation's ts face — observe()
hides it), seeded rng per (episode, act) shared across arms (the
paired design), aggregates-only results document (no raw rows, no
machine-local paths). Same code -> same bytes; pinned in
tests/test_ex6_option_death_461.py.

Reproduce:
  uv run --project . python experiments/ex6_option_death.py
(raw numbers: experiments/ex6-results.json, same commit).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _hooks_path import load_module_by_path  # noqa: E402  (#863 Family B)
from rlvr import obstacles, q_cells, state as ssig, termination  # noqa: E402

RESULTS_REL = Path("experiments") / "ex6-results.json"

N_EPISODES = 40
EPISODE_BUDGET = 8

ARMS = ("A", "B", "C")
ARM_LABELS = {
    "A": "decay-only",
    "B": "attribution+termination",
    "C": "cause-free control",
}


def _truth() -> dict[str, dict]:
    """EX-4's TRAJECTORY as the environment truth table (family ->
    step entry). The four failing families fail with their trajectory
    kind/cause/probe when tried; the breakthrough family succeeds.
    Loaded through the ONE by-path loader (#863 Family B delegation)."""
    ex4 = load_module_by_path(
        "ex4_attribution_trap", ROOT / "experiments" / "ex4_attribution_trap.py"
    )
    return {entry["family"]: entry for entry in ex4.TRAJECTORY}


TRUTH = None  # set lazily in replay (import side-effect isolation)


def _ts(arm: str, episode: int, act: int) -> str:
    """Deterministic ISO ts per (arm, episode, act) — no clock reads."""
    return f"2026-09-30T{12 + ARMS.index(arm):02d}:{episode:02d}:{act:02d}Z"


def _sample(ws, arm: str, episode: int, act: int, families: list[str]):
    """One act's policy draw through the real sampler faces.

    Arm A: no death kwarg. Arms B/C: the termination verdicts threaded
    (C's zero-registry rule yields {} — no kwarg — by construction,
    which is exactly the negative control). rng seeded per
    (episode, act), SHARED across arms — the paired design: episode 1
    is identical for all three arms (B's obstacle rows never enter the
    sampler), C stays identical to A forever, and B diverges exactly
    at the act its verdicts first floor something. Every draw
    distinct, replay-deterministic."""
    snap = ssig.snapshot(ws)
    sig = ssig.signature_hash(snap)
    prior = {fam: 1.0 for fam in families}  # declared uniform (above)
    kwargs: dict = {}
    if arm in ("B", "C"):
        verdicts = termination.verdicts(ws, families)
        if verdicts:
            kwargs["death"] = verdicts
    rng = random.Random(f"ex6/{episode}/{act}")
    receipt = q_cells.sample_method_family(
        snap, prior, q_cells.default_store(ws), rng=rng, **kwargs
    )
    return snap, sig, receipt


def _act(ws, arm: str, episode: int, act: int, families) -> dict:
    """One act: draw, execute against the truth table, record through
    the real faces. Returns the act outcome row (aggregates only)."""
    truth = TRUTH
    snap, sig, receipt = _sample(ws, arm, episode, act, families)
    family = str(receipt["family"])
    # the ALLOW-tail fidelity: one dispatch observation per act
    q_cells.append_observation(ws, sig, family, None, source="dispatch", ts=_ts(arm, episode, act))
    entry = truth[family]
    if entry["outcome"] == "success":
        q_cells.append_observation(
            ws, sig, family, 1.0, source="settlement", ts=_ts(arm, episode, act)
        )
        facts = ws / "facts"
        facts.mkdir(parents=True, exist_ok=True)
        (facts / f"F{episode + 1:03d}-breakthrough.md").write_text(
            "---\nid: F{0:03d}\nstatus: VERIFIED\nclaim_id: C-1\n"
            "verified: false\n---\n\n# breakthrough\nsynthetic "
            "breakthrough fact\n".format(episode + 1),
            encoding="utf-8",
        )
        return {"family": family, "outcome": "success"}
    # failure: settlement row (credit 0) +, attribution arms only,
    # the obstacle row citing a fresh probe artifact (EX-4's bytes)
    q_cells.append_observation(ws, sig, family, 0.0, source="settlement", ts=_ts(arm, episode, act))
    if arm == "B":
        rel = f"runs/probes/ex6-{family}-{episode}-{act}.txt"
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(entry["probe"], encoding="utf-8")
        out = obstacles.record(
            ws,
            kind=entry["kind"],
            cause=entry["cause"],
            evidence_path=rel,
            method_family=family,
            ts=_ts(arm, episode, act),
        )
        if not out["appended"]:  # pragma: no cover — contract break
            raise RuntimeError(f"ex6: obstacle record rejected: {out['errors']}")
    return {"family": family, "outcome": "failure", "kind": entry["kind"]}


def _run_arm(arm: str, families: list[str]) -> dict:
    """One arm's N_EPISODES episodes on one persistent workspace."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix=f"ex6-{arm}-") as td:
        ws = Path(td)
        dead = {fam for fam in families if fam != "crypto-core-identification"}
        episodes = []
        for episode in range(N_EPISODES):
            acts = []
            for act in range(EPISODE_BUDGET):
                row = _act(ws, arm, episode, act, families)
                acts.append(row)
                if row["outcome"] == "success":
                    break
            breakthrough = any(a["outcome"] == "success" for a in acts)
            episodes.append(
                {
                    "breakthrough": breakthrough,
                    "acts_used": len(acts),
                    "wasted": sum(1 for a in acts if a["family"] in dead),
                }
            )
        report = termination.report(ws)
        verdicts_sample = termination.verdicts(ws, families)
        return {"episodes": episodes, "report": report, "verdicts_sample": verdicts_sample}


def _aggregate(episodes: list[dict]) -> dict:
    n = len(episodes)
    hits = [e["acts_used"] for e in episodes if e["breakthrough"]]
    return {
        "n_episodes": n,
        "breakthrough_rate": round(sum(1 for e in episodes if e["breakthrough"]) / n, 6),
        "mean_acts_to_breakthrough": (round(sum(hits) / len(hits), 6) if hits else None),
        "mean_wasted_acts": round(sum(e["wasted"] for e in episodes) / n, 6),
    }


def _halves(episodes: list[dict]) -> dict:
    mid = len(episodes) // 2
    return {"first": _aggregate(episodes[:mid]), "second": _aggregate(episodes[mid:])}


def replay() -> dict:
    """The full three-arm replay; returns the aggregates-only results
    document (byte-identical across reruns — pinned by tests). Each
    arm runs on its own throwaway workspace (created inside; never
    shipped in the document)."""
    global TRUTH
    TRUTH = _truth()
    families = [e["family"] for e in sorted(_truth().values(), key=lambda e: e["step"])]
    doc = {
        "experiment": "ex6-option-death",
        "declared_synthetic": True,
        "schema": "ex6-option-death/1",
        "n_episodes": N_EPISODES,
        "episode_budget": EPISODE_BUDGET,
        "families": families,
        "non_real_faces": [
            "P_LLM: declared uniform over the five families (both "
            "production hosts measure the proposal channel)",
            "act environment: the deterministic EX-4 truth table (no Bernoulli draws)",
        ],
        "disclosed_asymmetry": (
            "arm B's ob= advances per failure, fragmenting its q-cell "
            "failure evidence across signatures (SHRINK_CAP 8 caps the "
            "family anchor) — B's ordinary DTS demotion is weaker than "
            "A's for the same failure count; B's advantage comes from "
            "the termination floor (2 attributed same-cause failures)"
        ),
        "arms": {},
    }
    for arm in ARMS:
        res = _run_arm(arm, families)
        doc["arms"][arm] = {
            "label": ARM_LABELS[arm],
            "episodes": res["episodes"],
            "aggregate": _aggregate(res["episodes"]),
            "halves": _halves(res["episodes"]),
            "report": res["report"],
            "verdicts_sample": res["verdicts_sample"],
        }
    return doc


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--out", default=str(ROOT / RESULTS_REL), help="results JSON path (default: experiments/)"
    )
    args = ap.parse_args(argv)
    doc = replay()
    out_path = Path(args.out)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for arm in ARMS:
        agg = doc["arms"][arm]["aggregate"]
        dead = doc["arms"][arm]["report"]["dead_families"]
        print(
            f"ex6 arm {arm} ({ARM_LABELS[arm]}): "
            f"breakthrough {agg['breakthrough_rate']:.3f}, "
            f"wasted {agg['mean_wasted_acts']:.2f}, "
            f"dead families {dead}"
        )
    print(f"ex6: results -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
