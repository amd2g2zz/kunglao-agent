# -*- coding: utf-8 -*-
"""B3 (#823): bench_tokens — the ONLY new metering piece of the bench.

transcript JSONL → {total_in, total_out, cache_creation, cache_read,
grand_total, wall_s, user_turn_count, usage_incomplete}.
user_turn_count > 1 = human-intervention evidence (z_self channel 4).
"""
import json
import sys
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
