# -*- coding: utf-8 -*-
"""E2E A — resume -> RL rounds -> learning -> settlement.

Seeded-random data (7 rounds per seed, >=5 required), three fault kinds
interleaved, and the REAL chain from the resume CLI through the blind
settlement wire, round credit, the Q-cell posterior and the mission-terminal
episode. Only the LLM settler is mocked (the harness writes the verdict doc).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "tests", ROOT / "scripts", ROOT / "hooks"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import _rl_e2e as H  # noqa: E402

SEEDS = (11, 23)


def _first_posterior(ws: Path):
    from rlvr import q_cells
    fold = q_cells.fold(q_cells.default_store(ws), gamma=1.0)
    for cell in sorted(fold.cells.values(),
                       key=lambda c: (c.signature_hash, c.family)):
        if (cell.success + cell.failure) <= 0:
            continue
        family = q_cells.family_of_action(cell.family)
        arm = cell.family if "|" in cell.family else None
        return q_cells.cell_posterior(
            fold, cell.signature_hash, family, arm_key=arm)
    return None


@pytest.mark.parametrize("seed", SEEDS)
def test_resume_to_learning_and_settlement(tmp_path, seed, monkeypatch):
    # the cross-task posterior store defaults INSIDE the repo — isolate the
    # E2E's store rows to the test's tmp tree (parallel seeds never race).
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-store"))
    # pin the ambient switch: the eval-settle mode skips the blind park.
    monkeypatch.setenv("KUNGLAO_EVAL_SETTLE", "0")
    sc = H.Scenario(seed)
    plan = sc.plan(rounds=7)
    ws = H.build_workspace(tmp_path, seed=seed, n_claims=len(plan))

    # ---- the resume entry point (real CLI, read-only) ------------------
    brief = H.resume_brief(ws)
    assert brief["rc"] == 0, brief
    assert brief["verdict"] == "RESUMABLE", brief["manual_reasons"]
    assert brief["summary"]["decision"]["decision"] == "DISPATCH", (
        brief["summary"])
    assert brief["health"]["heartbeat"]["status"] == "ALIVE"

    # ---- rounds 1-4 ----------------------------------------------------
    stats_a = H.run_rounds(ws, sc, plan[:4])

    # ---- MID-RUN fault: the activation TTL expires; resume reports it --
    H.expire_activation(ws)
    expired = H.resume_brief(ws)
    assert expired["health"]["activation"]["status"] == "EXPIRED", expired
    H.renew_activation(ws)               # the command's documented renew step
    assert H.resume_brief(ws)["health"]["activation"]["status"] == "ACTIVE"

    # ---- rounds 5-7 ----------------------------------------------------
    stats_b = H.run_rounds(ws, sc, plan[4:])
    stats = {k: stats_a[k] + stats_b[k] for k in stats_a}

    assert stats["settled"] >= 5, stats            # the user's 5-round floor
    assert stats["refused"] >= 1, stats            # fault injection exercised
    success, failure = H.cell_totals(ws)
    assert success > 0, "no positive learning landed"
    assert failure > 0, "no negative learning landed"
    posterior = _first_posterior(ws)
    assert posterior is not None, "no settled Q cell"
    assert tuple(posterior) != (1.0, 1.0), (
        f"posterior did not move off the uniform prior: {posterior}")

    # ---- mission terminal: one episode, idempotent ---------------------
    episode = H.settle_mission(ws)
    assert episode["episodes_written"] == 1, episode
    assert H.settle_mission(ws)["episodes_written"] == 0


def test_scenario_plan_is_seeded_and_varies():
    """The data face is seeded-random: the same seed replays identically,
    different seeds vary, and every plan carries both learning directions
    plus the three fault kinds."""
    plan_a = H.Scenario(11).plan(7)
    assert plan_a == H.Scenario(11).plan(7), "same seed must replay identically"

    def _sig(plan):
        return [(p["family"], p["credit"], p["fault"], p["oracle"])
                for p in plan]

    assert _sig(plan_a) != _sig(H.Scenario(23).plan(7)), (
        "different seeds must vary the data")
    assert plan_a[0]["oracle"] == "pass", "round 1 opens on a success"
    assert any(p["oracle"] == "fail" for p in plan_a), "one measured negative"
    assert {p["fault"] for p in plan_a if p["fault"] != "healthy"} == set(
        H.FAULT_KINDS), "every fault kind must be exercised"
