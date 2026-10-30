# -*- coding: utf-8 -*-
"""counterfactual_analysis.py — the CRAFT-shaped counterfactual
rollout-branching DATA ANALYSIS (research card issue 905, go/no-go
tier).

The question the data answers: do FAILED rollouts' per-step ΔP
profiles differ from their SUCCESSFUL siblings' BEFORE the failure
point? If the pre-failure contrast is informative, the contrast is
trainable credit and branching promotes to an implementation card; if
not, branching buys nothing and this card closes with the negative
result. BOTH outcomes are valid completions — the analysis is honest,
never rigged toward a contrast.

Tier label (rides every conclusion the report emits):
"mock-ledger tier; real-ledger analysis pending accumulation" — the
rollouts are loop_sim_v3's real policy/settlement/credit faces over
the real q_cells v2 trajectory ledger, with the worker FLAT and
deterministic (a correct-family dispatch verifies at the cheap bill,
every other dispatch never verifies). No real-ledger conclusion is
claimed here.

PRE-REGISTERED DESIGN (fixed in this docstring before any result was
computed; the report re-emits every constant so the threshold cannot
drift after the fact):

  1. Units. Per seed (5 seeds: 0..4) and per situation pair (3 pairs:
     dead-1↔offsets, dead-2↔packer, dead-3↔grammar), 2 sequential
     reps — each rep runs ONE rollout on the DEAD situation (no
     answering family in loop_sim_v3.SITUATIONS → every dispatch
     fails → the loss-cut rolls it back: the FAILED arm) and ONE on
     its LIVE sibling (answered by a known family → completes: the
     SUCCESS arm). One workspace per seed; the ledger accumulates
     across a 1-lap warm-up loop and all reps (the real committing
     faces bank every settled dispatch).

  2. ΔP profile (ledger-only reconstruction). For rollout R, the
     per-step sequence of the honest Beta posterior mean
     (1+s)/(2+s+f) of the family DRAWN at each step, where (s, f) is
     R's situation's settled fold mass at the moment R STARTED — all
     settlement observation rows physically preceding R's first
     assign_step action row in the append stream (credit banks at
     rollout commit, so a rollout's decisions never see its own
     rows). Reconstruction reads ONLY trajectory_rows(ws): actions
     (the drawn family per step), results (r_t / verified per step),
     settled observations (the mass), terminal actions (the arm's
     outcome). γ = 1.0 (the simulator's constant schedule), so replay
     weights are exactly 1.0.

  3. Matched prefix. Divergence step of the SUCCESS arm = its first
     verified dispatch. Prefix length L = min(len(F), first_verified
     − 1) — at every matched step BOTH arms show an unverified
     dispatch (r_t = 0; checked, not assumed). L = 0 pairs (the
     success arm verified immediately) contribute nothing and are
     COUNTED, never silently dropped.

  4. Contrast. Per pair: D = mean(profile_S over prefix) −
     mean(profile_F over prefix). Pooled statistic: Cohen's d =
     mean(D) / sd(D, ddof=1) over all usable pairs; per-seed
     stability = the sign of that seed's mean D.

  5. DECISION THRESHOLD (a priori). GO iff ALL of:
       (a) usable pairs >= MIN_USABLE_PAIRS (10),
       (b) pooled |d| >= EFFECT_SIZE_FLOOR (0.5, medium),
       (c) the pooled sign holds in >= MIN_SEED_SIGN_CONSENSUS (4)
           of the 5 seeds,
       (d) sd(D) > 0 (a degenerate zero-variance contrast is not
           evidence).
     Otherwise NO-GO at mock tier. The GO/NO-GO outcome is DATA — the
     tests pin the harness mechanics, never the outcome.

  6. Honesty decomposition (reported, decides nothing extra): the
     matched-prefix r_t streams of both arms. Under the flat worker
     they are identically zero — any contrast the analysis finds rides
     the accumulated fold-state axis (dead situations bank only
     failure mass, live siblings bank success mass), NOT a
     within-situation pre-error signature. The report states this
     explicitly alongside the numbers.
"""
from __future__ import annotations

import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LOOP = Path(__file__).resolve().parent
_SCRIPTS = _LOOP.parents[1] / "scripts"
for _p in (_LOOP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import q_cells  # noqa: E402

from loop_sim_v3 import (  # noqa: E402
    GAMMA, _seed_ctx, run_rollout, run_v3_loop)

MOCK_TIER_LABEL = ("mock-ledger tier; real-ledger analysis pending "
                   "accumulation")

QUESTION = ("do failed rollouts' delta-P profiles differ from their "
            "successful siblings' BEFORE the failure point?")

#: the analysis's seed sweep (multiple-seed stability is REQUIRED for
#: a GO — the pre-registered rule demands 4-of-5 sign consistency)
SEEDS = (0, 1, 2, 3, 4)

#: (dead situation, live sibling situation) — the battery's own shape:
#: anything outside loop_sim_v3.SITUATIONS is dead by construction
SITUATION_PAIRS = (("dead-1", "offsets"), ("dead-2", "packer"),
                   ("dead-3", "grammar"))

#: sequential reps per (seed, pair) — the ledger accumulates across them
REPS = 2

#: warm-up laps of the real loop before the analysis rollouts (enough
#: to differentiate the fold, not enough to pin every live sibling to
#: an immediate first-step verify — that would empty the prefixes)
WARM_LAPS = 1

#: ---- pre-registered decision thresholds (fixed a priori) ----
MIN_USABLE_PAIRS = 10
EFFECT_SIZE_FLOOR = 0.5
MIN_SEED_SIGN_CONSENSUS = 4


# ----------------------------------------------------- ledger replay

@dataclass(frozen=True)
class StepRecord:
    """ONE dispatch step, replayed from the (s,a,r) ledger rows."""
    step_no: int
    family: str
    r_t: float | None
    verified: bool


@dataclass(frozen=True)
class RolloutRecord:
    """ONE rollout, replayed ledger-only: its steps, its terminal
    action, and its situation's settled fold mass at its START (the
    predecessor state its every dispatch decided under)."""
    rollout_id: str
    signature: str
    terminal: str
    steps: tuple[StepRecord, ...]
    snapshot: dict[str, tuple[float, float]]
    profile: tuple[float, ...]


def posterior_mean(mass: tuple[float, float]) -> float:
    """The honest Beta(1,1)-prior posterior mean over banked mass."""
    s, f = mass
    return (1.0 + s) / (2.0 + s + f)


def _step_no_of(step_id: str) -> int | None:
    """The dispatch index encoded in ``<rid>-s<NN>`` (None for the
    terminal row, whose step_id is ``<rid>-terminal``)."""
    head, sep, tail = step_id.rpartition("-s")
    if not sep or not tail.isdigit():
        return None
    return int(tail)


def _settled_mass(mass: dict[str, dict[str, list[float]]],
                  sig: str) -> dict[str, tuple[float, float]]:
    """One situation's banked mass, frozen at a replay instant."""
    return {fam: (s_f[0], s_f[1])
            for fam, s_f in mass.get(sig, {}).items()}


def _signature_by_rollout(rows: list[dict]) -> dict[str, str]:
    """Pass 1: each rollout's situation signature, recovered from the
    settlement rows (their dispatch_id IS the step_id of the rollout's
    own dispatch). No signature, no honest snapshot — the rollout
    records an empty one."""
    sigs: dict[str, str] = {}
    for row in rows:
        if str(row.get("schema") or "") != q_cells.OBS_SCHEMA:
            continue
        did = str(row.get("dispatch_id") or "")
        head, sep, _tail = did.rpartition("-s")
        if sep and head and head not in sigs:
            sigs[head] = str(row["signature_hash"])
    return sigs


def settled_mass_by_signature(ws) -> dict[str, dict[str, tuple[float, float]]]:
    """The END-of-stream settled mass per (situation signature, family)
    — the same accumulation the replay feeds, run to completion. This
    is the cross-check face: with γ = GAMMA it must equal
    q_cells.fold(store, gamma=GAMMA)'s cells exactly."""
    mass: dict[str, dict[str, list[float]]] = {}
    for row in q_cells.trajectory_rows(ws):
        if str(row.get("schema") or "") == q_cells.OBS_SCHEMA:
            _absorb_observation(mass, row)
    return {sig: {fam: (s, f) for fam, (s, f) in fams.items()}
            for sig, fams in mass.items()}


def _absorb_observation(mass: dict[str, dict[str, list[float]]],
                        row: dict) -> None:
    """Fold ONE settled step-credit observation into the replay mass —
    the exact admission rules the fold face applies (step-kind rows
    only; the information band banks no mass; γ = GAMMA = 1.0 makes
    every weight exactly 1.0)."""
    if row.get("credit") is None:
        return
    if str(row.get("credit_kind") or "") != "step":
        return
    credit = float(row["credit"])
    if 0.0 < credit <= q_cells.OBSERVATION_BAND_CEIL:
        return  # the information option banks no mass
    fam_mass = mass.setdefault(str(row["signature_hash"]), {})
    cell = fam_mass.setdefault(str(row["method_family"]), [0.0, 0.0])
    cell[0] += credit
    cell[1] += 1.0 - credit


def _ingest_action(pending: dict[str, dict[str, Any]],
                   snapshotted: set[str],
                   mass: dict[str, dict[str, list[float]]],
                   sigs: dict[str, str], row: dict) -> None:
    """Ingest ONE action row: a rollout's first assign_step takes its
    start-of-rollout mass snapshot; assign_steps land the drawn
    family; terminal actions land the arm's outcome."""
    rid = str(row["rollout_id"])
    rec = pending.setdefault(rid, {"steps": {}, "terminal": "",
                                   "snapshot": {}})
    kind = str(row.get("kind") or "")
    if kind == "assign_step":
        if rid not in snapshotted:
            snapshotted.add(rid)
            rec["snapshot"] = _settled_mass(mass, sigs.get(rid, ""))
        step_no = _step_no_of(str(row["step_id"]))
        if step_no is not None:
            rec["steps"][step_no] = {"family": str(row["target"])}
    elif kind in ("terminate_rollout", "rollback"):
        rec["terminal"] = kind


def _ingest_result(pending: dict[str, dict[str, Any]],
                   row: dict) -> None:
    """Ingest ONE result row: the step's r_t and verified flag (the
    terminal result row is not a dispatch step and is skipped)."""
    step_no = _step_no_of(str(row["step_id"]))
    if step_no is None:
        return
    rec = pending.setdefault(str(row["rollout_id"]),
                             {"steps": {}, "terminal": "",
                              "snapshot": {}})
    step = rec["steps"].setdefault(step_no, {"family": ""})
    step["r_t"] = None if row.get("r_t") is None else float(row["r_t"])
    step["verified"] = bool(row["verified"])


def reconstruct_rollouts(ws) -> dict[str, RolloutRecord]:
    """Replay the workspace's trajectory ledger into per-rollout
    records — reads ONLY q_cells.trajectory_rows(ws) (actions, results,
    settled observations, terminal actions in append order). A
    rollout's snapshot is the settled mass at the instant the walk
    reaches its first assign_step row (credit banks at rollout commit,
    so the snapshot is exactly the state its every dispatch decided
    under); its profile prices each step's drawn family under that
    snapshot. γ = GAMMA (1.0) makes every replay weight exactly 1.0,
    matching q_cells.fold(store, gamma=GAMMA) at the stream's end."""
    rows = q_cells.trajectory_rows(ws)
    sigs = _signature_by_rollout(rows)
    mass: dict[str, dict[str, list[float]]] = {}
    pending: dict[str, dict[str, Any]] = {}
    snapshotted: set[str] = set()
    for row in rows:
        schema = str(row.get("schema") or "")
        if schema == q_cells.OBS_SCHEMA:
            _absorb_observation(mass, row)
        elif schema == q_cells.SCHEMA_ACTION_V2:
            _ingest_action(pending, snapshotted, mass, sigs, row)
        elif schema == q_cells.SCHEMA_RESULT_V2:
            _ingest_result(pending, row)

    records: dict[str, RolloutRecord] = {}
    for rid, rec in pending.items():
        snapshot = rec.get("snapshot") or {}
        steps = tuple(
            StepRecord(step_no=no,
                       family=rec["steps"][no]["family"],
                       r_t=rec["steps"][no].get("r_t"),
                       verified=rec["steps"][no].get("verified", False))
            for no in sorted(rec["steps"]))
        profile = tuple(
            round(posterior_mean(snapshot.get(st.family,
                                                (0.0, 0.0))), 6)
            for st in steps)
        records[rid] = RolloutRecord(
            rollout_id=rid, signature=sigs.get(rid, ""),
            terminal=rec["terminal"], steps=steps,
            snapshot=snapshot, profile=profile)
    return records


# ------------------------------------------------ matched-prefix axis

@dataclass(frozen=True)
class PairContrast:
    """ONE (failed, successful) sibling pair at its matched prefix."""
    usable: bool
    reason: str
    prefix_len: int = 0
    contrast: float | None = None
    prefix_r_t_failed: tuple[float | None, ...] = ()
    prefix_r_t_success: tuple[float | None, ...] = ()
    profile_failed: tuple[float, ...] = ()
    profile_success: tuple[float, ...] = ()


def matched_prefix_contrast(failed: RolloutRecord,
                            success: RolloutRecord) -> PairContrast:
    """The CRAFT alignment: both arms' PRE-DIVERGENCE steps, side by
    side. The failed arm contributes its whole pre-terminal run; the
    success arm contributes the steps before its first verified
    dispatch; the common prefix is the shorter of the two. A pair is
    unusable when either arm lacks its structural outcome or the
    success arm verified at its first step (empty prefix — counted,
    never silently dropped)."""
    if failed.terminal != "rollback":
        return PairContrast(False, "failed arm did not roll back")
    if success.terminal != "terminate_rollout":
        return PairContrast(False, "success arm did not complete")
    first_verified = next((st.step_no for st in success.steps
                           if st.verified), None)
    if first_verified is None:
        return PairContrast(False, "success arm has no verified step")
    pre_success = [st for st in success.steps
                   if st.step_no < first_verified]
    length = min(len(failed.steps), len(pre_success))
    if length == 0:
        return PairContrast(False, "empty matched prefix")
    prof_f = failed.profile[:length]
    prof_s = success.profile[:length]
    return PairContrast(
        usable=True, reason="matched", prefix_len=length,
        contrast=round(statistics.fmean(prof_s) - statistics.fmean(prof_f),
                       6),
        prefix_r_t_failed=tuple(st.r_t for st in
                                failed.steps[:length]),
        prefix_r_t_success=tuple(st.r_t for st in
                                 success.steps[:length]),
        profile_failed=prof_f, profile_success=prof_s)


# ------------------------------------------------------- the statistic

def cohen_d(values: list[float]) -> float | None:
    """Pooled Cohen's d over the paired contrasts (ddof=1); None when
    the sample cannot carry a sd (fewer than 2 values or zero
    variance — a degenerate contrast is not evidence)."""
    if len(values) < 2:
        return None
    sd = statistics.stdev(values)
    if sd == 0.0:
        return None
    return statistics.fmean(values) / sd


def decide(pooled_d: float | None, seed_signs: list[int],
           n_usable: int) -> dict[str, Any]:
    """The pre-registered decision rule, verbatim from the module
    docstring. GO requires the sample, the effect size, the per-seed
    sign consensus AND a non-degenerate sd — every other outcome is
    NO-GO at mock tier, reported with its numbers."""
    reasons: list[str] = []
    if n_usable < MIN_USABLE_PAIRS:
        reasons.append(f"usable pairs {n_usable} < {MIN_USABLE_PAIRS}")
    if pooled_d is None:
        reasons.append("degenerate contrast (no usable Cohen's d)")
    else:
        if abs(pooled_d) < EFFECT_SIZE_FLOOR:
            reasons.append(f"|d| {abs(round(pooled_d, 4))} < "
                           f"{EFFECT_SIZE_FLOOR}")
        pooled_sign = 1 if pooled_d > 0 else -1
        consistent = sum(1 for s in seed_signs if s == pooled_sign)
        if consistent < MIN_SEED_SIGN_CONSENSUS:
            reasons.append(f"seed sign consensus {consistent}/"
                           f"{len(seed_signs)} < "
                           f"{MIN_SEED_SIGN_CONSENSUS}")
    outcome = "NO-GO" if reasons else "GO"
    if not reasons:
        reasons.append("all pre-registered thresholds met")
    return {"outcome": outcome, "reasons": reasons,
            "rule": {"min_usable_pairs": MIN_USABLE_PAIRS,
                     "effect_size_floor": EFFECT_SIZE_FLOOR,
                     "min_seed_sign_consensus": MIN_SEED_SIGN_CONSENSUS}}


# -------------------------------------------------- pair generation

def generate_pairs(root, *, seeds: tuple[int, ...] = SEEDS,
                   pairs: tuple[tuple[str, str], ...] = SITUATION_PAIRS,
                   reps: int = REPS, warm_laps: int = WARM_LAPS) -> list:
    """The seeded rollout pairs, through the loop's REAL faces: per
    seed one fresh workspace, a warm-up loop (the ledger accumulates),
    then per (pair, rep) one live-sibling rollout and one dead
    rollout. Returns the generation manifest (Path-free, deterministic
    — the replay is what carries the data, the manifest carries the
    labels)."""
    root = Path(root)
    manifest: list[dict[str, Any]] = []
    for seed in seeds:
        ws = root / f"cf-seed-{seed}"
        run_v3_loop(ws, laps=warm_laps, seed=seed)
        ctx = _seed_ctx(ws, seed=seed, lap=warm_laps + 1, gamma=GAMMA)
        pair_rows: list[dict[str, Any]] = []
        for pi, (dead_sit, live_sit) in enumerate(pairs):
            for rep in range(reps):
                tag = f"{seed}-{pi}-{rep}"
                live = run_rollout(
                    ws, ctx, rid=f"ro-cf-{tag}-live",
                    task_id=f"cf-{tag}-live", situation=live_sit,
                    gamma=GAMMA, ablate_credit=False,
                    scramble_credit=False, ablate_selector=False)
                dead = run_rollout(
                    ws, ctx, rid=f"ro-cf-{tag}-dead",
                    task_id=f"cf-{tag}-dead", situation=dead_sit,
                    gamma=GAMMA, ablate_credit=False,
                    scramble_credit=False, ablate_selector=False)
                pair_rows.append(
                    {"seed": seed, "pair_index": pi, "rep": rep,
                     "live_situation": live_sit, "dead_situation": dead_sit,
                     "success_rollout_id": live["rollout_id"],
                     "failed_rollout_id": dead["rollout_id"],
                     "success_terminal": live["terminal"],
                     "failed_terminal": dead["terminal"],
                     "success_steps": live["steps"],
                     "failed_steps": dead["steps"]})
        manifest.append({"seed": seed, "pairs": pair_rows})
    return manifest


# ------------------------------------------------------ the analysis

def run_analysis(root, *, seeds: tuple[int, ...] = SEEDS,
                 pairs: tuple[tuple[str, str], ...] = SITUATION_PAIRS,
                 reps: int = REPS, warm_laps: int = WARM_LAPS) -> dict:
    """The full pre-registered analysis: generate the seeded pairs,
    reconstruct the ΔP profiles ledger-only, contrast at matched
    prefixes, aggregate, and decide. Returns a deterministic,
    Path-free report — the go/no-go verdict is DATA, emitted with its
    numbers and the honesty labels, never asserted by construction."""
    manifest = generate_pairs(root, seeds=seeds, pairs=pairs,
                              reps=reps, warm_laps=warm_laps)
    per_pair: list[dict[str, Any]] = []
    per_seed: list[dict[str, Any]] = []
    contrasts_by_seed: dict[int, list[float]] = {}
    empty_prefix_pairs = 0
    structural_skips = 0
    prefix_r_t_all: list[float | None] = []
    for seed_row in manifest:
        records = reconstruct_rollouts(
            Path(root) / f"cf-seed-{seed_row['seed']}")
        seed_contrasts: list[float] = []
        for pair in seed_row["pairs"]:
            failed = records[pair["failed_rollout_id"]]
            success = records[pair["success_rollout_id"]]
            contrast = matched_prefix_contrast(failed, success)
            if not contrast.usable:
                if contrast.reason == "empty matched prefix":
                    empty_prefix_pairs += 1
                else:
                    structural_skips += 1
            else:
                seed_contrasts.append(contrast.contrast or 0.0)
                prefix_r_t_all.extend(contrast.prefix_r_t_failed)
                prefix_r_t_all.extend(contrast.prefix_r_t_success)
            per_pair.append({
                "seed": pair["seed"], "pair_index": pair["pair_index"],
                "rep": pair["rep"], "usable": contrast.usable,
                "reason": contrast.reason,
                "prefix_len": contrast.prefix_len,
                "contrast": contrast.contrast,
                "profile_failed": list(contrast.profile_failed),
                "profile_success": list(contrast.profile_success),
                "prefix_r_t_failed": list(contrast.prefix_r_t_failed),
                "prefix_r_t_success": list(contrast.prefix_r_t_success),
                "failed_terminal": pair["failed_terminal"],
                "success_terminal": pair["success_terminal"]})
        contrasts_by_seed[seed_row["seed"]] = seed_contrasts
        seed_mean = (statistics.fmean(seed_contrasts)
                     if seed_contrasts else None)
        per_seed.append({
            "seed": seed_row["seed"], "n_usable": len(seed_contrasts),
            "mean_contrast": (None if seed_mean is None
                              else round(seed_mean, 6)),
            "sign": (0 if not seed_contrasts or seed_mean == 0
                     else (1 if seed_mean > 0 else -1))})
    all_contrasts = [c for cs in contrasts_by_seed.values() for c in cs]
    pooled_d = cohen_d(all_contrasts)
    seed_signs = [row["sign"] for row in per_seed]
    verdict = decide(pooled_d, seed_signs, len(all_contrasts))
    r_t_known = [r for r in prefix_r_t_all if r is not None]
    return {
        "tier": MOCK_TIER_LABEL,
        "question": QUESTION,
        "design": {"seeds": list(seeds), "situation_pairs": [
            {"dead": d, "live": l} for d, l in pairs],
            "reps": reps, "warm_laps": warm_laps, "gamma": GAMMA,
            "reconstruction": "ledger-only replay of q_cells v2 "
                              "trajectory rows; per-step delta-P = the "
                              "drawn family's honest posterior mean "
                              "under the rollout's start-of-rollout "
                              "fold snapshot"},
        "n_pairs_generated": len(per_pair),
        "n_usable_pairs": len(all_contrasts),
        "n_skipped_empty_prefix": empty_prefix_pairs,
        "n_skipped_structural": structural_skips,
        "per_pair": per_pair,
        "per_seed": per_seed,
        "pooled": {"cohen_d": (None if pooled_d is None
                               else round(pooled_d, 6)),
                   "mean_contrast": (round(statistics.fmean(all_contrasts),
                                           6) if all_contrasts else None),
                   "sd_contrast": (round(statistics.stdev(all_contrasts),
                                         6) if len(all_contrasts) > 1
                                   else None)},
        "prefix_r_t_identity": {
            "note": "under the flat worker both arms' matched-prefix "
                    "steps are unverified dispatches; any contrast "
                    "rides the accumulated fold-state axis, not a "
                    "within-situation pre-error signature",
            "n_prefix_steps": len(r_t_known),
            "all_zero": all(r == 0.0 for r in r_t_known)},
        "verdict": verdict,
    }
