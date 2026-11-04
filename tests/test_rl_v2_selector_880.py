# -*- coding: utf-8 -*-
"""tests/test_rl_v2_selector_880.py — the DTS task selector (issue 880).

RED-first pins for the select_task policy face:

  1. the posterior export — per-task (alpha, beta) derived from the
     ledger's TERMINAL rollout returns (the (s,a,r) store is the ONLY
     source; no parallel tally);
  2. cold-start exploration — an empty ledger samples near-uniformly
     (wide Beta(1,1): the DTS draw never degenerates to argmax);
  3. exploitation — a task with banked successes is sampled
     substantially more than a failed/cold one (chi-square tolerance);
  4. determinism — same inputs + seed -> identical receipt; a ledger
     that moved -> a different draw (the evidence-sensitivity
     contract);
  5. the recording face — the selection lands as ONE q-cell-action/1
     row (kind=select_task, target=the task) through the standard
     single-writer path;
  6. fail-closed reject pins.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import policy as policy_pkg  # noqa: E402,F401 — the package face
from policy import selector  # noqa: E402
from rlvr import q_cells  # noqa: E402

TASKS = ("C-001", "C-002", "C-003", "C-004", "C-005")
N_DRAWS = 2000
# chi-square critical value, df=4, p=0.01
CHI2_DF4_P01 = 13.28


_SEED_SEQ = iter(range(10000))


def _seed_task(ws, task: str, returns: list[float]) -> None:
    """One task's history: a select_task action + a rollout of
    step results whose LAST r_t is the terminal return. Every call
    mints a FRESH rollout (ten calls = ten observations)."""
    rid = f"ro-{task}-{next(_SEED_SEQ)}"
    q_cells.append_action(ws, kind="select_task", rollout_id=rid,
                          target=task)
    for i, r in enumerate(returns):
        q_cells.append_result(ws, rollout_id=rid, step_id=f"s-{i:02d}",
                              r_t=r, verified=r > 0.0)


# ------------------------------------------------- posterior export

def test_task_posteriors_from_terminal_returns(tmp_path):
    ws = tmp_path / "ws"
    _seed_task(ws, "C-001", [0.5, 1.0])
    _seed_task(ws, "C-002", [0.0])
    post = selector.task_posteriors(ws, ("C-001", "C-002", "C-003"))
    alpha1, beta1 = post["C-001"]
    assert alpha1 == pytest.approx(1.0 + 1.0)   # prior + terminal 1.0
    assert beta1 == pytest.approx(1.0 + 0.0)
    assert post["C-002"] == (1.0, 2.0)          # terminal 0.0 = failure
    assert post["C-003"] == (1.0, 1.0)          # cold: the wide prior


def test_only_terminal_return_banks_mass(tmp_path):
    ws = tmp_path / "ws"
    _seed_task(ws, "C-001", [0.0, 0.0, 1.0])
    alpha, beta = selector.task_posteriors(ws, ("C-001",))["C-001"]
    assert (alpha, beta) == (2.0, 1.0)          # the LAST r_t, not the sum


# ------------------------------------------------ DTS sampling face

def test_cold_start_explores_near_uniformly(tmp_path):
    ws = tmp_path / "ws"
    rng = random.Random(7)
    counts = {t: 0 for t in TASKS}
    for _ in range(N_DRAWS):
        receipt = selector.select_task(ws, TASKS, rng=random.Random(rng.random()))
        counts[receipt["task"]] += 1
    expected = N_DRAWS / len(TASKS)
    chi2 = sum((counts[t] - expected) ** 2 / expected for t in TASKS)
    assert chi2 < CHI2_DF4_P01, counts          # no argmax lock-in


def test_known_good_task_is_exploited(tmp_path):
    ws = tmp_path / "ws"
    for _ in range(10):          # ten ROLLOUTS = ten terminal observations
        _seed_task(ws, "C-001", [1.0])
        _seed_task(ws, "C-002", [0.0])
    rng = random.Random(11)
    counts = {t: 0 for t in TASKS}
    for _ in range(N_DRAWS):
        receipt = selector.select_task(ws, TASKS, rng=random.Random(rng.random()))
        counts[receipt["task"]] += 1
    # Beta(11,1) vs four Beta(1,1)s: win prob ~0.73; the failed task's
    # Beta(1,11) almost never wins. Bounds carry >=3-sd binomial margin.
    assert counts["C-001"] > 5 * max(counts[t] for t in TASKS if t != "C-001")
    assert counts["C-002"] < (N_DRAWS / len(TASKS)) / 2


def test_receipt_shape_and_determinism(tmp_path):
    ws = tmp_path / "ws"
    _seed_task(ws, "C-001", [1.0, 1.0])
    r1 = selector.select_task(ws, TASKS, rng=random.Random(3))
    r2 = selector.select_task(ws, TASKS, rng=random.Random(3))
    assert r1 == r2
    assert r1["schema"] == "task-select/1"
    assert r1["task"] in TASKS
    cand = r1["candidates"]["C-001"]
    assert cand["alpha"] == 2.0 and cand["beta"] == 1.0  # terminal only
    assert 0.0 < cand["theta"] < 1.0
    assert r1["action"] == {"kind": "select_task", "target": r1["task"]}


def test_ledger_movement_changes_the_draw(tmp_path):
    from collections import Counter

    rng = random.Random(5)
    ws_cold = tmp_path / "cold"
    ws_warm = tmp_path / "warm"
    for _ in range(8):           # eight terminal observations for C-003
        _seed_task(ws_warm, "C-003", [1.0])
    cold = [selector.select_task(ws_cold, TASKS, rng=random.Random(rng.random()))["task"]
            for _ in range(200)]
    warm = [selector.select_task(ws_warm, TASKS, rng=random.Random(rng.random()))["task"]
            for _ in range(200)]
    warm_counts = Counter(warm)
    # Beta(9,1) beats a max-of-4-uniform ~69% of the time — dominance,
    # never certainty (a near-deterministic draw would be argmax back).
    assert warm_counts["C-003"] > 2 * (200 / len(TASKS))
    assert len(set(cold)) >= 4                 # cold: spread


# --------------------------------------------------- recording face

def test_record_selection_lands_one_action_row(tmp_path):
    ws = tmp_path / "ws"
    out = selector.record_selection(ws, "C-002", rollout_id="ro-x",
                                    policy_version="v2")
    assert out["appended"] is True
    (row,) = q_cells.trajectory_rows(ws)
    assert row["schema"] == "q-cell-action/1"
    assert row["kind"] == "select_task"
    assert row["target"] == "C-002"
    assert row["rollout_id"] == "ro-x"
    assert row["policy_version"] == "v2"


# ------------------------------------------------------- reject pins

def test_reject_pins(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        selector.select_task(ws, [])
    with pytest.raises(ValueError):
        selector.select_task(ws, ["C-1", ""])
    with pytest.raises(ValueError):
        selector.select_task(ws, ["C-1", 42])
    with pytest.raises(ValueError):
        selector.record_selection(ws, "", rollout_id="ro-x")
