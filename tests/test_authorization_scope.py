# -*- coding: utf-8 -*-
"""The authorization scope: `task_spec.authorization` -> the dispatch -> the
disposition.

The disposition object's second gate is OUT_OF_SCOPE: a refusal on a target
outside the declared engagement scope is not a surrender. The scope is
declared once at intake (`task_spec.yaml`), copied verbatim into the
dispatch envelope, and read here — exact match only, no globs (a wildcard
would turn a typo into a silent scope expansion), fail closed on an absent
or malformed block.

The end-to-end case pins the mapping the spec requires: an authorized
refusal classifies SURRENDER, an out-of-scope refusal classifies
OUT_OF_SCOPE.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import lib_kunglao  # noqa: E402
from rlvr import authorization, disposition  # noqa: E402

TS = "2026-11-05T00:00:00Z"


# ---------- helpers ----------

def _auth(**fields) -> dict:
    block = {"targets": ["target.example.com", "bins/deadbeef"],
             "excluded": [], "authorization_ref": "ticket-42"}
    block.update(fields)
    return block


def _dispatch(block) -> str:
    payload = {"kunglao_dispatch": {
        "version": 1, "claim": "C-007", "tier": 1,
        "tools": ["grep"], "agent": "kunglao-worker"}}
    if block is not None:
        payload["kunglao_dispatch"]["authorization"] = block
    return json.dumps(payload)


def _record(authorized: bool) -> dict:
    return {
        "claim": "C-007",
        "authorized": authorized,
        "oracle_pass": False,
        "wall": None,
        "ledger": None,
        "act_outcomes": [],
        "session": {"returncode": None, "timed_out": False, "liveness": None},
        "strategic_action": None,
        "completion_claimed": False,
    }


# ---------- the scope decision ----------

def test_declared_target_is_authorized():
    # Arrange / Act
    got = authorization.authorized_target(_auth(), "target.example.com")

    # Assert
    assert got is True


def test_target_outside_the_scope_is_not_authorized():
    # Arrange / Act
    got = authorization.authorized_target(_auth(), "other.example.com")

    # Assert
    assert got is False


def test_exclusion_wins_over_the_target_list():
    # Arrange
    block = _auth(excluded=["target.example.com"])

    # Act
    got = authorization.authorized_target(block, "target.example.com")

    # Assert
    assert got is False


def test_absent_authorization_block_authorizes_nothing():
    # Arrange / Act / Assert
    assert authorization.authorized_target(None, "target.example.com") is False
    assert authorization.authorized_target({}, "target.example.com") is False


def test_empty_target_list_authorizes_nothing():
    # Arrange / Act
    got = authorization.authorized_target(_auth(targets=[]),
                                          "target.example.com")

    # Assert
    assert got is False


def test_malformed_target_list_fails_closed():
    # Arrange / Act / Assert
    assert authorization.authorized_target(
        _auth(targets="target.example.com"), "target.example.com") is False
    assert authorization.authorized_target(
        _auth(targets=[3]), "target.example.com") is False
    assert authorization.authorized_target(
        _auth(targets=[""]), "target.example.com") is False


def test_malformed_exclusions_fail_closed():
    # Arrange / Act / Assert
    assert authorization.authorized_target(
        _auth(excluded="target.example.com"), "target.example.com") is False


def test_matching_is_exact_not_a_glob():
    # Arrange
    block = _auth(targets=["*.example.com"])

    # Act
    got = authorization.authorized_target(block, "evil.example.com")

    # Assert
    assert got is False


def test_entries_and_target_are_whitespace_stripped():
    # Arrange
    block = _auth(targets=[" target.example.com "])

    # Act
    got = authorization.authorized_target(block, "  target.example.com  ")

    # Assert
    assert got is True


def test_non_string_target_is_not_authorized():
    # Arrange / Act / Assert
    assert authorization.authorized_target(_auth(), None) is False
    assert authorization.authorized_target(_auth(), 42) is False
    assert authorization.authorized_target(_auth(), "   ") is False


def test_authorization_ref_is_copied():
    # Arrange / Act / Assert
    assert authorization.authorization_ref(_auth()) == "ticket-42"
    assert authorization.authorization_ref({"targets": ["a"]}) is None
    assert authorization.authorization_ref({"authorization_ref": "  "}) is None
    assert authorization.authorization_ref(None) is None


def test_authorization_is_read_from_task_spec():
    # Arrange
    task_spec = {"authorization": _auth()}

    # Act
    block = authorization.authorization_from_task_spec(task_spec)

    # Assert
    assert block == _auth()
    assert authorization.authorization_from_task_spec({}) is None
    assert authorization.authorization_from_task_spec(None) is None
    assert authorization.authorization_from_task_spec(
        {"authorization": "yes"}) is None


def test_authorization_from_task_spec_returns_a_copy():
    # Arrange
    original = _auth()
    task_spec = {"authorization": original}

    # Act
    block = authorization.authorization_from_task_spec(task_spec)
    block["targets"].append("other.example.com")

    # Assert
    assert original["targets"] == ["target.example.com", "bins/deadbeef"]


# ---------- the dispatch copy ----------

def test_dispatch_carries_the_authorization_block():
    # Arrange
    text = _dispatch(_auth())

    # Act
    block = lib_kunglao.dispatch_authorization(text)

    # Assert
    assert block == _auth()


def test_dispatch_without_authorization_returns_none():
    # Arrange / Act / Assert
    assert lib_kunglao.dispatch_authorization(_dispatch(None)) is None
    assert lib_kunglao.dispatch_authorization("no envelope here") is None


def test_malformed_authorization_block_returns_none():
    # Arrange
    text = json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-007", "authorization": "yes"}})

    # Act / Assert
    assert lib_kunglao.dispatch_authorization(text) is None


# ---------- intake declaration surface ----------

def test_task_spec_template_declares_the_authorization_block():
    # Arrange
    template = yaml.safe_load(
        (ROOT / "templates" / "state" / "task_spec.yaml").read_text(
            encoding="utf-8"))

    # Act
    block = template.get("authorization")

    # Assert
    assert isinstance(block, dict)
    assert block.get("targets") == []
    assert block.get("excluded") == []
    assert "authorization_ref" in block


# ---------- end to end: refusal -> the right disposition ----------

def test_authorized_refusal_is_surrender():
    # Arrange
    task_spec = {"authorization": _auth()}
    block = authorization.authorization_from_task_spec(task_spec)
    dispatch_block = lib_kunglao.dispatch_authorization(_dispatch(block))
    authorized = authorization.authorized_target(
        dispatch_block, "target.example.com")
    record = _record(authorized)
    record["authorization"] = dispatch_block
    record["target"] = "target.example.com"

    # Act
    row = disposition.build_row(record, episode_id="ep-007", ts=TS)

    # Assert
    assert authorized is True
    assert row["disposition"] == "SURRENDER"
    assert row["gate"] == "unfinished"


def test_out_of_scope_refusal_is_out_of_scope():
    # Arrange
    task_spec = {"authorization": _auth()}
    block = authorization.authorization_from_task_spec(task_spec)
    dispatch_block = lib_kunglao.dispatch_authorization(_dispatch(block))
    authorized = authorization.authorized_target(
        dispatch_block, "other.example.com")
    record = _record(authorized)

    # Act
    row = disposition.build_row(record, episode_id="ep-008", ts=TS)

    # Assert
    assert authorized is False
    assert row["disposition"] == "OUT_OF_SCOPE"
    assert row["gate"] == "authorization"


def test_dispatch_without_authorization_is_out_of_scope():
    # Arrange
    dispatch_block = lib_kunglao.dispatch_authorization(_dispatch(None))
    authorized = authorization.authorized_target(
        dispatch_block, "target.example.com")
    record = _record(authorized)

    # Act
    row = disposition.build_row(record, episode_id="ep-009", ts=TS)

    # Assert
    assert row["disposition"] == "OUT_OF_SCOPE"


def test_record_authorized_flag_must_match_the_declared_scope():
    # Arrange: the flag claims in-scope while the declared scope excludes it.
    record = _record(True)
    record["authorization"] = _auth()
    record["target"] = "other.example.com"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(record, episode_id="ep-010", ts=TS)


def test_authorized_flag_without_a_scope_context_is_refused():
    # Arrange: authorized=True with no declared authorization block.
    record = _record(True)
    record["target"] = "target.example.com"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(record, episode_id="ep-011", ts=TS)


def test_record_with_a_matching_scope_is_accepted():
    # Arrange
    record = _record(True)
    record["authorization"] = _auth()
    record["target"] = "target.example.com"

    # Act
    row = disposition.build_row(record, episode_id="ep-012", ts=TS)

    # Assert
    assert row["disposition"] == "SURRENDER"
    assert row["authorization_ref"] == "ticket-42"


# ---------- the contract documentation stays in sync ----------

def test_dispatch_contracts_document_the_authorization_field():
    # Arrange
    worker = (ROOT / "agents" / "kunglao-worker.md").read_text(
        encoding="utf-8")
    skill = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")

    # Act / Assert
    for text in (worker, skill):
        assert "authorization" in text
        assert "OUT_OF_SCOPE" in text
        assert "SURRENDER" in text


def test_skill_documents_the_disposition_object():
    # Arrange
    skill = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")

    # Act / Assert
    for marker in ("disposition/1", "disposition_recorded",
                   "runs/disposition/"):
        assert marker in skill
    for value in disposition.DISPOSITIONS:
        assert value in skill
