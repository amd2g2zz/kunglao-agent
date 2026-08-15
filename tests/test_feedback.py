# -*- coding: utf-8 -*-
"""TDD RED — issue #241: feedback inbox + triage + stale detection.

Subagent feedback IS part of the environment: worker/reviewer reports that
contradict or extend the plan are neither blindly obeyed nor blindly ignored.
The pipeline: enqueue (append-only inbox) -> classify (env_alert = mechanical
signal straight through; everything else needs a redteam verify first) ->
check_stale (still NEW after 3 heartbeat ticks -> alarm, so the loop does not
sit on an unanswered challenge forever).

heartbeat_tick.py integration lands with #237 — this module is standalone;
tests exercise the functions + the CLI against synthetic workspaces.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import feedback as fb  # noqa: E402

def ts(minutes_ago: int = 0) -> str:
    # #375: compute AT CALL TIME — feedback.check_stale compares entry ages
    # against its own real clock; a module-frozen NOW under-ages "stale"
    # fixtures (4 * TICK_INTERVAL_MIN) in long suite runs.
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def make_entry(**overrides) -> dict:
    e = {
        "source": "worker-w1",
        "ts": ts(),
        "type": "discovery",
        "claim_id": "C-001",
        "summary": "found a second embedded config",
        "status": "NEW",
    }
    e.update(overrides)
    return e


# ---------- RED 1: enqueue appends a NEW entry with classified disposition ----------

def test_enqueue_appends_and_classifies(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"

    entry = fb.enqueue(inbox, make_entry())

    assert entry["status"] == "NEW"
    assert entry["id"]
    # discovery is not a mechanical signal -> needs redteam verification
    assert entry["needs_verify"] is True

    entries = fb.read_inbox(inbox)
    assert len(entries) == 1
    assert entries[0]["source"] == "worker-w1"
    assert entries[0]["status"] == "NEW"


# ---------- RED 2: env_alert is classified as mechanical, straight through ----------

def test_env_alert_skips_verify(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"

    entry = fb.enqueue(inbox, make_entry(type="env_alert"))

    assert entry["needs_verify"] is False


# ---------- RED 3: append-only — second enqueue does not clobber the first ----------

def test_inbox_is_append_only(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"

    fb.enqueue(inbox, make_entry(source="w1"))
    fb.enqueue(inbox, make_entry(source="w2"))

    entries = fb.read_inbox(inbox)
    assert len(entries) == 2
    assert [e["source"] for e in entries] == ["w1", "w2"]


# ---------- RED 4: classify() is a pure function (no mutation) ----------

def test_classify_pure_function():
    entry = make_entry()
    original = dict(entry)

    out = fb.classify(entry)

    assert entry == original  # input not mutated
    assert out["needs_verify"] is True
    assert out["needs_verify"] == (entry["type"] != "env_alert")


# ---------- RED 5: invalid feedback type is rejected at enqueue ----------

def test_enqueue_rejects_unknown_type(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"

    try:
        fb.enqueue(inbox, make_entry(type="not-a-type"))
    except ValueError:
        return
    raise AssertionError("unknown feedback type must raise ValueError")


# ---------- RED 6: check_stale — NEW entry older than 3 ticks alarms ----------

def test_stale_new_entry_alarms(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"
    fb.enqueue(inbox, make_entry(ts=ts(minutes_ago=4 * fb.TICK_INTERVAL_MIN)))

    stale = fb.check_stale(inbox)

    assert len(stale) == 1
    assert stale[0]["claim_id"] == "C-001"


# ---------- RED 7: fresh NEW entry is not stale ----------

def test_fresh_entry_not_stale(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"
    fb.enqueue(inbox, make_entry(ts=ts(minutes_ago=2)))

    assert fb.check_stale(inbox) == []


# ---------- RED 8: DISPOSED entry never alarms, regardless of age ----------

def test_disposed_entry_not_stale(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"
    fb.enqueue(inbox, make_entry(ts=ts(minutes_ago=24 * 60)))

    fb.dispose(inbox, {"index": 0})

    assert fb.check_stale(inbox) == []


# ---------- RED 9: empty / missing inbox does not false-alarm ----------

def test_empty_inbox_no_false_alarm(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    inbox = ws / "runs" / "feedback-inbox.yaml"

    assert fb.check_stale(inbox) == []


# ---------- RED 10: CLI enqueue/list/dispose round trip ----------

def test_cli_round_trip(tmp_path, capsys):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)

    import json
    payload = json.dumps({"source": "redteam", "type": "challenge",
                          "claim_id": "C-002", "summary": "re-derive byte-by-byte"})
    rc = fb.main([str(ws), "enqueue", payload])
    assert rc == 0

    rc = fb.main([str(ws), "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "C-002" in out and "challenge" in out

    rc = fb.main([str(ws), "dispose", '{"index": 0}'])
    assert rc == 0
    entries = fb.read_inbox(ws / "runs" / "feedback-inbox.yaml")
    assert entries[0]["status"] == "DISPOSED"
