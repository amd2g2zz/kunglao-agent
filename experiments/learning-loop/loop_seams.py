# -*- coding: utf-8 -*-
"""loop_seams.py — the loop's fault-injection seam faces (#913).

The #909 fault matrix, as faces: the matrix vocabulary plus the five
ledger-touching seam methods the DecisionLoop uses, extracted as one
mixin so the wiring module stays under the size cap. The seams are
the loop's audit faces — each carries its receipt and the OBSERVED
fault response (never assumed, always read back or recorded):

  select   empty_candidates    the selector raises fail-closed; the
                               chain stops honestly (no selection ->
                               no lap)
  execute  worker_exception    the crash captured at the seam; no
                               result row; the rollout aborts
  execute  worker_garbage      the result face refuses the non-bool
                               verdict fail-closed; nothing banks
  settle   crash_mid_rollout   the crash between draft and commit:
                               the recovery re-drafts (idempotent)
                               and late-commits
  credit   out_of_rail_credit  the boundary clamps into [0, 1];
                               flagged
  ledger   unsealed_row        a raw unsealed row is refused by the
                               seal wall (armed posture)
  ledger   (foreign_schema)    a foreign-schema row is excluded by
                               the prefix wall (always)
  watchdog malformed_deadline  the arming face refuses the garbage
                               fail-closed; re-arm through the
                               documented cold default
  belief   malformed_spec      the #903 mapping guard renders the
                               honest empty open-questions element

Deterministic: the loop's clock stamps every landed row; no wall
clock in any decision.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_SCRIPTS = _HERE.parents[1] / "scripts"
for _p in (_HERE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from core import Budget  # noqa: E402 — the bootstrap lands first
from loop_pins import CORE_TASK, POLICY_VERSION, arm_key  # noqa: E402
from loop_worker import TRACKED  # noqa: E402
from policy import selector, terminator  # noqa: E402 — the audit faces
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from state import belief  # noqa: E402

# the fault matrix: seam -> the modes it accepts (the #909 vocabulary,
# re-run through the REAL loop). An unknown pair refuses loudly.
FAULT_MODES: dict[str, frozenset[str]] = {
    "select": frozenset({"empty_candidates"}),
    "execute": frozenset({"worker_exception", "worker_garbage"}),
    "settle": frozenset({"crash_mid_rollout"}),
    "credit": frozenset({"out_of_rail_credit"}),
    "ledger": frozenset({"unsealed_row", "foreign_schema"}),
    "watchdog": frozenset({"malformed_deadline"}),
    "belief": frozenset({"malformed_spec"}),
}

# the faulted lap - the matrix places every fault mid-chain so the
# laps AFTER the fault prove the loop continued
FAULT_LAP_DEFAULT = 2

# the out-of-rail credit the bank seam injects (the boundary's rail
# is [0, 1]; the injected 2.5 lands clamped at 1.0, flagged)
OUT_OF_RAIL_CREDIT = 2.5

# the injected noise row's target marker (the #909 ledger walls)
NOISE_MARK = "noise-909"

# the history-less family the cold-default re-arm uses (#906 posture)
COLD_FAMILY = "cold-default"

# the malformed task_spec payload - a top-level scalar (the #903
# mapping guard's honest-empty edge)
MALFORMED_SPEC = "loop913-garbage-spec\n"

# the mock dispatch envelope's wall budget (the watchdog's operand)
PER_DISPATCH_BUDGET_S = 600.0


class SeamMixin:
    """The loop's fault-injection seam faces, as a mixin over the
    DecisionLoop state (``_ws`` / ``_seed`` / ``_clock`` / ``_sig`` /
    ``_faults`` / ``_fault_lap``). The wiring module keeps the
    protocol; the seams keep their receipts and their observed fault
    responses."""

    def _seam_active(self, seam: str, lap_no: int) -> bool:
        return self._faults.get(seam) is not None \
            and lap_no == self._fault_lap

    def _select(self, lap_no: int, rid: str) -> dict:
        """The SELECT seam: one real DTS draw + the recorded selection
        row (the driver's clock). The empty-candidates fault fires
        BEFORE any draw — the face's fail-closed raise IS the observed
        response; the chain stops there honestly."""
        pick_rng = random.Random(
            f"loop913/{self._seed}/lap{lap_no}/pick")
        if self._seam_active("select", lap_no):
            error = ""
            try:
                selector.select_task(self._ws, [], rng=pick_rng)
            except ValueError as exc:
                error = str(exc)
            raise _LoopStopped({
                "seam": "select", "mode": self._faults["select"],
                "response": "raised-fail-closed", "error": error,
            })
        pick = selector.select_task(self._ws, [CORE_TASK],
                                    rng=pick_rng)
        row = selector.record_selection(
            self._ws, pick["task"], rollout_id=rid,
            policy_version=POLICY_VERSION, ts=self._clock.tick())
        return {"receipt": pick, "row": row["row"],
                "appended": row["appended"]}

    def _arm_watchdog(self, lap_no: int) -> dict:
        """The WATCHDOG arming seam: the one-shot deadline from the
        #906 family prior. The malformed_deadline fault feeds the
        arming face garbage rows — the fail-closed refusal IS
        observed, then the loop re-arms through the documented cold
        default (never zero)."""
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

    def _bank_credit(self, lap_no: int, family: str,
                     draft_credit: float, claim: str,
                     dispatch_id: str) -> tuple[float, dict]:
        """The CREDIT seam: the settled draft's credit banks at the
        family's arm key. The out_of_rail_credit fault injects an
        out-of-rail figure — the boundary's [0, 1] clamp IS the
        observed response, and the receipt flags the delta."""
        injected = draft_credit
        if self._seam_active("credit", lap_no):
            injected = OUT_OF_RAIL_CREDIT
        row = q_cells.append_observation(
            self._ws, self._sig, family, injected, source="settlement",
            claim=claim, dispatch_id=dispatch_id,
            arm_key_col=arm_key(family), credit_kind="step",
            reason="loop913-dispatch-settlement",
            ts=self._clock.tick())
        banked = float(row["row"]["credit"])
        return banked, {"injected": injected, "banked": banked,
                        "clamped": banked != injected}

    def _belief_seam(self, lap_no: int, task_id: str) -> dict:
        """The BELIEF seam: the snapshot built from the faces, landed
        as credit-free telemetry under the driver's clock. The
        malformed_spec fault corrupts task_spec.yaml first — the #903
        mapping guard's honest empty is the expected response and is
        RECORDED as observed, never assumed."""
        fault_rec: dict[str, Any] | None = None
        if self._seam_active("belief", lap_no):
            (self._ws / "task_spec.yaml").write_text(
                MALFORMED_SPEC, encoding="utf-8")
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


class _LoopStopped(Exception):
    """The chain stopped at the faulted seam (the select fault's
    honest posture: no selection -> no lap). Args[0] is the fault
    record."""
