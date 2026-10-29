# -*- coding: utf-8 -*-
"""tests/test_proof_battery.py — the PROOF BATTERY for the learning
loop (beyond the P7 declaration gate).

The owner's demand: 更多的实验来证明 — more experiments to prove the
learning is REAL, killing the "learning is constructed by the fixture"
objection. Each experiment isolates one objection:

  E1b  endogenous reward — the mock worker's step reward derives from
       conclusion QUALITY (the real phi-contraction face over the
       step's own hypotheses), not from constants: same hypotheses,
       same tokens, better conclusion => strictly higher reward.
  E1c  scrambled-memory control — the memory face fed WRONG-family
       features loses the fam-a decline entirely (scrambled == ablated
       on the fam-a axis): memory CONTENT matters, not memory existence.
  E1d  convergence floor — six laps: the decline asymptotes (deltas
       strictly shrink, no oscillation) — a learning curve, not a step.
  E3a  component ablation — cost-face-only vs method-memory-only vs
       full: which component carries the lap-1->2 collapse (the mastery
       discount) vs the later refinement (the empirical table) vs the
       ordering change (the value table's ordering face).
  E3b  dose-response — 1/2/3 prior episodes: expected cost monotone
       (and pinned exactly) in the evidence dose.
  M    earned mastery — mastery is granted by the REAL memory_bridge
       differential (completed + positive reward), never by the loop;
       a failed mission must NOT master its family.

The closing test prints the full battery table and asserts every pass
condition in one place.
"""
from __future__ import annotations

import pytest

import rlvr.pool_scheduler as ps
from rlvr import loop_sim
from rlvr import reward_signal

DELTA = loop_sim.DELTA
BASE_A = loop_sim.FAM_A_BASE_COST
INPUT_ORDER = list(loop_sim.FAMILIES)
#: the honest spends of the a2 retry / a4 consolidation missions
#: ($1 == 10k tokens, reward_signal.COST_TOKENS_NORM)
A2_COST = 4000 / reward_signal.COST_TOKENS_NORM
AC_COST = 2000 / reward_signal.COST_TOKENS_NORM
#: the asymptote: the marginal consolidation mission's mastered cost
FLOOR = AC_COST * ps.MASTERY_COST_FACTOR


def _run(tmp_path, name="ws", **kw):
    ws = tmp_path / name
    ws.mkdir()
    return loop_sim.run_learning_loop(ws, delta=DELTA, **kw)


# ------------------------------ M: mastery is earned, never granted

def test_mastery_is_earned_not_granted(tmp_path):
    """The loop's stamp face rides the REAL memory_bridge differential:
    a FAILED mission must NOT master its family, a completed
    positive-reward mission must. (Under the old stand-in the grant was
    unconditional — this pin is the anti-construction witness.)"""
    ws = tmp_path / "earned-ws"
    ws.mkdir()
    loop_sim._bootstrap(ws)
    failed = {"claim": "C-FAIL", "status": "NEGATIVE",
              "title": "failed probe", "family": "fam-f", "tokens": 8000}
    loop_sim._register(ws, failed)
    loop_sim._ledger_row(ws, failed)
    out, memory = loop_sim._settle_and_stamp(ws, failed, {})
    assert out["episodes_written"] == 1
    assert memory["fam-f"]["mastered"] is False, memory
    ok = {"claim": "C-OK", "status": "PROVEN",
          "title": "cheap probe", "family": "fam-g", "tokens": 1000}
    loop_sim._register(ws, ok)
    loop_sim._ledger_row(ws, ok)
    _out, memory = loop_sim._settle_and_stamp(ws, ok, memory)
    assert memory["fam-g"]["mastered"] is True, memory


# --------------------------------------- E1b: endogenous step reward

def test_e1b_endogenous_step_reward_spread():
    """Same hypotheses, same tokens — only the conclusion's contraction
    quality differs, and the settled step reward follows it: kill+
    confirm > confirm-only > no-checkpoint (exactly 0, the zero gate).
    The recorded values ARE the real step_reward face's output, not
    constants. (step/1's own contract refuses a contraction-quiet
    conclusion outright, so the bottom rung is the gate, not theater.)"""
    hyps = [loop_sim._hyp("HX", "the checksum family is md5"),
            loop_sim._hyp("HY", "the constants are plain sha256")]

    def _run_step(conclusion, *, checkpoint_closed=True):
        return loop_sim._step("probe task", hyps, "static-scan", conclusion,
                              used_recalled=False, tokens=1000,
                              checkpoint_closed=checkpoint_closed)

    strong = _run_step("HX is refuted: the digest width contradicts md5; "
                       "HY survives: the constants match sha256")
    middle = _run_step("HY survives: the constants match sha256")
    gated = _run_step(strong["conclusion"], checkpoint_closed=False)
    assert strong["reward"]["value"] > middle["reward"]["value"] \
        > gated["reward"]["value"] == 0.0
    for step in (strong, middle):
        face = reward_signal.step_reward(hyps, step["conclusion"], True,
                                         True, 1000, 0.0)
        assert step["reward"]["value"] == pytest.approx(face)
    # the zero gate on the face itself: a conclusion that decides
    # nothing scores exactly 0 — activity theater dies
    assert reward_signal.step_reward(hyps, "the scan produced output",
                                     True, True, 1000, 0.0) == 0.0
    # the live fixture's own steps already ride this spread (the a1
    # trajectory's three settled rewards are three distinct values,
    # including the planted deviation's zero — its unclosed checkpoint
    # trips the zero gate on the REAL face). step/1 drops non-schema
    # fields at validation, so the recompute rides the rollout's own
    # declared per-step (tokens, checkpoint-closed) spec.
    steps, _mission = loop_sim._rollout_a1()
    declared = [(2000, True), (4000, False), (3000, True)]
    rewards = [s["reward"]["value"] for s in steps]
    assert len(set(rewards)) == len(rewards), rewards
    for s, (tokens, closed) in zip(steps, declared):
        face = reward_signal.step_reward(s["hypotheses"], s["conclusion"],
                                         True, closed, tokens, 0.0)
        assert s["reward"]["value"] == pytest.approx(face)


# ------------------------------- E1c: scrambled-memory control

def test_e1c_scrambled_memory_control(tmp_path):
    """MEMORY CONTENT matters, not memory existence: with the family key
    scrambled at stamp time the fam-a decline vanishes entirely — the
    scrambled arm's cost trace equals the ABLATED arm's (flat at the
    cold base), while the live arm keeps its earned decline."""
    live = _run(tmp_path)
    scrambled = _run(tmp_path, name="scrambled", scramble_memory=True)
    ablated = _run(tmp_path, name="ablated", ablate_pool_memory=True)
    s_trace = scrambled["expected_cost_trace"]
    assert s_trace == [pytest.approx(BASE_A)] * 3, s_trace
    assert s_trace == ablated["expected_cost_trace"]
    assert live["expected_cost_trace"][-1] < s_trace[-1]
    # the mispricing is real and dangerous: the ring scramble re-masters
    # EVERY family (each family's flag lands via some other family's
    # misfiled episode), so the mastery FLAGS are blind to the scramble
    # — the flags say everything is learned, while the prices say
    # nothing was. Flag-identical, price-flat: that is the gap between
    # memory existence and memory content.
    assert scrambled["final"]["memory"] == live["final"]["memory"]
    assert live["expected_cost_trace"] != s_trace


# ------------------------------- E1d: convergence floor (6 laps)

def test_e1d_convergence_floor_six_laps(tmp_path):
    """A learning curve, not a step function: over six laps the fam-a
    expected-cost decline keeps its sign, shrinks strictly in magnitude
    (no oscillation), and stays above the marginal-mission floor — an
    asymptote toward the consolidation cost, never below it."""
    report = _run(tmp_path, name="six", laps=6)
    trace = report["expected_cost_trace"]
    assert len(trace) == 6, trace
    deltas = [b - a for a, b in zip(trace, trace[1:])]
    assert all(d < 0 for d in deltas), trace
    assert all(abs(d2) < abs(d1)
               for d1, d2 in zip(deltas, deltas[1:])), deltas
    assert trace[-1] > FLOOR
    # the lap-end series agrees (refreshed table, same shape)
    ends = [lap["expected_cost_fam_a"] for lap in report["laps"]]
    assert all(b - a < 0 for a, b in zip(ends, ends[1:])), ends
    assert ends[-1] > FLOOR


# ------------------------------- E3a: component ablation arms

def test_e3a_component_ablation_arms(tmp_path):
    """WHICH component carries WHAT: the memory face carries the
    lap-1->2 collapse (the earned mastery discount) and nothing after;
    the cost face carries the later empirical refinement and the
    ordering change; only the full arm gets both. Cost-only declines
    WITHOUT the collapse; memory-only collapses WITHOUT refinement and
    loses the lane change."""
    cost_only = _run(tmp_path, name="cost-only", ablate_memory=True)
    mem_only = _run(tmp_path, name="mem-only", ablate_value_table=True)
    full = _run(tmp_path)
    c_trace = cost_only["expected_cost_trace"]
    m_trace = mem_only["expected_cost_trace"]
    f_trace = full["expected_cost_trace"]
    # collapse (lap1->2) = the memory face's mastery discount ...
    assert f_trace[1] == pytest.approx(BASE_A * ps.MASTERY_COST_FACTOR)
    assert m_trace[1] == pytest.approx(BASE_A * ps.MASTERY_COST_FACTOR)
    # ... which the cost-face-only arm never sees (its lap-1->2 is flat)
    assert c_trace[1] == pytest.approx(BASE_A)
    # refinement (lap2->3) = the cost face's empirical folding ...
    assert c_trace[2] == pytest.approx((BASE_A + A2_COST) / 2)
    assert f_trace[2] == pytest.approx((BASE_A + A2_COST) / 2
                                       * ps.MASTERY_COST_FACTOR)
    # ... which the memory-only arm cannot produce (no empirical cells)
    assert m_trace[2] == pytest.approx(BASE_A * ps.MASTERY_COST_FACTOR)
    # the lane change rides the value table's ordering face
    assert cost_only["laps"][2]["ordering"] == full["laps"][2]["ordering"]
    assert mem_only["laps"][2]["ordering"] == INPUT_ORDER


# ------------------------------- E3b: dose-response

def test_e3b_dose_response_monotone(tmp_path):
    """More evidence -> tighter family mean -> lower expected cost: with
    1/2/3 settled fam-a episodes the memory-derived expected cost is
    strictly monotone in the dose, pinned exactly (the empirical mean of
    the honest spends under the earned mastery discount)."""
    costs = []
    for dose in (1, 2, 3):
        report = _run(tmp_path, name=f"dose-{dose}", laps=dose)
        costs.append(report["laps"][-1]["expected_cost_fam_a"])
    assert costs == pytest.approx([
        BASE_A * ps.MASTERY_COST_FACTOR,
        (BASE_A + A2_COST) / 2 * ps.MASTERY_COST_FACTOR,
        (BASE_A + A2_COST + AC_COST) / 3 * ps.MASTERY_COST_FACTOR]), costs
    assert costs[0] > costs[1] > costs[2] > FLOOR


# ------------------------------- the full battery table

def test_proof_battery_table(tmp_path):
    """The owner's one-glance proof: every arm x lap cost, the dose
    curve, and the pass conditions (earned decline, scrambled==ablated,
    component split, dose monotone, asymptote) asserted together."""
    arms = {
        "live": _run(tmp_path, name="b-live"),
        "scrambled": _run(tmp_path, name="b-scrambled",
                          scramble_memory=True),
        "ablated": _run(tmp_path, name="b-ablated",
                        ablate_pool_memory=True),
        "cost-only": _run(tmp_path, name="b-cost-only", ablate_memory=True),
        "memory-only": _run(tmp_path, name="b-memory-only",
                            ablate_value_table=True),
    }
    doses = [_run(tmp_path, name=f"b-dose-{d}", laps=d)
             ["laps"][-1]["expected_cost_fam_a"] for d in (1, 2, 3)]
    six = _run(tmp_path, name="b-six", laps=6)["expected_cost_trace"]
    lines = ["arm          |  lap1   |  lap2   |  lap3"]
    for name, report in arms.items():
        t = report["expected_cost_trace"]
        lines.append(f"{name:<12} | {t[0]:.4f}  | {t[1]:.4f}  "
                     f"| {t[2]:.4f}")
    lines.append(f"dose 1/2/3: {doses[0]:.4f} -> {doses[1]:.4f} "
                 f"-> {doses[2]:.4f}")
    lines.append("six-lap:    " + " -> ".join(f"{c:.4f}" for c in six))
    lines.append(f"floor (marginal mastered cost): {FLOOR:.4f}")
    print("\n".join(lines))  # visible under pytest -s (the proof sheet)
    # pass conditions, all in one place
    live = arms["live"]["expected_cost_trace"]
    assert live[0] > live[1] > live[2]                    # earned decline
    assert arms["scrambled"]["expected_cost_trace"] == \
        arms["ablated"]["expected_cost_trace"]            # scrambled~ablated
    assert live[-1] < arms["scrambled"]["expected_cost_trace"][-1]
    assert doses[0] > doses[1] > doses[2] > FLOOR         # dose monotone
    deltas = [b - a for a, b in zip(six, six[1:])]
    assert all(d < 0 for d in deltas)                     # asymptote sign
    assert all(abs(b) < abs(a) for a, b in zip(deltas, deltas[1:]))
    # component split: neither face alone reproduces the full arm
    assert arms["memory-only"]["expected_cost_trace"][2] != \
        pytest.approx(live[2])
    assert arms["cost-only"]["expected_cost_trace"][1] != \
        pytest.approx(live[1])
