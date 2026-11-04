# -*- coding: utf-8 -*-
"""The disposition OBJECT and its runtime face (`disposition/1`).

`rlvr.disposition.classify_episode` (slice 1) assigns one evidence-gated
disposition. This file pins the row built from that verdict and the write
path that makes it observable:

- `build_row` shapes the `disposition/1` object: the classifier's verdict
  plus the evidence references, the recorded strategic action and its
  propensity, and the fixed budget;
- `validate_row` is fail-closed on every field (an unknown disposition,
  gate, or action word is refused — the controlled-vocabulary discipline);
- `write_row` lands ONE row per episode (`runs/disposition/<episode>.json`),
  mirrors it into the unified ledger, and emits the registered
  `disposition_recorded` event.

One episode, one disposition: re-writing the same row is idempotent, while
a divergent rewrite is refused (no retro-rewrite of an episode's outcome).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "scripts", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import event_taxonomy  # noqa: E402
import kunglao_log  # noqa: E402
from rlvr import consolidated_ledger, disposition  # noqa: E402

TS = "2026-11-05T00:00:00Z"


# ---------- helpers ----------

def _record(**fields) -> dict:
    """A minimal authorized in-scope episode ending unfinished -> SURRENDER."""
    record = {
        "claim": "C-001",
        "authorized": True,
        "authorization": {"targets": ["target.example.com"], "excluded": []},
        "target": "target.example.com",
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


def _row(**fields) -> dict:
    return disposition.build_row(_record(**fields),
                                 episode_id="ep-001", ts=TS)


def _ws(tmp_path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


def _write(ws, **fields) -> dict:
    return disposition.write_row(ws, _record(**fields),
                                 episode_id="ep-001", ts=TS)


def _events(ws: Path) -> list[dict]:
    path = kunglao_log.log_path(ws)
    if not path.is_file():
        return []
    return [json.loads(line) for line in
            path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------- build_row: the object carries the verdict + evidence ----------

def test_row_carries_the_classifier_verdict_and_schema():
    # Arrange / Act
    row = _row()

    # Assert
    assert row["schema"] == "disposition/1"
    assert row["episode_id"] == "ep-001"
    assert row["claim"] == "C-001"
    assert row["disposition"] == "SURRENDER"
    assert row["gate"] == "unfinished"
    assert row["ts"] == TS


def test_row_carries_the_recorded_action_and_its_propensity():
    # Arrange / Act
    row = _row(strategic_action="FIGHT", propensity=0.7)

    # Assert
    assert row["strategic_action"] == "FIGHT"
    assert row["propensity"] == 0.7


def test_row_defaults_the_optional_references():
    # Arrange / Act
    row = _row()

    # Assert
    assert row["evidence_refs"] == []
    assert row["route_ledger_ref"] is None
    assert row["wall_ref"] is None
    assert row["authorization_ref"] is None
    assert row["budget"] is None


def test_row_copies_the_evidence_references():
    # Arrange / Act
    row = _row(evidence_refs=["runs/rt-tests/C-001/manifest.json"],
               route_ledger_ref="runs/rt-tests/C-001/routes.json",
               wall_ref="blockers/captcha.md",
               authorization_ref="ticket-42")

    # Assert
    assert row["evidence_refs"] == ["runs/rt-tests/C-001/manifest.json"]
    assert row["route_ledger_ref"] == "runs/rt-tests/C-001/routes.json"
    assert row["wall_ref"] == "blockers/captcha.md"
    assert row["authorization_ref"] == "ticket-42"


def test_row_reads_the_budget_from_the_route_ledger():
    # Arrange / Act
    row = _row(ledger={"routes": ["r1"], "attempted": [],
                       "budget": 12, "budget_exhausted": False})

    # Assert
    assert row["budget"] == 12


# ---------- build_row: fail closed on the row contract ----------

def test_recorded_action_without_a_propensity_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(strategic_action="BYPASS")


def test_propensity_without_an_action_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(propensity=0.5)


def test_propensity_outside_the_unit_interval_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(strategic_action="INVEST", propensity=1.5)


def test_non_numeric_propensity_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(strategic_action="INVEST", propensity="0.5")


def test_unregistered_strategic_action_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(strategic_action="FLEE", propensity=0.5)


def test_unsafe_episode_id_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(_record(), episode_id="../escape", ts=TS)


def test_empty_episode_id_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(_record(), episode_id="", ts=TS)


def test_empty_timestamp_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(_record(), episode_id="ep-001", ts="")


def test_missing_claim_is_refused():
    # Arrange
    record = _record()
    record.pop("claim")

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(record, episode_id="ep-001", ts=TS)


def test_non_string_evidence_ref_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(evidence_refs=[3])


# ---------- validate_row: the object's own gate ----------

def test_validate_row_accepts_a_built_row():
    # Arrange
    row = _row()

    # Act / Assert
    assert disposition.validate_row(row) == row


def test_validate_row_refuses_a_missing_schema_stamp():
    # Arrange
    row = _row()
    row.pop("schema")

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_an_unknown_disposition():
    # Arrange
    row = _row()
    row["disposition"] = "MAYBE"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_an_unknown_gate():
    # Arrange
    row = _row()
    row["gate"] = "vibes"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_action_without_propensity():
    # Arrange
    row = _row()
    row["strategic_action"] = "FIGHT"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_an_unregistered_action_word():
    # Arrange
    row = _row()
    row["strategic_action"] = "FLEE"
    row["propensity"] = 0.5

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_a_non_positive_budget():
    # Arrange
    row = _row()
    row["budget"] = 0

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


# ---------- write_row: one row per episode, observable ----------

def test_write_row_lands_the_file_mirrors_it_and_emits_the_event(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    row = _row()

    # Act
    result = _write(ws)

    # Assert
    path = ws / "runs" / "disposition" / "ep-001.json"
    assert result["path"] == path
    assert json.loads(path.read_text(encoding="utf-8")) == row
    assert result["created"] is True
    assert result["mirrored"] is True
    assert result["emitted"] is True
    assert consolidated_ledger.read(
        ws, "telemetry", schema_prefix="disposition/") == [row]
    hits = [e for e in _events(ws)
            if e.get("action") == "disposition_recorded"]
    assert len(hits) == 1
    detail = json.loads(hits[0]["detail"])
    assert detail["episode_id"] == "ep-001"
    assert detail["disposition"] == "SURRENDER"
    assert detail["evidence_refs"] == []


def test_write_row_is_idempotent_for_the_same_row(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _write(ws)

    # Act
    second = _write(ws)

    # Assert
    assert second["created"] is False
    assert second["mirrored"] is True
    assert second["emitted"] is True
    hits = [e for e in _events(ws)
            if e.get("action") == "disposition_recorded"]
    assert len(hits) == 1


def test_write_row_refuses_a_divergent_rewrite(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _write(ws)

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        _write(ws, oracle_pass=True,
               evidence_refs=["runs/verify.json"])
    path = ws / "runs" / "disposition" / "ep-001.json"
    assert json.loads(path.read_text(encoding="utf-8"))["disposition"] == (
        "SURRENDER")


def test_write_row_refuses_an_unsafe_episode_id(tmp_path):
    # Arrange
    ws = _ws(tmp_path)

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.write_row(ws, _record(), episode_id="../escape", ts=TS)
    assert not (ws / "runs" / "escape.json").exists()


def test_write_row_reports_a_failed_mirror_without_losing_the_row(
        tmp_path, monkeypatch):
    # Arrange
    ws = _ws(tmp_path)
    monkeypatch.setattr(disposition.consolidated_ledger, "append",
                        lambda *a, **k: False)

    # Act
    result = _write(ws)

    # Assert
    assert result["created"] is True
    assert result["mirrored"] is False
    assert result["path"].is_file()


def test_write_row_reports_a_failed_event_without_losing_the_row(
        tmp_path, monkeypatch):
    # Arrange
    ws = _ws(tmp_path)
    monkeypatch.setattr(disposition, "emit", lambda *a, **k: False)

    # Act
    result = _write(ws)

    # Assert
    assert result["created"] is True
    assert result["emitted"] is False
    assert result["path"].is_file()


# ---------- authorization is positive evidence, not a flag ----------

def test_authorized_episode_without_a_scope_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(authorization=None, target=None)


def test_authorized_episode_with_an_excluding_scope_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(authorization={"targets": ["other.example.com"]})


def test_out_of_scope_without_a_declared_scope_is_accepted():
    # Arrange / Act
    row = _row(authorized=False, authorization=None, target=None)

    # Assert
    assert row["disposition"] == "OUT_OF_SCOPE"


def test_authorization_ref_contradiction_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(authorization={"targets": ["target.example.com"],
                            "authorization_ref": "ticket-42"},
             authorization_ref="ticket-99")


# ---------- the row's verdict must match its evidence ----------

def test_validate_row_refuses_a_gate_disposition_mismatch():
    # Arrange
    row = _row()
    row["disposition"] = "SOLVED"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_a_missing_field():
    # Arrange
    row = _row()
    row.pop("wall_ref")

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_solved_without_evidence():
    # Arrange
    row = _row()
    row["disposition"] = "SOLVED"
    row["gate"] = "oracle_pass"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_censored_without_a_wall_ref():
    # Arrange
    row = _row()
    row["disposition"] = "CENSORED_ENV"
    row["gate"] = "wall"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_validate_row_refuses_exhausted_without_a_route_ledger_ref():
    # Arrange
    row = _row()
    row["disposition"] = "ATTEMPTED_EXHAUSTED"
    row["gate"] = "route_ledger"

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


# ---------- numeric and timestamp contracts ----------

def test_infinite_budget_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(budget=float("inf"))


def test_conflicting_budget_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        _row(budget=99, ledger={"routes": ["r"], "attempted": [],
                                "budget": 3, "budget_exhausted": False})


def test_non_iso_timestamp_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(_record(), episode_id="ep-001", ts="zzz")


def test_calendar_invalid_timestamp_is_refused():
    # Arrange / Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.build_row(_record(), episode_id="ep-001",
                              ts="2026-99-99T99:99:99Z")


def test_large_integer_budget_is_accepted():
    # Arrange / Act
    row = _row(budget=10 ** 400)

    # Assert
    assert row["budget"] == 10 ** 400


def test_unknown_row_field_is_refused():
    # Arrange
    row = _row()
    row["oracle_pass"] = True

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        disposition.validate_row(row)


def test_no_hardlink_fallback_keeps_the_no_rewrite_rule(tmp_path, monkeypatch):
    # Arrange: the no-hardlink filesystem class (os.link -> ENOTSUP).
    ws = _ws(tmp_path)

    def unsupported(*args, **kwargs):
        raise OSError("hard links not supported")

    monkeypatch.setattr(disposition.os, "link", unsupported)
    first = _write(ws)

    # Act: identical re-write, then a divergent one.
    second = _write(ws)

    # Assert: one row, one mirror, one event; the divergent rewrite raises
    # and leaves the original row untouched.
    assert first["created"] is True
    assert second["created"] is False
    assert len(consolidated_ledger.read(
        ws, "telemetry", schema_prefix="disposition/")) == 1
    hits = [e for e in _events(ws)
            if e.get("action") == "disposition_recorded"]
    assert len(hits) == 1
    with pytest.raises(disposition.DispositionError):
        _write(ws, oracle_pass=True, evidence_refs=["runs/verify.json"])
    path = ws / "runs" / "disposition" / "ep-001.json"
    assert json.loads(path.read_text(encoding="utf-8"))["disposition"] == (
        "SURRENDER")


def test_event_dedupe_requires_the_full_row_identity():
    # Arrange: same episode id, different claim -> not this row's event.
    line = json.dumps({"action": "disposition_recorded",
                       "detail": json.dumps({"episode_id": "ep-001",
                                             "claim": "C-999",
                                             "disposition": "SURRENDER"})})

    # Act / Assert
    assert disposition._event_matches(line, _row()) is False


# ---------- retry heals the mirror/event; corruption is explicit ----------

def test_retry_heals_a_failed_mirror(tmp_path, monkeypatch):
    # Arrange
    ws = _ws(tmp_path)
    state = {"fail": True}
    original = disposition.consolidated_ledger.append

    def fake_append(*args, **kwargs):
        if state["fail"]:
            return False
        return original(*args, **kwargs)

    monkeypatch.setattr(disposition.consolidated_ledger, "append",
                        fake_append)
    first = _write(ws)

    # Act
    state["fail"] = False
    second = _write(ws)

    # Assert
    assert first["mirrored"] is False
    assert second["created"] is False
    assert second["mirrored"] is True
    assert len(consolidated_ledger.read(
        ws, "telemetry", schema_prefix="disposition/")) == 1


def test_retry_heals_a_failed_event(tmp_path, monkeypatch):
    # Arrange
    ws = _ws(tmp_path)
    state = {"fail": True}
    original = disposition.emit

    def fake_emit(*args, **kwargs):
        if state["fail"]:
            return False
        return original(*args, **kwargs)

    monkeypatch.setattr(disposition, "emit", fake_emit)
    first = _write(ws)

    # Act
    state["fail"] = False
    second = _write(ws)

    # Assert
    assert first["emitted"] is False
    assert second["emitted"] is True
    hits = [e for e in _events(ws)
            if e.get("action") == "disposition_recorded"]
    assert len(hits) == 1


def test_corrupt_existing_row_is_reported(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    _write(ws)
    path = ws / "runs" / "disposition" / "ep-001.json"
    path.write_text("not json", encoding="utf-8")

    # Act / Assert
    with pytest.raises(disposition.DispositionError):
        _write(ws)


# ---------- one row under concurrent writers ----------

def test_two_writers_create_one_row(tmp_path):
    # Arrange
    import threading

    ws = _ws(tmp_path)
    barrier = threading.Barrier(2)
    results = []

    def writer():
        barrier.wait()
        results.append(disposition.write_row(
            ws, _record(), episode_id="ep-001", ts=TS))

    threads = [threading.Thread(target=writer) for _ in range(2)]

    # Act
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # Assert
    assert sum(1 for result in results if result["created"]) == 1
    assert len(consolidated_ledger.read(
        ws, "telemetry", schema_prefix="disposition/")) == 1
    hits = [e for e in _events(ws)
            if e.get("action") == "disposition_recorded"]
    assert len(hits) == 1


# ---------- the vocabulary and the ledger liveness are registry-pinned ----------

def test_strategic_vocabulary_matches_the_action_registry():
    # Arrange
    from action_space import ACTIONS, STRATEGIC

    # Act
    registered = {spec.name.split(".", 1)[1].upper()
                  for spec in ACTIONS.values() if spec.level == STRATEGIC}

    # Assert
    assert registered == set(disposition.STRATEGIC_ACTIONS)


def test_liveness_reports_the_native_disposition_schema(tmp_path):
    # Arrange
    ws = _ws(tmp_path)
    before = consolidated_ledger.liveness(ws)["telemetry:disposition/1"]

    # Act
    _write(ws)

    # Assert
    assert before == 0
    assert consolidated_ledger.liveness(ws)["telemetry:disposition/1"] == 1


# ---------- the event word is registered once ----------

def test_disposition_event_word_is_registered():
    # Arrange / Act
    word = disposition.EVENT

    # Assert
    assert word == "disposition_recorded"
    assert word in event_taxonomy.EMIT_ACTIONS
    assert event_taxonomy.EMIT_ACTIONS == sorted(set(
        event_taxonomy.EMIT_ACTIONS))
