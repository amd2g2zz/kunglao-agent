# -*- coding: utf-8 -*-
"""tests/test_winrate_curve_156.py — #156 win-rate curve aggregator.

RED-first tests pin the contract before implementation:

- hand-computable fixture stream (7 scored settlements across 2 PQ
  families, window=3) -> exact windowed / cumulative / per-family series
- empty stream -> empty face, no error (missing files are an empty
  stream, never a failure)
- malformed rows skipped per the tolerant-reader convention
  (kunglao_log.iter_jsonl skip pattern: blank / non-JSON / non-dict)
- NEUTRAL / UNRESOLVED settlements are never win-rate observations
  (roi_settlement ruling 2: nothing comparable observed != negative)
- --html: self-contained single-file rendering with REAL plotted charts
  (vendored ECharts inlined via a Jinja2 template), the JSON face inlined
  verbatim and feeding the chart, zero external fetch references
- oracle status face counts join the face where present; case-bank
  summary counts join without entering the rate denominators
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import winrate_curve as wc  # noqa: E402


WINDOW = 3


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-1\n"
        "    answers_question: PQ-alpha\n"
        "  - id: C-2\n"
        "    answers_question: PQ-beta\n",
        encoding="utf-8")
    return ws


def _row(claim_id, roi_class, idx, tags=("re", "vm")):
    return {"settle_id": f"s-{idx}", "ts": "2026-09-01T00:00:00Z",
            "claim_id": claim_id,
            "intent": {"method": "ghidra-light", "context_tags": list(tags),
                       "uncertainty": "which builder", "expected_artifact": "map"},
            "intent_met": roi_class == "POSITIVE",
            "signals": [],
            "roi_class": roi_class, "outcome": {}}


def _fixture_rows():
    """7 scored settlements over 2 PQ families (hand-computable mix)."""
    return [
        _row("C-1", "POSITIVE", 0),   # PQ-alpha P
        _row("C-2", "NEGATIVE", 1),   # PQ-beta  N
        _row("C-1", "POSITIVE", 2),   # PQ-alpha P
        _row("C-2", "POSITIVE", 3),   # PQ-beta  P
        _row("C-1", "NEGATIVE", 4),   # PQ-alpha N
        _row("C-2", "POSITIVE", 5),   # PQ-beta  P
        _row("C-1", "POSITIVE", 6),   # PQ-alpha P
    ]


def _seed_stream(ws, rows):
    p = ws / "runs" / "roi-settlements.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# --------------------------- face series: hand-computed --------------------

class TestFaceSeriesHandComputed:
    def test_overall_windowed_cumulative(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        face = wc.face(ws, window=WINDOW)
        assert face["schema"] == "winrate-curve/1"
        assert face["window"] == WINDOW
        assert face["n_settlements"] == 7
        assert face["overall"] == {"positive": 5, "negative": 2,
                                   "rate": 0.7143}
        # windows over the SCORED stream: [0:3) 2P/1N, [3:6) 2P/1N, [6:7) 1P
        assert [(w["start"], w["end"]) for w in face["windowed"]] == \
            [(0, 3), (3, 6), (6, 7)]
        assert [(w["positive"], w["negative"], w["rate"])
                for w in face["windowed"]] == \
            [(2, 1, 0.6667), (2, 1, 0.6667), (1, 0, 1.0)]
        # cumulative: running P/(P+N) after each scored settlement
        assert [c["rate"] for c in face["cumulative"]] == \
            [1.0, 0.5, 0.6667, 0.75, 0.6, 0.6667, 0.7143]
        assert [c["index"] for c in face["cumulative"]] == \
            [1, 2, 3, 4, 5, 6, 7]
        assert face["cumulative"][-1]["positive"] == 5
        assert face["cumulative"][-1]["negative"] == 2

    def test_per_pq_family_split(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        face = wc.face(ws, window=WINDOW)
        fams = face["by_family"]
        assert set(fams) == {"PQ-alpha", "PQ-beta"}
        # PQ-alpha = C-1 rows (1,3,5,7): 3P/1N
        assert fams["PQ-alpha"]["positive"] == 3
        assert fams["PQ-alpha"]["negative"] == 1
        assert fams["PQ-alpha"]["rate"] == 0.75
        assert [c["rate"] for c in fams["PQ-alpha"]["cumulative"]] == \
            [1.0, 1.0, 0.6667, 0.75]
        # PQ-beta = C-2 rows (2,4,6): 2P/1N
        assert fams["PQ-beta"]["positive"] == 2
        assert fams["PQ-beta"]["negative"] == 1
        assert fams["PQ-beta"]["rate"] == 0.6667
        assert [c["rate"] for c in fams["PQ-beta"]["cumulative"]] == \
            [0.0, 0.5, 0.6667]

    def test_family_falls_back_to_context_tags_then_unknown(self, tmp_path):
        ws = _mk_ws(tmp_path)
        rows = [
            _row("C-9", "POSITIVE", 0, tags=("vm", "re")),   # not in register
            _row("C-8", "NEGATIVE", 1, tags=()),             # no tags either
        ]
        _seed_stream(ws, rows)
        face = wc.face(ws, window=2)
        # sorted tags joined: {"vm","re"} -> "re,vm"
        assert set(face["by_family"]) == {"re,vm", "unknown"}
        assert face["by_family"]["re,vm"]["rate"] == 1.0
        assert face["by_family"]["unknown"]["rate"] == 0.0

    def test_neutral_unresolved_never_in_denominator(self, tmp_path):
        ws = _mk_ws(tmp_path)
        rows = _fixture_rows()
        rows.insert(0, _row("C-2", "UNRESOLVED", 90))
        rows.insert(4, _row("C-1", "NEUTRAL", 91))
        _seed_stream(ws, rows)
        face = wc.face(ws, window=WINDOW)
        assert face["n_settlements"] == 7
        assert face["overall"] == {"positive": 5, "negative": 2,
                                   "rate": 0.7143}


# ------------------------------ empty stream -------------------------------

class TestEmptyStream:
    def test_missing_files_empty_face_no_error(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        face = wc.face(ws, window=5)
        assert face["n_settlements"] == 0
        assert face["windowed"] == []
        assert face["cumulative"] == []
        assert face["by_family"] == {}
        assert face["overall"] == {"positive": 0, "negative": 0,
                                   "rate": None}
        assert face["oracle"] is None
        assert face["case_bank"] is None

    def test_cli_empty_stream_exit_zero(self, tmp_path, capsys):
        rc = wc.main([str(tmp_path / "ws"), "--json"])
        assert rc == 0
        face = json.loads(capsys.readouterr().out)
        assert face["n_settlements"] == 0


# ------------------------------- tolerance ---------------------------------

class TestTolerantReaders:
    def test_malformed_rows_skipped(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        clean = wc.face(ws, window=WINDOW)
        p = ws / "runs" / "roi-settlements.jsonl"
        text = p.read_text(encoding="utf-8")
        junk = ("\nnot json at all\n{\"broken\": \n[1, 2, 3]\n"
                "\"a bare string\"\nnull\n")
        p.write_text(text.replace("\n", junk, 1), encoding="utf-8")
        assert wc.face(ws, window=WINDOW) == clean

    def test_malformed_oracle_status_degrades_to_none(self, tmp_path):
        ws = _mk_ws(tmp_path)
        (ws / "runs" / "oracle-status.json").write_text(
            "{not json", encoding="utf-8")
        assert wc.face(ws, window=WINDOW)["oracle"] is None


# --------------------- oracle face + case-bank summary ---------------------

class TestOracleAndCaseBank:
    def test_oracle_status_joins_face(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        (ws / "runs" / "oracle-status.json").write_text(json.dumps({
            "schema": "oracle-status/1",
            "cases": {"CASE-A": {"status": "pass",
                                 "pending_entries": 0,
                                 "instrumented": True},
                      "CASE-B": {"status": "fail",
                                 "pending_entries": 0,
                                 "instrumented": True},
                      "CASE-C": {"status": "pending",
                                 "pending_entries": 2,
                                 "instrumented": False}},
            "low_discriminativity": [],
            "counts": {"green": 1, "red": 1, "pending": 1},
        }, indent=2), encoding="utf-8")
        oracle = wc.face(ws, window=WINDOW)["oracle"]
        assert oracle["schema"] == "oracle-status/1"
        assert oracle["counts"] == {"green": 1, "red": 1, "pending": 1}
        assert oracle["cases"] == {"CASE-A": "pass", "CASE-B": "fail",
                                   "CASE-C": "pending"}

    def test_case_bank_summary_never_enters_rate_denominators(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        (ws / "runs" / "case-bank.jsonl").write_text(
            json.dumps({"claim_id": "C-1", "method": "ghidra-light",
                        "context_tags": ["re", "vm"],
                        "roi_class": "POSITIVE", "attribution": None,
                        "ts": "t"}) + "\n"
            + json.dumps({"claim_id": "C-2", "method": "frida",
                          "context_tags": ["re"], "roi_class": "NEGATIVE",
                          "attribution": "wrong premise", "ts": "t"}) + "\n"
            + "junk line\n", encoding="utf-8")
        face = wc.face(ws, window=WINDOW)
        assert face["case_bank"] == {"n_entries": 2,
                                     "by_roi_class": {"POSITIVE": 1,
                                                      "NEGATIVE": 1}}
        # the banked mirror does NOT double-count into the rate series
        assert face["n_settlements"] == 7
        assert face["overall"] == {"positive": 5, "negative": 2,
                                   "rate": 0.7143}


# --------------------------------- CLI -------------------------------------

class TestCli:
    def test_json_flag_prints_face(self, tmp_path, capsys):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        rc = wc.main([str(ws), "--json", "--window", "3"])
        assert rc == 0
        face = json.loads(capsys.readouterr().out)
        assert face["schema"] == "winrate-curve/1"
        assert face["window"] == 3

    def test_default_prints_summary(self, tmp_path, capsys):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        assert wc.main([str(ws)]) == 0
        out = capsys.readouterr().out
        assert "winrate-curve" in out
        assert "win_rate=0.7143" in out

    def test_window_clamped_to_at_least_one(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        face = wc.face(ws, window=0)
        assert face["window"] == 1
        assert len(face["windowed"]) == 7


# -------------------------------- html face --------------------------------

# --------------- tolerance: shape gaps (r1-156-winrate review) --------------

class TestTolerantShapeGaps:
    def test_non_mapping_claim_register_tolerated(self, tmp_path):
        """Valid YAML with a non-mapping top level must not crash the
        family split — the context_tags fallback stays reachable."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "- just\n- a\n- list\n", encoding="utf-8")
        _seed_stream(ws, [_row("C-1", "POSITIVE", 0)])
        face = wc.face(ws, window=2)
        assert set(face["by_family"]) == {"re,vm"}
        assert face["by_family"]["re,vm"]["rate"] == 1.0

    def test_oracle_non_numeric_counts_never_crash(self, tmp_path):
        """A typed-garbage counts face degrades per-field (roi_settlement
        _num convention: non-numeric -> 0), never a loud crash."""
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        (ws / "runs" / "oracle-status.json").write_text(json.dumps({
            "schema": "oracle-status/1",
            "cases": {"CASE-A": {"status": "pass"}},
            "counts": {"green": "many", "red": 1, "pending": None},
        }), encoding="utf-8")
        oracle = wc.face(ws, window=WINDOW)["oracle"]
        assert oracle["counts"] == {"green": 0, "red": 1, "pending": 0}
        assert oracle["cases"] == {"CASE-A": "pass"}

    def test_face_reads_settlements_once(self, tmp_path, monkeypatch):
        """n_rows_read and the series come from ONE read (a concurrent
        settle between two reads must not skew the face)."""
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        calls = []
        real = wc.read_settlements

        def counting(ws_arg):
            calls.append(1)
            return real(ws_arg)

        monkeypatch.setattr(wc, "read_settlements", counting)
        wc.face(ws, window=WINDOW)
        assert len(calls) == 1


# ------------------------------ html face ----------------------------------
# Rendering contract (owner revision on #156): Jinja2 template + the
# vendored Apache-2.0 ECharts build INLINED into the output — real plotted
# charts, zero CDN, zero build, zero server; double-click opens offline.

class TestHtmlFace:
    def test_html_contains_real_charts_and_inlined_data(self, tmp_path):
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        out = tmp_path / "curve.html"
        rc = wc.main([str(ws), "--html", str(out), "--window", "3"])
        assert rc == 0
        html = out.read_text(encoding="utf-8")
        # REAL charts: the vendored ECharts build rides inside the file
        # (a stub or a CDN reference would be small)
        assert "echarts" in html
        assert len(html) > 500_000
        assert "setOption" in html
        # chart contract: labeled axes, legend toggling, window shading
        assert "settlement index" in html
        assert "success rate (%)" in html
        assert "markArea" in html
        assert "legend" in html
        assert "cumulative" in html
        assert "windowed" in html
        # the JSON face (primary artifact) is inlined verbatim and feeds
        # the chart — human rendering and agent data are the same bytes
        assert '"n_settlements": 7' in html
        assert '"schema": "winrate-curve/1"' in html
        assert "PQ-alpha" in html
        assert "PQ-beta" in html
        # offline discipline: no fetch-capable external reference of any kind
        assert "<script src" not in html
        assert "<link " not in html
        assert "@import" not in html
        assert html.rstrip().endswith("</html>")

    def test_html_escapes_raw_family_names(self, tmp_path):
        """Raw < > & in data must not break the inlined-JSON <script> block
        (HTML-safe JSON escapes decode to the same characters — the face
        data stays value-identical for agents)."""
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-X\n"
            "    answers_question: 'PQ <w> & \"q\"'\n",
            encoding="utf-8")
        _seed_stream(ws, [_row("C-X", "POSITIVE", 0)])
        data = wc.face(ws, window=2)
        html = wc.render_html(data)
        assert "\\u003c" in html
        assert "</scr" not in html.replace("</script>", "")
        marker = '<script type="application/json" id="winrate-face">'
        start = html.index(marker) + len(marker)
        end = html.index("</script>", start)
        assert json.loads(html[start:end]) == data

    def test_html_empty_stream_renders_notice_not_crash(self, tmp_path):
        out = tmp_path / "empty.html"
        assert wc.main([str(tmp_path / "ws"), "--html", str(out)]) == 0
        html = out.read_text(encoding="utf-8")
        assert "no scored settlements" in html
        assert "setOption" not in html
        assert "markArea" not in html

    def test_html_missing_asset_refused_loudly(self, tmp_path, monkeypatch,
                                               capsys):
        """A missing rendering asset is a loud refusal (rc 2), never a
        half-written file — and the JSON face stays unaffected."""
        ws = _mk_ws(tmp_path)
        _seed_stream(ws, _fixture_rows())
        monkeypatch.setattr(wc, "_TEMPLATE_REL", ("templates", "nope.j2"))
        out = tmp_path / "x.html"
        rc = wc.main([str(ws), "--html", str(out)])
        assert rc == 2
        assert "REFUSED" in capsys.readouterr().err
        assert not out.exists()
