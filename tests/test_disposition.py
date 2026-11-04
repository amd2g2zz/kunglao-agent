# -*- coding: utf-8 -*-
"""Episode disposition algebra — the single evidence-gated classifier.

Each test pins one behavior of `rlvr.disposition.classify_episode` / the
legacy mapping. The record shape is the disposition contract:
claim, authorized, oracle_pass, wall, ledger, act_outcomes, session,
strategic_action, completion_claimed.
"""
from __future__ import annotations

import pytest

from rlvr import disposition


# ---------- helpers ----------

def _record(**fields) -> dict:
    """A minimal authorized in-scope episode record; tests override one
    field per behavior."""
    record = {
        "claim": "C-001",
        "authorized": True,
        "oracle_pass": False,
        "wall": None,
        "ledger": None,
        "act_outcomes": [],
        "session": {"returncode": None, "timed_out": False, "liveness": None},
        "strategic_action": None,
        "completion_claimed": False,
    }
    record.update(fields)
    return record


# ---------- precedence and evidence gates ----------

def test_verifier_pass_wins_over_missing_action():
    # Arrange
    record = _record(oracle_pass=True, strategic_action=None)

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "SOLVED"


def test_verifier_pass_wins_over_out_of_scope():
    # Arrange
    record = _record(oracle_pass=True, authorized=False)

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "SOLVED"


def test_out_of_scope_target_is_out_of_scope():
    # Arrange
    record = _record(authorized=False, strategic_action=None)

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "OUT_OF_SCOPE"


def test_corroborated_session_bound_wall_is_censored():
    # Arrange
    record = _record(wall={"session_bound": True, "corroborated": True},
                     session={"returncode": 1, "timed_out": False,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "CENSORED_ENV"


def test_uncorroborated_wall_is_not_censored():
    # Arrange
    record = _record(wall={"session_bound": True, "corroborated": False},
                     session={"returncode": 1, "timed_out": False,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"


def test_complete_route_ledger_is_attempted_exhausted():
    # Arrange
    record = _record(ledger={"routes": ["r1", "r2"], "attempted": ["r1", "r2"],
                             "budget_exhausted": False})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "ATTEMPTED_EXHAUSTED"


def test_budget_exhaustion_is_attempted_exhausted():
    # Arrange
    record = _record(ledger={"routes": ["r1", "r2"], "attempted": ["r1"],
                             "budget": 12, "budget_exhausted": True})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "ATTEMPTED_EXHAUSTED"


def test_budget_flag_without_a_recorded_budget_is_not_exhaustion():
    # Arrange
    record = _record(ledger={"budget_exhausted": True})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "SURRENDER"


def test_string_false_budget_flag_is_not_exhaustion():
    # Arrange
    record = _record(ledger={"routes": ["r1", "r2"], "attempted": ["r1"],
                             "budget": 12, "budget_exhausted": "false"})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "SURRENDER"


def test_incomplete_route_ledger_is_not_exhausted():
    # Arrange
    record = _record(ledger={"routes": ["r1", "r2"], "attempted": ["r1"],
                             "budget_exhausted": False})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "SURRENDER"


def test_terminating_blocked_act_is_infra():
    # Arrange
    record = _record(act_outcomes=["OK", "BLOCKED"],
                     session={"returncode": 1, "timed_out": False,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "INFRA"


def test_timeout_kill_is_failed():
    # Arrange
    record = _record(session={"returncode": None, "timed_out": True,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"


def test_nonzero_exit_is_failed():
    # Arrange
    record = _record(session={"returncode": 2, "timed_out": False,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"


def test_exit_zero_without_verification_is_failed():
    # Arrange
    record = _record(completion_claimed=True,
                     session={"returncode": 0, "timed_out": False,
                              "liveness": "alive"})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"


def test_unfinished_authorized_episode_without_action_is_surrender():
    # Arrange
    record = _record(strategic_action=None, completion_claimed=False,
                     session={"returncode": None, "timed_out": False,
                              "liveness": "alive"})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "SURRENDER"


def test_string_false_oracle_pass_is_not_a_pass():
    # Arrange
    record = _record(oracle_pass="false")

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "SURRENDER"


def test_string_false_wall_flags_are_not_evidence():
    # Arrange
    record = _record(wall={"session_bound": "false", "corroborated": "false"},
                     session={"returncode": 1, "timed_out": False,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"


def test_wall_needs_both_legs():
    # Arrange
    record = _record(wall={"session_bound": False, "corroborated": True},
                     session={"returncode": 1, "timed_out": False,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"


def test_nonterminating_blocked_act_is_not_infra():
    # Arrange
    record = _record(act_outcomes=["BLOCKED", "OK"],
                     session={"returncode": 1, "timed_out": False,
                              "liveness": None})

    # Act
    result = disposition.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"


def test_missing_authorization_raises():
    # Arrange
    record = _record()
    record.pop("authorized")

    # Act / Assert
    with pytest.raises(ValueError):
        disposition.classify_episode(record)


def test_non_bool_authorization_raises():
    # Arrange
    record = _record(authorized="yes")

    # Act / Assert
    with pytest.raises(ValueError):
        disposition.classify_episode(record)


# ---------- the published legacy mapping ----------

def test_legacy_terminal_with_pass_maps_to_solved():
    # Arrange / Act
    result = disposition.legacy_disposition("terminal", oracle_pass=True)

    # Assert
    assert result == "SOLVED"


def test_legacy_terminal_without_pass_maps_to_failed():
    # Arrange / Act
    result = disposition.legacy_disposition("terminal", oracle_pass=False)

    # Assert
    assert result == "FAILED"


def test_legacy_agent_death_maps_to_failed():
    # Arrange / Act
    result = disposition.legacy_disposition("agent_death", oracle_pass=False)

    # Assert
    assert result == "FAILED"


def test_legacy_censored_maps_to_censored_env():
    # Arrange / Act
    result = disposition.legacy_disposition("censored_env", oracle_pass=False)

    # Assert
    assert result == "CENSORED_ENV"


def test_legacy_string_false_pass_is_not_solved():
    # Arrange / Act
    result = disposition.legacy_disposition("terminal", oracle_pass="false")

    # Assert
    assert result == "FAILED"


def test_unknown_legacy_class_raises():
    # Arrange / Act / Assert
    with pytest.raises(ValueError):
        disposition.legacy_disposition("mystery_class", oracle_pass=False)
