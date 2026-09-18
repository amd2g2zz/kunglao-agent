# -*- coding: utf-8 -*-
"""Issue 250 — plan gate per-step contingency (piece 1 wiring).

RED target: `hooks/worker_budget_gates.check_worker_plan` accepts a
re-dispatch plan whose enumerated steps carry NO if-fails branch today;
after this change the gate REJECTS it (the linear happy-path plan is no
longer a passing shape). The #239 v2 contract is untouched: first dispatch
stays plan-free, legacy inline plans (zero enumerated entries) pass.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HOOKS = Path(__file__).parent.parent / "hooks"
if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))

import worker_budget_gates as wbg  # noqa: E402

TS = "2026-09-10T01:00:00Z"  # seeded prior approved dispatch


def _min_paths(ws: Path) -> dict:
    ws.mkdir(parents=True, exist_ok=True)
    return {
        'workspace': str(ws),
        'state': ws / 'analysis_state.txt',
        'register': ws / 'claim-register.yaml',
        'deps': ws / 'claim_deps.yaml',
        'task_spec': ws / 'task_spec.yaml',
    }


def _seed_prior_dispatch(ws: Path) -> None:
    (ws / 'runs').mkdir(parents=True, exist_ok=True)
    (ws / 'runs' / '.dispatch-anchor-C001.jsonl').write_text(
        json.dumps({'ts': TS, 'claim': 'C-001', 'agent': 'w-test'}) + '\n',
        encoding='utf-8')


LINEAR = (
    f"dispatch-anchor: {TS}\n"
    "goal: prove sub_1234 dispatch mode\n"
    "preflight: verify tool signatures\n"
    "steps:\n"
    "  1. run static xref on sub_1234 -> expect caller list\n"
    "  2. trace dispatch table -> expect handler address\n"
    "fallback: report blocker\n"
)

BRANCHED = (
    f"dispatch-anchor: {TS}\n"
    "goal: prove sub_1234 dispatch mode\n"
    "preflight: verify tool signatures\n"
    "steps:\n"
    "  1. run static xref on sub_1234 -> expect caller list\n"
    "     if-fails: if xref index empty -> scan for RegisterNatives\n"
    "  2. trace dispatch table -> expect handler address\n"
    "     if-fails: if trace refused -> emulate via qiling\n"
    "fallback: report blocker\n"
)


def _plan_ws(plan_text: str) -> tuple[Path, dict]:
    import tempfile
    ws = Path(tempfile.mkdtemp())
    paths = _min_paths(ws)
    _seed_prior_dispatch(ws)
    (ws / 'runs' / 'plan-C001.md').write_text(plan_text, encoding='utf-8')
    return ws, paths


def test_linear_enumerated_plan_rejected_on_redispatch():
    _ws, paths = _plan_ws(LINEAR)
    ok, reason = wbg.check_worker_plan(paths, 'C-001')
    assert not ok, f"linear happy-path plan must be rejected; got: {reason}"
    assert 'if-fails' in reason


def test_branched_plan_passes_redispatch():
    _ws, paths = _plan_ws(BRANCHED)
    ok, reason = wbg.check_worker_plan(paths, 'C-001')
    assert ok, f"branched plan with provenance must pass; got: {reason}"


def test_first_dispatch_still_plan_free():
    import tempfile
    ws = Path(tempfile.mkdtemp())
    paths = _min_paths(ws)
    ok, _reason = wbg.check_worker_plan(paths, 'C-001')
    assert ok  # no anchor log rows -> first dispatch, gate not armed


def test_legacy_inline_plan_unaffected():
    text = (f"dispatch-anchor: {TS}\n"
            "goal: decode strings\nsteps: dump strings\nfallback: xxd walk\n")
    _ws, paths = _plan_ws(text)
    ok, reason = wbg.check_worker_plan(paths, 'C-001')
    assert ok, f"legacy inline plan (no enumerated steps) must pass; got: {reason}"


def test_bare_if_fails_label_rejected():
    text = (f"dispatch-anchor: {TS}\n"
            "goal: g\n"
            "steps:\n"
            "  1. step one -> expect out\n"
            "     if-fails:\n"
            "fallback: f\n")
    _ws, paths = _plan_ws(text)
    ok, reason = wbg.check_worker_plan(paths, 'C-001')
    assert not ok
    assert 'if-fails' in reason
