# -*- coding: utf-8 -*-
"""tests/test_prediction_hit_rate_135.py — issue-135 prediction-calibration
metric.

Contract-pinning tests written ahead of the implementation:

- fixture bank (runs/case-bank.jsonl) with a KNOWN intent/outcome mix —
  6 scored rows: 2 predicted-green (confident declaration -> POSITIVE),
  1 predicted-green->red (a WRONG prediction), 2 lucky-green
  (hedged declaration -> POSITIVE: success without a committed
  prediction), 1 declared-uncertain->red — every count and rate in the
  face is asserted EXACTLY.
- luck-vs-skill visibility: the whole point of issue 135 — hits (2) must be
  distinguishable from successes (4) in the same face.
- rolling-window hit-rate series (window=3 and the named DEFAULT_WINDOW)
  with exact per-window numbers.
- per-roi_class / per-uncertainty-keyword breakdowns, exact.
- NEUTRAL / UNRESOLVED rows are never scored observations (roi_settlement
  ruling 2 convention, mirroring winrate_curve counting).
- tolerant reader: missing bank = empty face, malformed rows skipped.
- schema token + the named rolling-window constant.
- cockpit text face (summarize) carries the hit-rate line; empty face text.
- ZERO-CONSUMPTION PIN: no ranker / gate / hook module reads the metric —
  the only allowed references are the producer module itself and the
  statusline snapshot display face (v0.2 issue 129 does the consuming).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

ROI_POSITIVE = "POSITIVE"
ROI_NEGATIVE = "NEGATIVE"


def _row(claim_id, roi_class, uncertainty, tags=("re", "vm")):
    """One banked case row (case_bank.py schema, issues-110/146 lineage)."""
    return {
        "ts": "2026-09-15T00:00:00Z",
        "claim_id": claim_id,
        "method": "static",
        "context_tags": list(tags),
        "intent_uncertainty": uncertainty,
        "outcome_observed": {},
        "roi_class": roi_class,
        "attribution": ("verdict=fails checker=spawn signals=none"
                        if roi_class == ROI_NEGATIVE else None),
        "premise_correction": None,
        "how": None,
    }


def _fixture_rows():
    """6 scored rows — the exact mix the issue-135 task card prescribes.

    rows 1-2   predicted-green -> green   (confident declaration, POSITIVE)
    row  3     predicted-green -> red     (confident and WRONG — the
                                          prediction error issue 135 exists
                                          to make visible)
    rows 4-5   lucky-green                (hedged declaration, POSITIVE —
                                          success by luck, no commitment)
    row  6     declared-uncertain -> red  (hedged and red — honest hedge)
    """
    return [
        _row("C-1", ROI_POSITIVE, "binary is UPX-packed"),
        _row("C-2", ROI_POSITIVE, "builder is gcc-12"),
        _row("C-3", ROI_NEGATIVE, "crypto table at 0x401000"),
        _row("C-4", ROI_POSITIVE, "maybe packed with UPX or similar"),
        _row("C-5", ROI_POSITIVE, "unclear whether anti-debug present"),
        _row("C-6", ROI_NEGATIVE, "unconfirmed obfuscation in packer"),
    ]


def _seed_bank(ws, rows):
    bank = ws / "runs" / "case-bank.jsonl"
    bank.parent.mkdir(parents=True, exist_ok=True)
    with bank.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


HIT_RATE = round(2 / 3, 4)          # 2 hits / 3 committed predictions
SUCCESS_RATE = round(4 / 6, 4)      # 4 greens / 6 scored rows


# --------------------------- face: exact counts ----------------------------

class TestFaceExactNumbers:
    def test_overall_counts_are_exact(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        f = phr.face(ws)
        assert f["schema"] == "prediction-hit-rate/1"
        assert f["n_rows_read"] == 6
        assert f["n_scored"] == 6
        ov = f["overall"]
        assert ov["positive"] == 4
        assert ov["negative"] == 2
        assert ov["predicted"] == 3          # rows 1-3 committed
        assert ov["uncertain"] == 3          # rows 4-6 hedged
        assert ov["hits"] == 2               # rows 1-2
        assert ov["misses"] == 1             # row 3 — the wrong prediction
        assert ov["hit_rate"] == HIT_RATE
        assert ov["success_rate"] == SUCCESS_RATE

    def test_luck_is_distinguishable_from_skill(self, tmp_path):
        """The issue-135 thesis: success rate alone cannot see the 2 lucky
        greens; the hit-rate face must separate hits from successes."""
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        f = phr.face(ws)
        ov = f["overall"]
        assert ov["hits"] != ov["positive"], (
            "2 of the 4 greens were luck — hits must not equal successes")
        assert ov["predicted"] < f["n_scored"]

    def test_windowed_exact_window_3(self, tmp_path):
        """window=3 over [P,P,N,Pc?,...] — window 0 is the three confident
        rows (2 hits), window 1 is the three hedged rows (no commitment,
        hit_rate None — insufficient, never 0.0)."""
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        f = phr.face(ws, window=3)
        w0, w1 = f["windowed"]
        assert (w0["index"], w0["start"], w0["end"]) == (0, 0, 3)
        assert w0["n"] == 3 and w0["predicted"] == 3 and w0["hits"] == 2
        assert w0["hit_rate"] == HIT_RATE
        assert (w1["index"], w1["start"], w1["end"]) == (1, 3, 6)
        assert w1["n"] == 3 and w1["predicted"] == 0 and w1["hits"] == 0
        assert w1["hit_rate"] is None
        # overall is window-independent
        assert f["overall"]["hit_rate"] == HIT_RATE

    def test_windowed_default_window_named_constant(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        assert isinstance(phr.DEFAULT_WINDOW, int)
        assert phr.DEFAULT_WINDOW >= 1
        f = phr.face(ws)  # default window
        assert f["window"] == phr.DEFAULT_WINDOW
        starts = [w["start"] for w in f["windowed"]]
        assert starts == list(range(0, 6, phr.DEFAULT_WINDOW))
        w_last = f["windowed"][-1]
        assert w_last["end"] == 6 and w_last["start"] == 5  # partial window


# --------------------------- breakdowns: exact -----------------------------

class TestBreakdowns:
    def test_by_roi_class_exact(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        f = phr.face(ws)
        byc = f["by_roi_class"]
        assert byc["POSITIVE"] == {"n": 4, "predicted": 2, "uncertain": 2,
                                   "hits": 2, "misses": 0}
        assert byc["NEGATIVE"] == {"n": 2, "predicted": 1, "uncertain": 1,
                                   "hits": 0, "misses": 1}
        assert byc["NEUTRAL"] == {"n": 0, "predicted": 0, "uncertain": 0,
                                  "hits": 0, "misses": 0}
        assert byc["UNRESOLVED"] == {"n": 0, "predicted": 0, "uncertain": 0,
                                     "hits": 0, "misses": 0}

    def test_by_keyword_exact(self, tmp_path):
        """Each hedge keyword: how many banked rows carry it and what
        landed — the luck-side rate per keyword (P share of scored)."""
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        f = phr.face(ws)
        byk = f["by_keyword"]
        assert byk["maybe"] == {"n": 1, "positive": 1, "negative": 0,
                                "rate": 1.0}
        assert byk["unclear"] == {"n": 1, "positive": 1, "negative": 0,
                                  "rate": 1.0}
        assert byk["unconfirmed"] == {"n": 1, "positive": 0, "negative": 1,
                                      "rate": 0.0}
        # only keywords actually present in the bank appear
        assert set(byk) == {"maybe", "unclear", "unconfirmed"}

    def test_keyword_match_is_case_insensitive(self, tmp_path):
        ws = _mk_ws(tmp_path)
        rows = [_row("C-9", ROI_NEGATIVE, "MAYBE refactored handler")]
        _seed_bank(ws, rows)
        import prediction_hit_rate as phr
        f = phr.face(ws)
        assert f["by_keyword"]["maybe"]["n"] == 1
        assert f["overall"]["uncertain"] == 1


# --------------------------- counting conventions ---------------------------

class TestCountingConventions:
    def test_neutral_unresolved_never_scored(self, tmp_path):
        """Ruling-2 convention (winrate_curve mirror): nothing comparable
        observed is never a scored observation — no denominators."""
        ws = _mk_ws(tmp_path)
        rows = _fixture_rows() + [
            _row("C-7", "NEUTRAL", "maybe a unpacking stub"),
            _row("C-8", "UNRESOLVED", "unverified export table"),
        ]
        _seed_bank(ws, rows)
        import prediction_hit_rate as phr
        f = phr.face(ws)
        assert f["n_rows_read"] == 8
        assert f["n_scored"] == 6
        assert f["overall"]["positive"] == 4
        assert f["overall"]["negative"] == 2
        assert f["overall"]["uncertain"] == 3  # the unscored hedges don't count
        assert f["by_roi_class"]["NEUTRAL"]["n"] == 1
        assert f["by_roi_class"]["UNRESOLVED"]["n"] == 1

    def test_missing_bank_is_empty_face(self, tmp_path):
        ws = _mk_ws(tmp_path)
        import prediction_hit_rate as phr
        f = phr.face(ws)  # never raises
        assert f["n_rows_read"] == 0
        assert f["n_scored"] == 0
        assert f["overall"]["hit_rate"] is None
        assert f["overall"]["success_rate"] is None
        assert f["windowed"] == []
        assert f["by_keyword"] == {}

    def test_malformed_rows_skipped(self, tmp_path):
        ws = _mk_ws(tmp_path)
        bank = ws / "runs" / "case-bank.jsonl"
        bank.parent.mkdir(parents=True, exist_ok=True)
        good = _row("C-1", ROI_POSITIVE, "binary is UPX-packed")
        bank.write_text(
            "not json at all\n"
            + json.dumps(good, ensure_ascii=False) + "\n"
            + '[1, 2, 3]\n',
            encoding="utf-8")
        import prediction_hit_rate as phr
        f = phr.face(ws)
        assert f["n_rows_read"] == 1
        assert f["n_scored"] == 1

    def test_window_below_one_clamps(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        f = phr.face(ws, window=0)
        assert f["window"] == 1
        assert len(f["windowed"]) == 6


# --------------------------- cockpit faces ----------------------------------

class TestCockpitFaces:
    def test_summarize_carries_hit_rate_line(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        text = phr.summarize(phr.face(ws))
        assert "hit_rate=0.6667" in text
        assert "success_rate=0.6667" in text
        assert "hits=2" in text and "misses=1" in text

    def test_summarize_empty_face(self, tmp_path):
        import prediction_hit_rate as phr
        text = phr.summarize(phr.face(_mk_ws(tmp_path)))
        assert "prediction-hit-rate" in text
        assert "empty" in text

    def test_cli_json_face(self, tmp_path, capsys):
        ws = _mk_ws(tmp_path)
        _seed_bank(ws, _fixture_rows())
        import prediction_hit_rate as phr
        assert phr.main([str(ws), "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["overall"]["hit_rate"] == HIT_RATE


# --------------------------- zero-consumption pin ---------------------------

class TestZeroConsumptionPin:
    def test_no_ranker_or_gate_reads_the_metric(self):
        """PRODUCE only: the metric may be referenced by its own module and
        the statusline snapshot DISPLAY face. Any ranker / gate / hook /
        other consumer reference is a contract violation (v0.2 issue 129
        does the consuming)."""
        allowed = {"prediction_hit_rate.py", "statusline_snapshot.py"}
        scanned = sorted(
            list((ROOT / "scripts").glob("*.py"))
            + list((ROOT / "hooks").glob("*.py")))
        hits = []
        for p in scanned:
            if p.name in allowed:
                continue
            if "prediction_hit_rate" in p.read_text(encoding="utf-8",
                                                    errors="replace"):
                hits.append(p.name)
        assert not hits, (
            f"zero-consumption pin violated by: {hits} — the metric is "
            f"PRODUCE-only until v0.2 #129")
