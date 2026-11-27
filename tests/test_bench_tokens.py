# -*- coding: utf-8 -*-
"""B3 (#823): bench_tokens — the ONLY new metering piece of the bench.

transcript JSONL → {total_in, total_out, cache_creation, cache_read,
grand_total, wall_s, user_turn_count, usage_incomplete}.
user_turn_count > 1 = human-intervention evidence (z_self channel 4).

#1094: the receipt is a SESSION fold — the main transcript plus the
worker transcripts beside it in the real on-disk layout
(<session>/subagents/agent-*.jsonl). Pins: the worker population enters
the cost unit, user turns stay main-only, partial truth stays visible,
and the sums are deterministic in the canonical file order.
"""
import json
from pathlib import Path

import bench_tokens as bt


def _row(typ, ts, usage=None, content="hi"):
    row = {"type": typ, "timestamp": ts, "message": {"role": typ, "content": content}}
    if usage is not None:
        row["message"]["usage"] = usage
    return row


def _write(tmp: Path, rows) -> Path:
    p = tmp / "transcript.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return p


def _write_session(tmp: Path, main_rows, workers: dict) -> Path:
    """The real layout: <dir>/<session>.jsonl with <dir>/<session>/subagents/
    agent-*.jsonl beside it. workers maps filename (without the agent-
    prefix convention enforcement) -> rows."""
    main = tmp / "sess.jsonl"
    with main.open("w", encoding="utf-8") as f:
        for r in main_rows:
            f.write(json.dumps(r) + "\n")
    side = tmp / "sess" / "subagents"
    side.mkdir(parents=True, exist_ok=True)
    for name, rows in workers.items():
        with (side / name).open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
    return main


def test_totals_accumulate(tmp_path):
    p = _write(tmp_path, [
        _row("user", "2026-08-28T10:00:00Z"),
        _row("assistant", "2026-08-28T10:01:00Z",
             {"input_tokens": 100, "output_tokens": 50,
              "cache_creation_input_tokens": 30, "cache_read_input_tokens": 10}),
        _row("assistant", "2026-08-28T10:02:00Z",
             {"input_tokens": 200, "output_tokens": 70,
              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 40}),
    ])
    t = bt.collect(p)
    assert t["total_in"] == 300
    assert t["total_out"] == 120
    assert t["cache_creation"] == 30
    assert t["cache_read"] == 50
    assert t["grand_total"] == 500
    assert t["usage_incomplete"] is False


def test_wall_seconds(tmp_path):
    p = _write(tmp_path, [
        _row("user", "2026-08-28T10:00:00Z"),
        _row("assistant", "2026-08-28T10:30:00Z",
             {"input_tokens": 1, "output_tokens": 1}),
    ])
    assert bt.collect(p)["wall_s"] == 1800


def test_missing_usage_flags_incomplete(tmp_path):
    p = _write(tmp_path, [
        _row("user", "2026-08-28T10:00:00Z"),
        _row("assistant", "2026-08-28T10:01:00Z",
             {"input_tokens": 10, "output_tokens": 5}),
        _row("assistant", "2026-08-28T10:02:00Z"),  # no usage at all
    ])
    t = bt.collect(p)
    assert t["usage_incomplete"] is True
    assert t["total_in"] == 10  # present rows still counted


def test_user_turns_exclude_tool_results(tmp_path):
    tool_result_row = {"type": "user", "timestamp": "2026-08-28T10:01:00Z",
                       "message": {"role": "user", "content": [
                           {"tool_use_id": "t1", "type": "tool_result",
                            "content": "output"}]}}
    p = _write(tmp_path, [
        _row("user", "2026-08-28T10:00:00Z"),
        _row("assistant", "2026-08-28T10:01:30Z", {"input_tokens": 1, "output_tokens": 1}),
        tool_result_row,
        _row("assistant", "2026-08-28T10:02:00Z", {"input_tokens": 1, "output_tokens": 1}),
    ])
    t = bt.collect(p)
    assert t["user_turn_count"] == 1  # the tool_result user row is not a human turn


def test_human_intervention_detected(tmp_path):
    p = _write(tmp_path, [
        _row("user", "2026-08-28T10:00:00Z"),
        _row("assistant", "2026-08-28T10:01:00Z", {"input_tokens": 1, "output_tokens": 1}),
        _row("user", "2026-08-28T10:05:00Z", content="stop, do it differently"),
    ])
    t = bt.collect(p)
    assert t["user_turn_count"] == 2
    assert bt.human_intervention(t) is True


# ------------------------------------------------- #1094 session-scope pins

_MAIN = [
    _row("user", "2026-11-01T10:00:00Z"),
    _row("assistant", "2026-11-01T10:01:00Z",
         {"input_tokens": 100, "output_tokens": 50,
          "cache_creation_input_tokens": 30, "cache_read_input_tokens": 10}),
]

_WORKER_A = [
    {"type": "user", "timestamp": "2026-11-01T10:00:30Z",
     "message": {"role": "user", "content": "dispatch envelope"},  # not a human
     "isSidechain": True},
    {"type": "assistant", "timestamp": "2026-11-01T10:03:00Z",
     "message": {"role": "assistant", "content": "w",
                 "usage": {"input_tokens": 40, "output_tokens": 20,
                           "cache_creation_input_tokens": 5,
                           "cache_read_input_tokens": 200}},
     "isSidechain": True},
]

_WORKER_B = [
    {"type": "assistant", "timestamp": "2026-11-01T10:04:00Z",
     "message": {"role": "assistant", "content": "w2",
                 "usage": {"input_tokens": 7, "output_tokens": 3,
                           "cache_creation_input_tokens": 2,
                           "cache_read_input_tokens": 1}},
     "isSidechain": True},
]


def test_worker_transcripts_count_into_the_session_total(tmp_path):
    """#1094 pin: the real layout's worker population enters grand_total —
    the session receipt is strictly greater than the main file alone."""
    main = _write_session(tmp_path, _MAIN,
                          {"agent-aaa.jsonl": _WORKER_A,
                           "agent-bbb.jsonl": _WORKER_B})
    session = bt.collect(main)
    # fold the main file alone by pointing at a sessionless copy
    lone = tmp_path / "lone.jsonl"
    lone.write_text((tmp_path / "sess.jsonl").read_text(encoding="utf-8"),
                    encoding="utf-8")
    main_only = bt.collect(lone)
    assert session["grand_total"] > main_only["grand_total"]
    assert session["grand_total"] == (100 + 50 + 30 + 10
                                      + 40 + 20 + 5 + 200
                                      + 7 + 3 + 2 + 1)
    assert session["total_in"] == 100 + 40 + 7
    assert session["total_out"] == 50 + 20 + 3
    assert session["cache_creation"] == 30 + 5 + 2
    assert session["cache_read"] == 10 + 200 + 1
    assert session["worker_transcripts"] == 2


def test_session_without_workers_matches_the_single_file_receipt(tmp_path):
    """No subagents/ beside the transcript -> the fold is exactly the old
    single-file receipt (the capability_report reconciliation face)."""
    main = _write_session(tmp_path, _MAIN, {})
    t = bt.collect(main)
    assert t["grand_total"] == 100 + 50 + 30 + 10
    assert t["worker_transcripts"] == 0
    assert t["worker_unread"] == 0
    assert t["usage_incomplete"] is False


def test_user_turns_are_counted_from_the_main_transcript_only(tmp_path):
    """Worker files carry type=user rows that are dispatch envelopes —
    they must not become phantom human interventions (z_self channel 4)."""
    main = _write_session(tmp_path, _MAIN, {"agent-aaa.jsonl": _WORKER_A})
    t = bt.collect(main)
    assert t["user_turn_count"] == 1  # only the main file's opening prompt


def test_worker_row_without_usage_flags_incomplete(tmp_path):
    worker_row_no_usage = {"type": "assistant",
                           "timestamp": "2026-11-01T10:05:00Z",
                           "message": {"role": "assistant", "content": "x"},
                           "isSidechain": True}
    main = _write_session(tmp_path, _MAIN,
                          {"agent-aaa.jsonl": _WORKER_A + [worker_row_no_usage]})
    t = bt.collect(main)
    assert t["usage_incomplete"] is True
    # the rows that do carry usage are still summed (partial truth)
    assert t["total_in"] == 100 + 40


def test_unreadable_worker_transcript_counts_unread_and_keeps_partial_truth(
        tmp_path):
    """A worker path that cannot be read costs only its own contribution:
    the fold continues, the loss is counted, the receipt says incomplete."""
    main = _write_session(tmp_path, _MAIN, {"agent-aaa.jsonl": _WORKER_A})
    # a directory where a file is expected: read_text raises OSError on
    # every platform (no chmod tricks)
    (tmp_path / "sess" / "subagents" / "agent-zzz.jsonl").mkdir()
    t = bt.collect(main)
    assert t["worker_transcripts"] == 2
    assert t["worker_unread"] == 1
    assert t["usage_incomplete"] is True
    assert t["total_in"] == 100 + 40  # agent-aaa's rows still count


def test_session_sum_is_the_input_order_sum_of_its_files(tmp_path):
    """Determinism pin: the receipt equals the per-file folds summed in
    the canonical order, and repeated folds are identical (in-order
    integer accumulation, never a reordered/pairwise reduction)."""
    main = _write_session(tmp_path, _MAIN,
                          {"agent-aaa.jsonl": _WORKER_A,
                           "agent-bbb.jsonl": _WORKER_B})
    first = bt.collect(main)
    second = bt.collect(main)
    assert first == second
    # per-file baselines are ISOLATED copies (a session-scope collect on
    # the main file would fold the workers in — that is the feature)
    iso = tmp_path / "iso"
    iso.mkdir()
    baselines = []
    for src in (tmp_path / "sess.jsonl",
                tmp_path / "sess" / "subagents" / "agent-aaa.jsonl",
                tmp_path / "sess" / "subagents" / "agent-bbb.jsonl"):
        lone = iso / src.name
        lone.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        baselines.append(bt.collect(lone))
    for field in ("total_in", "total_out", "cache_creation", "cache_read"):
        running = 0
        for receipt in baselines:
            running += receipt[field]  # canonical order, in-order addition
        assert first[field] == running
    assert first["grand_total"] == (first["total_in"] + first["total_out"]
                                    + first["cache_creation"]
                                    + first["cache_read"])


def test_session_files_order_main_first_workers_sorted():
    """The canonical fold order: main transcript first, then the worker
    files sorted by name — the order the determinism pin relies on."""
    files = bt.session_transcript_files(Path("/x/sess.jsonl"))
    assert files == [Path("/x/sess.jsonl")]  # no layout -> main alone
    # with a layout the enumeration is imported from the shared reader
    import _common
    assert bt.session_transcript_files is _common.session_transcript_files


def test_wall_s_spans_the_worker_that_outlives_the_main_file(tmp_path):
    """wall_s is the session's first→last timestamp span across ALL its
    transcripts (measured: real workers write their last row after the
    main file's last row)."""
    late_worker = [
        {"type": "assistant", "timestamp": "2026-11-01T11:00:00Z",
         "message": {"role": "assistant", "content": "late",
                     "usage": {"input_tokens": 1, "output_tokens": 1}},
         "isSidechain": True},
    ]
    main = _write_session(tmp_path, _MAIN, {"agent-late.jsonl": late_worker})
    t = bt.collect(main)
    assert t["wall_s"] == 3600  # 10:00:00Z -> 11:00:00Z, not ->10:01:00Z


def test_all_four_worker_faces_enter_grand_total(tmp_path):
    """The cost unit carries all four token faces of the worker
    population — including cache_creation, which no ratio-side fold
    covers (the reason the receipt is not built from the ratio fold)."""
    main = _write_session(tmp_path, _MAIN, {"agent-cc.jsonl": [
        {"type": "assistant", "timestamp": "2026-11-01T10:02:00Z",
         "message": {"role": "assistant", "content": "cc",
                     "usage": {"input_tokens": 0, "output_tokens": 0,
                               "cache_creation_input_tokens": 999,
                               "cache_read_input_tokens": 0}},
         "isSidechain": True}]})
    t = bt.collect(main)
    assert t["grand_total"] == 190 + 999
    assert t["cache_creation"] == 30 + 999
