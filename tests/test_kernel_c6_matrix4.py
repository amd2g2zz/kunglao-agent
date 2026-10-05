# -*- coding: utf-8 -*-
"""matrix4 K3-root pins: a stop word over a SETTLED register is a
delivery, never a terminal stop.

matrix4 field evidence (2026-10-05, dev d177a391): three of six units
died at the convergence gate with their work DONE —
  asl  BLOCKED with PROVEN 5/5,      top_priorities []
  wac  BLOCKED with PROVEN 4 + DEFERRED 1 (zero OPEN), priorities []
  awa  BLOCKED with PROVEN 5/5,      top_priorities []
The workers solved the units (facts -> verify -> promote all landed);
the dispatcher honored the engine's BLOCKED string as terminal before
the computed delivery check ever ran, throwing away the finished work
one gate short of the C7 verdict.

The fix at the root: every stop word routes through the computed
delivery check — a settled register delivers (the verdict face is the
arbiter), open work still stops. A DEFERRED claim is a decline, not
actionable work (the engine's own empty ranking agrees) — it does not
keep a register open.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

from e2e import checkpoints as cp  # noqa: E402


def test_blocked_over_settled_register_delivers():
    """The asl/awa death verbatim: 5/5 PROVEN + BLOCKED -> deliver."""
    assert cp._kernel_flow_for_decision("BLOCKED", all_open=False) \
        == "deliver"


def test_blocked_with_open_work_still_stops():
    """Legitimately blocked (open claims, cannot proceed) unchanged."""
    assert cp._kernel_flow_for_decision("BLOCKED", all_open=True) \
        == "stop"


def test_park_over_settled_register_delivers():
    assert cp._kernel_flow_for_decision("PARK", all_open=False) \
        == "deliver"


def test_deferred_is_not_actionable(tmp_path):
    """The wac shape: PROVEN 4 + DEFERRED 1 counts ZERO open claims."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-004\n"
        "    status: PROVEN\n"
        "  - id: C-005\n"
        "    status: DEFERRED\n",
        encoding="utf-8")

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.ws = ws
    assert cp._open_claim_count(ctx) == 0


def test_open_still_counts(tmp_path):
    """Unchanged semantics: an OPEN claim keeps the register open."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-004\n"
        "    status: PROVEN\n"
        "  - id: C-005\n"
        "    status: OPEN\n",
        encoding="utf-8")

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.ws = ws
    assert cp._open_claim_count(ctx) == 1
