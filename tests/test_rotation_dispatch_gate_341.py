# -*- coding: utf-8 -*-
"""Issue #341 — the discriminating-experiment dispatch gate (C).

When the rotation induction has flagged a claim (`runtime_value_rotation`
fired), a dispatch that just re-hooks and retries — the #341 failure loop —
must be REJECTED: the dispatch prompt must carry the experiment-template
marker `rotation-experiment:` (same enforcement style as `tool-catalog:` /
`remedy: decompose`), pointing at
references/re-library/dynamic/rotation-characterization.md.

Reviewer attack (c) pinned here: the REJECT keys on rotation-FLAGGED claims
ONLY — an unflagged claim dispatches freely without any marker.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HOOKS))

from worker_budget_gates import (  # noqa: E402
    ROTATION_MARKER,
    check_rotation_experiment,
    load_rotation_flags,
)


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _seed_flag(ws: Path, claim: str = "C-001",
               slot: str = "config-decrypt-key") -> None:
    """The rotation induction's state file with one fired flag (the exact
    shape scripts/rotation_induction.py persists)."""
    (ws / "runs" / ".rotation-induction.json").write_text(json.dumps({
        "schema": 1,
        "rotations": {
            f"{claim}|{slot}": {
                "fingerprints": ["b" * 64, "c" * 64],
                "fired": True,
                "hypothesis_id": "H-001",
                "note": "notes/N-001-rotation.md",
            },
        },
    }, ensure_ascii=False), encoding="utf-8")


def _paths(ws: Path) -> dict:
    return {"workspace": str(ws)}


# =====================================================================
# load_rotation_flags
# =====================================================================

def test_load_flags_reads_fired_rotations(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_flag(ws)
    flags = load_rotation_flags(ws)
    assert flags == {"C-001": ["config-decrypt-key"]}


def test_load_flags_absent_state_is_empty(tmp_path):
    ws = _mk_ws(tmp_path)
    assert load_rotation_flags(ws) == {}


def test_load_flags_skips_unfired_rows(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_flag(ws)
    data = json.loads((ws / "runs" / ".rotation-induction.json")
                      .read_text(encoding="utf-8"))
    data["rotations"]["C-002|license-token"] = {
        "fingerprints": ["d" * 64], "fired": False}
    (ws / "runs" / ".rotation-induction.json").write_text(
        json.dumps(data), encoding="utf-8")
    flags = load_rotation_flags(ws)
    assert flags == {"C-001": ["config-decrypt-key"]}


def test_load_flags_corrupt_state_degrades_to_empty(tmp_path):
    ws = _mk_ws(tmp_path)
    (ws / "runs" / ".rotation-induction.json").write_text(
        "{not json", encoding="utf-8")
    assert load_rotation_flags(ws) == {}


# =====================================================================
# check_rotation_experiment
# =====================================================================

def test_unflagged_claim_passes_without_marker(tmp_path):
    """Reviewer attack (c): the gate NEVER fires on unflagged claims."""
    ws = _mk_ws(tmp_path)
    ok, msg = check_rotation_experiment(_paths(ws), "C-009", "dispatch text")
    assert ok and msg == ""


def test_flagged_claim_without_marker_rejects_with_guidance(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_flag(ws)
    ok, msg = check_rotation_experiment(_paths(ws), "C-001", "re-hook the key")
    assert not ok
    assert "C-001" in msg
    assert "config-decrypt-key" in msg
    assert ROTATION_MARKER in msg
    assert "rotation-characterization" in msg
    assert "rotation-characterization.md" in msg


def test_flagged_claim_with_marker_passes(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_flag(ws)
    ok, _ = check_rotation_experiment(
        _paths(ws), "C-001",
        f"{ROTATION_MARKER} rotation-characterization\nplan: double capture")
    assert ok


def test_marker_without_value_still_keys_the_gate(tmp_path):
    """Same enforcement face as `tool-catalog:`: the marker KEY is the
    mechanical check; the value is guidance for the worker."""
    ws = _mk_ws(tmp_path)
    _seed_flag(ws)
    ok, _ = check_rotation_experiment(
        _paths(ws), "C-001", f"{ROTATION_MARKER} see reference card")
    assert ok


def test_missing_workspace_paths_fail_open(tmp_path):
    """No workspace in paths (non-dispatch callers) — the gate stays silent
    rather than crashing the checks loop."""
    ok, _ = check_rotation_experiment({}, "C-001", "prompt")
    assert ok


def test_none_claim_id_is_never_flagged(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_flag(ws)
    ok, _ = check_rotation_experiment(_paths(ws), None, "prompt")
    assert ok


# =====================================================================
# pre_check wiring: the REJECT actually fires on a real dispatch payload
# =====================================================================

_ENVELOPE = ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", '
             '"tier": 1, "tools": ["grep"], "agent": "w-test"}}')


def _payload(prompt: str) -> dict:
    return {"tool_input": {"name": "w-test", "description": "", "prompt": prompt}}


def test_pre_check_rejects_rotation_flagged_dispatch_without_marker(
        tmp_path, capsys):
    from worker_budget_sinks import pre_check
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    _seed_flag(ws)
    rc = pre_check(_payload(f"{_ENVELOPE}\nfacts-snapshot: 2 facts"),
                   {"workspace": str(ws), "state": ws / "analysis_state.txt",
                    "register": ws / "claim-register.yaml",
                    "deps": ws / "claim_deps.yaml",
                    "task_spec": ws / "task_spec.yaml"})
    captured = capsys.readouterr()
    assert rc == 2, captured.err
    assert "REJECT rotation" in captured.err
    assert ROTATION_MARKER in captured.err


def test_pre_check_allows_rotation_flagged_dispatch_with_marker(
        tmp_path, capsys):
    from worker_budget_sinks import pre_check
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    _seed_flag(ws)
    rc = pre_check(_payload(
        f"{_ENVELOPE}\nfacts-snapshot: 2 facts\n"
        f"{ROTATION_MARKER} rotation-characterization"),
        {"workspace": str(ws), "state": ws / "analysis_state.txt",
         "register": ws / "claim-register.yaml",
         "deps": ws / "claim_deps.yaml",
         "task_spec": ws / "task_spec.yaml"})
    assert rc == 0, capsys.readouterr().err
