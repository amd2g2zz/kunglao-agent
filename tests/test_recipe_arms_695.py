#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_recipe_arms_695.py — issue #695: tool-chain recipe arms
(the learned-action substrate for tool choice).

Owner rulings: tool selection / tool-chain orchestration are first-class
actions of the controller, never a static table (2026-10-11); tool value
is context-dependent with no silver bullet, so the controller must learn
which toolchain to plan per situation, credited from outputs
(2026-10-14). This card is the v0.1.6 SUBSTRATE: arms + propensity +
trusted settlement attribution. Recommendation, never restriction — the
worker (frozen LLM) stays free; the recipe rides as an annotation.

The four faces pinned here:

1. ``test_dispatch_records_recipe_propensity_and_source`` — every
   approved dispatch's q-cell observation row carries
   ``{recipe_id, recipe_propensity, recipe_source}`` with source ∈
   sampled | declared | none (the #691 reconciliation shape, now at the
   tool-chain grain);
2. ``test_settlement_banks_credit_against_recipe_without_worker_narrative``
   — the settlement (``observe_settlement``, the #678 trusted chain)
   banks its credit against the DISPATCH-RECORDED recipe_id and never
   reads a worker narrative (a lying ``steps:`` line cannot move the
   bank — the #881 tool_value anti-pattern stays dead);
3. ``test_recipe_arms_floor_weight_never_deleted`` — every registered
   family carries >= 3 arms, every arm's sampling weight stays strictly
   positive after brutal failure mass (THETA_FLOOR — floored, never
   deleted, revivable) and the floored arm remains samplable;
4. ``test_no_new_reject_surface_for_tool_choice`` — a declared recipe
   that deviates from the gate's sampler draw (or an unregistered one)
   is a RECORDED decision (``recipe_deviation`` event), never a new
   REJECT surface: ``pre_check`` still returns 0.

Plus ``test_replay_reports_arm_level_separation`` (the S2-shape replay:
rerun the sampler over recorded history, report the arm-level
separation and the disagreement rate — offline only, no online switch).
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import worker_budget_sinks as sinks

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))

_SEED_SIG = "abcdabcdabcd"          # any 12-hex state signature
_FAM = "static-decompile"           # a closed-vocabulary family


# ---------------------------------------------------------------------------
# fixtures (same sink-face harness as tests/test_rl_output_path_691.py:
# minimal paths, v1 envelope + facts-snapshot marker)
# ---------------------------------------------------------------------------

def _min_paths(ws: Path) -> dict:
    ws.mkdir(parents=True, exist_ok=True)
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _dispatch_payload(prompt: str) -> dict:
    return {'tool_input': {'name': 'w-test', 'description': '',
                           'prompt': prompt}}


def _full_prompt(family: str, recipe_id: str | None = None,
                 claim: str = 'C-001') -> str:
    env = {'version': 1, 'claim': claim, 'tier': 1,
           'tools': ['grep'], 'agent': 'w-test',
           'method_family': family}
    if recipe_id is not None:
        env['recipe_id'] = recipe_id
    return json.dumps({'kunglao_dispatch': env}) + '\nfacts-snapshot: 1 facts'


def _obs_rows(ws: Path) -> list[dict]:
    # #721: ride the read face (consolidated experience file + legacy
    # fallback) — a direct q-cell-log.jsonl read strands after the move.
    from rlvr import q_cells as _qc
    return [r for r in _qc.JSONLQStore(ws).observations()
            if isinstance(r, dict)]


def _dispatch_rows(ws: Path) -> list[dict]:
    return [r for r in _obs_rows(ws) if r.get('source') == 'dispatch']


def _events(ws: Path, action: str) -> list[dict]:
    out: list[dict] = []
    logs = ws / 'runs' / 'logs'
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob('kunglao-*.jsonl')):
        for ln in p.read_text(encoding='utf-8').splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            if row.get('action') == action:
                out.append(row)
    return out


def _detail(row: dict) -> dict:
    det = row.get('detail')
    if isinstance(det, str):
        return json.loads(det)
    return det or {}


def _draw(ws: Path, family: str) -> str:
    """The sampler's own cold-state draw — the on-policy arm to declare."""
    from rlvr import recipe_arms
    return recipe_arms.sample_recipe(ws, family)['recipe_id']


# ---------------------------------------------------------------------------
# 1. the dispatch observation records recipe + propensity + source
# ---------------------------------------------------------------------------

def test_dispatch_records_recipe_propensity_and_source(tmp_path, capsys):
    """#695 T2: the approval point's q-cell dispatch row carries the
    recipe triple. Declaring exactly what the gate's sampler draws is
    the on-policy face (source=sampled); declaring a different arm is
    the off-policy face (source=declared, propensity = its probability
    under the sampler). Both rows persist with explicit values."""
    ws = tmp_path / 'ws'
    arms = None
    from rlvr import recipe_arms
    arms = recipe_arms.arm_ids_for(_FAM)
    assert len(arms) >= 3, arms
    on_policy = _draw(ws, _FAM)
    off_policy = next(a for a in arms if a != on_policy)

    rc = sinks.pre_check(_dispatch_payload(_full_prompt(_FAM, on_policy)),
                         _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    row = _dispatch_rows(ws)[-1]
    assert row['recipe_id'] == on_policy
    assert row['recipe_source'] == 'sampled'
    assert isinstance(row['recipe_propensity'], float)
    assert 0.0 < row['recipe_propensity'] <= 1.0

    # the #690 sync barrier is workspace-global (no dispatch while a
    # prior step is unsettled) — the off-policy face gets its own ws
    ws2 = tmp_path / 'ws2'
    rc = sinks.pre_check(
        _dispatch_payload(_full_prompt(_FAM, off_policy, claim='C-002')),
        _min_paths(ws2))
    assert rc == 0, capsys.readouterr().err
    row = _dispatch_rows(ws2)[-1]
    assert row['recipe_id'] == off_policy
    assert row['recipe_source'] == 'declared'
    assert isinstance(row['recipe_propensity'], float)
    assert 0.0 < row['recipe_propensity'] < 1.0


# ---------------------------------------------------------------------------
# 2. settlement banks credit against recipe_id — never a worker narrative
# ---------------------------------------------------------------------------

def test_settlement_banks_credit_against_recipe_without_worker_narrative(
        tmp_path, capsys):
    """#695 T3: the dispatch records a recipe; a worker narrative then
    CLAIMS a different toolchain was used (the #881 tool_value pattern —
    worker-written ``steps:`` lines). The settlement (observe_settlement,
    the #678 trusted chain) banks its credit against the DISPATCH row's
    recipe_id: the narrative cannot move the bank, and the fold shows
    the credited arm."""
    from rlvr import q_cells, recipe_arms
    ws = tmp_path / 'ws'
    arms = recipe_arms.arm_ids_for(_FAM)
    declared = _draw(ws, _FAM)
    lying = next(a for a in arms if a != declared)

    rc = sinks.pre_check(_dispatch_payload(_full_prompt(_FAM, declared)),
                         _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    # the worker's own narrative claims a DIFFERENT toolchain — the
    # narrative channel the #881 table used to trust; the bank must not.
    runs = ws / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    (runs / 'worker-status-w-test.md').write_text(
        'steps:\n- executed recipe ' + lying + ' on the target\n',
        encoding='utf-8')

    bank = q_cells.observe_settlement(ws, 'C-001', 0.8)
    assert bank['matched'] and bank['appended'], bank
    settle = [r for r in _obs_rows(ws) if r.get('source') == 'settlement']
    assert len(settle) == 1, settle
    assert settle[0]['recipe_id'] == declared      # the dispatch row, not the prose
    assert settle[0]['recipe_propensity'] == bank['recipe_propensity']
    assert settle[0]['credit'] == 0.8
    fold = recipe_arms.arm_fold(ws)
    assert fold[declared]['success'] == 0.8
    assert fold[lying]['success'] == 0.0           # the narrative banked nothing


# ---------------------------------------------------------------------------
# 3. >= 3 arms per family; the floor weight is never deleted
# ---------------------------------------------------------------------------

def test_recipe_arms_floor_weight_never_deleted(tmp_path):
    """#695 T4: the registry carries >= 3 arms per registered family
    (cold-start static prior with gravity — overturnable, never policy).
    An arm hammered by failure mass keeps a strictly positive weight at
    THETA_FLOOR (floored, never zeroed — the PARK posture) and stays
    samplable; the other arms are never deleted to make room."""
    from rlvr import q_cells, recipe_arms
    for family, arm_ids in recipe_arms.ARMS_BY_FAMILY.items():
        assert len(arm_ids) >= 3, (family, arm_ids)
    ws = tmp_path / 'ws'
    arms = recipe_arms.arm_ids_for(_FAM)
    beaten, survivor = arms[0], arms[1]
    before = recipe_arms.arm_weights(ws, _FAM)
    prior = recipe_arms.ARMS_BY_ID[beaten].prior
    # brutal failure mass — 30 settled zeros against one arm
    for i in range(30):
        q_cells.append_observation(ws, _SEED_SIG, _FAM, 0.0,
                                   source='settlement', claim=f'f-{i}',
                                   recipe_id=beaten,
                                   recipe_source='declared')
    weights = recipe_arms.arm_weights(ws, _FAM)
    # floor-not-delete: every arm still present, still strictly positive
    assert set(weights) == set(arms)
    assert all(w > 0.0 for w in weights.values()), weights
    # the beaten arm is floored at prior * THETA_FLOOR, never zeroed
    assert weights[beaten] <= before[beaten]
    assert abs(weights[beaten]
               - prior * recipe_arms.THETA_FLOOR) < 1e-9
    # revivable + samplable: the floored arm still appears in draws
    hits = sum(
        1 for i in range(128)
        if recipe_arms.sample_recipe(
            ws, _FAM, rng=random.Random(i))['recipe_id'] == beaten)
    assert hits > 0, hits


# ---------------------------------------------------------------------------
# 4. no new REJECT surface for tool choice
# ---------------------------------------------------------------------------

def test_no_new_reject_surface_for_tool_choice(tmp_path, capsys):
    """#695 acceptance (c): deviation from the sampler draw is a
    recorded decision, never a gate — and an UNREGISTERED recipe is
    recorded too (propensity 0.0: the draw could never have chosen it),
    still never rejected. ``pre_check`` returns 0 in both cases and one
    ``recipe_deviation`` event per deviating dispatch lands in the
    unified log."""
    import event_taxonomy as et
    from rlvr import recipe_arms
    assert 'recipe_deviation' in et.EMIT_ACTIONS
    ws = tmp_path / 'ws'
    arms = recipe_arms.arm_ids_for(_FAM)
    off_policy = next(a for a in arms if a != _draw(ws, _FAM))

    rc = sinks.pre_check(_dispatch_payload(_full_prompt(_FAM, off_policy)),
                         _min_paths(ws))
    assert rc == 0, capsys.readouterr().err
    evs = _events(ws, 'recipe_deviation')
    assert len(evs) == 1, evs
    det = _detail(evs[0])
    assert det['declared'] == off_policy
    assert det['sampled'] != off_policy
    assert isinstance(det['propensity'], float)
    assert det['registered'] is True

    # an unregistered recipe: recorded, propensity 0.0, NEVER rejected
    # (fresh ws — the #690 barrier is workspace-global)
    ws2 = tmp_path / 'ws2'
    rc = sinks.pre_check(
        _dispatch_payload(
            _full_prompt(_FAM, 'not-a-registered-recipe', claim='C-003')),
        _min_paths(ws2))
    assert rc == 0, capsys.readouterr().err
    row = _dispatch_rows(ws2)[-1]
    assert row['recipe_id'] == 'not-a-registered-recipe'
    assert row['recipe_source'] == 'declared'
    assert row['recipe_propensity'] == 0.0
    det = _detail(_events(ws2, 'recipe_deviation')[-1])
    assert det['registered'] is False

    # the none-gap dispatch (an other(...) family — passes the #432
    # gate, has NO registered arms): pre-#695 byte-identity — the row
    # carries NO recipe keys at all (review-1: source "none" must not
    # trip the emit gate)
    ws3 = tmp_path / 'ws3'
    rc = sinks.pre_check(
        _dispatch_payload(
            _full_prompt('other(unknown approach)', None, claim='C-004')),
        _min_paths(ws3))
    assert rc == 0, capsys.readouterr().err
    row = _dispatch_rows(ws3)[-1]
    assert 'recipe_id' not in row
    assert 'recipe_propensity' not in row
    assert 'recipe_source' not in row


# ---------------------------------------------------------------------------
# 5. S2-shape replay: arm-level separation before any online switch
# ---------------------------------------------------------------------------

def test_replay_reports_arm_level_separation(tmp_path):
    """#695 T5: over recorded history the replay reruns the sampler
    (S2 shape — offline only, no online switch) and reports arm-level
    separation: one arm settled high, one low, and the disagreement
    rate between the recorded recipes and the current argmax arm."""
    from rlvr import q_cells, recipe_arms
    ws = tmp_path / 'ws'
    winner, loser = recipe_arms.arm_ids_for(_FAM)[:2]
    for i in range(6):
        q_cells.append_observation(
            ws, _SEED_SIG, _FAM, None, source='dispatch', claim=f'w-{i}',
            recipe_id=winner, recipe_propensity=1.0,
            recipe_source='declared')
        q_cells.append_observation(
            ws, _SEED_SIG, _FAM, 1.0, source='settlement', claim=f'w-{i}',
            recipe_id=winner)
        q_cells.append_observation(
            ws, _SEED_SIG, _FAM, None, source='dispatch', claim=f'l-{i}',
            recipe_id=loser, recipe_propensity=1.0,
            recipe_source='declared')
        q_cells.append_observation(
            ws, _SEED_SIG, _FAM, 0.0, source='settlement', claim=f'l-{i}',
            recipe_id=loser)
    rep = recipe_arms.replay_report(ws)
    assert rep['shape'] == 'S2'
    assert rep['rows'] == 12, rep
    fam = rep['families'][_FAM]
    assert fam['argmax'] == winner, fam
    assert fam['mean_credit'][winner] == 1.0
    assert fam['mean_credit'][loser] == 0.0
    # the 6 loser rows disagree with the current argmax -> rate 0.5
    assert abs(rep['disagreement_rate'] - 0.5) < 1e-9
