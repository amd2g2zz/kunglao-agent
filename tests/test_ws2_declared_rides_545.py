# -*- coding: utf-8 -*-
"""Declared dispatch receipts and keyed settlement.

#1033 supersedes the old pi=1 and declaration-injected-candidate assumptions.
A declared action remains identified, behavior probability stays unknown,
and an outage never fabricates candidate support. Direct MC is deferred to #1034.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import checkpoints, llm_faces, model  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402 — #721 read face
from rlvr import q_cells  # noqa: E402
from rlvr import strategy_store  # noqa: E402

FAMILY = "static-decompile"


def _ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n", encoding="utf-8")
    return ws


def _ctx(ws, declared: str):
    state = model.RunState(
        run_id="r", unit="u", family="release", repo=str(ROOT),
        task_dir=str(ROOT), ws=str(ws),
        evidence_dir=str(ws.parent / "ev"),
        budget_seconds=10, llm_mode="dry", started_ts="t",
        started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"},
        method_family=declared)
    face = type("_Face", (), {"launch_dispatch": staticmethod(
        lambda request: "h")})()
    return checkpoints.RunContext(state=state, runner=object(), face=face,
                                  clock=object(), sleep_fn=lambda _s: None)


def _envelopes(ws) -> list[dict]:
    out = []
    p = ws / "runs" / "logs" / "e2e-audit.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if "method_family_recorded" not in line:
            continue
        e = json.loads(line)
        d = e.get("detail")
        if isinstance(d, str):
            d = json.loads(d)
        out.append(d)
    return out


def test_declared_family_records_propensity_1_and_rides_candidates(
        tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    from rlvr import priors
    (ws / "task_spec.yaml").write_text("family: static-replay\n")
    priors.seed_intake_prior(ws, families=[FAMILY])
    ctx = _ctx(ws, FAMILY)
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family == FAMILY, "the declared family wins"
    env = _envelopes(ws)[-1]
    receipt = env["envelope"]
    assert receipt["propensity"] is None
    assert receipt["probability_source"] == "unknown"
    assert receipt["actual_method_family"] == FAMILY
    cands = receipt.get("candidates") or {}
    assert FAMILY in cands, \
        "the declared family enters the candidates with its P_LLM weight"

    # the settle face completes the OPE record end-to-end
    for fid in ("F001", "F002"):
        (ws / "facts" / f"{fid}.md").write_text(
            "---\nclaim_id: C-004\n---\nbody\n", encoding="utf-8")
    checkpoints._land_dispatch(
        ctx, "C-004",
        llm_faces.ActRecord(claim="C-004", mode="auto",
                            outcome="DISPATCHED", detail={}),
        set(), {"acts": []})
    trans = [r for r in ir.read_transitions(ws)
             if r.get("dispatch_id") == "C-004"]
    assert trans and trans[-1].get("propensity") is None
    rows = strategy_store.load_rows(ws)
    assert rows and rows[-1]["propensity"] is None
    assert rows[-1]["arm_key"] == f"{FAMILY}|facts_snapshot|none|1", \
        "the store row is keyed by the dispatch's 4-dim arm_key"
    assert rows[-1]["provenance"]["dispatch_id"] == "C-004"


def test_sampler_failure_still_records_propensity_1(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    ctx = _ctx(ws, FAMILY)
    monkeypatch.setattr(checkpoints, "_sample_envelope_family",
                        lambda *a, **k: ("", None))
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family == FAMILY
    env = _envelopes(ws)[-1]
    receipt = env["envelope"]
    assert receipt["propensity"] is None
    assert receipt["probability_source"] == "unknown"
    assert receipt["actual_method_family"] == FAMILY
    assert receipt.get("sampled_family") is None
    assert receipt["candidates"] == {}


def test_undeclared_path_stamps_the_exact_selection_law(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    from rlvr import priors
    (ws / "task_spec.yaml").write_text("family: static-replay\n")
    priors.seed_intake_prior(ws, families=[FAMILY])
    ctx = _ctx(ws, "")  # no declaration -> the sampler decides
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family, "the sampler picked a family"
    receipt = _envelopes(ws)[-1]["envelope"]
    assert receipt.get("propensity") is not None
    assert receipt.get("probability_source") == "selection_law_exact"
    assert not receipt.get("declared"), \
        "the sampled path keeps its exact selection-law propensity, never the forced 1.0"
    assert q_cells.JSONLQStore(ws).observations(), \
        "the dispatch row is recorded either way"


def test_settle_unmatched_dispatch_writes_no_store_row(
        tmp_path, monkeypatch):
    """No pending q-cell dispatch row -> no family attribution -> the
    honest gap: no store row, never a fabricated bucket."""
    ws = _ws(tmp_path)
    ctx = _ctx(ws, "")
    monkeypatch.setattr(checkpoints, "_sample_envelope_family",
                        lambda *a, **k: ("", None))
    # a settle with NO launch at all (no dispatch row, no transition):
    checkpoints._land_dispatch(
        ctx, "C-404",
        llm_faces.ActRecord(claim="C-404", mode="auto", outcome="TIMEOUT",
                            detail={}),
        set(), {"acts": []})
    assert strategy_store.load_rows(ws) == [], \
        "unmatched settlements never fabricate store rows"


def test_executor_records_adopted_choice_with_a_dispatch_identity(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    ctx = _ctx(ws, "")
    receipt = {"family": FAMILY, "prior_source": "history",
               "candidates": {FAMILY: {"weight": 1.0}},
               "candidate_sources": {FAMILY: ["history"]}}
    monkeypatch.setattr(checkpoints, "_sample_envelope_family",
                        lambda ws: (FAMILY, receipt))
    request, _ = checkpoints._launch_dispatch(ctx, "C-004", set())
    row = q_cells.dispatch_rows(ws)[-1]
    assert row["method_source"] == "sampled-adoption"
    assert row["dispatch_id"] == request.dispatch_id
    assert ir.current_dispatch_id(ws, "C-004") == request.dispatch_id
    assert row["propensity"] == 1.0
    assert row["probability_source"] == "selection_law_exact"
    assert _envelopes(ws)[-1]["envelope"]["dispatch_id"] == request.dispatch_id
    checkpoints._land_dispatch(
        ctx, "C-004", llm_faces.ActRecord(
            claim="C-004", mode="auto", outcome="DISPATCHED", detail={}),
        set(), {"acts": []}, attempt_id=request.launch_id,
        dispatch_id=request.dispatch_id)
    assert q_cells.banked_mass(ws, request.dispatch_id)[2] == 1


def test_executor_rejects_a_revoked_method_before_recording(tmp_path):
    ws = _ws(tmp_path)
    (ws / "task_spec.yaml").write_text(
        "constraints:\n  dynamic_re: forbidden\n", encoding="utf-8")
    ctx = _ctx(ws, "dynamic-trace")
    request, _ = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request is None
    assert q_cells.dispatch_rows(ws) == []


def test_executor_replaying_a_result_does_not_bank_twice(tmp_path):
    ws = _ws(tmp_path)
    request, _ = checkpoints._launch_dispatch(_ctx(ws, FAMILY), "C-004", set())
    act = llm_faces.ActRecord(
        claim="C-004", mode="auto", outcome="DISPATCHED", detail={})
    ctx = _ctx(ws, FAMILY)
    for _ in range(2):
        checkpoints._land_dispatch(
            ctx, act.claim, act, set(), {"acts": []},
            attempt_id=request.launch_id, dispatch_id=request.dispatch_id)
    assert q_cells.banked_mass(ws, request.dispatch_id)[2] == 1
