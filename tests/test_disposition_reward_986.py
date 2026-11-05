# -*- coding: utf-8 -*-
"""The disposition classification and reward face.

Pins the reward consumer of the episode disposition algebra:

- classification evidence: an authorized refusal is SURRENDER, an
  out-of-scope refusal is OUT_OF_SCOPE, a timeout is FAILED, and
  CENSORED_ENV needs BOTH wall legs (session-bound AND corroborated);
  an early stop without the route ledger and without both legs never
  censors;
- the reward mapping: SOLVED is the oracle lock, SURRENDER is 0.0 inside
  the declared rails (TRACE floor only with reproducible evidence) with
  a strategic-action failure outcome, ATTEMPTED_EXHAUSTED is a
  capability gap with no strategy credit, CENSORED_ENV is excluded from
  strategy learning, and OUT_OF_SCOPE / INFRA / FAILED are reported
  separately;
- the bounded choice signal: one `disposition-signal/1` telemetry row
  per episode plus the registered `disposition_signal` event;
- the mission-terminal settlement call site writes the signal exactly
  once and leaves non-disposition workspaces untouched.
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

import event_taxonomy  # noqa: E402
import kunglao_log  # noqa: E402
from rlvr import consolidated_ledger, disposition  # noqa: E402
from rlvr import disposition_reward, episode_settle, scalar  # noqa: E402

TS = "2026-11-05T00:00:00Z"


# ---------- helpers ----------

def _record(**fields) -> dict:
    """A minimal authorized, in-scope episode ending unfinished."""
    record = {
        "claim": "C-986",
        "authorized": True,
        "authorization": {"targets": ["target.example.com"], "excluded": []},
        "target": "target.example.com",
        "oracle_pass": False,
        "wall": None,
        "ledger": None,
        "act_outcomes": [],
        "session": {"returncode": None, "timed_out": False, "liveness": "alive"},
        "strategic_action": None,
        "completion_claimed": False,
    }
    record.update(fields)
    return record


def _row(**fields) -> dict:
    return disposition.build_row(_record(**fields),
                                 episode_id="ep-986", ts=TS)


def _ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _events(ws: Path) -> list[dict]:
    path = kunglao_log.log_path(ws)
    if not path.is_file():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _signals(ws: Path) -> list[dict]:
    return consolidated_ledger.read(
        ws, "telemetry", schema_prefix=disposition_reward.SIGNAL_SCHEMA,
        include_legacy=False)


# ---------- classification: refusal, timeout, wall, out-of-scope --------

def test_authorized_refusal_is_surrender():
    # Arrange
    record = _record(session={"returncode": None, "timed_out": False,
                              "liveness": "alive"})

    # Act
    result = disposition_reward.classify_episode(record)

    # Assert
    assert result["disposition"] == "SURRENDER"
    assert result["gate"] == "unfinished"


def test_out_of_scope_refusal_is_out_of_scope():
    # Arrange
    record = _record(authorized=False, target=None,
                     authorization=None,
                     session={"returncode": None, "timed_out": False,
                              "liveness": "alive"})

    # Act
    result = disposition_reward.classify_episode(record)

    # Assert
    assert result["disposition"] == "OUT_OF_SCOPE"
    assert result["gate"] == "authorization"


def test_timeout_is_failed_not_surrender():
    # Arrange
    record = _record(session={"returncode": None, "timed_out": True,
                              "liveness": None})

    # Act
    result = disposition_reward.classify_episode(record)

    # Assert
    assert result["disposition"] == "FAILED"
    assert result["gate"] == "execution_failure"


def test_corroborated_session_bound_wall_is_censored():
    # Arrange
    wall = {"session_bound": True, "corroborated": True}

    # Act
    result = disposition_reward.classify_episode(_record(), wall=wall)

    # Assert
    assert result["disposition"] == "CENSORED_ENV"
    assert result["gate"] == "wall"


def test_one_legged_wall_never_censors():
    # Arrange — session binding alone is not corroboration
    wall = {"session_bound": True, "corroborated": False}

    # Act
    result = disposition_reward.classify_episode(_record(), wall=wall)

    # Assert
    assert result["disposition"] == "SURRENDER"
    assert result["disposition"] != "CENSORED_ENV"


def test_corroboration_alone_without_session_binding_never_censors():
    # Arrange
    wall = {"session_bound": False, "corroborated": True}

    # Act
    result = disposition_reward.classify_episode(_record(), wall=wall)

    # Assert
    assert result["disposition"] == "SURRENDER"


def _censored_session(tmp_path) -> tuple[Path, dict]:
    """A real interruption-corroborated censoring fixture: the declared
    sample anchor is present, no sample remains, and the blocker names
    the claim, so interruption.classify derives ``censored_env`` from
    the workspace itself."""
    ws = tmp_path / "censor-ws"
    ws.mkdir()
    (ws / "task_spec.yaml").write_text(
        "sample_sha256: " + "a" * 64 + "\n", encoding="utf-8")
    blockers = ws / "blockers"
    blockers.mkdir()
    (blockers / "missing.md").write_text(
        "sample-missing: the sample vanished for C-986\n", encoding="utf-8")
    session = {"returncode": 1, "timed_out": False, "liveness": None,
               "claim": "C-986"}
    return ws, session


def test_interruption_censored_verdict_supplies_both_wall_legs(tmp_path):
    # Arrange — the classifier, not the caller, produces the class word.
    ws, session = _censored_session(tmp_path)
    record = _record(claim="C-986", session=session)

    # Act
    result = disposition_reward.classify_episode(
        record, session_record=session, ws=ws)

    # Assert
    assert result["disposition"] == "CENSORED_ENV"
    assert result["gate"] == "wall"


def test_interruption_agent_death_never_censors(tmp_path):
    # Arrange — an empty workspace has no corroborated blocker, so the
    # classifier's residual class is agent_death, never censoring.
    ws = tmp_path / "plain-ws"
    ws.mkdir()
    session = {"returncode": 1, "timed_out": False, "liveness": None,
               "claim": "C-986"}
    result = disposition_reward.classify_episode(
        _record(session=session), session_record=session, ws=ws)

    # Assert
    assert result["disposition"] == "FAILED"
    assert result["disposition"] != "CENSORED_ENV"


def test_early_stop_without_ledger_or_wall_is_surrender():
    # Arrange — no route ledger, no wall, no solve, no failure.
    record = _record(ledger=None, wall=None, oracle_pass=False)

    # Act
    result = disposition_reward.classify_episode(record)

    # Assert
    assert result["disposition"] == "SURRENDER"


def test_route_ledger_exhaustion_is_not_surrender():
    # Arrange
    record = _record(ledger={"routes": ["r1"], "attempted": ["r1"],
                             "budget": 12, "budget_exhausted": False})

    # Act
    result = disposition_reward.classify_episode(record)

    # Assert
    assert result["disposition"] == "ATTEMPTED_EXHAUSTED"


def test_wall_evidence_is_none_without_a_leg():
    # Arrange / Act / Assert
    assert disposition_reward.wall_evidence() is None
    assert disposition_reward.wall_evidence(
        wall={"session_bound": "true", "corroborated": True}) is None
    assert disposition_reward.wall_evidence(
        wall={"session_bound": True, "corroborated": True}) == {
        "session_bound": True, "corroborated": True}


def test_authorized_for_reads_the_task_spec_scope():
    # Arrange
    spec = {"authorization": {"targets": ["target.example.com"],
                              "excluded": []}}

    # Act / Assert
    assert disposition_reward.authorized_for(spec, "target.example.com") is True
    assert disposition_reward.authorized_for(spec, "other.example.com") is False
    assert disposition_reward.authorized_for({}, "target.example.com") is False
    assert disposition_reward.authorized_for(
        {"authorization": {"targets": ["a.example.com"],
                           "excluded": ["a.example.com"]}},
        "a.example.com") is False


# ---------- reward_for: the consumer mapping ----------------------------

def test_solved_earns_the_oracle_lock():
    # Arrange / Act
    face = disposition_reward.reward_for("SOLVED")

    # Assert
    assert face["credit"] == scalar.ORACLE_PASS_LOCK
    assert face["credit"] == 1.0
    assert face["rail"] == "GOLD"
    assert face["strategy_learning"] is True
    assert face["strategic_action_outcome"] == "positive"


def test_surrender_settles_zero_inside_the_rails():
    # Arrange / Act
    face = disposition_reward.reward_for("SURRENDER")

    # Assert
    assert face["credit"] == 0.0
    assert 0.0 <= face["credit"] <= 1.0
    assert face["strategy_learning"] is True
    assert face["strategic_action_outcome"] == "failure"
    assert face["capability_denominator"] is True


def test_surrender_with_reproducible_evidence_uses_the_trace_floor():
    # Arrange / Act
    face = disposition_reward.reward_for(
        "SURRENDER", has_reproducible_evidence=True)

    # Assert
    assert face["credit"] == scalar.TRACE_CANONICAL
    assert 0.0 <= face["credit"] <= 1.0
    assert face["rail"] == "TRACE"


def test_attempted_exhausted_is_a_capability_gap_without_strategy_credit():
    # Arrange / Act
    face = disposition_reward.reward_for("ATTEMPTED_EXHAUSTED")

    # Assert
    assert face["credit"] == 0.0
    assert face["capability_gap"] is True
    assert face["strategy_learning"] is False
    assert face["strategic_action_outcome"] is None


def test_censored_is_excluded_from_strategy_learning_and_counted():
    # Arrange / Act
    face = disposition_reward.reward_for("CENSORED_ENV")

    # Assert
    assert face["credit"] == 0.0
    assert face["censoring"] is True
    assert face["strategy_learning"] is False
    assert face["strategic_action_outcome"] is None


@pytest.mark.parametrize("word", ["OUT_OF_SCOPE", "INFRA", "FAILED"])
def test_separately_reported_dispositions_carry_no_strategy_signal(word):
    # Arrange / Act
    face = disposition_reward.reward_for(word)

    # Assert
    assert face["credit"] == 0.0
    assert face["reported_separately"] is True
    assert face["strategy_learning"] is False
    assert face["strategic_action_outcome"] is None


def test_every_disposition_has_a_bounded_credit():
    # Arrange / Act / Assert
    for word in disposition.DISPOSITIONS:
        face = disposition_reward.reward_for(word)
        assert 0.0 <= face["credit"] <= 1.0
        assert face["disposition"] == word


def test_unknown_disposition_fails_closed():
    # Arrange / Act / Assert
    with pytest.raises(ValueError):
        disposition_reward.reward_for("SURRENDERED")


# ---------- the bounded choice signal -----------------------------------

def test_signal_carries_the_bounded_choice_fields():
    # Arrange
    row = _row(strategic_action="FIGHT", propensity=0.6)

    # Act
    signal = disposition_reward.build_signal(row, ts=TS)

    # Assert
    assert signal["schema"] == "disposition-signal/1"
    assert signal["episode_id"] == "ep-986"
    assert signal["claim"] == "C-986"
    assert signal["disposition"] == "SURRENDER"
    assert 0.0 <= signal["credit"] <= 1.0
    assert signal["strategic_action"] == "FIGHT"
    assert 0.0 <= signal["propensity"] <= 1.0
    assert signal["strategy_learning"] is True
    assert signal["strategic_action_outcome"] == "failure"
    assert signal["ts"] == TS
    assert set(signal) == set(disposition_reward.SIGNAL_FIELDS)


def test_signal_for_censored_has_no_strategy_learning():
    # Arrange
    row = _row(wall={"session_bound": True, "corroborated": True},
               wall_ref="blockers/captcha.md")

    # Act
    signal = disposition_reward.build_signal(row, ts=TS)

    # Assert
    assert signal["disposition"] == "CENSORED_ENV"
    assert signal["strategy_learning"] is False
    assert signal["strategic_action_outcome"] is None


def test_signal_writer_appends_one_telemetry_row_and_emits_the_event(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    row = _row(strategic_action="INVEST", propensity=0.4)

    # Act
    out = disposition_reward.settle_disposition(ws, row, ts=TS)

    # Assert
    assert out["appended"] is True
    assert out["emitted"] is True
    rows = _signals(ws)
    assert len(rows) == 1
    assert rows[0]["disposition"] == "SURRENDER"
    assert rows[0]["credit"] == 0.0
    assert rows[0]["strategic_action"] == "INVEST"
    hits = [e for e in _events(ws) if e.get("action") == "disposition_signal"]
    assert len(hits) == 1
    detail = json.loads(hits[0]["detail"])
    assert detail["episode_id"] == "ep-986"
    assert detail["disposition"] == "SURRENDER"


def test_signal_writer_is_idempotent_per_episode(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    row = _row()

    # Act
    first = disposition_reward.settle_disposition(ws, row, ts=TS)
    second = disposition_reward.settle_disposition(ws, row, ts=TS)

    # Assert
    assert first["appended"] is True
    assert second["appended"] is False
    assert second["emitted"] is True  # post-call state: the event is present
    assert len(_signals(ws)) == 1
    hits = [e for e in _events(ws) if e.get("action") == "disposition_signal"]
    assert len(hits) == 1


def test_failed_append_never_emits_an_orphan_event_and_heals(tmp_path,
                                                              monkeypatch):
    # Arrange — the row is the admission ticket: no row, no event.
    ws = _ws(tmp_path)
    row = _row()
    real_append = consolidated_ledger.append
    state = {"append": False}

    def _flaky_append(*args, **kwargs):
        return real_append(*args, **kwargs) if state["append"] else False

    monkeypatch.setattr(consolidated_ledger, "append", _flaky_append)

    # Act
    first = disposition_reward.settle_disposition(ws, row, ts=TS)
    orphan_hits = [e for e in _events(ws)
                   if e.get("action") == "disposition_signal"]
    state["append"] = True
    second = disposition_reward.settle_disposition(ws, row, ts=TS)

    # Assert
    assert first["appended"] is False
    assert first["emitted"] is False
    assert orphan_hits == []
    assert second["appended"] is True
    assert second["emitted"] is True
    assert len(_signals(ws)) == 1
    hits = [e for e in _events(ws) if e.get("action") == "disposition_signal"]
    assert len(hits) == 1


def test_existing_row_heals_a_failed_event_on_retry(tmp_path, monkeypatch):
    # Arrange — the row landed but the event write failed.
    ws = _ws(tmp_path)
    row = _row()
    real_emit = disposition_reward.emit
    state = {"emit": False}

    def _flaky_emit(*args, **kwargs):
        return real_emit(*args, **kwargs) if state["emit"] else False

    monkeypatch.setattr(disposition_reward, "emit", _flaky_emit)

    # Act
    first = disposition_reward.settle_disposition(ws, row, ts=TS)
    state["emit"] = True
    second = disposition_reward.settle_disposition(ws, row, ts=TS)

    # Assert
    assert first["appended"] is True
    assert first["emitted"] is False
    assert second["appended"] is False
    assert second["emitted"] is True
    assert len(_signals(ws)) == 1
    hits = [e for e in _events(ws) if e.get("action") == "disposition_signal"]
    assert len(hits) == 1


def test_signal_event_word_is_registered_sorted_unique():
    # Arrange / Act
    word = disposition_reward.EVENT

    # Assert
    assert word == "disposition_signal"
    assert word in event_taxonomy.EMIT_ACTIONS
    assert event_taxonomy.EMIT_ACTIONS == sorted(set(
        event_taxonomy.EMIT_ACTIONS))


def test_signal_schema_is_registered_for_liveness(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    before = consolidated_ledger.liveness(ws)[
        f"telemetry:{disposition_reward.SIGNAL_SCHEMA}"]

    # Act
    disposition_reward.settle_disposition(ws, _row(), ts=TS)

    # Assert
    assert before == 0
    assert consolidated_ledger.liveness(ws)[
        f"telemetry:{disposition_reward.SIGNAL_SCHEMA}"] == 1


def test_validate_signal_rejects_out_of_range_credit():
    # Arrange
    signal = disposition_reward.build_signal(_row(), ts=TS)
    signal["credit"] = 1.5

    # Act / Assert
    with pytest.raises(ValueError):
        disposition_reward.validate_signal(signal)


def test_validate_signal_rejects_an_unregistered_action():
    # Arrange
    signal = disposition_reward.build_signal(_row(), ts=TS)
    signal["strategic_action"] = "PANIC"
    signal["propensity"] = 0.5

    # Act / Assert
    with pytest.raises(ValueError):
        disposition_reward.validate_signal(signal)


def test_validate_signal_rejects_propensity_without_an_action():
    # Arrange
    signal = disposition_reward.build_signal(_row(), ts=TS)
    signal["propensity"] = 0.5

    # Act / Assert
    with pytest.raises(ValueError):
        disposition_reward.validate_signal(signal)


# ---------- the mission-terminal settlement call site -------------------

def _settle_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "mission"
    ws.mkdir()
    claims = {"claims": [{"id": "C-001", "status": "PROVEN",
                          "title": "packaging"}]}
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(claims), encoding="utf-8")
    runs = ws / "runs"
    runs.mkdir()
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n- id: pq1\n  q: produce the trainer\n",
        encoding="utf-8")
    return ws


def test_episode_settle_writes_the_disposition_signal(tmp_path):
    # Arrange
    ws = _settle_ws(tmp_path)
    disposition.write_row(ws, _record(), episode_id="ep-986", ts=TS)

    # Act
    out = episode_settle.settle_mission(ws)

    # Assert
    assert out["disposition_signals"] == 1
    rows = _signals(ws)
    assert len(rows) == 1
    assert rows[0]["episode_id"] == "ep-986"


def test_episode_settle_leaves_non_disposition_workspaces_unchanged(tmp_path):
    # Arrange
    ws = _settle_ws(tmp_path)

    # Act
    out = episode_settle.settle_mission(ws)

    # Assert
    assert out["disposition_signals"] == 0
    assert _signals(ws) == []


def test_episode_settle_signal_write_is_idempotent(tmp_path):
    # Arrange
    ws = _settle_ws(tmp_path)
    disposition.write_row(ws, _record(), episode_id="ep-986", ts=TS)

    # Act
    episode_settle.settle_mission(ws)
    second = episode_settle.settle_mission(ws)

    # Assert
    assert second["disposition_signals"] == 0
    assert len(_signals(ws)) == 1
