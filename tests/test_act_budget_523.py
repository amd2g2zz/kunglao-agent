# -*- coding: utf-8 -*-
"""Issue #523 G3 rerun finding — the act budget travels with the dispatch.

G3 matrix evidence (runs/e2e/e2e-20261007-01*, 6/6 BLOCKED): every
dispatched worker/verifier session ran until the 1800s subprocess cap
killed it — facts were being written (facts_citing=4 on some units) but
no act ever ENDED. The eval harness's exp5 M1 lesson applies verbatim:
the face that owns the cap must communicate the cap. These pins hold:

  1. the worker dispatch prompt names its exact kill time and the
     schedule discipline (facts incremental, deliverable before 70%,
     STATUS: DONE before the cap, killed-at-cap banks zero);
  2. the verifier prompt carries the same contract scoped to
     verification (verify ONLY, verification file before 70%);
  3. the settle face reads the act duration from act.detail (the
     ActRecord shape) — the G3 TIMEOUT rows banked r_incr=0.0 because
     the first wiring read a phantom act.duration_ms attribute, so the
     incremental reward lost its cost term.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "scripts" / "e2e"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SRC = (ROOT / "scripts" / "e2e" / "checkpoints.py").read_text(
    encoding="utf-8")


def test_worker_prompt_carries_the_act_budget():
    assert "ACT BUDGET" in SRC
    assert "{ladder_timeout_s}s" in SRC          # the exact kill time
    assert "KILLED" in SRC                        # unambiguous consequence
    assert "banks zero facts credit" in SRC       # the incentive line
    assert "before 70% of the budget" in SRC      # the schedule rule


def test_verifier_prompt_carries_the_scoped_budget():
    assert "verify ONLY" in SRC
    assert "{llm_faces.CLAUDE_ACT_TIMEOUT_S}s" in SRC
    assert "leaves the claim unverified" in SRC


def test_settle_reads_duration_from_act_detail():
    # the phantom-attribute bug: duration lives in act.detail, not on
    # the ActRecord itself
    assert 'act.detail or {}).get("duration_ms")' in SRC
    assert 'getattr(act, "duration_ms"' not in SRC
