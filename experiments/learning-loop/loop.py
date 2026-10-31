# -*- coding: utf-8 -*-
"""loop.py — the unified decision loop, the plan module tree's loop
face (#913).

The #909 fault harness (tests/chain_test_harness.py) PROMOTED to the
production loop module: the same protocol over the real rl-v2 faces,
with the carried pins BUILT IN, not bolted on. Pure orchestration —
the faces decide, this module wires:

    select (policy/selector.py DTS) -> assign (policy/assigner.py
    P⊗Q) -> execute (workers/spawner.py construction-style brief + the
    MOCK worker, loop_worker.py — the #887 harness posture) ->
    terminate (policy/terminator.py β + the one-shot watchdog) ->
    settle (settlement/ per-dispatch draft->commit) -> credit
    (credit/ returns->advantage, V = P(s)) -> belief (state/belief.py)
    -> next select

The carried-pin faces live in loop_pins.py (the phase envelope, the
intent declaration, the evidence wall — the #50①② residuals and the
#898 review duty). The WIRING's own pins: the DRIVER CLOCK (the loop's
deterministic counter stamps EVERY landed row — record_selection and
record_belief included, the #909 finding: the terminator's seed hashes
the rows verbatim, so a wall ts anywhere would move the deadline seed);
V WIRING (the decision-time P(s) of each dispatch feeds credit/
advantage through progress.values_from — a moving baseline subtracts,
a flat series keeps the pinned A == R cold identity); STAGNATION (the
advisory is consumed at the data level — the next assigns widen to the
full registry vocabulary and down-weight the flat window's direction;
advisory only, the faces still decide); THE ARBITER (at rollout end
ΔP's sign decides, the #884/#898 semantics end-to-end: positive ->
ROLLUP — the commit marker lands, the settled tree carries;
non-positive -> ROLLBACK — the audited discard marker lands, the
terminal advantage is negative, the tree reverts, and the per-dispatch
facts STILL bank: the settlement credit is the only credit authority).

Determinism: seeds thread every draw, the counter clock stamps every
row, two identical runs land byte-identical ledgers modulo ts.
MIRROR: tests/chain_test_harness.py and loop_sim_v3.py.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

_LOOP = Path(__file__).resolve().parent
_SCRIPTS = _LOOP.parents[1] / "scripts"
for _p in (_LOOP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget  # noqa: E402 — the path bootstrap lands first
from credit import returns as credit_returns  # noqa: E402
from loop_pins import (CORE_TASK, INTENTS, POLICY_VERSION, PHASES,  # noqa: E402
                       LoopError, arm_key, bank_evaluation, declare_intent,
                       evidence_wall, fact_base_ids, infer_phase,
                       require_intent, situation_signature,
                       terminal_advantage)
from loop_seams import (FAULT_LAP_DEFAULT, FAULT_MODES, NOISE_MARK,  # noqa: E402
                        OUT_OF_RAIL_CREDIT, PER_DISPATCH_BUDGET_S,
                        SeamMixin, _LoopStopped)
from loop_seams import (COLD_FAMILY, MALFORMED_SPEC)  # noqa: E402
from loop_worker import (RIGHT_SECONDS, RIGHT_TOKENS, TRACKED,  # noqa: E402
                         WRONG_SECONDS, WRONG_TOKENS, LoopWorkerError,
                         WorkerFn, _worker_execute)
from policy import assigner, selector, terminator  # noqa: E402
import method_families  # noqa: E402 — the closed vocabulary owner
from rlvr import action_params as _ap  # noqa: E402 — the #924 param spec
from rlvr import q_cells  # noqa: E402 — the (s,a,r) store
from settlement import draft_commit  # noqa: E402
from state import evaluation, progress, stagnation  # noqa: E402
from state import telemetry as _telemetry  # noqa: E402 — the #915 face
from workers import brief as worker_brief  # noqa: E402
from workers import spawner  # noqa: E402

__all__ = [
    "PHASES", "INTENTS", "LoopError", "LoopWorkerError", "WorkerFn",
    "LoopReport", "infer_phase", "declare_intent", "require_intent",
    "DistillResearchFn",
    "fact_base_ids", "evidence_wall", "bank_evaluation",
    "terminal_advantage", "situation_signature", "arm_key",
    "DecisionLoop", "run_loop", "SCHEMA", "POLICY_VERSION", "GAMMA",
    "RETURNS_GAMMA", "TERMINAL_BONUS", "UNVERIFIED_CONFIDENCE",
    "PER_DISPATCH_BUDGET_S", "RIGHT_TOKENS", "WRONG_TOKENS",
    "RIGHT_SECONDS", "WRONG_SECONDS", "FAMILIES", "TRACKED",
    "CORE_TASK", "MAX_STEPS", "STAGNATION_RANK_PENALTY",
    "OUT_OF_RAIL_CREDIT", "NOISE_MARK", "COLD_FAMILY", "MALFORMED_SPEC",
    "FAULT_LAP_DEFAULT", "FAULT_MODES",
]

SCHEMA = "loop-report/1"

#: constant γ — the fold arithmetic pins exactly (the loop_sim_v3 pin)
GAMMA = 1.0
#: the terminal-shaping discount (credit.returns' own domain)
RETURNS_GAMMA = 0.9
#: the outcome bonus magnitude — mirrors settlement.rollout_agg
TERMINAL_BONUS = 1.0
#: the unverified step's trust weight (the loop_sim_v3 constant)
UNVERIFIED_CONFIDENCE = 0.5

#: the loop's base method vocabulary and the tracked family (the
#: loop_sim_v3 truth table, reused so the drivers describe one world)
FAMILIES = ("crypto-core-identification", "dynamic-trace",
            "static-decompile")
#: the rollout safety cap (never reached once the loss-cut is live)
MAX_STEPS = 12

#: the stagnation posture's data-level constant: the flat direction's
#: planner rank penalty (P(f) = 1/rank falls 1.0 -> 1/3) — documented
#: policy, NOT fitted (the terminator.LOSS_CUT_N governance class)
STAGNATION_RANK_PENALTY = 3.0

#: the report type — a deterministic, Path-free dict (the harness's
#: report discipline)
LoopReport = dict[str, Any]

#: the mock loop's EXPLICIT dispatch width (#924): the loop's spawn
#: seam records the orchestrator's conscious choice on every spawn row
#: — a constant HERE (never auto-sized; the orchestrator-choice policy
#: lands later on #901's integration surface), overridable per run
#: through run_loop's spawn_slots so pins can prove pass-through.

#: the DISTILL research-execution seam (#938): the Callable the loop
#: invokes when a worker receipt's shelf-miss trigger fires AND the
#: caller injected an execution face. EXECUTOR INDEPENDENCE: this is
#: NEVER the worker and never receives it — its whole argv is
#: (ws, formulation, clock=...) (the research face's own signature;
#: the worker Callable stays structurally out of distillation).
DistillResearchFn = Callable[..., Mapping[str, Any]]


class _Clock:
    """Deterministic timestamp counter — no wall clock anywhere (the
    #909 pattern, owned by the loop now)."""

    def __init__(self) -> None:
        self._n = 0

    def tick(self) -> str:
        self._n += 1
        seconds = self._n % 60
        minutes = (self._n // 60) % 60
        hours = self._n // 3600
        return f"2026-01-01T{hours:02d}:{minutes:02d}:{seconds:02d}Z"


class DecisionLoop(SeamMixin):
    """One deterministic multi-lap run of the unified decision loop
    over one workspace — the faces decide, this class wires."""

    def __init__(self, ws: Path, *, seed: int, laps: int,
                 budget: Budget | None, faults: Mapping[str, str] | None,
                 situation: str, worker: WorkerFn | None,
                 spawn_slots: int,
                 distill_research: DistillResearchFn | None = None) -> None:
        self._ws = Path(ws)
        self._seed = seed
        self._laps = laps
        self._spawn_slots = spawn_slots
        self._distill_research = distill_research
        # fail-fast at the loop boundary: the row wall would refuse a
        # bad width MID-LAP; a conscious choice is validated up front
        _ap.normalize_params("spawn_candidate", {"slots": spawn_slots})
        self._budget = budget or Budget(wall_s=PER_DISPATCH_BUDGET_S,
                                        max_calls=None)
        faults = dict(faults or {})
        for seam, mode in faults.items():
            accepted = FAULT_MODES.get(seam, frozenset())
            if mode not in accepted:
                raise LoopError(
                    f"loop913: fault {mode!r} is not a {seam!r}-seam "
                    f"fault (accepted: {sorted(accepted)})")
        self._faults = faults
        self._fault_lap = FAULT_LAP_DEFAULT
        self._situation = situation
        self._worker = worker
        self._clock = _Clock()
        self._tree: list[progress.Subgoal] = []
        self._facts: list[str] = []
        self._deltas: list[float] = []
        self._direction: str | None = None
        self._posture: dict[str, Any] = self._base_posture()
        # the selector seam's lap-boundary baseline (the banked
        # task-posterior mass; None until the first lap completes)
        self._prev_mass: float | None = None
        self._sig = situation_signature(situation)
        self.report: LoopReport = {
            "schema": SCHEMA, "seed": seed, "laps": laps,
            "situation": situation, "gamma": GAMMA, "per_lap": [],
            "p_series": [], "delta_p_series": [],
            "chain_stopped_lap": None,
        }

    # ---------------------------------------------------- the posture

    @staticmethod
    def _base_posture() -> dict[str, Any]:
        return {"candidates": list(FAMILIES),
                "ranking": {f: 1.0 for f in FAMILIES},
                "direction": None}

    def _refresh_posture(self, rid: str, delta: float) -> dict | None:
        """Consume the stagnation trigger at the data level: the
        receipt ADVISES (terminates: False — the β terminator keeps
        the terminate decision), the loop answers by widening the
        assigner's candidate set to the full registry vocabulary and
        down-weighting the flat window's direction (the harmonic
        P(f) = 1/rank falls). A real ΔP move resets the flat tail, so
        the posture clears itself."""
        self._deltas.append(delta)
        receipt = stagnation.stagnation_receipt(list(self._deltas),
                                                rollout_id=rid)
        if receipt is None:
            self._posture = self._base_posture()
            return None
        direction = self._direction or TRACKED
        candidates = sorted(
            method_families.registered_tokens(self._ws))
        ranking: dict[str, float] = {f: 1.0 for f in candidates}
        ranking[direction] = STAGNATION_RANK_PENALTY
        self._posture = {"candidates": candidates, "ranking": ranking,
                         "direction": direction}
        return receipt

    # ---------------------------------------------- the dispatch plan

    def _plan(self, rid: str, step_no: int, phase: str,
              intent: dict[str, str]) -> dict[str, Any]:
        """The ASSIGN seam: one real P⊗Q draw under the current
        posture (the stagnation advisory already re-shaped the
        candidates/ranking data — the assigner still decides). The
        loop's assign receipt is the face's receipt ENRICHED with the
        phase tag and the intent declaration."""
        rng = random.Random(
            f"loop913/{self._seed}/{rid}/{step_no}/assign")
        assign = assigner.assign_method(
            self._ws, self._posture["candidates"],
            self._posture["ranking"], signature_hash=self._sig, tier=1,
            rng=rng, gamma=GAMMA)
        self._direction = assign["family"]
        return {**assign, "phase": phase, "intent": dict(intent)}

    def _construct(self, rid: str, sid: str, phase: str,
                   intent: dict[str, str]) -> tuple[dict, dict, dict]:
        """The EXECUTE seam's construction half (#885): the worker's
        whole world assembled BEFORE it runs — the spawn receipt, its
        audited ledger row (kind spawn_candidate, the #878 action
        space; stamped by the DRIVER clock — record_spawn self-stamps,
        so the loop re-validates the receipt and appends through the
        standard face with its own stamp), and the construction-style
        brief."""
        goal = (f"[{phase}] {intent['expected_output']} "
                f"on {CORE_TASK}/{self._situation}")
        spawn = spawner.prepare_spawn(
            goal, {"task": CORE_TASK, "situation": self._situation,
                   "phase": phase, "rollout": rid},
            (), self._budget, worker_id=f"w-{sid}")
        if spawn.get("schema") != spawner.SCHEMA \
                or not spawn.get("spawn_id"):
            raise LoopError("loop.construct: the spawn receipt lost "
                            "its schema or content id")
        spawn_row = q_cells.append_action(
            self._ws, kind="spawn_candidate", rollout_id=rid,
            step_id=sid, target=spawn["worker_id"],
            params={"slots": self._spawn_slots,
                    "spawn_id": spawn["spawn_id"], "goal": goal,
                    "phase": phase},
            budget=spawn["budget"], policy_version=POLICY_VERSION,
            ts=self._clock.tick())
        brief_doc = worker_brief.assemble_brief(
            goal, list(self._facts), (), self._budget,
            ("static-scan", "decompiler", "debugger"))
        return spawn, spawn_row, brief_doc

    def _land_fact(self, lap_no: int, step_no: int,
                   claim: str) -> str:
        """Land ONE fact file into the fact base — the byte anchor the
        evidence wall will demand. The mock fact is honest: PROVEN
        behind a green verifier gate is exactly what the belief face's
        own classification confirms."""
        facts_dir = self._ws / "facts"
        facts_dir.mkdir(exist_ok=True)
        fact_id = f"F{lap_no:02d}{step_no:02d}"
        body = (f"---\nid: {fact_id}\nstatus: PROVEN\n"
                "verify_status: passes\nconfidence: high\n---\n\n"
                f"{claim}\n")
        (facts_dir / f"{fact_id}.md").write_text(body, encoding="utf-8")
        return fact_id

    def _dispatch(self, lap_no: int, rid: str, step_no: int) -> dict:
        """ONE dispatch: phase inference -> intent declaration ->
        assign (posture-shaped) -> construction -> the mock worker ->
        result row -> (verified: fact + evidence wall + apply_
        proposals) -> per-dispatch draft. The subgoal is BORN into the
        tree at the floor; the banking moves it only through the wall."""
        sid = f"{rid}-s{step_no:02d}"
        p_decision = progress.P(self._tree)
        phase = infer_phase(self._tree, rid)
        intent = require_intent(declare_intent(phase, CORE_TASK))
        assign = self._plan(rid, step_no, phase, intent)
        family = assign["family"]
        spawn, spawn_row, brief_doc = self._construct(rid, sid, phase,
                                                      intent)
        action_row = q_cells.append_action(
            self._ws, kind="assign_step", rollout_id=rid, step_id=sid,
            target=family,
            params={"method_family": family, "tier": 1, "phase": phase,
                    "intent": dict(intent),
                    # the decision-time P⊗Q distribution rides the row
                    # (card 925) — the full per-candidate doc, the same
                    # object the report receipt carries, one fail-closed
                    # write with the winner it selected from
                    "distribution": assign["candidates"]},
            budget={"wall_s": PER_DISPATCH_BUDGET_S, "max_calls": None},
            policy_version=POLICY_VERSION, ts=self._clock.tick())
        # telemetry AFTER the durable row (the SIM loop's exact
        # semantics) — a describe-before-durable emit would leave a
        # phantom assignment receipt on append failure
        if len(self._posture["candidates"]) > 1:
            _telemetry.emit(self._ws, "assigner", "ASSIGN_WIDENED",
                            lap=lap_no, rollout_id=rid,
                            detail=f"{len(self._posture['candidates'])} "
                                   f"families in the draw")
        _telemetry.emit(self._ws, "assigner", "ASSIGN_ASSIGNED",
                        lap=lap_no, rollout_id=rid,
                        detail=f"family {family}")
        self._tree = [*self._tree,
                      progress.Subgoal(id=f"g-{sid}",
                                       status="UNVERIFIED")]
        step: dict[str, Any] = {
            "step_id": sid, "phase": phase, "intent": dict(intent),
            "family": family, "verified": False, "r_t": None,
            "cost": None, "seconds": None, "p_decision": p_decision,
            "direction": self._posture["direction"],
            "assign": assign, "action_row": action_row,
            "spawn": spawn, "spawn_row": spawn_row,
            "brief": brief_doc, "result_row": None, "draft": None,
            "eval_doc": None, "banked_credit": None,
            "bank_receipt": None, "fault": None, "distill": None,
        }
        out = self._execute(lap_no, rid, step_no, family, step)
        if out is None:
            return step
        return self._land_result(lap_no, rid, step_no, sid, family,
                                 phase, out, step)

    def _execute(self, lap_no: int, rid: str, step_no: int,
                 family: str, step: dict) -> dict | None:
        """The worker seam, with the execute-seam fault modes: the
        crash is captured at the seam (no result row; the rollout
        aborts), the garbage verdict is refused by the result face
        fail-closed (nothing banks). Returns the worker output, or
        None when the fault consumed the dispatch."""
        fault_mode = self._faults.get("execute")
        fault_here = fault_mode is not None \
            and lap_no == self._fault_lap and step_no == 1
        if fault_here and fault_mode == "worker_exception":
            try:
                _worker_execute(self._situation, family,
                                fault="worker_exception")
            except LoopWorkerError as exc:
                step["fault"] = {
                    "seam": "execute", "mode": fault_mode,
                    "response": "worker-raise-captured",
                    "error": str(exc),
                }
                return None
        if fault_here and fault_mode == "worker_garbage":
            return {"verified": "true", "tokens": RIGHT_TOKENS,
                    "seconds": RIGHT_SECONDS}
        return self._worker(self._situation, family)

    def _trigger_distill(self, rid: str, sid: str,
                         signal: Any) -> dict[str, Any]:
        """The shelf-miss trigger (#938): a worker receipt's capability-
        gap signal lands ONE DISTILL decision row — distillation as an
        action in the closed space (the spec wall governs the row; the
        budget_scale param scales the row's wall budget). EXECUTOR
        INDEPENDENCE: the research execution is a SEPARATE injected
        Callable — never the worker, never handed the worker; its whole
        argv is (ws, formulation, clock=). Uninjected, the decision +
        row are the WHOLE action (no auto-research loop on this card)."""
        if not isinstance(signal, str) or not signal.strip():
            raise LoopError(
                f"loop.distill: shelf-miss signal {signal!r} must be a "
                "non-empty formulation string (the capability gap's "
                "problem statement)")
        params = _ap.normalize_params("distill",
                                      {"formulation": signal.strip()})
        row = q_cells.append_action(
            self._ws, kind="distill", rollout_id=rid, step_id=sid,
            target=CORE_TASK, params=params,
            budget={"wall_s": PER_DISPATCH_BUDGET_S
                    * float(params["budget_scale"]), "max_calls": None},
            policy_version=POLICY_VERSION, ts=self._clock.tick())
        receipt: dict[str, Any] = {"trigger": "shelf_miss",
                                   "formulation": signal.strip(),
                                   "row": row["row"], "research": None}
        if self._distill_research is not None:
            receipt["research"] = self._distill_research(
                self._ws, signal.strip(), clock=self._clock)
        return receipt

    def _land_result(self, lap_no: int, rid: str, step_no: int,
                     sid: str, family: str, phase: str, out: Mapping,
                     step: dict) -> dict:
        """The result seam: the (s,a,r) row lands (the result face
        refuses a garbage verdict itself), the verified dispatch banks
        its fact through the evidence wall, and the per-dispatch draft
        prices the three-layer conjunctive gate."""
        cost = out["tokens"] / 10_000.0
        try:
            result_row = q_cells.append_result(
                self._ws, rollout_id=rid, step_id=sid,
                r_t=1.0 if out["verified"] else 0.0,
                verified=out["verified"], cost=cost,
                verdict="pass" if out["verified"] else "fail",
                summary=f"{family} on {self._situation} [{phase}]",
                ts=self._clock.tick())
        except ValueError as exc:
            step["fault"] = {
                "seam": "execute", "mode": self._faults.get("execute")
                or "",
                "response": "result-refused", "error": str(exc),
            }
            return step
        step["result_row"] = result_row
        step["verified"] = bool(out["verified"])
        step["r_t"] = 1.0 if step["verified"] else 0.0
        step["cost"] = cost
        step["seconds"] = out["seconds"]
        challenge = out.get("phase_challenge")
        if challenge is not None:
            if challenge not in PHASES:
                raise LoopError(
                    f"loop.worker: phase challenge {challenge!r} "
                    f"outside the closed vocab {PHASES}")
            step["phase_challenge"] = challenge
        if step["verified"]:
            step["eval_doc"] = self._bank_progress(lap_no, step_no,
                                                   sid, family, phase)
        shelf_signal = out.get("shelf_miss")
        if shelf_signal is not None:
            step["distill"] = self._trigger_distill(rid, sid,
                                                    shelf_signal)
        verdicts = {"mechanical": step["verified"],
                    "scope_verifier": step["verified"], "redteam": True}
        step["draft"] = draft_commit.ensure_draft(
            self._ws, rid, sid, cost, verdicts, ts=self._clock.tick())
        return step

    def _bank_progress(self, lap_no: int, step_no: int, sid: str,
                       family: str, phase: str) -> dict:
        """The verified dispatch's banking path: the fact lands, the
        evaluation document proposes the subgoal's PROVEN move, and
        bank_evaluation runs the evidence wall BEFORE apply_proposals
        moves the tree."""
        claim = (f"{CORE_TASK}/{self._situation} rung {phase} verified "
                 f"by {family} ({sid})")
        fact_id = self._land_fact(lap_no, step_no, claim)
        self._facts.append(claim)
        doc = {
            "schema": evaluation.SCHEMA, "new_facts": [claim],
            "validated_hypotheses": [], "rejected_hypotheses": [],
            "unresolved_questions": [], "possible_new_directions": [],
            "exploration_progress": 0.0, "redundancy": 0.0,
            "proposals": [{"subgoal_id": f"g-{sid}",
                           "to_status": "PROVEN",
                           "evidence_refs": (fact_id,)}],
        }
        self._tree = list(bank_evaluation(self._ws, self._tree, doc))
        return doc

    # ------------------------------------------------------ the seams

    # --------------------------------------------------- the rollout

    def _step_gates(self, rid: str, step_no: int, covered: bool,
                    verified_ids: list[str], elapsed: float,
                    deadline: Mapping) -> tuple[dict, dict, str | None,
                                                str | None]:
        """The TERMINATE seam for one landed step: the β termination
        check + the one-shot watchdog spend. Returns (check, watchdog
        check, terminal, rule); terminal None = keep dispatching."""
        coverage = {"covered": covered,
                    "question": f"the {self._situation} question "
                                "answered by the verified phase ladder",
                    "verified_step_ids": list(verified_ids)}
        check = terminator.check_termination(
            rid, coverage, q_cells.trajectory_rows(self._ws),
            rng=random.Random(
                f"loop913/{self._seed}/{rid}/{step_no}/term"))
        wd_check = terminator.watchdog_check(
            deadline, elapsed_s=elapsed, rollout_completed=False)
        if wd_check["fired"]:
            return check, wd_check, "rolled_back", "watchdog_fired"
        if check["terminate"]:
            rule = str(check["rule"])
            return check, wd_check, ("completed" if covered
                                     else "rolled_back"), rule
        if step_no >= MAX_STEPS:
            return check, wd_check, "rolled_back", "step_cap"
        return check, wd_check, None, None

    def _run_rollout(self, lap_no: int, rid: str,
                     wd: dict) -> dict[str, Any]:
        """One rollout: dispatches under the β + watchdog gates, then
        THE ARBITER, the credit bank, and the terminal pricing."""
        tree_before = tuple(self._tree)
        steps: list[dict] = []
        covered = False
        verified_ids: list[str] = []
        confidences: list[float] = []
        step_p: list[float] = []
        elapsed = 0.0
        terminal: str | None = None
        rule: str | None = None
        while terminal is None:
            step_no = len(steps) + 1
            step = self._dispatch(lap_no, rid, step_no)
            steps.append(step)
            if step["fault"] is not None:
                rule = "worker_fault"
                terminal = "aborted"
                break
            confidences.append(1.0 if step["verified"]
                               else UNVERIFIED_CONFIDENCE)
            step_p.append(step["p_decision"])
            if step["verified"] and step["phase"] == "verify":
                covered = True          # the ladder walked to the top
            if step["verified"]:
                verified_ids.append(step["step_id"])
            elapsed += step["seconds"]
            _c, _w, terminal, rule = self._step_gates(
                rid, step_no, covered, verified_ids, elapsed,
                wd["deadline"])
            wd["checks"].append(_w)
        ro = self._arbiter(lap_no, rid, tree_before, steps, rule)
        ro["covered"] = covered
        ro["verified_dispatches"] = sum(1 for s in steps
                                        if s["verified"])
        ro["credit_banked"] = self._credit_rollout(lap_no, rid, steps)
        self._price_terminal(rid, ro, confidences, step_p)
        ro["p_decisions"] = [s["p_decision"] for s in steps
                             if s["result_row"] is not None]
        ro["stagnation"] = self._refresh_posture(rid, ro["delta_p"])
        self.report["p_series"].append(progress.P(self._tree))
        self.report["delta_p_series"].append(ro["delta_p"])
        return ro

    def _arbiter(self, lap_no: int, rid: str,
                 tree_before: tuple[progress.Subgoal, ...],
                 steps: list[dict], rule: str | None) -> dict[str, Any]:
        """THE ROLLBACK/ROLLUP ARBITER (#884/#898 driven end-to-end):
        ΔP's sign decides the disposition — positive ROLLS UP (the
        commit marker lands, the settled tree carries); non-positive
        ROLLS BACK (the audited discard marker lands, the settled
        tree reverts). The terminal action row records the arbiter's
        disposition (the β rule rides params); the settle fault stops
        the marker between draft and commit — the recovery lands it."""
        tree_after = tuple(self._tree)
        delta = progress.delta_P(tree_before, tree_after)
        disposition = "rolled_up" if delta > 0 else "rolled_back"
        kind = "terminate_rollout" if disposition == "rolled_up" \
            else "rollback"
        q_cells.append_action(
            self._ws, kind=kind, rollout_id=rid, target=CORE_TASK,
            policy_version=POLICY_VERSION,
            params={"rule": rule, "delta_p": delta},
            ts=self._clock.tick())
        ro: dict[str, Any] = {
            "rollout_id": rid, "task_id": CORE_TASK, "steps": steps,
            "terminal": None, "terminal_rule": rule,
            "disposition": disposition, "delta_p": delta,
            "p_before": progress.P(tree_before),
            "p_after": None,
            "commit": None, "discard": None, "fault": None,
        }
        if steps and steps[-1]["fault"] is not None:
            # the execute-seam fault rides the step AND the rollout
            # receipt (the chain's audit face mirrors it upward)
            ro["fault"] = steps[-1]["fault"]
        if disposition == "rolled_up":
            self._tree = list(tree_after)
            if not self._seam_active("settle", lap_no):
                ro["commit"] = draft_commit.commit_batch(
                    self._ws, rid, ts=self._clock.tick())
            else:
                ro["fault"] = {
                    "seam": "settle", "mode": "crash_mid_rollout",
                    "response": "crash-simulated-pre-commit",
                }
        else:
            self._tree = list(tree_before)
            if not self._seam_active("settle", lap_no):
                ro["discard"] = draft_commit.discard_drafts(
                    self._ws, rid, reason=f"delta_p={delta}",
                    ts=self._clock.tick())
        # the receipt's p_after reads the tree AFTER the arbiter's
        # carry/revert decision (a rollback's births never carry)
        ro["p_after"] = progress.P(self._tree)
        return ro

    def _credit_rollout(self, lap_no: int, rid: str,
                        steps: list[dict]) -> float:
        """The credit bank: the batch's settled drafts price the fold
        obs at each dispatch's arm key — in BOTH dispositions (the
        facts still bank on a rollback; the settlement credit is the
        only credit authority and the arbiter never touches it)."""
        total = 0.0
        for draft in draft_commit.draft_rows(self._ws, rid):
            step = next(s for s in steps
                        if s["step_id"] == draft["dispatch_id"])
            banked, receipt = self._bank_credit(
                lap_no, step["family"], float(draft["credit"]),
                claim=CORE_TASK, dispatch_id=draft["dispatch_id"])
            step["banked_credit"] = banked
            step["bank_receipt"] = receipt
            total += banked
        return total

    def _price_terminal(self, rid: str, ro: dict[str, Any],
                        confidences: list[float],
                        step_p: list[float]) -> None:
        """The terminal return: credit.returns prices the outcome-
        shaped discounted return (the arbiter's disposition picks the
        bonus sign), the V-wired advantage modulates it, and ONE
        terminal result row lands it — the rollout's LAST numeric
        r_t, the selector's documented terminal."""
        rewards = credit_returns.rollout_rewards(self._ws, rid)
        ro["terminal_r_t"] = None
        ro["terminal_a_t"] = None
        ro["advantage_source"] = None
        ro["v_series_used"] = None
        if not rewards.size:
            return
        disposition = ro["disposition"]
        terminal = "completed" if disposition == "rolled_up" \
            else "rolled_back"
        shaped = credit_returns.terminal_shaped(
            rewards, RETURNS_GAMMA, terminal=terminal,
            terminal_bonus=TERMINAL_BONUS)
        priced = terminal_advantage(shaped, confidences, step_p)
        row = q_cells.append_result(
            self._ws, rollout_id=rid, step_id=f"{rid}-terminal",
            r_t=float(shaped[-1]), verified=disposition == "rolled_up",
            R_t=float(shaped[-1]), A_t=float(priced["advantage"][-1]),
            verdict=terminal,
            summary="terminal return (loop913: credit.returns "
                    "shaped, V = P(s))",
            ts=self._clock.tick())
        ro["terminal_r_t"] = float(shaped[-1])
        ro["terminal_a_t"] = float(priced["advantage"][-1])
        ro["advantage_source"] = priced["source"]
        ro["v_series_used"] = priced["values"]
        ro["terminal_row"] = row["row"]

    def _recover(self, rid: str) -> dict:
        """The crash-recovery procedure (the #884, chained): re-draft
        every surviving draft — idempotent by the already-drafted
        guard — then the late commit. Returns the recovery receipt."""
        drafts = draft_commit.draft_rows(self._ws, rid)
        re_drafts = [
            draft_commit.ensure_draft(self._ws, rid, d["dispatch_id"],
                                      float(d["spend"]), d["verdicts"],
                                      ts=self._clock.tick())
            for d in drafts]
        late_commit = draft_commit.commit_batch(
            self._ws, rid, ts=self._clock.tick())
        return {"re_drafts": re_drafts, "late_commit": late_commit}

    # -------------------------------------------------------- one lap

    def _prior_moved(self, lap_no: int) -> None:
        """The selector seam's lap-boundary telemetry (the SIM loop's
        prev-mass pattern): the banked task-posterior mass is the
        prior the DTS draw samples — when it grows across the lap
        (batch) boundary, the move lands. The first completed lap is
        the baseline, never a mover."""
        post = selector.task_posteriors(self._ws, [CORE_TASK])
        mass = sum(a + b for _t, (a, b) in post.items())
        if self._prev_mass is not None and mass > self._prev_mass:
            _telemetry.emit(self._ws, "selector", "SELECT_PRIOR_MOVED",
                            lap=lap_no,
                            detail=f"banked posterior mass {mass}")
        self._prev_mass = mass

    def _run_lap(self, lap_no: int) -> dict[str, Any]:
        """One lap of the COMPLETE protocol with every seam's receipt
        captured: select -> watchdog arm -> rollout (dispatch loop ->
        arbiter -> credit -> terminal pricing -> stagnation) ->
        belief -> (faulted lap: the ledger-noise injection)."""
        rid = f"ro-{CORE_TASK}-lap{lap_no}"
        lap: dict[str, Any] = {"lap": lap_no, "picks": [],
                               "rollouts": [], "watchdog": None,
                               "belief": None, "noise": None,
                               "fault": None}
        lap["picks"].append(self._select(lap_no, rid))
        wd = self._arm_watchdog(lap_no)
        lap["watchdog"] = wd
        ro = self._run_rollout(lap_no, rid, wd)
        lap["rollouts"].append(ro)
        if ro["fault"] is not None:
            # the rollout's fault mirrors upward (the audit face)
            lap["fault"] = ro["fault"]
            if ro["fault"].get("seam") == "settle":
                ro["fault"]["recovery"] = self._recover(rid)
        lap["belief"] = self._belief_seam(lap_no, CORE_TASK)
        if self._seam_active("ledger", lap_no):
            lap["noise"] = self._inject_noise(self._faults["ledger"],
                                              lap_no)
        self._prior_moved(lap_no)
        return lap

    # ------------------------------------------------------------ run

    def _guard_used_workspace(self) -> None:
        """One workspace, one run, fail-closed at the entry: the
        loop's rollout ids are deterministic (``ro-core-lapN``), so a
        second run over a prior run's rows would join its drafts and
        terminal rows onto ANOTHER run's history — the residual-draft
        join that surfaces as a bare StopIteration from the credit
        join. The guard reads before anything mutates."""
        existing = q_cells.trajectory_rows(self._ws)
        if not existing:
            return
        actions = sum(1 for row in existing
                      if row.get("schema") == q_cells.SCHEMA_ACTION_V2)
        raise LoopError(
            f"loop913: {self._ws} already carries {len(existing)} "
            f"ledger rows ({actions} action rows) from another run — "
            f"one workspace, one run: re-running would join this "
            f"run's deterministic rollout ids onto the residual rows; "
            f"use a fresh workspace")

    def run(self) -> tuple[dict, Path]:
        self._guard_used_workspace()
        _bootstrap(self._ws)
        for lap_no in range(1, self._laps + 1):
            try:
                self.report["per_lap"].append(self._run_lap(lap_no))
            except _LoopStopped as stop:
                self.report["per_lap"].append(
                    {"lap": lap_no, "fault": stop.args[0], "picks": [],
                     "rollouts": [], "watchdog": None, "belief": None,
                     "noise": None})
                self.report["chain_stopped_lap"] = lap_no
                break
        return {"ws": self._ws, "report": self.report}, self._ws


def _bootstrap(ws: Path) -> None:
    """The one-workspace-one-run scaffold: fresh task_spec seed plus
    the runs/ dir. Extracted from the sim tier (#936) — production
    machinery the SIM was merely the first consumer of. run() calls it
    right after the used-workspace guard; the sim faces import it back
    from here (the allowed sim→production direction)."""
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n- id: pq1\n  q: replay the fixture family\n",
        encoding="utf-8")
    (ws / "runs").mkdir(parents=True, exist_ok=True)


def run_loop(ws: Path, *, laps: int = 5, budget: Budget | None = None,
             seed: int = 0, faults: Mapping[str, str] | None = None,
             situation: str = "offsets",
             worker: WorkerFn,
             spawn_slots: int,
             distill_research: DistillResearchFn | None = None
             ) -> tuple[LoopReport, Path]:
    """``laps`` laps of the unified decision loop over ``ws`` — the
    full protocol with the carried pins built in and per-seam
    receipts. Returns ``(run, ws)`` where ``run["report"]`` is the
    deterministic, Path-free report (the #909 receipt discipline):
    per-lap seam receipts, the P(s) series, the ΔP series, and the
    OBSERVED fault responses. ``budget`` is the dispatch envelope's
    wall budget (the watchdog's operand); ``worker`` is the test seam
    for the mock worker (the default is the flat deterministic mock —
    never a real LLM); ``spawn_slots`` is the run's EXPLICIT dispatch
    width (#924 — the mock loop's constant is the documented posture,
    the orchestrator-choice policy lands later; never auto-sized).
    ``distill_research`` (#938) is the OPTIONAL research-execution
    seam for the shelf-miss trigger — a Callable SEPARATE from the
    worker (executor independence), invoked with
    (ws, formulation, clock=); uninjected, the trigger lands the
    DISTILL decision row only."""
    return DecisionLoop(Path(ws), seed=seed, laps=laps, budget=budget,
                        faults=faults, situation=situation,
                        worker=worker,
                        spawn_slots=spawn_slots,
                        distill_research=distill_research).run()
