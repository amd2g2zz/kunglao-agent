# -*- coding: utf-8 -*-
"""tests/test_init_marker_625.py — #625: init-completeness must survive YAML edits.

RED: init_complete() keyed on a text substring in claim-register.yaml — any
rewrite (formatter/linter/write_guard shadow/手工) of that line silently
dropped completeness with no recovery (worse: re-init overwrote operator
claims without backup). Adjudicated fix (方案 A): a dedicated
.kunglao-init.json state file is the PRIMARY truth (state_hash / type /
seed_count / ts); the YAML comment marker stays as a legacy fallback
(double-read for one version window).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import init_state  # noqa: E402


def _ws_with_yaml_marker(tmp_path: Path, ptype="android") -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "analysis_state.txt").write_text(f"# stub\nproject_type={ptype}\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n# [initialized] kunglao-init state_hash=abc seeds=3\n",
        encoding="utf-8")
    return ws


def test_state_file_is_primary_truth(tmp_path):
    """Marker JSON present + YAML marker stripped (editor rewrite) → still complete."""
    ws = _ws_with_yaml_marker(tmp_path)
    init_state.write_init_marker(ws, state_hash="abc", project_type="android", seed_count=3)
    (ws / "claim-register.yaml").write_text("claims:\n  - id: C-001\n", encoding="utf-8")
    ok, detail = init_state.init_complete(ws)
    assert ok, f"state file must carry completeness past YAML edits: {detail}"


def test_yaml_marker_still_fallback(tmp_path):
    """No state file (legacy workspace) + intact YAML marker → complete (back-compat)."""
    ws = _ws_with_yaml_marker(tmp_path)
    ok, _ = init_state.init_complete(ws)
    assert ok


def test_neither_source_fails_clean(tmp_path):
    """No state file + no YAML marker → incomplete with actionable detail."""
    ws = _ws_with_yaml_marker(tmp_path)
    (ws / "claim-register.yaml").write_text("claims:\n  - id: C-001\n", encoding="utf-8")
    ok, detail = init_state.init_complete(ws)
    assert not ok
    assert "not initialized" in detail or "missing" in detail


def test_state_file_shape(tmp_path):
    """write_init_marker persists state_hash/type/seed_count/ts (JSON, ISO8601 Z)."""
    ws = _ws_with_yaml_marker(tmp_path)
    init_state.write_init_marker(ws, state_hash="deadbeef", project_type="windows", seed_count=2)
    data = json.loads((ws / ".kunglao-init.json").read_text(encoding="utf-8"))
    assert data["state_hash"] == "deadbeef"
    assert data["project_type"] == "windows"
    assert data["seed_count"] == 2
    assert "ts" in data and data["ts"].endswith("Z")


def test_invalid_type_in_state_file_fails(tmp_path):
    """State file carries completeness, but type validation still applies
    (hand-written bad state file — write_init_marker itself fail-louds)."""
    import json as _json
    ws = _ws_with_yaml_marker(tmp_path)
    (ws / ".kunglao-init.json").write_text(
        _json.dumps({"state_hash": "x", "project_type": "toaster",
                     "seed_count": 3, "ts": "2026-08-25T00:00:00Z"}), encoding="utf-8")
    ok, detail = init_state.init_complete(ws)
    assert not ok
    assert "invalid project_type" in detail
