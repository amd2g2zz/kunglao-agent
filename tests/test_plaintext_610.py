# -*- coding: utf-8 -*-
"""tests/test_plaintext_610.py — #610: plain-text output must not crash.

RED: priority_ratio.py plain-text branch iterated the to_dict() dicts with
attribute access (a.claim_id) → AttributeError. Adjudicated fix (方案 A):
iterate the original typed `actions`; keep `out` for --json only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import priority_ratio as pr  # noqa: E402


def _make_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-001", "status": "OPEN", "statement": "s1"},
            {"id": "C-002", "status": "OPEN", "statement": "s2"},
        ]}), encoding="utf-8")
    (ws / "claim_deps.yaml").write_text("depends_on: {}\n", encoding="utf-8")
    facts = ws / "facts"
    facts.mkdir()
    (facts / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")
    return ws


def test_plaintext_output_does_not_crash(tmp_path, capsys):
    """#610: default (non---json) run must print a table, not raise AttributeError."""
    ws = _make_ws(tmp_path)
    rc = pr.main([str(ws)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "C-001" in out and "score=" in out


def test_plaintext_empty_result_placeholder(tmp_path, capsys):
    """No dispatchable claims → the '(no dispatchable claims)' placeholder, still exit 0."""
    ws = _make_ws(tmp_path)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-001", "status": "PROVEN", "statement": "done"},
        ]}), encoding="utf-8")
    rc = pr.main([str(ws)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "(no dispatchable claims)" in out


def test_json_mode_guard_unaffected(tmp_path, capsys):
    """--json keeps working: list of dicts from to_dict()."""
    ws = _make_ws(tmp_path)
    rc = pr.main([str(ws), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(payload, list) and len(payload) == 2
    assert {"claim_id", "score"} <= set(payload[0])
