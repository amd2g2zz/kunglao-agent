# -*- coding: utf-8 -*-
"""Issue #523 (smoke pilot 2026-10-06) — the loop's completion contract must
reach the session BEFORE it blocks convergence, and the loop's hooks must not
crash on their own substrate.

Pilot field evidence (runs/exp-cc-rl/smoke-kunglao-1usd, 3/3 sessions): every
workspace carried a correct deliverable (checker 3/3 PASS) yet every decide
tick returned BLOCKED — goal-operationalization.yaml stayed draft:true and no
oracle case was armed, while NO always-in-context face (workspace CLAUDE.md
template, session constitution) named the file. The sessions never learned
what convergence wanted and ran to the wall (3/3 SIGKILL, 0/3 completion).

Four faces are pinned here:
  1. the session constitution carries the PRE-DISPATCH CONTRACT
     (goal_operationalization.py pass + oracle arming via oracle_runner.py)
     and the BLOCKED semantics cover the verification-undeclared case;
  2. the workspace template names goal-operationalization.yaml and its
     convergence-blocking role;
  3. heartbeat exposes _parse_hb_ts — hooks/heartbeat_touch.py:144 calls it
     through the heartbeat module and the pilot logged AttributeError on
     every tool call (the liveness sidecar pulse never landed);
  4. infeasible_signal treats an absent runs/infeasible-state.json as the
     normal cold state (no warn) and keeps the warn for real failures.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import heartbeat  # noqa: E402
import heartbeat_loop_prompt as hlp  # noqa: E402
import infeasible_signal as infeas  # noqa: E402

TEMPLATE = ROOT / "templates" / "CLAUDE.md.base.tmpl"


# ---- face 1: the session constitution -----------------------------------

def test_constitution_carries_pre_dispatch_contract(tmp_path):
    """The once-per-session constitution names BOTH pre-dispatch legs:
    the operationalization validator AND the oracle arming runner —
    without them the pilot's sessions had no in-context path to
    CONVERGED."""
    text = hlp.constitution(str(tmp_path))
    assert "PRE-DISPATCH CONTRACT" in text
    assert "goal-operationalization.yaml" in text
    assert "goal_operationalization.py" in text
    assert "oracle_runner.py" in text
    assert "--stamp-dispatch" in text
    # the BLOCKED-forever clause is the load-bearing warning
    assert "draft: true" in text


def test_constitution_blocked_covers_verification_undeclared(tmp_path):
    """BLOCKED semantics must cover the undeclared-verification variant —
    the pilot's BLOCKED had ZERO open claims, so 'reactivate the failed
    claim' pointed at nothing."""
    text = hlp.constitution(str(tmp_path))
    assert "verification-undeclared" in text
    assert "PRE-DISPATCH CONTRACT" in text  # the action it names


def test_constitution_paths_resolve():
    """The contract's named scripts must exist at the paths the
    constitution prints (a phantom path in the constitution is a
    guaranteed dead instruction)."""
    import re
    text = hlp.constitution("/tmp/ws")
    for match in re.findall(r"`(python [^`]+\.py)", text):
        assert Path(match.split(" ", 1)[1]).is_file(), match


# ---- face 2: the workspace template --------------------------------------

def test_template_names_goal_operationalization():
    """The state-file table + the loop-enforcement block both name the
    file — the table so the model knows it exists, the block so it knows
    convergence refuses while it is unaudited."""
    text = TEMPLATE.read_text(encoding="utf-8")
    assert text.count("goal-operationalization.yaml") >= 2
    assert "goal_operationalization.py" in text
    assert "oracle_runner.py" in text
    assert "#147" in text


# ---- face 3: heartbeat exposes the touch hook's parser -------------------

def test_heartbeat_exposes_parse_hb_ts():
    """hooks/heartbeat_touch.py:144 calls hbmod._parse_hb_ts — the
    re-export is the fix for the pilot's per-tool-call AttributeError."""
    assert callable(getattr(heartbeat, "_parse_hb_ts", None))
    ts = heartbeat._parse_hb_ts("2026-10-06T03:39:45Z")
    assert ts is not None and ts.tzinfo is not None
    assert ts == datetime(2026, 10, 6, 3, 39, 45,
                          tzinfo=timezone.utc)
    assert heartbeat._parse_hb_ts("not-a-timestamp") is None
    assert heartbeat._parse_hb_ts("") is None


# ---- face 4: infeasible cold state is silent ------------------------------

def test_infeasible_load_state_cold_is_silent(tmp_path, monkeypatch):
    """An absent state file is the pre-first-signal state — no warn row.
    A corrupted/unreadable file stays a warnable anomaly."""
    warns: list[tuple[str, str]] = []
    monkeypatch.setattr(infeas, "warn",
                        lambda op, reason: warns.append((op, reason)))
    assert infeas._load_state(tmp_path) == {}
    assert warns == []
    state = tmp_path / "runs" / "infeasible-state.json"
    state.parent.mkdir()
    state.write_text("{not json", encoding="utf-8")
    assert infeas._load_state(tmp_path) == {}
    assert len(warns) == 1 and warns[0][0] == "_load_state"
