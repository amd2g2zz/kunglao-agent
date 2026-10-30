# -*- coding: utf-8 -*-
"""chain_test_harness.py — the FULL-CHAIN fault-injection driver (909).

The #887 battery (loop_sim_v3) proves the loop LEARNS; this driver
proves the loop is COHERENT under faults. It runs N laps of the
COMPLETE protocol over the real faces and the q_cells v2 ledger, with
SEAM VISIBILITY — every stage's receipt lands in a per-lap record:

    select (DTS) -> assign (P⊗Q) -> execute (flat mock worker) ->
    result -> draft -> terminator check -> watchdog spend -> terminal
    action -> commit -> credit bank -> terminal return pricing ->
    belief snapshot -> next select

— and a fault-injection parameter per seam. The matrix (mode ->
injection seam -> observed response; the tests pin what IS observed,
never the hope):

  select    empty_candidates     the selector raises fail-closed; not
                                 one row lands for the faulted lap
  execute   worker_exception     the crash is captured at the seam; no
                                 result row; the rollout aborts with
                                 an audited rollback terminal
  execute   worker_garbage       the result face refuses the non-bool
                                 verdict fail-closed; nothing banks;
                                 the loop continues
  settle    crash_mid_rollout    the crash between draft and commit:
                                 the recovery re-drafts (idempotent)
                                 and late-commits; the loop continues
  credit    out_of_rail_credit   the boundary clamps the injected
                                 credit into [0, 1]; flagged
  ledger    unsealed_row         a raw unsealed row injected into the
                                 experience file is refused by the
                                 seal wall (armed posture)
  ledger    foreign_schema       a foreign-schema row is excluded by
                                 the prefix wall (always)
  watchdog  malformed_deadline   the arming face refuses the garbage
                                 fail-closed; the loop re-arms through
                                 the documented cold default
  belief    malformed_spec       the #903 mapping guard renders the
                                 honest empty open-questions element

Deterministic: seeds thread every draw, a counter clock stamps EVERY
row (the #909 finding: the terminator's seed hashes the rows verbatim,
so the two recording faces that used to self-stamp — record_selection,
record_belief — now take the driver's clock through their additive
``ts`` parameter; a wall ts moved the deadline seed across identical
decision histories), and no assertion reads the wall clock. MIRROR:
loop_sim_v3.py — the harness is its fault-injected generalization;
the worker is FLAT, so every realized improvement is attributable to
the policy faces.
"""
from __future__ import annotations

import hashlib
import random
import sys
from pathlib import Path
from typing import Any, Mapping

import numpy as np

_LOOP = Path(__file__).resolve().parent
_SCRIPTS = _LOOP.parents[1] / "scripts"
for _p in (_LOOP, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import loop_sim  # noqa: E402 — the shared workspace bootstrap
from core import Budget  # noqa: E402
from credit import advantage as credit_advantage  # noqa: E402
from credit import returns as credit_returns  # noqa: E402
from policy import assigner, selector, terminator  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from settlement import draft_commit  # noqa: E402
from state import belief, progress  # noqa: E402

POLICY_VERSION = "rl-v2-chain/1"

#: constant γ — the fold arithmetic pins exactly (the loop_sim_v3 pin)
GAMMA = 1.0
#: the terminal-shaping discount (credit.returns' own documented domain)
RETURNS_GAMMA = 0.9
#: the outcome bonus magnitude — mirrors settlement.rollout_agg
TERMINAL_BONUS = 1.0
#: the unverified step's trust weight (the loop_sim_v3 constant)
UNVERIFIED_CONFIDENCE = 0.5

#: the mock dispatch envelope's wall budget (the watchdog's operand)
PER_DISPATCH_BUDGET_S = 600.0

#: the flat worker's honest bills (the loop_sim_v3 flat worker)
RIGHT_TOKENS = 1000
WRONG_TOKENS = 4000
RIGHT_SECONDS = 10.0
WRONG_SECONDS = 40.0

#: the loop's method vocabulary and the tracked family (loop_sim_v3's
#: truth table, reused verbatim so both drivers describe one world)
FAMILIES = ("crypto-core-identification", "dynamic-trace",
            "static-decompile")
TRACKED = "static-decompile"
CHAIN_SITUATION = "offsets"
CORE_TASK = "core"
#: situation -> the family that actually answers it (the worker's truth)
SITUATIONS: dict[str, str] = {
    "offsets": TRACKED,
    "packer": "dynamic-trace",
    "grammar": "crypto-core-identification",
}

#: the rollout safety cap (never reached once the loss-cut is live)
MAX_STEPS = 12

#: the out-of-rail credit the bank seam injects (the boundary's rail is
#: [0, 1] — the injected 2.5 must land clamped at 1.0, flagged)
OUT_OF_RAIL_CREDIT = 2.5

#: the injected noise row's target token — the marker the pins find in
#: the RAW file (it must be on disk) and must NOT find in any trusted
#: read
NOISE_MARK = "noise-909"

#: the deliberately history-less family the cold-default re-arm uses
COLD_FAMILY = "cold-default"

#: the malformed task_spec payload — a top-level scalar (the #903
#: mapping guard's honest-empty edge, not the YAML-error edge)
MALFORMED_SPEC = "chain909-garbage-spec\n"

#: the fault matrix: seam -> the modes it accepts. The driver validates
#: every request against this map (an unknown pair refuses loudly).
FAULT_MODES: dict[str, frozenset[str]] = {
    "select": frozenset({"empty_candidates"}),
    "execute": frozenset({"worker_exception", "worker_garbage"}),
    "settle": frozenset({"crash_mid_rollout"}),
    "credit": frozenset({"out_of_rail_credit"}),
    "ledger": frozenset({"unsealed_row", "foreign_schema"}),
    "watchdog": frozenset({"malformed_deadline"}),
    "belief": frozenset({"malformed_spec"}),
}

#: the faulted lap — the matrix runs place every fault mid-chain so the
#: laps AFTER the fault prove the loop continued
FAULT_LAP_DEFAULT = 2


class ChainWorkerError(RuntimeError):
    """The mock worker's crash — the worker_exception fault's payload."""


class ChainStopped(Exception):
    """The chain stopped at the faulted seam (the select fault's honest
    posture: no selection -> no lap). Args[0] is the fault record."""


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


def situation_signature(situation: str) -> str:
    """The situation's 12-hex state signature — SAME situation, SAME
    signature: the fold cell the learning banks into is keyed by it."""
    digest = hashlib.sha256(
        f"chain909-situation/{situation}".encode("utf-8"))
    return digest.hexdigest()[:12]


def arm_key(family: str) -> str:
    """The 4-dim fold key the loop banks credit under (the loop_sim_v3
    arm shape)."""
    return q_cells.arm_key(family, "facts_snapshot", "none", 1)


class ChainHarness:
    """One deterministic full-chain run over one workspace."""

    def __init__(self, ws: Path, *, seed: int, laps: int,
                 faults: Mapping[str, str] | None) -> None:
        self._ws = ws
        self._seed = seed
        self._laps = laps
        faults = dict(faults or {})
        for seam, mode in faults.items():
            accepted = FAULT_MODES.get(seam, frozenset())
            if mode not in accepted:
                raise ValueError(
                    f"chain_test_harness: fault {mode!r} is not a "
                    f"{seam!r}-seam fault (accepted: {sorted(accepted)})")
        self._faults = faults
        self._fault_lap = FAULT_LAP_DEFAULT
        self._clock = _Clock()
        self._subgoals: list[progress.Subgoal] = []
        self._sig = situation_signature(CHAIN_SITUATION)
        self.report: dict[str, Any] = {
            "seed": seed, "laps": laps, "faults": dict(faults),
            "gamma": GAMMA, "per_lap": [], "p_series": [],
            "chain_stopped_lap": None,
        }

    # ------------------------------------------------------ seam gates

    def _seam_active(self, seam: str, lap_no: int) -> bool:
        return self._faults.get(seam) is not None \
            and lap_no == self._fault_lap

    # ------------------------------------------------------------ seams

    def _select(self, lap_no: int, rid: str) -> dict:
        """The SELECT seam: one real DTS draw + the recorded selection
        row. The empty-candidates fault fires BEFORE any draw — the
        face's own fail-closed raise IS the observed response; the
        chain stops there honestly (no selection -> no lap)."""
        pick_rng = random.Random(
            f"chain909/{self._seed}/lap{lap_no}/pick")
        if self._seam_active("select", lap_no):
            error = ""
            try:
                selector.select_task(self._ws, [], rng=pick_rng)
            except ValueError as exc:
                error = str(exc)
            raise ChainStopped({
                "seam": "select", "mode": self._faults["select"],
                "response": "raised-fail-closed", "error": error,
            })
        pick = selector.select_task(self._ws, [CORE_TASK], rng=pick_rng)
        row = selector.record_selection(
            self._ws, pick["task"], rollout_id=rid,
            policy_version=POLICY_VERSION, ts=self._clock.tick())
        return {"receipt": pick, "row": row["row"],
                "appended": row["appended"]}

    def _arm_watchdog(self, lap_no: int) -> dict:
        """The WATCHDOG arming seam: the one-shot deadline from the
        family prior learned off the ledger. The malformed_deadline
        fault feeds the arming face garbage rows — the fail-closed
        refusal IS observed, then the loop re-arms through the
        documented cold default (never zero, #906 posture)."""
        rows = q_cells.trajectory_rows(self._ws)
        budget = Budget(wall_s=PER_DISPATCH_BUDGET_S)
        out: dict[str, Any] = {"fault": None, "deadline": None,
                               "checks": []}
        if self._seam_active("watchdog", lap_no):
            error = ""
            try:
                terminator.watchdog_deadline(
                    TRACKED, [{"schema": "quantum-tunnel/9"}], budget,
                    round_no=lap_no)
            except ValueError as exc:
                error = str(exc)
            out["fault"] = {
                "seam": "watchdog", "mode": "malformed_deadline",
                "response": "cold-default-rearmed", "error": error,
            }
            out["deadline"] = terminator.watchdog_deadline(
                COLD_FAMILY, rows, budget, round_no=lap_no)
        else:
            out["deadline"] = terminator.watchdog_deadline(
                TRACKED, rows, budget, round_no=lap_no)
        return out

    def _dispatch(self, rid: str, lap_no: int, step_no: int) -> dict:
        """ONE dispatch: assign -> action row -> execute -> result ->
        draft. A fault at the execute seam (lap- and step-gated) aborts
        the rollout: the fault record rides the step, the caller lands
        the audited rollback terminal, nothing downstream fabricates."""
        sid = f"{rid}-s{step_no:02d}"
        rng = random.Random(
            f"chain909/{self._seed}/{rid}/{step_no}/assign")
        assign = assigner.assign_method(
            self._ws, list(FAMILIES), {f: 1.0 for f in FAMILIES},
            signature_hash=self._sig, tier=1, rng=rng, gamma=GAMMA)
        family = assign["family"]
        action_row = q_cells.append_action(
            self._ws, kind="assign_step", rollout_id=rid, step_id=sid,
            target=family,
            params={"method_family": family, "tier": 1},
            budget={"wall_s": PER_DISPATCH_BUDGET_S, "max_calls": None},
            policy_version=POLICY_VERSION, ts=self._clock.tick())
        step: dict[str, Any] = {
            "step_id": sid, "family": family, "verified": False,
            "r_t": None, "cost": None, "seconds": None, "assign": assign,
            "action_row": action_row, "result_row": None, "draft": None,
            "banked_credit": None, "bank_receipt": None, "fault": None,
        }
        fault_mode = self._faults.get("execute")
        fault_here = fault_mode is not None \
            and lap_no == self._fault_lap and step_no == 1
        out: dict[str, Any]
        if fault_here:
            if fault_mode == "worker_exception":
                try:
                    _worker_execute(CHAIN_SITUATION, family,
                                    fault="worker_exception")
                except ChainWorkerError as exc:
                    step["fault"] = {
                        "seam": "execute", "mode": fault_mode,
                        "response": "worker-raise-captured",
                        "error": str(exc),
                    }
                    return step
            out = {"verified": "true", "tokens": RIGHT_TOKENS,
                   "seconds": RIGHT_SECONDS}
        else:
            out = _worker_execute(CHAIN_SITUATION, family)
        cost = out["tokens"] / 10_000.0
        r_t = 1.0 if out["verified"] else 0.0
        try:
            result_row = q_cells.append_result(
                self._ws, rollout_id=rid, step_id=sid, r_t=r_t,
                verified=out["verified"], cost=cost,
                verdict="pass" if out["verified"] else "fail",
                summary=f"{family} on {CHAIN_SITUATION}",
                ts=self._clock.tick())
        except ValueError as exc:
            step["fault"] = {
                "seam": "execute", "mode": fault_mode or "",
                "response": "result-refused", "error": str(exc),
            }
            return step
        step["result_row"] = result_row
        step["verified"] = bool(out["verified"])
        step["r_t"] = r_t
        step["cost"] = cost
        step["seconds"] = out["seconds"]
        verdicts = {"mechanical": step["verified"],
                    "scope_verifier": step["verified"], "redteam": True}
        step["draft"] = draft_commit.ensure_draft(
            self._ws, rid, sid, cost, verdicts, ts=self._clock.tick())
        return step

    def _bank(self, lap_no: int, family: str, draft_credit: float,
              claim: str, dispatch_id: str) -> tuple[float, dict]:
        """The CREDIT seam: the settled draft's credit banks at the
        family's arm key. The out_of_rail_credit fault injects an
        out-of-rail figure here — the boundary's [0, 1] clamp IS the
        observed response, and the receipt flags the delta."""
        injected = draft_credit
        if self._seam_active("credit", lap_no):
            injected = OUT_OF_RAIL_CREDIT
        row = q_cells.append_observation(
            self._ws, self._sig, family, injected, source="settlement",
            claim=claim, dispatch_id=dispatch_id,
            arm_key_col=arm_key(family), credit_kind="step",
            reason="chain909-dispatch-settlement", ts=self._clock.tick())
        banked = float(row["row"]["credit"])
        return banked, {"injected": injected, "banked": banked,
                        "clamped": banked != injected}

    def _belief(self, lap_no: int, task_id: str) -> dict:
        """The BELIEF seam: the snapshot built from the faces and landed
        as credit-free telemetry. The malformed_spec fault corrupts
        task_spec.yaml first — the #903 mapping guard's honest empty is
        the expected response and is RECORDED as observed, never
        assumed (a guard that stopped firing would read
        ``guard-did-not-fire`` here, loudly)."""
        fault_rec: dict[str, Any] | None = None
        if self._seam_active("belief", lap_no):
            (self._ws / "task_spec.yaml").write_text(MALFORMED_SPEC,
                                                     encoding="utf-8")
        snap = belief.build_snapshot(self._ws)
        if self._seam_active("belief", lap_no):
            fault_rec = {
                "seam": "belief", "mode": "malformed_spec",
                "observed": "honest-empty" if not snap["open_questions"]
                else "guard-did-not-fire",
            }
        row = belief.record_belief(self._ws, snap, claim=task_id,
                                   ts=self._clock.tick())
        return {"snapshot": snap, "row": row["row"], "fault": fault_rec}

    # --------------------------------------------------------- one lap

    def run_lap(self, lap_no: int) -> dict:
        """One lap of the COMPLETE protocol with every seam's receipt
        captured. The candidate task set is the recurring core task —
        the selector still makes a real DTS draw — and the situation is
        fixed, so the laps differ ONLY through what the ledger taught
        the faces (the credit-flow axis)."""
        rid = f"ro-{CORE_TASK}-lap{lap_no}"
        lap: dict[str, Any] = {"lap": lap_no, "picks": [], "rollouts": [],
                               "credit_banked": 0.0, "commit": None,
                               "watchdog": None, "belief": None,
                               "noise": None, "fault": None,
                               "p_transitions": []}
        lap["picks"].append(self._select(lap_no, rid))
        wd = self._arm_watchdog(lap_no)
        deadline = wd["deadline"]
        lap["watchdog"] = wd
        rollout: dict[str, Any] = {"rollout_id": rid, "task_id": CORE_TASK,
                                   "steps": [], "terminal": None,
                                   "terminal_r_t": None, "fault": None,
                                   "covered": False}
        lap["rollouts"].append(rollout)
        covered = False
        verified_ids: list[str] = []
        confidences: list[float] = []
        elapsed = 0.0
        steps: list[dict] = []
        last_check: dict[str, Any] = {}
        terminal: str | None = None
        rule: str | None = None
        while terminal is None:
            step_no = len(steps) + 1
            step = self._dispatch(rid, lap_no, step_no)
            steps.append(step)
            if step["fault"] is not None:
                rule = "worker_fault"
                terminal = "rolled_back"
                break
            confidences.append(1.0 if step["verified"]
                               else UNVERIFIED_CONFIDENCE)
            if step["verified"]:
                covered = True
                verified_ids.append(step["step_id"])
            elapsed += step["seconds"]
            last_check = terminator.check_termination(
                rid, {"covered": covered,
                      "question": f"the {CHAIN_SITUATION} question",
                      "verified_step_ids": list(verified_ids)},
                q_cells.trajectory_rows(self._ws),
                rng=random.Random(
                    f"chain909/{self._seed}/{rid}/{step_no}/term"))
            check = terminator.watchdog_check(
                deadline, elapsed_s=elapsed, rollout_completed=False)
            wd["checks"].append(check)
            if check["fired"]:
                rule = "watchdog_fired"
                terminal = "rolled_back"
            elif last_check["terminate"]:
                rule = str(last_check["rule"])
                terminal = "completed" if covered else "rolled_back"
            elif step_no >= MAX_STEPS:
                rule = "step_cap"
                terminal = "rolled_back"
        rollout["steps"] = steps
        rollout["covered"] = covered
        if steps[-1]["fault"] is not None:
            # the execute-seam fault rides the step AND the rollout/lap
            # receipts (the chain's audit face mirrors it upward)
            rollout["fault"] = steps[-1]["fault"]
            lap["fault"] = steps[-1]["fault"]
        kind = "terminate_rollout" if terminal == "completed" \
            else "rollback"
        q_cells.append_action(
            self._ws, kind=kind, rollout_id=rid, target=CORE_TASK,
            policy_version=POLICY_VERSION,
            params={"rule": rule}, ts=self._clock.tick())
        rollout["terminal"] = terminal
        # ---- settle: the crash fault stops between draft and commit;
        # the recovery (re-draft idempotent + late commit) runs in-line,
        # then the loop resumes its normal tail
        if self._seam_active("settle", lap_no):
            fault_rec = {
                "seam": "settle", "mode": "crash_mid_rollout",
                "response": "crash-simulated-pre-commit",
                "recovery": self._recover(rid),
            }
            rollout["fault"] = fault_rec
            lap["fault"] = fault_rec
        else:
            lap["commit"] = draft_commit.commit_batch(
                self._ws, rid, ts=self._clock.tick())
        # ---- credit: the batch's own committed drafts price the bank
        for draft in draft_commit.draft_rows(self._ws, rid):
            step = next(s for s in steps
                        if s["step_id"] == draft["dispatch_id"])
            banked, receipt = self._bank(
                lap_no, step["family"], float(draft["credit"]),
                claim=CORE_TASK, dispatch_id=draft["dispatch_id"])
            step["banked_credit"] = banked
            step["bank_receipt"] = receipt
            lap["credit_banked"] += banked
        # ---- terminal return pricing (skipped when nothing priced)
        rewards = _rollout_rewards(self._ws, rid)
        if rewards:
            shaped = _terminal_rows(self._ws, self._clock, rid, rewards,
                                    terminal=terminal,
                                    confidences=confidences)
            rollout["terminal_r_t"] = shaped["terminal_r_t"]
            rollout["terminal_row"] = shaped["row"]
        # ---- the P(s) ladder: one subgoal per dispatch, climbing to
        # PROVEN only on the ledger's own verified flag (evidence ref =
        # the step's result row)
        after = [progress.Subgoal(id=f"g-{s['step_id']}",
                                  status="PROVEN" if s["verified"]
                                  else "UNVERIFIED",
                                  evidence_refs=(f"{rid}/{s['step_id']}",))
                 for s in steps]
        before = [progress.Subgoal(id=f"g-{s['step_id']}",
                                   status="UNVERIFIED") for s in steps]
        self._subgoals.extend(after)
        self.report["p_series"].append(progress.P(self._subgoals))
        lap["p_transitions"] = [
            {"id": b.id, "before": b.status, "after": a.status}
            for b, a in zip(before, after)]
        # ---- belief lands last in the lap
        lap["belief"] = self._belief(lap_no, CORE_TASK)
        # ---- the ledger-noise injection (between laps)
        if self._seam_active("ledger", lap_no):
            lap["noise"] = self._inject_noise(self._faults["ledger"],
                                              lap_no)
        return lap

    def _recover(self, rid: str) -> dict:
        """The crash-recovery procedure (the #884, chained): re-draft
        every surviving draft — idempotent by the already-drafted guard
        — then the late commit. Returns the recovery receipt."""
        drafts = draft_commit.draft_rows(self._ws, rid)
        re_drafts = [
            draft_commit.ensure_draft(self._ws, rid, d["dispatch_id"],
                                      float(d["spend"]), d["verdicts"])
            for d in drafts]
        late_commit = draft_commit.commit_batch(
            self._ws, rid, ts=self._clock.tick())
        return {"re_drafts": re_drafts, "late_commit": late_commit}

    def _inject_noise(self, mode: str, lap_no: int) -> dict:
        """The LEDGER seam: one raw row appended DIRECTLY into the
        experience file, bypassing the q_cells faces — exactly the
        noise the walls must refuse. The observed response is READ
        BACK from the trusted read, never assumed."""
        unsealed = mode == "unsealed_row"
        raw = {
            "schema": q_cells.SCHEMA_ACTION_V2 if unsealed
            else "quantum-tunnel/9",
            "ts": self._clock.tick(),
            "kind": "assign_step" if unsealed else "probe",
            "rollout_id": f"ro-noise-lap{lap_no}",
            "step_id": f"ro-noise-lap{lap_no}-s01",
            "target": NOISE_MARK,
            "params": {"method_family": TRACKED},
        }
        cl.append(self._ws, "experience", raw)
        leaked = any(str(r.get("target") or "") == NOISE_MARK
                     for r in q_cells.trajectory_rows(self._ws))
        return {"mode": mode,
                "observed": "passed-through" if leaked else "excluded"}

    # ------------------------------------------------------------ run

    def run(self) -> tuple[dict, Path]:
        loop_sim._bootstrap(self._ws)
        for lap_no in range(1, self._laps + 1):
            try:
                self.report["per_lap"].append(self.run_lap(lap_no))
            except ChainStopped as stop:
                self.report["per_lap"].append(
                    {"lap": lap_no, "fault": stop.args[0], "picks": [],
                     "rollouts": [], "credit_banked": 0.0, "commit": None,
                     "watchdog": None, "belief": None, "noise": None,
                     "p_transitions": []})
                self.report["chain_stopped_lap"] = lap_no
                break
        return {"ws": self._ws, "report": self.report}, self._ws


# ------------------------------------------------- the flat mock worker

def _worker_execute(situation: str, family: str,
                    *, fault: str | None = None) -> dict:
    """THE MOCK WORKER — flat and deterministic: the answering family
    verifies at the cheap bill, every other family never verifies at
    the expensive bill. No proficiency drift — the policy learns, the
    worker doesn't. The worker_exception fault raises HERE, so the
    seam catches what a real worker crash produces."""
    if fault == "worker_exception":
        raise ChainWorkerError(
            f"chain909: the mock worker crashed on {family}/{situation}")
    if SITUATIONS.get(situation) is not None \
            and family == SITUATIONS[situation]:
        return {"verified": True, "tokens": RIGHT_TOKENS,
                "seconds": RIGHT_SECONDS}
    return {"verified": False, "tokens": WRONG_TOKENS,
            "seconds": WRONG_SECONDS}


def _rollout_rewards(ws: Path, rid: str) -> list[float]:
    """One rollout's priced step rewards, append order (the honest gap
    when nothing priced — a fault-aborted rollout has no rewards, so
    the terminal shaping is skipped, never fabricated)."""
    out: list[float] = []
    for row in q_cells.trajectory_rows(ws):
        if row.get("schema") != q_cells.SCHEMA_RESULT_V2:
            continue
        if str(row.get("rollout_id") or "") != rid:
            continue
        r_t = row.get("r_t")
        if isinstance(r_t, (int, float)) and not isinstance(r_t, bool):
            out.append(float(r_t))
    return out


def _terminal_rows(ws: Path, clock: _Clock, rid: str,
                   rewards: list[float], *, terminal: str,
                   confidences: list[float]) -> dict:
    """The rollout's terminal return: the credit faces price it (the
    discounted, outcome-shaped return over the rollout's own result
    rows; the advantage is confidence-modulated) and ONE terminal
    result row lands it — the loop_sim_v3 shape, receipts captured."""
    shaped = credit_returns.terminal_shaped(
        np.asarray(rewards, dtype=float), RETURNS_GAMMA, terminal=terminal,
        terminal_bonus=TERMINAL_BONUS)
    advantage = credit_advantage.modulate(
        credit_advantage.advantages(shaped, None),
        np.asarray(confidences, dtype=float))
    row = q_cells.append_result(
        ws, rollout_id=rid, step_id=f"{rid}-terminal",
        r_t=float(shaped[-1]), verified=terminal == "completed",
        R_t=float(shaped[-1]), A_t=float(advantage[-1]), verdict=terminal,
        summary="terminal return (credit.returns shaped)",
        ts=clock.tick())
    return {"terminal_r_t": float(shaped[-1]),
            "terminal_a_t": float(advantage[-1]), "row": row["row"]}


def run_chain(ws: Path, *, laps: int = 3, seed: int = 0,
              faults: Mapping[str, str] | None = None) -> tuple[dict, Path]:
    """``laps`` laps of the COMPLETE protocol over ``ws`` with the
    per-seam fault-injection matrix. Returns ``(run, ws)`` where
    ``run["report"]`` carries the per-lap seam receipts, the P(s)
    series and the OBSERVED fault responses (deterministic; Path-free
    apart from the ``ws`` key)."""
    return ChainHarness(Path(ws), seed=seed, laps=laps,
                        faults=faults).run()
