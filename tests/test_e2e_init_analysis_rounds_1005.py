# -*- coding: utf-8 -*-
"""E2E B — init -> analysis rounds -> learning -> settlement (user
requirement 2026-11-06).

The REAL init CLI scaffolds a fresh workspace (anchors pre-answered, toolchain
probe skipped), the analysis decision machine opens the loop, and the same
seeded round matrix as flow A drives dispatch -> completion -> blind
settlement -> round credit -> Q-cell posterior -> mission episode, with three
fault kinds interleaved. Only the LLM faces are mocked.
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
def test_init_analysis_to_learning_and_settlement(tmp_path, seed, monkeypatch):
    # the cross-task posterior store defaults INSIDE the repo — isolate it.
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-store"))
    # pin the ambient switch: the eval-settle mode skips the blind park.
    monkeypatch.setenv("KUNGLAO_EVAL_SETTLE", "0")
    sc = H.Scenario(seed)
    plan = sc.plan(rounds=7)
    ws = H.init_workspace(tmp_path, seed=seed, n_claims=len(plan))

    # ---- init really scaffolded the workspace --------------------------
    assert (ws / ".claude" / "settings.json").is_file(), "init wrote no settings"
    assert (ws / "task_spec.yaml").is_file(), "init lost the anchor contract"

    # ---- the analysis decision machine opens the loop ------------------
    from convergence_check import decide
    decision = decide(ws, emit_snapshot=False)
    assert decision["decision"] == "DISPATCH", decision

    # ---- the seeded round matrix --------------------------------------
    stats = H.run_rounds(ws, sc, plan)

    assert stats["settled"] >= 5, stats
    assert stats["refused"] >= 1, stats
    success, failure = H.cell_totals(ws)
    assert success > 0, "no positive learning landed"
    assert failure > 0, "no negative learning landed"
    posterior = _first_posterior(ws)
    assert posterior is not None, "no settled Q cell"
    assert tuple(posterior) != (1.0, 1.0), (
        f"posterior did not move off the uniform prior: {posterior}")

    episode = H.settle_mission(ws)
    assert episode["episodes_written"] == 1, episode
    assert H.settle_mission(ws)["episodes_written"] == 0
