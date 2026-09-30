#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ex7_kernel_judgment.py — EX-7: does the real DTS/q_cells kernel beat
uniform arm selection once fed data?

The owner's falsification gate for the landed kernel (#429/#428/#432 +
#466 actuation): run the REAL code paths — `rlvr.q_cells.sample_method_
family` under the shipped adaptive γ schedule and the constant γ=1
diagnostic face, the closed #432 vocabulary as the arm set, and
`rlvr.state.signature_hash` for the state key — against a uniform
control and an ε-greedy ε=0.1 learnability calibration over synthetic
worlds whose ground truth the policies can see ONLY through the
Bernoulli outcomes of their own chosen arms.

Pre-registration: openspec/changes/kernel-judgment-experiment/design.md
(world constants, arms, metrics, PRIMARY endpoints, stopping rule,
discriminators D1-D4/D3′) — fixed BEFORE this run and never re-tuned;
see design-review.md for the independent pre-code review amendments.
Run ONCE at exactly 200 seeds/regime, horizon 100 acts per class. A
kernel loss is a publishable verdict, not a re-run trigger.

Signature classes: the 8 eval-fixture release families, each hashed
through the real state-sig/2 derivation. Regimes: R1 aligned-sparse
(same strong families everywhere — family anchors point right), R2
class-specific-sparse (per-class strong arms — state key required),
R3 dense-easy (high signal — learning-speed probe).

Reproduce:
  uv run --project . python experiments/ex7_kernel_judgment.py
(raw numbers: experiments/ex7-results.json, same commit; deterministic
— two runs produce byte-identical output; no wall clock, no absolute
paths in the output).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import method_families  # noqa: E402 — the #432 registry (the subject's arm set)
from rlvr import feature_prior as fp  # noqa: E402 — replay block substrate reuse
from rlvr import q_cells  # noqa: E402 — THE subject under judgment
from rlvr import state as ssig  # noqa: E402 — the real state-key derivation

SCHEMA = "ex7-kernel-judgment/1"
RESULTS_REL = Path("experiments") / "ex7-results.json"
DEFAULT_TABLE = (ROOT / "tests" / "fixtures" / "feature-mining-460"
                 / "golden" / "feature-table.jsonl")

# --- pre-registered constants (design Decision 1/4; never tuned) ----------
CLASSES = ("arm-kdf", "mod-crypto-js", "mod-crypto", "net-verify-license",
           "req-sign", "smc-x86", "web-pack-sign", "win-kdf")
REGIMES = {
    "R1": {"name": "aligned-sparse", "n_strong": 2,
           "p_strong": 0.55, "p_weak": 0.05},
    "R2": {"name": "class-specific-sparse", "n_strong": 2,
           "p_strong": 0.55, "p_weak": 0.05},
    "R3": {"name": "dense-easy", "n_strong": 4,
           "p_strong": 0.75, "p_weak": 0.15},
}
HORIZON = 100                 # acts per class (design Decision 4)
CHECKPOINTS = (5, 10, 25, 50, 100)
SEED_IDS = tuple(range(200))  # EXACTLY 200, always (design Decision 4)
ARMS = ("kernel", "kernel-g1", "uniform", "eps-greedy")
EPSILON = 0.1
PAIRS = (("kernel", "uniform"), ("kernel-g1", "uniform"),
         ("eps-greedy", "uniform"))
N_TRIALS_REPLAY = 200
UNDERPOWERED_MIN_USABLE = 3


# ---------------------------------------------------------------------------
# world (design Decision 1) — ground truth the policies never see directly
# ---------------------------------------------------------------------------

def class_signatures() -> dict[str, str]:
    """The 8 signature classes through the REAL state-sig/2 derivation:
    per-class index i in 0..7 -> canonical snapshot -> signature_hash."""
    out: dict[str, str] = {}
    for i, cls in enumerate(CLASSES):
        snap = {
            "schema": ssig.SCHEMA,
            "facts": {"count": i + 1, "verified": i, "bucket": i % 6},
            "claims": {"pattern": f"OPEN={i + 1}"},
            "budget": {"fraction": 0.0, "bucket": 0, "present": False},
            "chain": {"k": i, "n": len(CLASSES)},
            "phase": "DISPATCH",
            "obstacles": {"present": False, "count": 0, "kinds": ""},
            "sides": {},
        }
        out[cls] = ssig.signature_hash(snap)
    return out


def ground_truth(regime_id: str, vocab: frozenset[str]
                 ) -> tuple[dict[str, dict[str, float]], dict[str, list[str]]]:
    """(class -> family -> p) from the pre-registered sparse mixture, plus
    the strong-arm sets (recorded in the results for D3 diagnostics).
    R1 shares one strong set; R2/R3 draw per class. All draws keyed by
    fixed strings — world seeds live in the ex7/world/* namespace,
    disjoint from every policy/env seed."""
    cfg = REGIMES[regime_id]
    fams = sorted(vocab)
    if regime_id == "R1":
        shared = random.Random("ex7/world/R1/shared").sample(
            fams, cfg["n_strong"])
        strong = {cls: sorted(shared) for cls in CLASSES}
    else:
        strong = {cls: random.Random(
            f"ex7/world/{regime_id}/{cls}").sample(fams, cfg["n_strong"])
            for cls in CLASSES}
    truth = {cls: {f: (cfg["p_strong"] if f in strong[cls]
                       else cfg["p_weak"]) for f in fams}
             for cls in CLASSES}
    return truth, strong


def env_success(regime_id: str, seed: int, t: int, cls: str, family: str,
                p: float) -> bool:
    """The paired environment: keyed WITHOUT any policy term, so two
    policies drawing the same (t, cls, family) observe the SAME
    outcome (design Decision 2; the EX-5 paired-env fold)."""
    return random.Random(
        f"ex7/env/{regime_id}/{seed}/{t}/{cls}/{family}").random() < p


# ---------------------------------------------------------------------------
# arms (design Decision 3)
# ---------------------------------------------------------------------------

def _flat_prior(vocab: frozenset[str]) -> dict[str, float]:
    """The class-independent P_LLM (the W4 uniform-over-registered
    production fallback): {family: 1.0} — day-one kernel distribution
    is exactly uniform under it, so any separation is pure Q."""
    return {f: 1.0 for f in sorted(vocab)}


class KernelArm:
    """The real sampler. gamma=None -> the shipped adaptive DTS
    schedule; gamma=1.0 -> the pre-registered constant-γ diagnostic.

    The store is built PER ACT from the grown rows (the public
    protocol only): InMemoryStore's constructor COPIES the iterable it
    is given, so a store constructed once at arm init would stay empty
    forever — the run-1 deviation (see the report's deviation note);
    the learning-sensitivity test pins this."""

    def __init__(self, regime_id: str, seed: int, label: str,
                 vocab: frozenset[str], gamma):
        self.gamma = gamma
        self.prior = _flat_prior(vocab)
        self.rows: list[dict] = []
        self.rng = random.Random(f"ex7/policy/{regime_id}/{label}/{seed}")

    def act(self, sig: str) -> str:
        receipt = q_cells.sample_method_family(
            sig, self.prior, q_cells.InMemoryStore(self.rows),
            rng=self.rng, gamma=self.gamma)
        return str(receipt["family"])

    def observe(self, sig: str, family: str, credit: float) -> None:
        self.rows.append({
            "schema": q_cells.OBS_SCHEMA, "ts": "ex7",
            "source": "settlement", "signature_hash": sig,
            "method_family": family, "claim": None, "agent": None,
            "dispatch_id": None, "credit": credit,
        })


class UniformArm:
    """The control: uniform over the registered vocabulary."""

    def __init__(self, regime_id: str, seed: int, label: str,
                 vocab: frozenset[str], gamma=None):
        self.fams = sorted(vocab)
        self.rng = random.Random(f"ex7/policy/{regime_id}/{label}/{seed}")

    def act(self, sig: str) -> str:
        return self.rng.choice(self.fams)

    def observe(self, sig: str, family: str, credit: float) -> None:
        return None  # symmetric bookkeeping face; the control reads nothing


class EpsGreedyArm:
    """The learnability calibration: ε=0.1 uniform exploration, else
    argmax of its own per-(class, family) Beta(1,1) posterior mean
    (s+1)/(s+f+2); argmax ties broken by rng."""

    def __init__(self, regime_id: str, seed: int, label: str,
                 vocab: frozenset[str], gamma=None):
        self.fams = sorted(vocab)
        self.rng = random.Random(f"ex7/policy/{regime_id}/{label}/{seed}")
        self.counts: dict[tuple[str, str], list[int]] = {}

    def _mean(self, cls: str, family: str) -> float:
        s, f = self.counts.get((cls, family), (0, 0))
        return (s + 1) / (s + f + 2)

    def act(self, sig: str, cls: str) -> str:
        if self.rng.random() < EPSILON:
            return self.rng.choice(self.fams)
        best = max(self._mean(cls, f) for f in self.fams)
        winners = [f for f in self.fams if self._mean(cls, f) == best]
        return self.rng.choice(winners)

    def observe(self, sig: str, family: str, credit: float,
                cls: str) -> None:
        key = (cls, family)
        s, f = self.counts.get(key, (0, 0))
        self.counts[key] = [s + (1 if credit > 0.5 else 0),
                            f + (0 if credit > 0.5 else 1)]


# ---------------------------------------------------------------------------
# trajectory + metrics (design Decision 4)
# ---------------------------------------------------------------------------

def run_trajectory(regime_id: str, seed: int, arm_name: str,
                   truth: dict[str, dict[str, float]],
                   sigs: dict[str, str], horizon: int) -> dict:
    """One arm, one seed: `horizon` acts per class, classes round-robin
    (class of step t = CLASSES[t mod 8]). Returns per-class histories:
    regret per act and the first-success act count (1-based, None while
    censored)."""
    vocab = method_families.registered_tokens()
    if arm_name == "kernel":
        arm: object = KernelArm(regime_id, seed, arm_name, vocab, None)
    elif arm_name == "kernel-g1":
        arm = KernelArm(regime_id, seed, arm_name, vocab, 1.0)
    elif arm_name == "uniform":
        arm = UniformArm(regime_id, seed, arm_name, vocab)
    else:
        arm = EpsGreedyArm(regime_id, seed, arm_name, vocab)
    greedy = isinstance(arm, EpsGreedyArm)
    best = {cls: max(table.values()) for cls, table in truth.items()}
    hist = {cls: {"regret": [], "first_success": None} for cls in CLASSES}
    for t in range(horizon * len(CLASSES)):
        cls = CLASSES[t % len(CLASSES)]
        sig = sigs[cls]
        if greedy:
            family = arm.act(sig, cls)
        else:
            family = arm.act(sig)
        p = truth[cls][family]
        success = env_success(regime_id, seed, t, cls, family, p)
        hist[cls]["regret"].append(best[cls] - p)
        if success and hist[cls]["first_success"] is None:
            hist[cls]["first_success"] = len(hist[cls]["regret"])
        if greedy:
            arm.observe(sig, family, 1.0 if success else 0.0, cls)
        else:
            arm.observe(sig, family, 1.0 if success else 0.0)
    return hist


def trajectory_metrics(hist: dict, checkpoints: tuple[int, ...]) -> dict:
    """Mean-over-classes scalars per checkpoint: cumulative regret and
    waste-acts before first success (censored to n). These scalars
    carry the sign tests (design Decision 4)."""
    out = {"regret": {}, "waste": {}}
    for n in checkpoints:
        regrets, wastes = [], []
        for cls in CLASSES:
            h = hist[cls]
            regrets.append(sum(h["regret"][:n]))
            wastes.append((h["first_success"] - 1) if
                          h["first_success"] is not None else n)
        out["regret"][n] = sum(regrets) / len(regrets)
        out["waste"][n] = sum(wastes) / len(wastes)
    return out


def per_class_regret(hist: dict, n: int) -> dict[str, float]:
    """Per-class cumulative regret at n (the D3/D3′ diagnostic cut)."""
    return {cls: sum(hist[cls]["regret"][:n]) for cls in CLASSES}


# ---------------------------------------------------------------------------
# statistics (design Decision 4) — lower is better on both metrics
# ---------------------------------------------------------------------------

def sign_test(a: list[float], b: list[float]) -> dict:
    """Two-sided exact binomial sign test, paired, ties dropped."""
    wins = sum(1 for x, y in zip(a, b) if x < y)
    losses = sum(1 for x, y in zip(a, b) if x > y)
    ties = len(a) - wins - losses
    n = wins + losses
    if n == 0:
        p = 1.0
    else:
        tail = sum(math.comb(n, k)
                   for k in range(min(wins, losses) + 1)) / (2 ** n)
        p = min(1.0, 2.0 * tail)
    verdict = "NO_SEPARATION"
    if p <= 0.05 and n > 0:
        verdict = "A_BETTER" if wins > losses else "A_WORSE"
    return {"wins": wins, "losses": losses, "ties": ties, "n": n,
            "p_value": p, "verdict": verdict}


# ---------------------------------------------------------------------------
# the grid
# ---------------------------------------------------------------------------

def _arm_aggregates(per_seed: dict, checkpoints: tuple[int, ...]) -> dict:
    """Mean over seeds of each metric scalar, per checkpoint."""
    seeds = sorted(per_seed)
    out = {"regret": {}, "waste": {}, "n_seeds": len(seeds)}
    for n in checkpoints:
        out["regret"][n] = (sum(per_seed[s]["regret"][n] for s in seeds)
                            / len(seeds))
        out["waste"][n] = (sum(per_seed[s]["waste"][n] for s in seeds)
                           / len(seeds))
    return out


def _pair_cells(per_seed: dict, a: str, b: str,
                checkpoints: tuple[int, ...]) -> dict:
    """Sign-test cells for one (arm, arm) pair over both metrics."""
    cells = {}
    for metric in ("regret", "waste"):
        cells[metric] = {}
        for n in checkpoints:
            va = [per_seed[s][a][metric][n] for s in sorted(per_seed)]
            vb = [per_seed[s][b][metric][n] for s in sorted(per_seed)]
            cells[metric][n] = sign_test(va, vb)
    return cells


def run_regime(regime_id: str, seeds: tuple[int, ...], horizon: int,
               checkpoints: tuple[int, ...]) -> dict:
    """One regime: all arms over all seeds, aggregates, sign tests."""
    vocab = method_families.registered_tokens()
    truth, strong = ground_truth(regime_id, vocab)
    sigs = class_signatures()
    per_seed: dict[int, dict[str, dict]] = {}
    per_class_n = {arm: {} for arm in ARMS}
    for seed in seeds:
        per_seed[seed] = {}
        for arm_name in ARMS:
            hist = run_trajectory(regime_id, seed, arm_name, truth,
                                  sigs, horizon)
            per_seed[seed][arm_name] = trajectory_metrics(hist, checkpoints)
            pc = per_class_regret(hist, checkpoints[-1])
            for cls, value in pc.items():
                per_class_n[arm_name].setdefault(cls, []).append(value)
    arms = {arm: _arm_aggregates({s: per_seed[s][arm] for s in seeds},
                                 checkpoints)
            for arm in ARMS}
    pairs = {f"{a}_vs_{b}": _pair_cells(per_seed, a, b, checkpoints)
             for a, b in PAIRS}
    per_class = {arm: {cls: sum(v) / len(v)
                       for cls, v in sorted(per_class_n[arm].items())}
                 for arm in ARMS}
    return {
        "name": REGIMES[regime_id]["name"],
        "params": REGIMES[regime_id],
        "seed_count": len(seeds), "horizon": horizon,
        "ground_truth": truth, "strong_arms": strong,
        "class_signature_hashes": sigs,
        "arms": arms, "pairs": pairs,
        "per_class_regret_final": per_class,
    }


# ---------------------------------------------------------------------------
# discriminators (design Decision 5 — evaluated exactly as pre-registered)
# ---------------------------------------------------------------------------

def _verdict(regimes: dict, regime_id: str, pair: str, metric: str,
             n: int) -> str:
    return regimes[regime_id]["pairs"][pair][metric][n]["verdict"]


def evaluate_discriminators(results: dict) -> dict:
    r = results["regimes"]
    kvu = "kernel_vs_uniform"
    g1vu = "kernel-g1_vs_uniform"
    evu = "eps-greedy_vs_uniform"
    fired: list[str] = []
    # D1: implementation defect — gated on the γ=1 diagnostic (review A1)
    d1 = (_verdict(r, "R3", kvu, "regret", 100) == "NO_SEPARATION"
          and _verdict(r, "R3", g1vu, "regret", 100) == "NO_SEPARATION"
          and any(_verdict(r, "R3", evu, "regret", n) == "A_BETTER"
                  for n in (5, 10, 25)))
    if d1:
        fired.append("D1")
    # D4: healthy (outranks D2 when it holds — review A2)
    d4 = all(_verdict(r, reg, kvu, "regret", 100) != "A_WORSE"
             for reg in r) and sum(
        _verdict(r, reg, kvu, "regret", 100) == "A_BETTER" for reg in r) >= 2
    if d4:
        fired.append("D4")
    # D2: vocabulary/sparse-reward drag — early-drag OR γ-drag-dominant
    d2a = any(
        _verdict(r, reg, kvu, "regret", 5) == "NO_SEPARATION"
        and _verdict(r, reg, kvu, "regret", 10) == "NO_SEPARATION"
        and any(_verdict(r, reg, kvu, "regret", n) == "A_BETTER"
                for n in (25, 50, 100))
        and any(_verdict(r, reg, evu, "regret", n) == "A_BETTER"
                for n in (5, 10))
        for reg in ("R1", "R3"))
    d2b = (all(_verdict(r, reg, kvu, "regret", 100) == "NO_SEPARATION"
               for reg in ("R1", "R3"))
           and any(_verdict(r, reg, g1vu, "regret", n) == "A_BETTER"
                  for reg in ("R1", "R3") for n in CHECKPOINTS))
    if d2a or d2b:
        fired.append("D2")
    # D3 / D3': state-key sign flip (shipped-γ face and γ=1 face)
    def flip(pair: str) -> bool:
        return any(_verdict(r, "R2", pair, "regret", n) == "A_WORSE"
                   and _verdict(r, "R1", pair, "regret", n) == "A_BETTER"
                   for n in CHECKPOINTS)
    if flip(kvu):
        fired.append("D3")
    if flip(g1vu):
        fired.append("D3'")
    order = ["D1", "D4", "D2", "D3", "D3'"]
    headline = next((d for d in order if d in fired), None)
    return {"fired": fired, "headline": headline,
            "precedence": order,
            "detail": {
                "D1_implementation_defect": d1, "D4_kernel_healthy": d4,
                "D2_early_drag_clause": d2a,
                "D2_gamma_drag_dominant_clause": d2b,
                "D3_statekey_flip_shipped_gamma": flip(kvu),
                "D3prime_statekey_flip_gamma1": flip(g1vu),
            }}


# ---------------------------------------------------------------------------
# real-data floor calibration (design Decision 6 — the mined table)
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
    hits: dict[str, list[bool]] = {}
    for outcome in _scoring_outcomes(run):
        family = str(outcome.get("method_family_or_claim_source") or "")
        if family:
            hits.setdefault(family, []).append(_is_success(outcome))
    return {f: sum(v) / len(v) for f, v in sorted(hits.items())}


def _training_store(rows: list[dict]) -> q_cells.InMemoryStore:
    obs = []
    for row in rows:
        for outcome in _scoring_outcomes(row):
            mass = fp.outcome_mass(outcome)
            obs.append({"schema": q_cells.OBS_SCHEMA, "ts": "ex7",
                        "source": "settlement",
                        "signature_hash": str(row.get("signature_hash")
                                              or ""),
                        "method_family": str(
                            outcome.get("method_family_or_claim_source")
                            or ""),
                        "claim": None, "agent": None, "dispatch_id": None,
                        "credit": mass[0]})
    return q_cells.InMemoryStore(obs)


def _proposal_prior(training: list[dict]) -> dict[str, float]:
    counts: dict[str, int] = {}
    for row in training:
        for outcome in _scoring_outcomes(row):
            family = str(outcome.get("method_family_or_claim_source") or "")
            if family:
                counts[family] = counts.get(family, 0) + 1
    return dict(sorted(counts.items())) if counts else {}


def replay(table_path: Path) -> dict:
    """Paired kernel-vs-uniform replay over the mined feature-table/1
    (EX-5's leave-one-run-out protocol). Expected NO_SEPARATION at
    current table scale — the honest floor, reported as a floor."""
    rows = fp.load_table(table_path)
    usable = [r for r in rows if _scoring_outcomes(r)]
    replays = []
    pooled: dict[str, list[int]] = {"kernel": [], "uniform": []}
    for i, run in enumerate(usable):
        training = [r for j, r in enumerate(usable) if j != i]
        probs = _success_probs(run)
        prior = _proposal_prior(training)
        store = _training_store(training)
        sig = str(run.get("signature_hash") or "")
        per_arm = {}
        for arm in ("kernel", "uniform"):
            successes = 0
            for trial in range(N_TRIALS_REPLAY):
                if arm == "kernel":
                    rng = random.Random(
                        f"ex7/replay/policy/{run.get('run_id')}/kernel/{trial}")
                    receipt = q_cells.sample_method_family(
                        sig, prior or {"other": 1.0}, store, rng=rng)
                    family = str(receipt["family"])
                else:
                    rng = random.Random(
                        f"ex7/replay/policy/{run.get('run_id')}/uniform/{trial}")
                    family = rng.choice(sorted(prior) or ["other"])
                p = probs.get(family, 0.0)
                ok = random.Random(
                    f"ex7/replay/env/{run.get('run_id')}/{trial}/{family}"
                ).random() < p
                successes += 1 if ok else 0
                pooled[arm].append(1 if ok else 0)
            per_arm[arm] = {"first_act_success_rate":
                            successes / N_TRIALS_REPLAY}
        replays.append({"run_id": run.get("run_id"),
                        "task_id": run.get("task_id"),
                        "env_success_probs": probs,
                        "arms": per_arm})
    if pooled["kernel"]:
        test = sign_test([float(k) for k in pooled["kernel"]],
                         [float(u) for u in pooled["uniform"]])
    else:
        test = {"wins": 0, "losses": 0, "ties": 0, "n": 0,
                "p_value": 1.0, "verdict": "NO_SEPARATION"}
    underpowered = len(usable) < UNDERPOWERED_MIN_USABLE
    return {
        "table": str(table_path.relative_to(ROOT)),
        "table_rows": len(rows), "usable_runs": len(usable),
        "n_trials": N_TRIALS_REPLAY,
        "underpowered": underpowered,
        "sign_test": test,
        "expected": "NO_SEPARATION (the honest floor at this table scale)",
        "replays": replays,
    }


# ---------------------------------------------------------------------------
# harness
# ---------------------------------------------------------------------------

def run(seeds: tuple[int, ...] = SEED_IDS, horizon: int = HORIZON,
        table_path: Path = DEFAULT_TABLE) -> dict:
    checkpoints = tuple(n for n in CHECKPOINTS if n <= horizon)
    regimes = {reg: run_regime(reg, seeds, horizon, checkpoints)
               for reg in REGIMES}
    results = {
        "schema": SCHEMA,
        "pre_registration": {
            "openspec_change": "kernel-judgment-experiment",
            "design_amended_after_review": True,
            "primary_endpoints": ("kernel_vs_uniform mean cumulative "
                                  "regret at n=100, one per regime"),
            "seed_policy": "exactly 200 seeds/regime, run once, "
                           "never re-tuned",
        },
        "classes": list(CLASSES),
        "vocabulary": sorted(method_families.registered_tokens()),
        "checkpoints": list(checkpoints),
        "arms": list(ARMS),
        "regimes": regimes,
    }
    results["discriminators"] = evaluate_discriminators(results)
    results["replay"] = replay(table_path)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ex7_kernel_judgment.py",
        description="EX-7: kernel-judgment MC experiment — the real "
                    "DTS/q_cells kernel vs uniform vs ε-greedy over "
                    "pre-registered synthetic worlds + mined-table "
                    "floor replay")
    parser.add_argument("--table", type=Path, default=DEFAULT_TABLE,
                        help="mined feature-table/1 jsonl (default: the "
                             "Part-A fixture golden table)")
    args = parser.parse_args(argv)
    results = run(table_path=args.table)
    out_path = ROOT / RESULTS_REL
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, sort_keys=True, indent=2)
        + "\n", encoding="utf-8")
    summary = {k: results[k] for k in (
        "schema", "checkpoints")}
    summary["discriminators"] = results["discriminators"]["fired"]
    summary["headline"] = results["discriminators"]["headline"]
    for reg, data in results["regimes"].items():
        summary[f"{reg}_kernel_vs_uniform_n100"] = data["pairs"][
            "kernel_vs_uniform"]["regret"][100]["verdict"]
        summary[f"{reg}_g1_vs_uniform_n100"] = data["pairs"][
            "kernel-g1_vs_uniform"]["regret"][100]["verdict"]
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
