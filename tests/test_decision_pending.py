# -*- coding: utf-8 -*-
"""Tests for scripts/decision_pending.py (#455) — the shared pending-decision
schema consumed by kunglao-init intake step 0 and (by design) by #449's
needs-first intake and #451's negotiation menu.

TDD RED phase: module does not exist yet (collection error = RED).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# sys.path: pytest.ini pythonpath includes scripts/
import decision_pending  # noqa: E402  (RED: ModuleNotFoundError until GREEN)


# ---------- dataclass + JSON round-trip ----------

def test_pending_decision_fields():
    d = decision_pending.PendingDecision(
        decision_id="type", question="Project type?",
        kind="choice", options=("windows", "linux", "android"),
        default=None, context={"suggested_type": "windows"},
    )
    assert d.decision_id == "type"
    assert d.kind == "choice"
    assert list(d.options) == ["windows", "linux", "android"]
    assert d.default is None
    assert d.context == {"suggested_type": "windows"}


def test_pending_list_roundtrip_through_json():
    dl = decision_pending.build_pending_doc(
        flow="kunglao-init", workspace=None,
        guidance="Collect answers, re-run with --resolve.",
        decisions=[
            decision_pending.PendingDecision(
                decision_id="target", question="Which file?",
                kind="choice", options=("a.exe", "b.apk"),
                default=None, context={"bins": ["a.exe", "b.apk"]},
            ),
        ],
        resume={"argv": ["kunglao-init.py", "<ws>", "--resolve", "<answers.json>"]},
    )
    parsed = json.loads(decision_pending.pending_doc_json(dl))
    assert parsed["schema_version"] == decision_pending.SCHEMA_VERSION
    assert parsed["flow"] == "kunglao-init"
    assert parsed["workspace"] is None
    assert parsed["decisions"][0]["decision_id"] == "target"
    assert parsed["decisions"][0]["options"] == ["a.exe", "b.apk"]
    assert parsed["decisions"][0]["default"] is None
    assert parsed["decisions"][0]["context"] == {"bins": ["a.exe", "b.apk"]}
    assert parsed["resume"]["argv"][0] == "kunglao-init.py"


def test_schema_version_is_declared():
    assert decision_pending.SCHEMA_VERSION == "1"


# ---------- answers (the --resolve payload) ----------

def test_answers_from_json_valid_object():
    assert decision_pending.answers_from_json('{"type": "windows"}') == {
        "type": "windows"}


def test_answers_from_json_rejects_non_object():
    with pytest.raises(ValueError):
        decision_pending.answers_from_json("[1, 2]")
    with pytest.raises(ValueError):
        decision_pending.answers_from_json('42')


def test_answers_from_json_rejects_invalid_json():
    with pytest.raises(ValueError):
        decision_pending.answers_from_json("{not json")


def test_answers_from_json_rejects_non_string_values():
    """Fail-closed: an answers payload must be {decision_id: string}."""
    with pytest.raises(ValueError):
        decision_pending.answers_from_json('{"type": 3}')


def test_load_answers_reads_file(tmp_path: Path):
    f = tmp_path / "answers.json"
    f.write_text('{"target": "a.exe", "type": "windows"}', encoding="utf-8")
    assert decision_pending.load_answers(f) == {
        "target": "a.exe", "type": "windows"}


def test_load_answers_missing_file(tmp_path: Path):
    with pytest.raises(ValueError):
        decision_pending.load_answers(tmp_path / "nope.json")


def test_load_answers_corrupt_file(tmp_path: Path):
    f = tmp_path / "answers.json"
    f.write_text("{{{ broken", encoding="utf-8")
    with pytest.raises(ValueError):
        decision_pending.load_answers(f)
