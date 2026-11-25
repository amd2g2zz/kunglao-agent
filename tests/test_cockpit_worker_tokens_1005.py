# -*- coding: utf-8 -*-
"""tests/test_cockpit_worker_tokens_1005.py — the cockpit ratio must see
the worker transcripts (issue 1005, instrument half ①).

A Claude Code session writes its own rows to <session>.jsonl and EVERY
subagent's rows to <session>/subagents/agent-*.jsonl beside it; the main
file carries no isSidechain-truthy row at all (measured over the real
session corpus). The issue-801 fold read the main file only, so
analysis_output_tokens stayed 0 for every session that dispatched
workers, the ratio degenerated to machine_input/1, and the
harness-out-competing-analysis alarm could not be read at all.

Faces pinned here:
  (a) worker output tokens count into the analysis side;
  (b) the machine side keeps its exact scope — orchestrator input rows
      only, worker input tokens never join it;
  (c) sidechain rows inlined in the main transcript keep counting (the
      pre-change contract, unchanged);
  (d) a session with no worker transcripts folds exactly as before;
  (e) malformed worker lines are skipped, an unreadable worker transcript
      costs its own contribution and is COUNTED in the face — the sample
      itself never drops;
  (f) a worker transcript that grows changes the number;
  (g) the memo that keeps a per-tool-call sample cheap never changes the
      number: a memoized sample equals a fresh fold, and a corrupt memo
      folds from scratch."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
sys.path.insert(0, str(HOOKS))

import cost_input_capture as cic  # noqa: E402

TS = "2026-11-25T00:00:00.000Z"


def _row(*, sidechain: bool, inp: int = 0, cache: int = 0,
         out: int = 0) -> str:
    """One assistant row in the shape the CLI writes: usage under message,
    the sidechain flag at the top level."""
    return json.dumps({
        "type": "assistant", "timestamp": TS, "cwd": "/ws",
        "isSidechain": sidechain,
        "message": {"role": "assistant", "model": "worker-model",
                    "usage": {"input_tokens": inp,
                              "cache_read_input_tokens": cache,
                              "output_tokens": out}},
    })


def _session(tmp_path: Path, main_rows: list[str],
             workers: dict[str, list[str]] | None = None) -> Path:
    """The real layout: <proj>/<session>.jsonl plus
    <proj>/<session>/subagents/agent-*.jsonl beside it."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    tx = proj / "sess-1.jsonl"
    tx.write_text("\n".join(main_rows) + "\n", encoding="utf-8")
    if workers:
        side = proj / "sess-1" / "subagents"
        side.mkdir(parents=True, exist_ok=True)
        for name, rows in workers.items():
            (side / name).write_text("\n".join(rows) + "\n",
                                     encoding="utf-8")
    return tx


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


# ------------------------------------------------------------------ (a) + (b)
def test_worker_output_tokens_in_sidechain_files_count_into_analysis(
        tmp_path):
    # Arrange: orchestrator rows (no sidechain row, as every real main
    # transcript has it) and two worker transcripts.
    tx = _session(tmp_path, [_row(sidechain=False, inp=1000, out=10),
                             _row(sidechain=False, inp=500, cache=7,
                                  out=20)],
                  workers={"agent-a.jsonl": [_row(sidechain=True, out=300),
                                             _row(sidechain=True, out=400)],
                          "agent-b.jsonl": [_row(sidechain=True,
                                                  inp=9999, out=500)]})

    # Act
    machine, analysis = cic._fold_usage(tx)

    # Assert: machine = orchestrator input incl. cache reads; analysis =
    # every worker output token, none of which the main file carries.
    assert machine == 1507
    assert analysis == 1200, ("worker transcripts are where the analysis "
                              "side lives; a fold that misses them reports "
                              "0")


def test_worker_input_tokens_do_not_enter_the_machine_side(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=1000)],
                  workers={"agent-a.jsonl": [_row(sidechain=True, inp=9999,
                                                  cache=8888, out=1)]})

    # Act
    machine, analysis = cic._fold_usage(tx)

    # Assert: the machine:analysis scope is orchestrator input over worker
    # output — widening the machine side would move the ratio's numerator.
    assert machine == 1000
    assert analysis == 1


# --------------------------------------------------------------------- (c)
def test_sidechain_rows_inlined_in_the_main_transcript_still_count(
        tmp_path):
    # Arrange: a harness that keeps the worker rows in the main file.
    tx = _session(tmp_path, [_row(sidechain=False, inp=1000, out=10),
                             _row(sidechain=True, out=250)])

    # Act
    machine, analysis = cic._fold_usage(tx)

    # Assert: the pre-change contract holds on its own terms.
    assert (machine, analysis) == (1000, 250)


# --------------------------------------------------------------------- (d)
def test_session_without_worker_transcripts_folds_as_before(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=400, out=4)])

    # Act
    machine, analysis = cic._fold_usage(tx)
    found = cic.sidechain_transcripts(tx)

    # Assert
    assert found == []
    assert (machine, analysis) == (400, 0)


def test_sidechain_transcripts_are_found_beside_the_main_file(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=1)],
                  workers={"agent-a.jsonl": [_row(sidechain=True, out=1)],
                           "agent-b.jsonl": [_row(sidechain=True, out=2)]})

    # Act
    found = cic.sidechain_transcripts(tx)

    # Assert: both worker files, in a stable order.
    assert [p.name for p in found] == ["agent-a.jsonl", "agent-b.jsonl"]


# --------------------------------------------------------------------- (e)
def test_row_without_a_usage_face_is_skipped_not_fatal(tmp_path):
    # Arrange: rows whose message is absent or not an object — the fold now
    # walks every worker file of a session, so one odd row must not cost the
    # whole sample.
    tx = _session(tmp_path, [json.dumps({"type": "system", "subtype": "x"}),
                             json.dumps({"type": "assistant",
                                         "message": "a bare string"}),
                             _row(sidechain=False, inp=120, out=6)],
                  workers={"agent-a.jsonl": [
                      json.dumps({"type": "user", "message": ["not",
                                                               "a",
                                                               "dict"]}),
                      _row(sidechain=True, out=40)]})

    # Act
    machine, analysis = cic._fold_usage(tx)

    # Assert
    assert (machine, analysis) == (120, 40)


def test_malformed_worker_line_is_skipped_not_fatal(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=100)],
                  workers={"agent-a.jsonl": ["{not json",
                                             _row(sidechain=True, out=70),
                                             ""]})

    # Act
    machine, analysis = cic._fold_usage(tx)

    # Assert
    assert machine == 100
    assert analysis == 70


def test_unreadable_worker_file_keeps_the_sample_and_shows_in_the_face(
        tmp_path):
    # Arrange: a directory sitting on the worker-file name — reading it
    # raises the same OSError family a torn permission bite does.
    tx = _session(tmp_path, [_row(sidechain=False, inp=100, out=5)],
                  workers={"agent-a.jsonl": [_row(sidechain=True,
                                                  out=70)]})
    (tx.parent / "sess-1" / "subagents" / "agent-broken.jsonl").mkdir()
    ws = _ws(tmp_path)

    # Act
    face = cic.cockpit_ratio(ws, tx)

    # Assert: one contribution lost, named in the face; the sample itself
    # never drops because a worker file could not be read.
    assert face is not None, "an unreadable worker file must not void the face"
    assert face["analysis_output_tokens"] == 70
    assert face["worker_unread"] == 1


# --------------------------------------------------------------------- (f)
def test_worker_transcript_growth_changes_the_analysis_total(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=100)],
                  workers={"agent-a.jsonl": [_row(sidechain=True,
                                                  out=70)]})

    # Act
    first = cic._fold_usage(tx)[1]
    worker = tx.parent / "sess-1" / "subagents" / "agent-a.jsonl"
    with worker.open("a", encoding="utf-8") as f:
        f.write(_row(sidechain=True, out=35) + "\n")
    second = cic._fold_usage(tx)[1]

    # Assert
    assert first == 70
    assert second == 105


# --------------------------------------------------------------------- (g)
def test_memoized_sample_equals_the_fresh_fold(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=1000, out=9)],
                  workers={"agent-a.jsonl": [_row(sidechain=True, out=300),
                                             _row(sidechain=True, out=400)],
                           "agent-b.jsonl": [_row(sidechain=True, out=500)]})
    ws = _ws(tmp_path)

    # Act: the hook path (memo written), then the pure path (no memo).
    face = cic.cockpit_ratio(ws, tx)
    fresh_machine, fresh_analysis = cic._fold_usage(tx)

    # Assert: the memo is a speed face, never a number of its own.
    assert face["analysis_output_tokens"] == fresh_analysis == 1200
    assert face["machine_input_tokens"] == fresh_machine


def test_corrupt_memo_does_not_change_the_number(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=1000, out=9)],
                  workers={"agent-a.jsonl": [_row(sidechain=True,
                                                  out=300)]})
    ws = _ws(tmp_path)
    cic.cockpit_ratio(ws, tx)
    (ws / cic.WORKER_MEMO_REL).write_text("{ half a json", encoding="utf-8")

    # Act
    face = cic.cockpit_ratio(ws, tx)

    # Assert: junk memo -> recompute from the transcripts, exact again.
    assert face["analysis_output_tokens"] == 300


def test_unusable_memo_entry_is_a_miss_and_folds_from_disk(tmp_path):
    # Arrange: a memo entry whose fingerprint fields are junk.
    tx = _session(tmp_path, [_row(sidechain=False, inp=1000, out=9)],
                  workers={"agent-a.jsonl": [_row(sidechain=True,
                                                  out=300)]})
    ws = _ws(tmp_path)
    cic.cockpit_ratio(ws, tx)
    memo_path = ws / cic.WORKER_MEMO_REL
    doc = json.loads(memo_path.read_text(encoding="utf-8"))
    doc["files"]["agent-a.jsonl"]["size"] = "not a number"
    memo_path.write_text(json.dumps(doc), encoding="utf-8")

    # Act
    face = cic.cockpit_ratio(ws, tx)

    # Assert: a junk fingerprint is a miss — recomputed exactly, then
    # rewritten with a usable entry, never a voided sample.
    assert face["analysis_output_tokens"] == 300
    fixed = json.loads(memo_path.read_text(encoding="utf-8"))
    worker = tx.parent / "sess-1" / "subagents" / "agent-a.jsonl"
    assert fixed["files"]["agent-a.jsonl"]["size"] == worker.stat().st_size


def test_worker_memo_lands_as_a_workspace_sidecar(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=10)],
                  workers={"agent-a.jsonl": [_row(sidechain=True, out=300)]})
    ws = _ws(tmp_path)

    # Act
    cic.cockpit_ratio(ws, tx)

    # Assert: the hook writes ONE new workspace face, stamped, beside the
    # ratio face it already owns.
    memo = json.loads((ws / cic.WORKER_MEMO_REL).read_text(encoding="utf-8"))
    assert memo["schema"] == cic.WORKER_MEMO_SCHEMA
    assert memo["files"]["agent-a.jsonl"]["tokens"] == 300


# ----------------------------------------------------------------- acceptance
def test_cockpit_face_reports_nonzero_worker_output_and_a_real_ratio(
        tmp_path):
    # Arrange: a tool call carrying the session transcript, workers ran.
    ws = _ws(tmp_path)
    tx = _session(tmp_path, [_row(sidechain=False, inp=9000, cache=1000,
                                  out=100)],
                  workers={"agent-a.jsonl": [_row(sidechain=True,
                                                  out=2000)]})

    # Act
    cic.process_event({"cwd": str(ws), "tool_name": "Bash",
                       "tool_response": "no cost line here",
                       "transcript_path": str(tx)})

    # Assert: the recorded defect was analysis_output_tokens == 0 and
    # ratio == machine_input/1; both faces now carry worker spend.
    face = json.loads(
        (ws / cic.COCKPIT_RATIO_REL).read_text(encoding="utf-8"))
    assert face["analysis_output_tokens"] == 2000
    assert face["worker_transcripts"] == 1
    assert face["ratio"] == pytest.approx(10000 / 2000)
    assert face["alarm"] is True


def test_ratio_denominator_is_the_worker_output_not_one(tmp_path):
    # Arrange
    tx = _session(tmp_path, [_row(sidechain=False, inp=100)],
                  workers={"agent-a.jsonl": [_row(sidechain=True, out=50)]})

    # Act
    ratio = cic.compute_ratio(tx)

    # Assert: a fold that saw no worker would answer 100/1.
    assert ratio == pytest.approx(2.0)
