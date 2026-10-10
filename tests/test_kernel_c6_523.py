#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_kernel_c6_523.py — the G2 kernel dispatcher's four surgical
replacements (#523 G2). Each kills an observed matrix3 death class:

  K1  Luby timeout: per-claim retry maps to the Luby sequence x base —
      no more fixed 1800s burn on a doomed act (P1)
  K2  settled-cell filter: meta-arms with settled posteriors (p<0.1 or
      p>0.9) are not proposed for worker dispatch (DAPO zero-info skip)
  K3  vocabulary immunity: SATURATED / INVALID / unknown decisions fall
      to the COMPUTED delivery check (no-open-claims -> deliver), never
      the sleep-forever spin (P4/AD1)
  K4  key release on settlement: the verifier vkey is discarded when the
      act settles regardless of promotion outcome (RC3 success-forever)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import checkpoints as cp  # noqa: E402


# ------------------------------------------------------------------ K1

def test_luby_sequence():
    # Luby et al. 1993: 1,1,2,1,1,2,4,1,1,2,1,1,2,4,8...
    seq = [cp._luby_units(i) for i in range(15)]
    assert seq == [1, 1, 2, 1, 1, 2, 4, 1, 1, 2, 1, 1, 2, 4, 8], seq


def test_luby_timeout_scales_with_retry():
    base = cp.LUBY_BASE_S
    assert cp._luby_timeout_s(0) == base
    assert cp._luby_timeout_s(2) == 2 * base
    assert cp._luby_timeout_s(6) == 4 * base


# ------------------------------------------------------------------ K2

def test_settled_cell_filter_skips_extreme_posteriors():
    rows = ([{"method_family": "static-decompile", "credit": 1.0,
              "fingerprint": "fp"}] * 12)
    fams = ["static-decompile", "hypothesis-falsification"]
    weights = cp._settled_filtered_prior(rows, fams, "fp")
    # static-decode is settled-success (12/12): its weight floors to the
    # exploration minimum, the unproven arm carries the proposal mass
    assert weights["hypothesis-falsification"] > \
        weights["static-decompile"], weights


# ------------------------------------------------------------------ K3

def test_unknown_decision_falls_to_computed_delivery(tmp_path):
    """SATURATED/INVALID with all claims closed -> deliver (break), not
    the sleep-forever spin (the P4 death)."""
    assert cp._kernel_flow_for_decision("SATURATED", all_open=False) \
        == "deliver"
    assert cp._kernel_flow_for_decision("INVALID", all_open=False) \
        == "deliver"
    assert cp._kernel_flow_for_decision("SATURATED", all_open=True) \
        == "wait"
    # known dispatch vocabulary still routes through
    assert cp._kernel_flow_for_decision("DISPATCH", all_open=True) \
        == "dispatch"
    assert cp._kernel_flow_for_decision("CONVERGED", all_open=True) \
        == "break"


# ------------------------------------------------------------------ K4

def test_verifier_key_released_on_settlement(tmp_path):
    """A settled verifier act frees its vkey even when promotion was
    refused (the RC3 success-forever death: re-decide forever, dispatch
    nothing, burn budget)."""
    from e2e import llm_faces, model  # noqa: E402

    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-004\n  status: OPEN\n", encoding="utf-8")
    state = model.RunState(
        run_id="r", unit="u", family="release", repo=str(ROOT),
        task_dir=str(ROOT), ws=str(ws), evidence_dir=str(tmp_path / "ev"),
        budget_seconds=10, llm_mode="dry", started_ts="t",
        started_monotonic=0.0,
        anchors={"goal_verbatim": "g", "success_criterion": "s",
                 "verification_method": "reproduction"},
        method_family="static-decompile")

    class _Face:
        def launch_dispatch(self, request):
            return "h"

    ctx = cp.RunContext(state=state, runner=object(), face=_Face(),
                        clock=object(), sleep_fn=lambda _s: None)
    dispatched = {"V:C-004"}
    act = llm_faces.ActRecord(claim="C-004", mode="auto",
                              outcome="DISPATCHED", detail={})
    detail = {"acts": []}
    # the landing path settles the act AND releases the verifier key
    cp._land_dispatch(ctx, "C-004", act, dispatched, detail)
    assert "V:C-004" not in dispatched, \
        "settlement must release the in-flight key (RC3)"
