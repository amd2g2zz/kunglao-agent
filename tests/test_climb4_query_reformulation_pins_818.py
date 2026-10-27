#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_query_reformulation_pins_818.py — #818 climb segment 4K.

Behavior pins for the #487 faceted-retrieval half of query_formulation.py
(the formulation half already carries its own file): the baseline term
face, the corpus loader (determinism, suffix/size filters, tolerant
skips), the half-ceiling hit rule with its ranking and cap, the one-retry
reformulation contract (provenance rewording minus originals, capped,
honest corpus-lack over fake retries), the coverage matrix verdicts
(hit / reformulated-hit / corpus-lack / missing-corpus degradation), the
compact audit face, the corpus label, the host convenience, and the CLI
contract over a real trigger stamp.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import query_formulation as qf  # noqa: E402


# ------------------------------------------------------------- primitives

class TestPrimitives:
    def test_baseline_terms_are_the_token_and_its_words(self) -> None:
        assert qf.fragment_baseline_terms("anti_debug.") == [
            "anti debug", "anti", "debug"]  # '.' normalizes to a space
        assert qf.fragment_baseline_terms("  ") == []

    def test_half_ceiling_rule(self) -> None:
        assert qf._need(["a"]) == 1
        assert qf._need(["a", "b"]) == 1
        assert qf._need(["a", "b", "c"]) == 2
        assert qf._need(["a", "b", "c", "d"]) == 2

    def test_corpus_loader_filters_and_orders(self, tmp_path) -> None:
        corpus = tmp_path / "re-library"
        (corpus / "sub").mkdir(parents=True)
        (corpus / "b.md").write_text("frida gadget", encoding="utf-8")
        (corpus / "a.yaml").write_text("anti_debug bypass", encoding="utf-8")
        (corpus / "c.txt").write_text("wrong suffix", encoding="utf-8")
        (corpus / "sub" / "huge.md").write_text("x" * 600, encoding="utf-8")
        # shrink the cap so the big card is skipped by policy
        old = qf.CARD_MAX_BYTES
        qf.CARD_MAX_BYTES = 512
        try:
            cards = qf._load_cards(corpus)
        finally:
            qf.CARD_MAX_BYTES = old
        assert [p for p, _t in cards] == ["a.yaml", "b.md"]


# ------------------------------------------------------------ matching

def _cards() -> list[tuple[str, str]]:
    return [("lib/frida.md", "the frida gadget injects into the media "
             "server process"),
            ("notes/xposed.md", "xposed hooks the gadget surface"),
            ("notes/none.md", "totally unrelated text about parsers")]


class TestHits:
    def test_half_ceiling_ranking_and_cap(self) -> None:
        hits = qf._hits_for(_cards(), ["frida", "gadget", "injects"],
                            top_k=5)
        assert hits[0]["path"] == "lib/frida.md"
        assert hits[0]["score"] == 3  # all three terms land
        assert all("none.md" not in h["path"] for h in hits)

    def test_top_k_caps_the_rows(self) -> None:
        hits = qf._hits_for(_cards(), ["gadget"], top_k=1)
        assert len(hits) == 1

    def test_word_boundary_blocks_substring_hits(self) -> None:
        hits = qf._hits_for(_cards(), ["friday"], top_k=5)
        assert hits == []


# ------------------------------------------------------- reformulation

class TestReformulation:
    def test_provenance_values_reword_minus_originals(self) -> None:
        facet = {"terms": ["frida", "crash"],
                 "provenance": [{"value": "frida inject crash loop"},
                                {"value": "gadget load"}]}
        out = qf._reformulated_terms(facet)
        assert "frida" not in out and "crash" not in out
        assert out[0] == "inject"  # stopwords + short words dropped

    def test_cap_and_honest_no_retry(self) -> None:
        facet = {"terms": ["a"],
                 "provenance": [{"value": " ".join(f"w{i}" for i in
                                                   range(20))}]}
        assert len(qf._reformulated_terms(facet)) == qf.MAX_TERMS
        assert qf._reformulated_terms({"terms": ["x"], "provenance": []}) \
            == []
        assert qf._reformulated_terms({"terms": ["x"],
                                       "provenance": ["junk", 4]}) == []


# --------------------------------------------------------- coverage matrix

def _facet(kind: str, terms: list[str], provenance=None) -> dict:
    return {"kind": kind, "face": None, "terms": terms,
            "provenance": provenance or []}


class TestRetrieveFacets:
    def _corpus(self, tmp_path: Path) -> Path:
        corpus = tmp_path / "re-library"
        corpus.mkdir()
        (corpus / "frida.md").write_text(
            "the frida gadget injects and may crash the media process",
            encoding="utf-8")
        return corpus

    def test_missing_corpus_is_a_named_degradation(self, tmp_path) -> None:
        out = qf.retrieve_facets(tmp_path / "nowhere",
                                 {"facets": [_facet("tool", ["frida"])]})
        assert out["error"] == "corpus-missing"
        assert out["summary"] == {"facets": 0, "hits": 0,
                                  "reformulated_hits": 0, "corpus_lack": 0}

    def test_hit_verdict(self, tmp_path) -> None:
        row = qf.retrieve_facets(
            self._corpus(tmp_path),
            {"facets": [_facet("tool", ["frida", "gadget"])]})["facets"][0]
        assert row["verdict"] == "hit"
        assert row["reformulated"] is False

    def test_reformulated_hit_beats_corpus_lack(self, tmp_path) -> None:
        corpus = self._corpus(tmp_path)
        (corpus / "alt.md").write_text("dynamic instrumentation via the "
                                       "inline hook engine", encoding="utf-8")
        facet = _facet("technique", ["vm bytecode"], provenance=[
            {"value": "dynamic instrumentation hook"}])
        row = qf.retrieve_facets(corpus, {"facets": [facet]})["facets"][0]
        assert row["verdict"] == "reformulated-hit"
        assert row["reformulated"] is True
        summary = qf.retrieve_facets(corpus, {"facets": [facet]})["summary"]
        assert summary["reformulated_hits"] == 1

    def test_corpus_lack_is_honest_without_provenance(self, tmp_path) -> None:
        row = qf.retrieve_facets(
            self._corpus(tmp_path),
            {"facets": [_facet("tool", ["vm bytecode"])]})["facets"][0]
        assert row["verdict"] == "corpus-lack"

    def test_summary_counts_every_verdict(self, tmp_path) -> None:
        corpus = self._corpus(tmp_path)
        out = qf.retrieve_facets(corpus, {"facets": [
            _facet("tool", ["frida", "gadget"]),
            _facet("tool", ["nothing", "matches"]),
        ]})
        assert out["summary"] == {"facets": 2, "hits": 1,
                                  "reformulated_hits": 0, "corpus_lack": 1}

    def test_corpus_label_special_face(self, tmp_path) -> None:
        refs = tmp_path / "references" / "re-library"
        refs.mkdir(parents=True)
        assert qf._corpus_label(refs) == "references/re-library"
        assert qf._corpus_label(tmp_path / "other") == str(
            (tmp_path / "other").as_posix())

    def test_audit_face_and_host_convenience(self, tmp_path) -> None:
        assert qf.coverage_summary(None) == {}
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        out = qf.formulate_and_retrieve(ws, {"kind": "manual",
                                             "token": "frida"},
                                        repo=tmp_path)
        assert out["formulation"]["schema"] == qf.SCHEMA
        assert out["coverage"]["schema"] == qf.COVERAGE_SCHEMA


# ------------------------------------------------------------------ CLI

class TestCli:
    def _ws_with_stamp(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "runs" / "distill-trigger.json").write_text(json.dumps({
            "triggers": [{"kind": "manual", "token": "frida crash"}]}),
            encoding="utf-8")
        return ws

    def test_formulate_face_prints_both_documents(self, tmp_path,
                                                  capsys) -> None:
        ws = self._ws_with_stamp(tmp_path)
        rc = qf.main([str(ws), "--formulate", "--corpus",
                      str(tmp_path / "absent-corpus")])
        assert rc == 0
        out = json.loads(capsys.readouterr().out)
        assert out["formulation"]["trigger"]["kind"] == "manual"
        assert out["coverage"]["error"] == "corpus-missing"

    def test_no_stamp_is_rc1_with_a_reason(self, tmp_path, capsys) -> None:
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        rc = qf.main([str(ws), "--formulate"])
        assert rc == 1
        assert json.loads(capsys.readouterr().out)["reason"] == \
            "no trigger stamp"

    def test_without_formulate_flag_is_a_usage_face(self, tmp_path) -> None:
        assert qf.main([str(self._ws_with_stamp(tmp_path))]) == 2
