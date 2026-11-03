# -*- coding: utf-8 -*-
"""tests/test_winrate_measured_818.py — the belief-side win-rate curve
in the MEASURED leg (issue #818 coverage climb).

The behavior pins live in fast-tier files (test_winrate_curve_156); the
CI measured-set coverage leg never executes them. This file re-pins on
a REAL workspace with REAL settlement rows: only POSITIVE/NEGATIVE
settlements score (NEUTRAL never enters a denominator), the PQ-family
join rides claim-register answers_question then context_tags, the
cumulative/windowed series carry exact integer counts with the
4-decimal rate, and the tolerant side faces (case bank, oracle status)
degrade to None without crashing.
"""
from __future__ import annotations

import json
from pathlib import Path

from rlvr import winrate as wr  # noqa: E402  (scripts/ on pytest path)


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-1\n    answers_question: how is the IV hidden\n"
        "  - id: C-2\n    answers_question: how is the IV hidden\n"
        "  - id: C-3\n    answers_question: where is the key schedule\n",
        encoding="utf-8")
    rows = [
        {"claim_id": "C-1", "roi_class": "POSITIVE",
         "intent": {"context_tags": ["unpack"]}},
        {"claim_id": "C-2", "roi_class": "POSITIVE",
         "intent": {"context_tags": ["unpack"]}},
        {"claim_id": "C-3", "roi_class": "NEGATIVE",
         "intent": {"context_tags": ["keyschedule"]}},
        # NEUTRAL: a settlement but never an observation (ruling 2)
        {"claim_id": "C-4", "roi_class": "NEUTRAL", "intent": {}},
    ]
    (ws / "runs" / "roi-settlements.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return ws


def test_claim_pq_map_and_family_join(tmp_path) -> None:
    ws = _ws(tmp_path)
    pqs = wr.claim_pq_map(ws)
    assert pqs["C-1"] == "how is the IV hidden"
    stream = wr.scored_stream(ws)
    assert len(stream) == 3                      # NEUTRAL never scores
    fams = {wr.family_of(o["row"], pqs) for o in stream}
    assert fams == {"how is the IV hidden", "where is the key schedule"}
    # a row with no register entry and no tags falls to unknown
    assert wr.family_of({"claim_id": "C-9"}, pqs) == wr.UNKNOWN_FAMILY
    assert wr.family_of({"claim_id": "C-9",
                         "intent": {"context_tags": ["b", "a"]}},
                        pqs) == "a,b"


def test_face_series_are_exact_and_windowed(tmp_path) -> None:
    ws = _ws(tmp_path)
    face = wr.face(ws, window=2)
    assert face["schema"] == wr.SCHEMA
    assert face["n_settlements"] == 3
    assert face["n_rows_read"] == 4              # NEUTRAL read but unscored
    assert face["overall"] == {"positive": 2, "negative": 1, "rate": 0.6667}
    # cumulative: running counts are exact ints, rate rounds to 4 places
    assert face["cumulative"][1] == {"index": 2, "positive": 2,
                                     "negative": 0, "rate": 1.0}
    assert face["cumulative"][2]["rate"] == 0.6667
    # windows of 2: [P,P] then [N] (a short last window is its own truth)
    assert face["windowed"][0] == {"index": 0, "start": 0, "end": 2,
                                   "positive": 2, "negative": 0,
                                   "rate": 1.0}
    assert face["windowed"][1] == {"index": 1, "start": 2, "end": 3,
                                   "positive": 0, "negative": 1,
                                   "rate": 0.0}
    # per-PQ-family split
    assert face["by_family"]["how is the IV hidden"]["rate"] == 1.0
    assert face["by_family"]["where is the key schedule"]["rate"] == 0.0


def test_empty_stream_face_and_window_clamp(tmp_path) -> None:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    face = wr.face(ws)
    assert face["n_settlements"] == 0
    assert face["overall"]["rate"] is None
    assert face["cumulative"] == [] and face["windowed"] == []
    # window < 1 clamps to 1 (meaningless zero window, not an error)
    assert wr.face(ws, window=0)["window"] == 1


def test_side_faces_are_tolerant(tmp_path) -> None:
    ws = _ws(tmp_path)
    assert wr.case_bank_summary(ws) is None
    assert wr.oracle_summary(ws) is None
    (ws / "runs" / "case-bank.jsonl").write_text(
        json.dumps({"roi_class": "POSITIVE"}) + "\n"
        + "garbage line\n", encoding="utf-8")
    bank = wr.case_bank_summary(ws)
    assert bank == {"n_entries": 1,
                    "by_roi_class": {"POSITIVE": 1}}
    (ws / "runs" / "oracle-status.json").write_text(
        json.dumps({"schema": "oracle-status/1",
                    "counts": {"green": "2", "red": None},
                    "cases": {"C-1": {"status": "pass"},
                              "bad": "not-a-dict"}}), encoding="utf-8")
    oracle = wr.oracle_summary(ws)
    assert oracle["counts"] == {"green": 2, "red": 0, "pending": 0}
    assert oracle["cases"] == {"C-1": "pass"}
    (ws / "runs" / "oracle-status.json").write_text(
        "]not json", encoding="utf-8")
    assert wr.oracle_summary(ws) is None


def test_summarize_text_faces() -> None:
    assert "no scored settlements" in wr.summarize({})
    assert "no scored settlements" in wr.summarize(
        {"n_settlements": 0})
    text = wr.summarize({"n_settlements": 3,
                         "overall": {"positive": 2, "negative": 1,
                                     "rate": 0.6667}})
    assert "3" in text
