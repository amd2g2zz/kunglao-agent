#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ex5_predict_before_try.py — EX-5: the #460 Part B MC replay A/B
(predict-before-try activation gate).

Policy A (status quo): flat cells + fixed probe set — the DTS sampler
over the training pool with the feature prior OFF (flag unset).

Policy B: feature-conditioned prior + probe arms — the same sampler
with KUNGLAO_PREDICT_BEFORE_TRY=1, the held-out run's instance
features, and the training rows as the feature table.

Replay protocol (deterministic; same table => byte-identical results):
  - usable runs = table rows with >= 1 scoring outcome (credit non-null
    or landed/timeout/blocked act_result);
  - leave-one-run-out: for each held-out run R, both policies draw
    ONLY from the other rows (policy B additionally passes
    exclude_run=R.run_id — belt and braces, the split is the rows);
  - candidates = the training pool's observed method vocabulary, P_LLM
    = the measured proposal share (per-family outcome count share,
    uniform when the pool has none) — the production measured-prior
    idiom, not a hand-picked prior;
  - environment: family f's success probability p_f = R's empirical
    success rate among its own outcomes for f (success = settled
    credit > 0 or act_result landed); a family R never tried scores
    p=0 (unverifiable history — a miss for BOTH policies equally);
  - N trials per run per policy (seeded per (run, policy)); trial t
    draws the first method act from the policy's sampler and scores it
    Bernoulli(p_f);
  - metrics: cold-start first-act success rate (trials with a
    successful first act / all trials) and oracle PASS rate (per run:
    whether the policy's modal first act carries a settled credit > 0
    outcome in R).

UNDERPOWERED DISCLOSURE (the honest result): the only table in-repo
(the Part-A sanitized fixture golden) carries 2 usable runs — the
harness declares underpower when usable runs < 3 and the numbers are
protocol demonstration, NOT activation evidence. Activation needs a
decisive policy-B win (both metrics) at real table scale (--table).

Reproduce:
  uv run --project . python experiments/ex5_predict_before_try.py
(raw numbers: experiments/ex5-results.json, same commit).
"""
from __future__ import annotations

import json
import os
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from rlvr import feature_prior as fp  # noqa: E402
from rlvr import q_cells  # noqa: E402

RESULTS_REL = Path("experiments") / "ex5-results.json"
DEFAULT_TABLE = (ROOT / "tests" / "fixtures" / "feature-mining-460"
                 / "golden" / "feature-table.jsonl")

N_TRIALS = 200
UNDERPOWERED_MIN_USABLE = 3
FLAG = fp.FLAG_ENV


# ---------------------------------------------------------------------------
# environment model
# ---------------------------------------------------------------------------

def _scoring_outcomes(row: dict) -> list[dict]:
    return [o for o in row.get("outcomes") or []
            if isinstance(o, dict) and fp.outcome_mass(o) is not None]


def _is_success(outcome: dict) -> bool:
    credit = outcome.get("credit")
    if isinstance(credit, (int, float)) and not isinstance(credit, bool):
        return float(credit) > 0.0
    return outcome.get("act_result") == "landed"


def _success_probs(run: dict) -> dict[str, float]:
    """Family -> empirical success rate among the held-out run's own
    scoring outcomes for that family (the replay's environment)."""
    hits: dict[str, list[bool]] = {}
    for outcome in _scoring_outcomes(run):
        family = str(outcome.get("method_family_or_claim_source") or "")
        if family:
            hits.setdefault(family, []).append(_is_success(outcome))
    return {f: sum(v) / len(v) for f, v in sorted(hits.items())}


def _oracle_families(run: dict) -> set[str]:
    """Families with a settled positive-credit outcome in the run."""
    out = set()
    for outcome in run.get("outcomes") or []:
        if not isinstance(outcome, dict):
            continue
        credit = outcome.get("credit")
        if isinstance(credit, (int, float)) \
                and not isinstance(credit, bool) and float(credit) > 0.0:
            out.add(str(outcome.get("method_family_or_claim_source") or ""))
    return out


# ---------------------------------------------------------------------------
# policies
# ---------------------------------------------------------------------------

def _training_store(rows: list[dict]) -> q_cells.InMemoryStore:
    """The training pool as a q-cell store: one observation row per
    scoring outcome, keyed by the mined INSTANCE signature (the
    replay's namespace — cells pool per instance, anchors per family).
    The row's credit IS the outcome's success mass c; the fold splits
    it into success c / failure (1-c) by itself."""
    obs = []
    for row in rows:
        for outcome in _scoring_outcomes(row):
            mass = fp.outcome_mass(outcome)
            obs.append({
                "schema": q_cells.OBS_SCHEMA, "ts": "ex5",
                "source": "settlement",
                "signature_hash": str(row.get("signature_hash") or ""),
                "method_family": str(
                    outcome.get("method_family_or_claim_source") or ""),
                "claim": outcome.get("claim"), "agent": None,
                "credit": mass[0],
            })
    return q_cells.InMemoryStore(obs)


def _proposal_prior(training: list[dict]) -> dict[str, float]:
    counts: Counter[str] = Counter()
    for row in training:
        for outcome in _scoring_outcomes(row):
            family = str(outcome.get("method_family_or_claim_source") or "")
            if family:
                counts[family] += 1
    if not counts:
        return {}
    return {f: float(n) for f, n in sorted(counts.items())}


def _draw_first_act(policy: str, run: dict, training: list[dict],
                    trial: int) -> str:
    """One policy's first METHOD act for the held-out run (seeded)."""
    store = _training_store(training)
    prior = _proposal_prior(training) or {"other": 1.0}
    rng = random.Random(f"ex5/{run.get('run_id')}/{policy}/{trial}")
    kwargs: dict = {}
    if policy == "B":
        kwargs = {"features": run.get("features") or {},
                  "feature_table": training,
                  }  # flag raised by the caller around the call
    receipt = q_cells.sample_method_family(
        str(run.get("signature_hash") or ""), prior, store, rng=rng,
        **kwargs)
    return str(receipt["family"])


def _replay_run(run: dict, training: list[dict]) -> dict:
    probs = _success_probs(run)
    oracle = _oracle_families(run)
    out = {"run_id": run.get("run_id"), "family": run.get("family"),
           "task_id": run.get("task_id"),
           "signature_hash": run.get("signature_hash"),
           "env_success_probs": probs, "oracle_families": sorted(oracle)}
    for policy in ("A", "B"):
        old = os.environ.get(FLAG)
        try:
            if policy == "B":
                os.environ[FLAG] = "1"
            elif old is not None:
                del os.environ[FLAG]
            acts: list[str] = []
            successes = 0
            for trial in range(N_TRIALS):
                family = _draw_first_act(policy, run, training, trial)
                acts.append(family)
                p = probs.get(family, 0.0)
                # PAIRED environment (code-review fold): the env seed
                # carries (run, trial, family) but NOT the policy, so
                # an identical (trial, family) draw sees identical
                # env randomness under both policies — the comparison
                # is paired, not two independent Bernoulli streams
                successes += 1 if random.Random(
                    f"ex5/env/{run.get('run_id')}/{trial}"
                    f"/{family}").random() < p else 0
            modal, _ = Counter(acts).most_common(1)[0]
            out[policy] = {
                "first_act_success_rate": successes / N_TRIALS,
                "modal_first_act": modal,
                "oracle_pass": modal in oracle,
            }
        finally:
            if old is None:
                os.environ.pop(FLAG, None)
            else:
                os.environ[FLAG] = old
    return out


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

def run(table_path: Path = DEFAULT_TABLE) -> dict:
    rows = fp.load_table(table_path)
    usable = [r for r in rows if _scoring_outcomes(r)]
    underpowered = len(usable) < UNDERPOWERED_MIN_USABLE
    replays = []
    for i, run_row in enumerate(usable):
        training = [r for j, r in enumerate(usable) if j != i]
        replays.append(_replay_run(run_row, training))
    agg: dict[str, dict] = {}
    for policy in ("A", "B"):
        rates = [r[policy]["first_act_success_rate"] for r in replays]
        passes = [1 if r[policy]["oracle_pass"] else 0 for r in replays]
        agg[policy] = {
            "mean_first_act_success": (sum(rates) / len(rates)
                                       if rates else 0.0),
            "oracle_pass_rate": (sum(passes) / len(passes)
                                 if passes else 0.0),
        }
    verdict = "UNDERPOWERED" if underpowered else (
        "B_WINS" if (agg["B"]["mean_first_act_success"]
                     > agg["A"]["mean_first_act_success"]
                     and agg["B"]["oracle_pass_rate"]
                     >= agg["A"]["oracle_pass_rate"]) else "NO_B_WIN")
    return {
        "schema": "ex5-predict-before-try/1",
        "table": str(table_path), "table_rows": len(rows),
        "usable_runs": len(usable), "n_trials": N_TRIALS,
        "underpowered": underpowered,
        "underpowered_min_usable": UNDERPOWERED_MIN_USABLE,
        "activation_verdict": verdict,
        "aggregates": agg,
        "replays": replays,
        "activation_rule": ("policy B must win mean first-act success "
                            "strictly and oracle pass rate at >= A's, on a "
                            "NON-underpowered table, before the default-off "
                            "flag is even a candidate to flip (owner "
                            "decision)"),
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="ex5_predict_before_try.py",
        description="EX-5: #460 Part B MC replay A/B (policy A flat "
                    "vs policy B feature-prior + probe arms)")
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE,
                        help="mined feature-table/1 jsonl (default: the "
                             "Part-A fixture golden table)")
    args = parser.parse_args(argv)
    results = run(args.table)
    out_path = ROOT / RESULTS_REL
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n", encoding="utf-8")
    print(json.dumps({k: results[k] for k in (
        "table_rows", "usable_runs", "n_trials", "underpowered",
        "activation_verdict", "aggregates")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
