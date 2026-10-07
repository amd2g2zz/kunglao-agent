# -*- coding: utf-8 -*-
"""tests/test_ws2_declared_rides_545.py — WS2 (#545) deliverable 3: the
declared-family bypass fix. A declared family no longer skips the sampler
silently: the sampler still runs (the score face — candidates ride the
receipt), the DECLARED family wins the envelope, and the receipt records
propensity 1.0 (the declared proposal is π≈1 — correctly re-weighted for
OPE; policy_compare's `skipped_no_propensity` gap closes).

The censored-review data (PR #549) showed the practical cost of the
bypass: 0/50 real transition rows carry a propensity field — every
dispatch was declared-path, so the DR-OPE record never existed in
practice.

Pins:

  1. declared dispatch: envelope carries candidates INCLUDING the
     declared family + propensity 1.0; the transition row banks that
     propensity (the OPE record completes end-to-end).
  2. sampler failure on the declared path degrades to the minimal honest
     receipt (propensity 1.0, the declared family as the sole candidate)
     — never envelope-less, never a skipped OPE row.
  3. undeclared dispatch (control): the MC propensity face unchanged.
  4. the settle face records the store row with the dispatch's arm_key
     and the banked propensity (the cross-task record is keyed).
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
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "store"))
    ctx = _ctx(ws, FAMILY)
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family == FAMILY, "the declared family wins"
    env = _envelopes(ws)[-1]
    receipt = env["envelope"]
    assert receipt["propensity"] == 1.0, \
        "the declared proposal is deterministic: pi = 1.0 for OPE"
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
    trans = [json.loads(line) for line in
             (ws / "runs" / "transitions.jsonl")
             .read_text(encoding="utf-8").splitlines() if line.strip()]
    assert trans and trans[-1].get("propensity") == 1.0, \
        "the transition row banks the declared propensity (DR-OPE record)"
    rows = strategy_store.load_rows(ws=None)
    assert rows and rows[-1]["propensity"] == 1.0
    assert rows[-1]["arm_key"] == f"{FAMILY}|facts_snapshot|none|1", \
        "the store row is keyed by the dispatch's 4-dim arm_key"
    assert rows[-1]["provenance"]["dispatch_id"] == "C-004"


def test_sampler_failure_still_records_propensity_1(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "store"))
    ctx = _ctx(ws, FAMILY)
    monkeypatch.setattr(checkpoints, "_sample_envelope_family",
                        lambda *a, **k: ("", None))
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family == FAMILY
    env = _envelopes(ws)[-1]
    receipt = env["envelope"]
    assert receipt["propensity"] == 1.0, \
        "even with the sampler down, the OPE record rides (pi = 1.0)"
    assert FAMILY in (receipt.get("candidates") or {}), \
        "the minimal honest receipt names the declared candidate"


def test_undeclared_path_still_uses_the_mc_propensity(tmp_path, monkeypatch):
    ws = _ws(tmp_path)
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "store"))
    ctx = _ctx(ws, "")  # no declaration -> the sampler decides
    request, _handle = checkpoints._launch_dispatch(ctx, "C-004", set())
    assert request.method_family, "the sampler picked a family"
    receipt = _envelopes(ws)[-1]["envelope"]
    assert receipt.get("propensity") is not None
    assert not receipt.get("declared"), \
        "the sampled path keeps its MC propensity, never the forced 1.0"
    assert q_cells.JSONLQStore(ws).observations(), \
        "the dispatch row is recorded either way"


def test_settle_unmatched_dispatch_writes_no_store_row(
        tmp_path, monkeypatch):
    """No pending q-cell dispatch row -> no family attribution -> the
    honest gap: no store row, never a fabricated bucket."""
    ws = _ws(tmp_path)
    store = tmp_path / "store"
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store))
    ctx = _ctx(ws, "")
    monkeypatch.setattr(checkpoints, "_sample_envelope_family",
                        lambda *a, **k: ("", None))
    # a settle with NO launch at all (no dispatch row, no transition):
    checkpoints._land_dispatch(
        ctx, "C-404",
        llm_faces.ActRecord(claim="C-404", mode="auto", outcome="TIMEOUT",
                            detail={}),
        set(), {"acts": []})
    assert strategy_store.load_rows(ws=None) == [], \
        "unmatched settlements never fabricate store rows"
