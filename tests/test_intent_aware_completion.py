# -*- coding: utf-8 -*-
"""TDD RED — intent-aware strategic stopping (#664).

When the oracle would otherwise PASS (items closed, defers signed), judge()
SHOULD extract content anchors from task_text (reusing #54 F1's
_extract_anchors) and verify each anchor is covered by some primary_question
id/text in task_spec.yaml. ≥1 unmatched anchor → exit 4 INTENT_UNMATCHED with
the unmatched anchors named in the reason. Precedence: exit 3 > 2 > 1 > 4 > 0
(intent check fires at the would-be-PASS point; item-level defects outrank it).

Fail-open layers (D4): no workspace_path, no task_spec.yaml, malformed, no
primary_questions, zero anchors, anchor-module import failure → check skipped.

Spec: openspec/changes/issue-664-intent-aware-stopping/specs/intent-aware-completion/spec.md
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import completion_gate as cg  # noqa: E402  (scripts/ on sys.path)


# ---------------------------------------------------------------------------
# Helpers — oracle + workspace + task_spec builders (synthetic)
# ---------------------------------------------------------------------------

def _all_closed_oracle(workspace_path: str | None = None, task_text: str = "do X"):
    """An oracle that would PASS without the intent check — all items closed,
    zero defers. workspace_path is optional (RED3 covers the absent case)."""
    o = {
        "task_text": task_text,
        "open_items": [
            {"id": "A", "desc": "A", "closed_by": "commit 0001", "closed_at": "2026-08-25T00:00:00Z"},
            {"id": "B", "desc": "B", "closed_by": "commit 0002", "closed_at": "2026-08-25T00:00:01Z"},
        ],
        "deferrals": [],
    }
    if workspace_path is not None:
        o["workspace_path"] = workspace_path
    return o


def _write_task_spec(ws: Path, primary_questions: list) -> Path:
    """Write a minimal task_spec.yaml with the given primary_questions list."""
    p = ws / "task_spec.yaml"
    p.write_text(
        "primary_questions:\n" +
        "\n".join(f"  - id: {q['id']}\n    question: {q['q']}\n"
                  for q in primary_questions),
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# RED1 — anchor in task_text absent from PQ text, items all closed
# ---------------------------------------------------------------------------

def test_red1_unmatched_anchor_returns_exit4_with_named_anchors(tmp_path):
    """task_text mentions a specific concern whose anchor appears in no
    primary_question. items all closed → exit 4 + the anchor named in reason."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_task_spec(ws, [
        {"id": "Q1", "q": "what is the file structure"},  # generic — no match
        {"id": "Q2", "q": "is the binary packed"},
    ])
    oracle = _all_closed_oracle(
        workspace_path=str(ws),
        task_text="focus on the cryptographic key derivation pathway and any anti-debug tricks",
    )
    code, reason = cg.judge(oracle)
    assert code == 4, f"expected exit 4 INTENT_UNMATCHED, got {code}: {reason}"
    assert "INTENT_UNMATCHED" in reason or "unmatched" in reason.lower(), reason
    # The reason names at least one of the unmatched anchors
    assert ("cryptographic" in reason) or ("anti-debug" in reason) or ("derivation" in reason), reason


# ---------------------------------------------------------------------------
# RED2 — anchors covered by PQ text → verdict unchanged (PASS)
# ---------------------------------------------------------------------------

def test_red2_covered_anchors_unchanged_pass(tmp_path):
    """Every task_text anchor appears in some PQ's id or question text and the
    oracle is otherwise clean → judge returns PASS (verdict unchanged from pre-#664)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_task_spec(ws, [
        {"id": "Q1", "q": "explain the cryptographic key derivation pathway"},
        {"id": "Q2", "q": "are there any anti-debug tricks"},
    ])
    # task_text mirrors the PQ corpus verbatim — every content anchor is owned
    oracle = _all_closed_oracle(
        workspace_path=str(ws),
        task_text="explain the cryptographic key derivation pathway and anti-debug tricks",
    )
    code, reason = cg.judge(oracle)
    assert code == 0, f"expected PASS (all anchors covered), got {code}: {reason}"


# ---------------------------------------------------------------------------
# RED3 — no workspace_path → check skipped, oracle verdict unchanged
# ---------------------------------------------------------------------------

def test_red3_no_workspace_path_skips_check():
    """Oracle carries no workspace_path key. Even with task_text containing
    rich anchors that would be unmatched, the check is skipped and a clean
    oracle still PASSes (verdict unchanged)."""
    oracle = _all_closed_oracle(workspace_path=None,
                                task_text="focus on the cryptographic key derivation pathway")
    code, reason = cg.judge(oracle)
    assert code == 0, f"expected PASS (no workspace → check skipped), got {code}: {reason}"


# ---------------------------------------------------------------------------
# RED4 — no task_spec / malformed → check skipped, no crash
# ---------------------------------------------------------------------------

def test_red4_no_task_spec_skips_check(tmp_path):
    """workspace_path points at a directory with no task_spec.yaml. Clean
    oracle PASSes; the intent check is skipped; no crash."""
    ws = tmp_path / "ws"
    ws.mkdir()  # no task_spec.yaml
    oracle = _all_closed_oracle(
        workspace_path=str(ws),
        task_text="focus on the cryptographic key derivation pathway",
    )
    code, reason = cg.judge(oracle)
    assert code == 0, f"expected PASS (no task_spec → check skipped), got {code}: {reason}"


def test_red4b_malformed_task_spec_skips_check(tmp_path):
    """task_spec.yaml exists but is malformed. Clean oracle PASSes; check skipped."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(
        "this is not: valid: yaml: at all:\n  - broken\n  bad indent\n",
        encoding="utf-8",
    )
    oracle = _all_closed_oracle(
        workspace_path=str(ws),
        task_text="focus on the cryptographic key derivation pathway",
    )
    code, reason = cg.judge(oracle)
    assert code == 0, f"expected PASS (malformed task_spec → check skipped), got {code}: {reason}"


def test_red4c_empty_primary_questions_skips_check(tmp_path):
    """task_spec.yaml exists with primary_questions: []. The check is
    skipped (no PQ layer to match against)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text("primary_questions: []\n", encoding="utf-8")
    oracle = _all_closed_oracle(
        workspace_path=str(ws),
        task_text="focus on the cryptographic key derivation pathway",
    )
    code, reason = cg.judge(oracle)
    assert code == 0, f"expected PASS (empty primary_questions → check skipped), got {code}: {reason}"


# ---------------------------------------------------------------------------
# RED5 — precedence: unresolved items + unmatched anchor → exit 1 (not 4)
# ---------------------------------------------------------------------------

def test_red5_unresolved_items_outrank_unmatched_anchor(tmp_path):
    """Items still open AND an unmatched anchor → exit 1 INCOMPLETE (item-
    level defects keep priority over intent — design D1 precedence)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_task_spec(ws, [
        {"id": "Q1", "q": "what is the file structure"},
    ])
    oracle = {
        "task_text": "focus on the cryptographic key derivation pathway",
        "workspace_path": str(ws),
        "open_items": [
            {"id": "G4", "desc": "G4 unresolved", "closed_by": "", "closed_at": ""},
        ],
        "deferrals": [],
    }
    code, reason = cg.judge(oracle)
    assert code == 1, f"expected exit 1 (items outrank intent), got {code}: {reason}"
    assert "G4" in reason


# ---------------------------------------------------------------------------
# RED6 — CLI JSON verdict label INTENT_UNMATCHED
# ---------------------------------------------------------------------------

def test_red6_cli_verdict_label_intent_unmatched(tmp_path):
    """scripts/completion_gate.py CLI JSON output maps exit 4 to verdict
    label INTENT_UNMATCHED."""
    ws = tmp_path / "ws"
    ws.mkdir()
    _write_task_spec(ws, [
        {"id": "Q1", "q": "what is the file structure"},
    ])
    oracle = _all_closed_oracle(
        workspace_path=str(ws),
        task_text="focus on the cryptographic key derivation pathway",
    )
    import yaml
    oracle_path = tmp_path / "oracle.yaml"
    oracle_path.write_text(yaml.safe_dump(oracle, allow_unicode=True), encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "completion_gate.py"), str(oracle_path)],
        capture_output=True, text=True,
    )
    assert r.returncode == 4, r.stderr
    out = json.loads(r.stdout)
    assert out["exit_code"] == 4
    assert out["verdict"] == "INTENT_UNMATCHED", out