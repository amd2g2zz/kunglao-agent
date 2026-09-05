# -*- coding: utf-8 -*-
"""#49 case bank — symmetric outcome collection + failures-first retrieval.

RED-first tests pin the contract before implementation (owner ruling 4):

- Symmetric banking: failures carry attribution (+ optional premise_correction);
  a NEGATIVE entry WITHOUT attribution is REFUSED with CaseBankError — no
  silent banking of unattributed failures.
- Retrieval: matching entries with FAILURES FIRST (counterexample pruning >
  positive reuse), newest first within each class; tag-intersection matching.
- Agent-context output: emit_case_hints wraps in <case-hints> per
  references/xml-injection-standard.md (the reserved producer is THIS PR).
"""
import json
from pathlib import Path

import pytest

import case_bank as cb


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _entry(**kw):
    base = dict(claim_id="C-1", method="ghidra-light",
                context_tags=["re", "vm"],
                intent_uncertainty="which config builder runs first",
                outcome_observed={"verdict": "passes"},
                roi_class="POSITIVE")
    base.update(kw)
    return base


# ---------- append: schema + ruling-4 lint rule ----------

class TestAppend:
    def test_append_round_trip(self, tmp_path):
        stored = cb.append(tmp_path, _entry())
        assert stored["ts"]
        rows = cb.read_entries(tmp_path)
        assert len(rows) == 1
        assert rows[0]["claim_id"] == "C-1"
        assert rows[0]["method"] == "ghidra-light"
        assert rows[0]["intent_uncertainty"] == \
            "which config builder runs first"
        assert rows[0]["outcome_observed"] == {"verdict": "passes"}
        assert rows[0]["roi_class"] == "POSITIVE"
        assert cb.bank_path(tmp_path).exists()

    def test_negative_requires_attribution(self, tmp_path):
        """Ruling 4: a no-attribution failure is NOT banked (raises)."""
        with pytest.raises(cb.CaseBankError, match="attribution"):
            cb.append(tmp_path, _entry(roi_class="NEGATIVE"))
        assert not cb.bank_path(tmp_path).exists()

    def test_negative_blank_attribution_refused(self, tmp_path):
        """Whitespace attribution is not attribution."""
        with pytest.raises(cb.CaseBankError, match="attribution"):
            cb.append(tmp_path, _entry(roi_class="NEGATIVE",
                                       attribution="   "))
        assert not cb.bank_path(tmp_path).exists()

    def test_negative_with_attribution_banked(self, tmp_path):
        cb.append(tmp_path, _entry(
            roi_class="NEGATIVE",
            attribution="packed entrypoint guess skipped the real OEP; "
                        "verify-by-replay next time",
            premise_correction="entrypoint != OEP for this packer family"))
        rows = cb.read_entries(tmp_path)
        assert rows[0]["roi_class"] == "NEGATIVE"
        assert "OEP" in rows[0]["attribution"]
        assert rows[0]["premise_correction"].startswith("entrypoint")

    def test_positive_needs_no_attribution(self, tmp_path):
        cb.append(tmp_path, _entry())
        assert cb.read_entries(tmp_path)[0]["attribution"] is None

    def test_context_tags_normalized_to_list(self, tmp_path):
        cb.append(tmp_path, _entry(context_tags="re"))
        assert cb.read_entries(tmp_path)[0]["context_tags"] == ["re"]

    def test_missing_required_field_raises(self, tmp_path):
        for missing in ("claim_id", "method", "roi_class"):
            entry = _entry()
            entry.pop(missing)
            with pytest.raises(cb.CaseBankError, match=missing):
                cb.append(tmp_path, entry)
        assert not cb.bank_path(tmp_path).exists()

    def test_unknown_roi_class_raises(self, tmp_path):
        with pytest.raises(cb.CaseBankError, match="roi_class"):
            cb.append(tmp_path, _entry(roi_class="HUGE_WIN"))
        assert not cb.bank_path(tmp_path).exists()


# ---------- retrieve: failures first, newest first (ruling 4) ----------

class TestRetrieve:
    def test_failures_first_then_positives(self, tmp_path):
        """Counterexample pruning: NEGATIVE entries surface before positives
        regardless of append order."""
        cb.append(tmp_path, _entry(claim_id="C-1", roi_class="POSITIVE"))
        cb.append(tmp_path, _entry(claim_id="C-2", roi_class="NEGATIVE",
                                   attribution="wrong unpack order"))
        cb.append(tmp_path, _entry(claim_id="C-3", roi_class="POSITIVE"))
        got = cb.retrieve(tmp_path, ["re"], limit=10)
        assert [e["claim_id"] for e in got] == ["C-2", "C-3", "C-1"]

    def test_newest_first_within_class(self, tmp_path):
        for n in ("1", "2", "3"):
            cb.append(tmp_path, _entry(claim_id=f"C-{n}"))
        got = cb.retrieve(tmp_path, ["re"], limit=10)
        assert [e["claim_id"] for e in got] == ["C-3", "C-2", "C-1"]

    def test_tag_intersection_filter(self, tmp_path):
        cb.append(tmp_path, _entry(claim_id="C-1", context_tags=["re", "vm"]))
        cb.append(tmp_path, _entry(claim_id="C-2", context_tags=["osint"]))
        got = cb.retrieve(tmp_path, ["vm"], limit=10)
        assert [e["claim_id"] for e in got] == ["C-1"]

    def test_empty_query_tags_match_all(self, tmp_path):
        cb.append(tmp_path, _entry(claim_id="C-1", context_tags=["re"]))
        cb.append(tmp_path, _entry(claim_id="C-2", context_tags=["osint"]))
        assert len(cb.retrieve(tmp_path, [], limit=10)) == 2

    def test_limit_truncates_after_ordering(self, tmp_path):
        """Limit applies AFTER failures-first + newest-first ordering."""
        cb.append(tmp_path, _entry(claim_id="C-1"))
        cb.append(tmp_path, _entry(claim_id="C-2", roi_class="NEGATIVE",
                                   attribution="a"))
        cb.append(tmp_path, _entry(claim_id="C-3"))
        got = cb.retrieve(tmp_path, ["re"], limit=2)
        assert [e["claim_id"] for e in got] == ["C-2", "C-3"]

    def test_unmatched_tags_empty(self, tmp_path):
        cb.append(tmp_path, _entry())
        assert cb.retrieve(tmp_path, ["nomatch"], limit=5) == []


# ---------- emit_case_hints: the reserved <case-hints> producer ----------

class TestEmitCaseHints:
    def test_wrapper_per_xml_standard(self, tmp_path):
        """references/xml-injection-standard.md reserves <case-hints> for
        THIS producer; output is the wrapped text block."""
        cb.append(tmp_path, _entry(claim_id="C-2"))
        out = cb.emit_case_hints(tmp_path, ["re"], limit=3)
        assert out.startswith("<case-hints>") and out.endswith("</case-hints>")
        assert "C-2" in out
        assert "ghidra-light" in out

    def test_failures_before_positives_in_text(self, tmp_path):
        cb.append(tmp_path, _entry(claim_id="C-1"))
        cb.append(tmp_path, _entry(claim_id="C-2", roi_class="NEGATIVE",
                                   attribution="wrong unpack order",
                                   premise_correction="entrypoint != OEP"))
        out = cb.emit_case_hints(tmp_path, ["re"], limit=5)
        assert out.index("C-2") < out.index("C-1")
        assert "wrong unpack order" in out

    def test_empty_bank_returns_empty_string(self, tmp_path):
        """No entries -> no injection at all (never an empty tag)."""
        assert cb.emit_case_hints(tmp_path, ["re"], limit=3) == ""

    def test_unmatched_tags_return_empty_string(self, tmp_path):
        cb.append(tmp_path, _entry())
        assert cb.emit_case_hints(tmp_path, ["nomatch"], limit=3) == ""


# ---------- CLI face ----------

class TestCli:
    def test_retrieve_json(self, tmp_path, capsys):
        cb.append(tmp_path, _entry(claim_id="C-1"))
        rc = cb.main([str(tmp_path), "retrieve", "--tags", "re,vm",
                      "--limit", "3", "--json"])
        assert rc == 0
        rows = json.loads(capsys.readouterr().out)
        assert [r["claim_id"] for r in rows] == ["C-1"]

    def test_retrieve_text_shows_case_hints_block(self, tmp_path, capsys):
        cb.append(tmp_path, _entry(claim_id="C-1"))
        rc = cb.main([str(tmp_path), "retrieve", "--tags", "re", "--limit", "3"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "<case-hints>" in out and "C-1" in out

    def test_retrieve_empty_bank_text(self, tmp_path, capsys):
        rc = cb.main([str(tmp_path), "retrieve", "--tags", "re",
                      "--limit", "3", "--json"])
        assert rc == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_tags_default_empty_matches_all(self, tmp_path, capsys):
        cb.append(tmp_path, _entry(claim_id="C-9"))
        rc = cb.main([str(tmp_path), "retrieve", "--json"])
        assert rc == 0
        assert [r["claim_id"] for r in json.loads(capsys.readouterr().out)] \
            == ["C-9"]


# ---------- regression guards ----------

class TestRegressionGuards:
    def test_missing_bank_file_reads_empty(self, tmp_path):
        assert cb.read_entries(tmp_path) == []
        assert cb.retrieve(tmp_path, ["re"], limit=5) == []

    def test_malformed_bank_lines_skipped(self, tmp_path):
        cb.append(tmp_path, _entry(claim_id="C-1"))
        p = cb.bank_path(tmp_path)
        p.write_text(p.read_text(encoding="utf-8") + "\nnot json\n{broken\n",
                     encoding="utf-8")
        assert [e["claim_id"] for e in cb.retrieve(tmp_path, [], limit=10)] \
            == ["C-1"]

    def test_no_new_utc_now_helper(self):
        """#863 Family F confinement: the timestamp comes from
        harness_common, never a local re-definition."""
        import case_bank
        import inspect
        assert "harness_common" in inspect.getsource(case_bank)
