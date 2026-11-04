# -*- coding: utf-8 -*-
"""loop_sim_v3.py — the closed-loop simulator re-based on the rl-v2
faces (#887).

The #887 adaptation of the learning-loop simulator: the loop's
DECISIONS are the real rl-v2 policy faces and its memory is the REAL
trajectory ledger — the mock is confined to the WORKER (task
outcomes), never the policy:

    select (policy.selector DTS draw + record_selection) ->
    per dispatch: assign (policy.assigner P⊗Q draw) -> the mock worker
    executes -> result row (q_cells v2 (s,a,r) store) -> per-dispatch
    draft (settlement.per_dispatch conjunctive three-layer gate) ->
    β termination check (policy.terminator) + one-shot watchdog ->
    terminal action -> commit (settlement.draft_commit) -> credit
    spine: settled credit banks the family's fold cell (q_cells
    append_observation, the same substrate the assigner's
    cell_posterior reads) + shaped terminal return (credit.returns) ->
    advantage (credit.advantage) -> spawn flowback (credit.lineage) ->
    next lap.

Every realized improvement is therefore attributable to the POLICY
faces: the worker is FLAT (a correct-family dispatch always verifies
at the same token bill, a wrong-family dispatch never does — no
proficiency drift), so the only thing that changes across laps is what
the ledger taught the selector/assigner/terminator.

Determinism: fixed seeds thread every draw (no wall clock in any
decision — timestamps come from a deterministic counter clock and ride
every row); γ is the constant 1.0 schedule so the fold arithmetic pins
exactly. The battery over this simulator is
tests/test_proof_battery_v3_887.py.
"""
from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path
from typing import Any

_SIM = Path(__file__).resolve().parent
_LOOP = _SIM.parent
_SCRIPTS = _SIM.parents[2] / "scripts"
for _p in (_SIM, _LOOP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import numpy as np  # noqa: E402

import loop_sim  # noqa: E402 — the shared workspace bootstrap
from core import Budget  # noqa: E402
from credit import advantage as credit_advantage  # noqa: E402
from credit import lineage as credit_lineage  # noqa: E402
from credit import returns as credit_returns  # noqa: E402
from policy import assigner, selector, terminator  # noqa: E402
from rlvr import q_cells  # noqa: E402
from settlement import draft_commit  # noqa: E402
from state import telemetry as _telemetry  # noqa: E402

POLICY_VERSION = "rl-v2-loop/1"

#: constant γ: age-free, so every fold pin in the battery is exact
#: (the fold's own domain — q_cells accepts γ ∈ (0, 1])
GAMMA = 1.0

#: the temporal-credit discount for credit.returns (that face's own
#: documented domain, strictly inside (0, 1) — a DIFFERENT axis from
#: the fold's evidence-age γ above)
RETURNS_GAMMA = 0.9

#: the spawn-credit discount (credit.lineage's γ_L)
GAMMA_LINEAGE = 0.5

#: the outcome bonus magnitude — mirrors settlement.rollout_agg
TERMINAL_BONUS = 1.0

#: J(φ) = E[R_task − λ·C_total]'s cost weight (documented, NOT fitted)
LAMBDA_COST = 0.1

#: the fixed-deadline arm's step count — the terminator's own documented
#: cold default (a fair fixed policy: the prior BEFORE any learning)
FIXED_STEPS = int(terminator.COLD_FAMILY_PRIOR)

#: the rollout safety cap (never reached once the loss-cut is live)
MAX_STEPS = 12

#: the flat worker's honest bills: a correct-family dispatch verifies
#: at 1000 tokens / 10s; a wrong-family dispatch never verifies and
#: burns 4000 tokens / 40s. FLAT — the policy learns, the worker doesn't.
RIGHT_TOKENS = 1000
WRONG_TOKENS = 4000
RIGHT_SECONDS = 10.0
WRONG_SECONDS = 40.0

#: the mock dispatch envelope's wall budget (the watchdog's operand)
PER_DISPATCH_BUDGET_S = 600.0

#: the trust weight an UNVERIFIED step's outcome carries into the
#: advantage modulation (a verified one carries 1.0)
UNVERIFIED_CONFIDENCE = 0.5

RECIPE_SEGMENT = "facts_snapshot"
VERIF_SEGMENT = "none"
TIER = 1
#: the lineage axis's EXPLICIT spawn width (#924 — the mock driver's
#: constant choice; the row must record the conscious decision)
SPAWN_SLOTS = 1

#: the loop's method vocabulary — REAL closed-registry tokens
FAMILIES = ("crypto-core-identification", "dynamic-trace",
            "static-decompile")
#: the tracked family (the v2 battery's fam-a analog)
TRACKED = "static-decompile"

#: situation -> the family that actually answers it (the worker's truth)
SITUATIONS: dict[str, str] = {
    "offsets": "static-decompile",
    "packer": "dynamic-trace",
    "grammar": "crypto-core-identification",
}

#: lap -> ((task_id, situation), ...). The offsets situation repeats
#: every lap (the same-situation learning axis); lap 4 pairs the
#: learned-good situation against a dead one (the selection axis).
LAP_TASKS: tuple[tuple[tuple[str, str], ...], ...] = (
    (("t1", "offsets"), ("t2", "packer")),
    (("t3", "offsets"), ("t4", "packer")),
    (("t5", "offsets"), ("t6", "grammar")),
    (("t7", "offsets"), ("t8", "dead-1")),
)


def situation_signature(situation: str) -> str:
    """The situation's 12-hex state signature — SAME situation, SAME
    signature: the fold cell the learning banks into is keyed by it."""
    digest = hashlib.sha256(f"v3-situation/{situation}".encode("utf-8"))
    return digest.hexdigest()[:12]


def ring_next(family: str) -> str:
    """The E1c scramble rotation: one step around the family ring."""
    names = list(FAMILIES)
    return names[(names.index(family) + 1) % len(names)]


def arm_key(family: str) -> str:
    """The 4-dim fold key the loop banks credit under."""
    return q_cells.arm_key(family, RECIPE_SEGMENT, VERIF_SEGMENT, TIER)


class _Clock:
    """Deterministic timestamp counter — no wall clock anywhere."""

    def __init__(self) -> None:
        self._n = 0

    def tick(self) -> str:
        self._n += 1
        seconds = self._n % 60
        minutes = (self._n // 60) % 60
        hours = self._n // 3600
        return f"2026-01-01T{hours:02d}:{minutes:02d}:{seconds:02d}Z"


def _true_family(situation: str) -> str | None:
    """The family that answers the situation; None = dead (nothing
    answers — the planted oversized-task analog)."""
    return SITUATIONS.get(situation)


def _worker_execute(situation: str, family: str,
                    planted: dict | None = None) -> dict:
    """THE MOCK WORKER — the loop's only fiction. Flat and
    deterministic: correct family verifies at the cheap bill, wrong
    family (or a dead situation) never verifies at the expensive bill.
    ``planted`` injects a documented deviation (the battery's fault
    injection — the v2 battery's planted-wrong-tool precedent)."""
    if planted is not None:
        out = {"verified": False, "tokens": WRONG_TOKENS,
               "seconds": WRONG_SECONDS}
        out.update(planted)
        return out
    if _true_family(situation) is not None and family == _true_family(situation):
        return {"verified": True, "tokens": RIGHT_TOKENS,
                "seconds": RIGHT_SECONDS}
    return {"verified": False, "tokens": WRONG_TOKENS,
            "seconds": WRONG_SECONDS}


def _assign(ws, ctx: dict, rid: str, sig: str, step_no: int,
            candidates: list[str]) -> dict:
    """ONE real assigner draw for the dispatch (neutral planner
    ranking: the P⊗Q tilt is pure posterior — the learning lives in Q,
    never in a mock planner's opinion)."""
    ranking = {f: 1.0 for f in candidates}
    rng = random.Random(f"v3/{ctx['seed']}/{rid}/{step_no}/assign")
    return assigner.assign_method(
        ws, candidates, ranking, signature_hash=sig, tier=TIER,
        rng=rng, gamma=ctx["gamma"])


# ------------------------------------------------------- the credit spine

def _bank_settled_credit(ws, ctx: dict, sig: str, family: str,
                         credit: float, *, claim: str, dispatch_id: str,
                         scramble: bool) -> dict | None:
    """The settlement → fold spine: the settled dispatch credit lands
    as ONE q-cell-obs row at the family's arm key (source=settlement,
    credit_kind=step — exactly the shape the fold admits). The E1c
    scramble misattributes the row to the ring's next family: the
    memory face is FED but fed the WRONG family."""
    if scramble:
        family = ring_next(family)
    row = q_cells.append_observation(
        ws, sig, family, credit, source="settlement", claim=claim,
        dispatch_id=dispatch_id, arm_key_col=arm_key(family),
        credit_kind="step", reason="v3-dispatch-settlement",
        ts=ctx["clock"].tick())
    banked = float(row["row"]["credit"])
    if banked != credit:
        _telemetry.emit(ws, "credit", "CREDIT_V_CLAMPED", lap=ctx["lap"],
                        detail=f"injected {credit} banked {banked} — the "
                               f"rail clamp held")
    return row


def _terminal_rows(ws, ctx: dict, rid: str, *, terminal: str,
                   confidences: list[float]) -> dict:
    """The rollout's terminal return: the credit faces price it (the
    discounted, outcome-shaped return over the rollout's own result
    rows; the advantage is confidence-modulated) and ONE terminal
    result row lands it — the rollout's LAST numeric r_t, the
    selector's documented terminal."""
    rewards = credit_returns.rollout_rewards(ws, rid)
    shaped = credit_returns.terminal_shaped(
        rewards, RETURNS_GAMMA, terminal=terminal,
        terminal_bonus=TERMINAL_BONUS)
    advantage = credit_advantage.modulate(
        credit_advantage.advantages(shaped, None),
        np.asarray(confidences, dtype=float))
    row = q_cells.append_result(
        ws, rollout_id=rid, step_id=f"{rid}-terminal",
        r_t=float(shaped[-1]), verified=terminal == "completed",
        R_t=float(shaped[-1]), A_t=float(advantage[-1]), verdict=terminal,
        summary="terminal return (credit.returns shaped)",
        ts=ctx["clock"].tick())
    return {"terminal_r_t": float(shaped[-1]),
            "terminal_a_t": float(advantage[-1]), "row": row}


# ---------------------------------------------------------- one dispatch

def _dispatch(ws, ctx: dict, rid: str, sig: str, situation: str,
              step_no: int, *, planted: dict | None = None,
              candidates: list[str] | None = None) -> dict:
    """ONE dispatch: real assigner draw -> action row -> mock worker ->
    result row -> per-dispatch draft (the three-layer conjunctive
    gate). Returns the dispatch's receipt; settlement and credit land
    later, at the loop's committing faces."""
    cands = candidates if candidates is not None else list(FAMILIES)
    receipt = _assign(ws, ctx, rid, sig, step_no, cands)
    family = receipt["family"]
    sid = f"{rid}-s{step_no:02d}"
    q_cells.append_action(
        ws, kind="assign_step", rollout_id=rid, step_id=sid, target=family,
        params={"method_family": family, "tier": TIER},
        budget={"wall_s": PER_DISPATCH_BUDGET_S, "max_calls": None},
        policy_version=POLICY_VERSION, ts=ctx["clock"].tick())
    # telemetry AFTER the ledger row — a describe-before-durable emit
    # would leave a phantom assignment row on append_action failure
    if len(cands) > 1:
        _telemetry.emit(ws, "assigner", "ASSIGN_WIDENED", lap=ctx["lap"],
                        rollout_id=rid,
                        detail=f"{len(cands)} families in the draw")
    _telemetry.emit(ws, "assigner", "ASSIGN_ASSIGNED", lap=ctx["lap"],
                    rollout_id=rid, detail=f"family {family}")
    out = _worker_execute(situation, family, planted)
    r_t = 1.0 if out["verified"] else 0.0
    cost = out["tokens"] / 10_000.0
    q_cells.append_result(
        ws, rollout_id=rid, step_id=sid, r_t=r_t, verified=out["verified"],
        cost=cost, verdict="pass" if out["verified"] else "fail",
        summary=f"{family} on {situation}: "
                f"{'verified fact' if out['verified'] else 'no new fact'}",
        ts=ctx["clock"].tick())
    verdicts = {"mechanical": out["verified"],
                "scope_verifier": out["verified"], "redteam": True}
    draft = draft_commit.ensure_draft(ws, rid, sid, cost, verdicts,
                                      ts=ctx["clock"].tick())
    return {"step_id": sid, "family": family, "verified": out["verified"],
            "cost": cost, "seconds": out["seconds"], "r_t": r_t,
            "draft_appended": draft["appended"]}


# ----------------------------------------------------------- one rollout

def _open_rollout(ws, ctx: dict, rid: str, task_id: str, *,
                  ablate_selector: bool) -> None:
    """The rollout's first row: the REAL selector's recorded selection
    (skipping it is the E3a selector ablation — the posterior join key
    never lands, so no terminal return ever attributes to the task)."""
    if ablate_selector:
        return
    # the recording face stamps its own ts (no parameter) — every
    # DECISION input downstream reads only the join key + terminal
    # returns, never the timestamp, so the loop stays deterministic
    selector.record_selection(ws, task_id, rollout_id=rid,
                              policy_version=POLICY_VERSION)


def _decide_terminal(check: dict, covered: bool, watchdog: dict,
                     step_no: int) -> str | None:
    """The loop's terminal decision, from the REAL terminator's
    receipts: rule-fired -> completed when the question is covered,
    rolled_back when the loss-cut killed a dead arm; watchdog fire or
    the safety cap -> rolled_back; None = keep dispatching."""
    if check["terminate"]:
        return "completed" if covered else "rolled_back"
    if watchdog["fired"] or step_no >= MAX_STEPS:
        return "rolled_back"
    return None


def _emit_rule(ws, ctx: dict, rid: str, check: dict) -> None:
    """#915 telemetry: a β rule that fired lands its code (fail-open;
    the row is the record, never stdout)."""
    code = {"loss_cut": "TERM_LOSSCUT",
            "question_covered": "TERM_QUESTION_COVERED",
            }.get(check["rule"])
    if code is not None:
        _telemetry.emit(ws, "terminator", code, lap=ctx["lap"],
                        rollout_id=rid, detail=check["why"])


def run_rollout(ws, ctx: dict, *, rid: str, task_id: str,
                situation: str, gamma: float, ablate_credit: bool,
                scramble_credit: bool, ablate_selector: bool,
                fixed_steps: int | None = None,
                pinned_family: str | None = None) -> dict:
    """ONE rollout under the real faces: open (selection) -> dispatches
    with the β termination check + one-shot watchdog -> terminal action
    -> commit -> credit bank (settlement → fold spine) -> terminal
    return row. ``fixed_steps`` switches the rollout to the
    fixed-deadline arm: the terminator's faces do not run at all (the
    fixed policy has no β, so it arms no watchdog and earns no
    efficiency credit). ``pinned_family`` collapses the assigner's
    candidate set to ONE family (the real face, deterministic draw) —
    the NEW-A isolation: with the assignment identical in both arms,
    J measures the TERMINATION axis alone. Returns the rollout's
    receipt."""
    sig = situation_signature(situation)
    _open_rollout(ws, ctx, rid, task_id, ablate_selector=ablate_selector)
    covered = False
    verified_ids: list[str] = []
    confidences: list[float] = []
    steps: list[dict] = []
    terminal = None
    last_check: dict = {}
    deadline: dict | None = None
    if fixed_steps is None:
        # armed PRE-assignment (the one-shot watchdog precedes the
        # first dispatch), so the neutral arm is the COLD default —
        # never the situation's true family (a truth leak); re-arming
        # on the drawn family is a noted v2 refinement.
        nominal = TRACKED
        deadline = terminator.watchdog_deadline(
            nominal, q_cells.trajectory_rows(ws),
            Budget(wall_s=PER_DISPATCH_BUDGET_S), round_no=ctx["lap"])
        _telemetry.emit(ws, "terminator", "TERM_WATCHDOG_ARMED",
                        lap=ctx["lap"], rollout_id=rid,
                        detail=f"cold={deadline['cold']} "
                               f"deadline_s={deadline['deadline_s']}")
    while terminal is None:
        step_no = len(steps) + 1
        disp = _dispatch(ws, ctx, rid, sig, situation, step_no,
                         candidates=[pinned_family]
                         if pinned_family else None)
        steps.append(disp)
        confidences.append(1.0 if disp["verified"]
                           else UNVERIFIED_CONFIDENCE)
        if disp["verified"]:
            covered = True
            verified_ids.append(disp["step_id"])
        if fixed_steps is not None:
            if step_no >= fixed_steps:
                terminal = "completed" if covered else "rolled_back"
            continue
        coverage = {"covered": covered,
                    "question": f"the {situation} question answered",
                    "verified_step_ids": list(verified_ids)}
        last_check = terminator.check_termination(
            rid, coverage, q_cells.trajectory_rows(ws),
            rng=random.Random(f"v3/{ctx['seed']}/{rid}/{step_no}/term"))
        _emit_rule(ws, ctx, rid, last_check)
        watchdog = terminator.watchdog_check(
            deadline, elapsed_s=sum(s["seconds"] for s in steps),
            rollout_completed=False)
        if watchdog["fired"]:
            _telemetry.emit(ws, "terminator", "TERM_WATCHDOG_FIRED",
                            lap=ctx["lap"], rollout_id=rid,
                            detail=f"elapsed "
                                   f"{watchdog['elapsed_s']} >= deadline "
                                   f"{watchdog['deadline_s']}")
        terminal = _decide_terminal(last_check, covered, watchdog,
                                    step_no)
    kind = "terminate_rollout" if terminal == "completed" else "rollback"
    q_cells.append_action(ws, kind=kind, rollout_id=rid, target=task_id,
                          policy_version=POLICY_VERSION,
                          params={"rule": last_check.get("rule")},
                          ts=ctx["clock"].tick())
    commits = draft_commit.commit_batch(ws, rid, ts=ctx["clock"].tick())
    credit_banked = 0.0
    if commits["appended"]:
        # the batch's OWN committed drafts price the credit — the
        # settlement confirmed, so the fold spine banks it
        for draft in draft_commit.draft_rows(ws, rid):
            if ablate_credit:
                continue
            disp = next(d for d in steps
                        if d["step_id"] == draft["dispatch_id"])
            _bank_settled_credit(ws, ctx, sig, disp["family"],
                                 float(draft["credit"]), claim=task_id,
                                 dispatch_id=draft["dispatch_id"],
                                 scramble=scramble_credit)
            credit_banked += float(draft["credit"])
    if deadline is not None:
        wd_final = terminator.watchdog_check(
            deadline, elapsed_s=sum(s["seconds"] for s in steps),
            rollout_completed=True)
        _telemetry.emit(ws, "terminator", "TERM_WATCHDOG_CANCELLED",
                        lap=ctx["lap"], rollout_id=rid,
                        detail=f"early_cancel reason={wd_final['reason']}")
        efficiency = wd_final["efficiency_credit"]
    else:
        efficiency = False
    shaped = _terminal_rows(ws, ctx, rid, terminal=terminal,
                            confidences=confidences)
    committed = draft_commit.committed_rollout(ws, rid)
    return {"task_id": task_id, "rollout_id": rid, "situation": situation,
            "terminal": terminal, "covered": covered, "steps": len(steps),
            "cost": sum(d["cost"] for d in steps),
            "verified_dispatches": sum(1 for d in steps if d["verified"]),
            "terminal_rule": last_check.get("rule"),
            "efficiency_credit": efficiency,
            "credit_banked": credit_banked,
            "committed_total": committed["total_credit"],
            **shaped}


# ------------------------------------------------------ the full lap loop

def _seed_ctx(ws, *, seed: int, lap: int, gamma: float) -> dict:
    return {"ws": ws, "seed": seed, "lap": lap, "gamma": gamma,
            "clock": _Clock()}


def _spawn_child(ws, ctx: dict, parent: dict, *, gamma: float,
                 ablate_credit: bool = False,
                 scramble_credit: bool = False,
                 ablate_selector: bool = False) -> dict:
    """The lineage axis: the retry lap's rollout spawns ONE candidate
    child; the child's credited return flows back at γ_L through
    credit.lineage (the spawning decision EARNED the child's outcome).
    The arm flags propagate — an ablation/scramble arm scrambles the
    WHOLE loop, the child included."""
    parent_rid = parent["rollout_id"]
    child_rid = f"{parent_rid}-child"
    child_tid = f"{parent['task_id']}-child"
    q_cells.append_action(ws, kind="spawn_candidate", rollout_id=parent_rid,
                          step_id=f"{parent_rid}-spawn", target=child_tid,
                          params={"slots": SPAWN_SLOTS},
                          policy_version=POLICY_VERSION,
                          ts=ctx["clock"].tick())
    child = run_rollout(ws, ctx, rid=child_rid, task_id=child_tid,
                        situation=parent["situation"], gamma=gamma,
                        ablate_credit=ablate_credit,
                        scramble_credit=scramble_credit,
                        ablate_selector=ablate_selector)
    credited = credit_lineage.flowback(
        {parent_rid: parent["terminal_r_t"],
         child_rid: child["terminal_r_t"]},
        {child_rid: parent_rid}, gamma_lineage=GAMMA_LINEAGE)
    return {"parent_rid": parent_rid, "child_rid": child_rid,
            "parent_r_t": parent["terminal_r_t"],
            "child_r_t": child["terminal_r_t"], "credited": credited}


def _situation_mass(ws, situation: str, *, gamma: float) -> dict[str, tuple[float, float]]:
    """(success, failure) fold mass per family for ONE situation — the
    exact read the policy's price and the battery's pins use."""
    fold_view = q_cells.fold(q_cells.default_store(ws), gamma=gamma)
    sig = situation_signature(situation)
    mass: dict[str, list[float]] = {f: [0.0, 0.0] for f in FAMILIES}
    for (row_sig, key), cell in fold_view.cells.items():
        if row_sig != sig:
            continue
        fam = q_cells.family_of_action(key)
        if fam in mass:
            mass[fam][0] += cell.success
            mass[fam][1] += cell.failure
    return {f: (mass[f][0], mass[f][1]) for f in FAMILIES}


def _posterior_mean(mass: tuple[float, float]) -> float:
    """The cell's honest Beta posterior mean — the wide Beta(1,1) prior
    under the banked (success, failure) mass."""
    s, f = mass
    return (1.0 + s) / (2.0 + s + f)


def expected_dispatch_cost(ws, situation: str, *, gamma: float = GAMMA) -> float:
    """The policy's exact expected cost for the NEXT dispatch on the
    situation: the families' honest posterior means normalized into a
    draw distribution, priced by the worker's truth (the answering
    family costs the cheap bill, every other one the expensive bill)."""
    true_family = _true_family(situation)
    if true_family is None:
        raise ValueError(f"expected_dispatch_cost: {situation!r} is dead")
    mass = _situation_mass(ws, situation, gamma=gamma)
    means = {f: _posterior_mean(m) for f, m in mass.items()}
    total_mean = sum(means.values())
    cost_total = 0.0
    for family, mean in means.items():
        cost = RIGHT_TOKENS / 10_000.0 if family == true_family \
            else WRONG_TOKENS / 10_000.0
        cost_total += (mean / total_mean) * cost
    return cost_total


def situation_posterior_means(ws, situation: str, *,
                              gamma: float = GAMMA) -> dict[str, float]:
    """The situation's exact per-family honest posterior means — the
    deterministic learning readout (the cold workspace reads the exact
    wide prior, 0.5 everywhere)."""
    mass = _situation_mass(ws, situation, gamma=gamma)
    return {f: _posterior_mean(m) for f, m in mass.items()}


def assignment_distribution(ws, situation: str, *, draws: int = 300,
                            seed0: int = 0,
                            gamma: float = GAMMA) -> dict[str, float]:
    """The assigner's empirical draw distribution over the situation —
    the behavioral read the battery's learning-effect pins ride."""
    sig = situation_signature(situation)
    counts = {f: 0 for f in FAMILIES}
    for i in range(draws):
        rng = random.Random(f"v3/dist/{seed0}/{i}/assign")
        ranking = {f: 1.0 for f in FAMILIES}
        receipt = assigner.assign_method(ws, list(FAMILIES), ranking,
                                         signature_hash=sig, tier=TIER,
                                         rng=rng, gamma=gamma)
        counts[receipt["family"]] += 1
    return {f: counts[f] / draws for f in FAMILIES}


def selection_distribution(ws, task_ids: list[str], *, draws: int = 300,
                           seed0: int = 0) -> dict[str, float]:
    """The selector's empirical draw distribution over the candidate
    tasks (the DTS face, swept at a fixed seed batch)."""
    counts = {t: 0 for t in task_ids}
    for i in range(draws):
        rng = random.Random(f"v3/seldist/{seed0}/{i}")
        receipt = selector.select_task(ws, task_ids, rng=rng)
        counts[receipt["task"]] += 1
    return {t: counts[t] / draws for t in task_ids}


def run_v3_loop(ws, *, laps: int = 3, seed: int = 0, gamma: float = GAMMA,
                ablate_credit: bool = False, ablate_selector: bool = False,
                scramble_credit: bool = False) -> dict:
    """``laps`` laps of the rl-v2 closed loop over ``ws``. Ablation arms
    replay the IDENTICAL scenario with one learning channel removed at
    its write face (``ablate_credit``: the settled credit never banks;
    ``ablate_selector``: the selection never records); ``scramble_credit``
    feeds the credit face WRONG-family keys (the E1c control). Returns
    ``{"ws": ws, "report": <deterministic, Path-free dict>}``."""
    ws = Path(ws)
    loop_sim._bootstrap(ws)
    ctx = _seed_ctx(ws, seed=seed, lap=0, gamma=gamma)
    report: dict[str, Any] = {
        "seed": seed, "laps": laps, "gamma": gamma,
        "ablate_credit": ablate_credit, "ablate_selector": ablate_selector,
        "scramble_credit": scramble_credit,
        "per_lap": [], "lineage": [], "task_posteriors": {},
        "assignment_p_tracked_trace": [], "expected_cost_trace": [],
        "lap_verified_rate": [], "rollouts": [],
    }
    all_task_ids: list[str] = []
    verified = 0
    dispatches = 0
    prev_mass: float | None = None
    for lap_no in range(1, laps + 1):
        ctx["lap"] = lap_no
        lap_tasks = list(LAP_TASKS[lap_no - 1])
        all_task_ids.extend(tid for tid, _s in lap_tasks)
        lap: dict[str, Any] = {"lap": lap_no, "picks": [], "rollouts": []}
        remaining = list(lap_tasks)
        pick_no = 0
        while remaining:
            candidates = [tid for tid, _s in remaining]
            pick_rng = random.Random(f"v3/{seed}/lap{lap_no}/pick{pick_no}")
            pick = selector.select_task(ws, candidates, rng=pick_rng)
            pick_no += 1
            tid, situation = next(t for t in remaining
                                  if t[0] == pick["task"])
            remaining = [t for t in remaining if t[0] != tid]
            lap["picks"].append(tid)
            rid = f"ro-{tid}"
            rollout = run_rollout(ws, ctx, rid=rid, task_id=tid,
                                  situation=situation, gamma=gamma,
                                  ablate_credit=ablate_credit,
                                  scramble_credit=scramble_credit,
                                  ablate_selector=ablate_selector)
            report["rollouts"].append(rollout)
            lap["rollouts"].append(rollout)
            verified += rollout["verified_dispatches"]
            dispatches += rollout["steps"]
            if lap_no >= 2 and situation == "offsets":
                spawn = _spawn_child(ws, ctx, rollout, gamma=gamma,
                                     ablate_credit=ablate_credit,
                                     scramble_credit=scramble_credit,
                                     ablate_selector=ablate_selector)
                report["lineage"].append(spawn)
                _telemetry.emit(ws, "selector", "SELECT_CANDIDATES_WIDENED",
                                lap=lap_no,
                                detail=f"spawned child "
                                       f"{rollout['task_id']}-child widens "
                                       f"the candidates")
        # #915 telemetry: the lap END is the batch boundary — the task
        # posteriors' banked mass moving is the selector's prior move
        post = selector.task_posteriors(ws, sorted(set(all_task_ids)))
        mass = sum(a + b for _t, (a, b) in post.items())
        if prev_mass is not None and mass > prev_mass:
            _telemetry.emit(ws, "selector", "SELECT_PRIOR_MOVED",
                            lap=lap_no,
                            detail=f"banked posterior mass {mass}")
        prev_mass = mass
        report["per_lap"].append(lap)
        report["assignment_p_tracked_trace"].append(
            assignment_distribution(ws, "offsets", draws=100,
                                    seed0=seed * 100 + lap_no,
                                    gamma=gamma)[TRACKED])
        report["expected_cost_trace"].append(
            expected_dispatch_cost(ws, "offsets", gamma=gamma))
        report["lap_verified_rate"].append(
            verified / dispatches if dispatches else 0.0)
    report["task_posteriors"] = selector.task_posteriors(ws, all_task_ids)
    report["dispatch_success_rate"] = verified / dispatches \
        if dispatches else 0.0
    return {"ws": ws, "report": report}


# ------------------------------------------------ unit-level path drivers

def settle_one_dispatch(ws, situation: str, family: str, *, rollout: str,
                        settle: bool = True, planted: dict | None = None,
                        gamma: float = GAMMA) -> dict:
    """ONE dispatch through the loop's real path with the assignment
    PINNED to ``family`` (single-candidate assigner draw — the real
    face, deterministic outcome) — the battery's unit-level driver for
    the credit spine. ``settle=False`` withholds the draft/commit: the
    settlement never confirms, so nothing banks (the M pin)."""
    ws = Path(ws)
    loop_sim._bootstrap(ws)
    ctx = _seed_ctx(ws, seed=0, lap=1, gamma=gamma)
    sig = situation_signature(situation)
    disp = _dispatch(ws, ctx, rollout, sig, situation, 1, planted=dict(planted)
                     if planted else None, candidates=[family])
    out: dict[str, Any] = {"step_id": disp["step_id"], "cost": disp["cost"],
                           "step_r_t": disp["r_t"], "credit": None,
                           "terminal_r_t": None, "terminal_a_t": None,
                           "committed": None}
    if not settle:
        out["committed"] = draft_commit.committed_rollout(ws, rollout)
        return out
    terminal = "completed" if disp["verified"] else "rolled_back"
    kind = "terminate_rollout" if terminal == "completed" else "rollback"
    q_cells.append_action(ws, kind=kind, rollout_id=rollout, target=situation,
                          policy_version=POLICY_VERSION,
                          ts=ctx["clock"].tick())
    commit = draft_commit.commit_batch(ws, rollout, ts=ctx["clock"].tick())
    if commit["appended"]:
        # the batch's own committed draft carries the conjunctive
        # three-layer credit — the settlement confirmed, so it banks
        draft = draft_commit.draft_rows(ws, rollout)[0]
        _bank_settled_credit(ws, ctx, sig, family, float(draft["credit"]),
                             claim=situation,
                             dispatch_id=disp["step_id"], scramble=False)
        out["credit"] = float(draft["credit"])
    conf = [1.0 if disp["verified"] else UNVERIFIED_CONFIDENCE]
    shaped = _terminal_rows(ws, ctx, rollout, terminal=terminal,
                            confidences=conf)
    out["terminal_r_t"] = shaped["terminal_r_t"]
    out["terminal_a_t"] = shaped["terminal_a_t"]
    out["committed"] = draft_commit.committed_rollout(ws, rollout)
    return out


def dose_curve(ws, *, situation: str, doses: int,
               gamma: float = GAMMA) -> list[dict]:
    """The dose-response/convergence driver: ``doses`` settled correct
    dispatches bank one at a time through the real settle path (the
    assignment pinned to the situation's answering family), measured
    after each dose — the exact (d, 0) cell, its honest posterior mean,
    and the policy's exact expected cost."""
    ws = Path(ws)
    true_family = _true_family(situation)
    if true_family is None:
        raise ValueError(f"dose_curve: {situation!r} is dead")
    points: list[dict] = []
    for d in range(1, doses + 1):
        settle_one_dispatch(ws, situation, true_family,
                            rollout=f"ro-dose-{d}", gamma=gamma)
        fold_view = q_cells.fold(q_cells.default_store(ws), gamma=gamma)
        cell = fold_view.cells[(situation_signature(situation),
                                arm_key(true_family))]
        points.append({
            "dose": d,
            "cell": cell,
            "posterior_mean": _posterior_mean((cell.success, cell.failure)),
            "expected_cost": expected_dispatch_cost(ws, situation,
                                                    gamma=gamma),
        })
    return points
