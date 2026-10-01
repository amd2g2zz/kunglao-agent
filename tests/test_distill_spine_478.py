# -*- coding: utf-8 -*-
"""#478 PR1: the distillation spine — schemas, fixed-order T-pass,
source-trust gate. Spec scenarios pinned one-to-one."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import distill_spine as ds  # noqa: E402


def _playbook(**over):
    pb = {"schema": "playbook/1", "name": "hardened-so-static",
          "problem_signature": ["arm64", "ollvm"],
          "steps": [{"n": 1, "tool_ref": "ghidra-light",
                     "expected_evidence": "symbols-mapped"},
                    {"n": 2, "tool_ref": "replay",
                     "expected_evidence": "byte-exact"}]}
    pb.update(over)
    return pb


class TestSchemas:
    def test_malformed_playbook_rejected(self):
        bad = _playbook(steps=[{"n": 1}])  # no tool_ref
        r = ds.tpass("playbook", bad, provenance={}, fixture={})
        assert r["action"] == "rejected"
        assert "step-0-no-tool-ref" in r["violations"]

    def test_decision_missing_field_named(self):
        r = ds.tpass("decision", {"schema": ds.DECISION_SCHEMA},
                     provenance={}, fixture={})
        assert r["action"] == "rejected"
        assert "decision-missing-method_family" in r["violations"]


class TestTPass:
    def test_de_case_strips_paths_and_blobs(self):
        pb = _playbook(name="x /Users/alice/ws/thing "
                            "9f2c1d8a7b3e5f0a9c2d4e6f8a0b1c2d3e4")
        doc = ds.de_case(pb, {"source": "run"})
        assert "/Users/" not in str(doc)
        assert "9f2c1d8a" not in str(doc)
        assert doc["provenance"]["source"] == "run"

    def test_promote_form_attaches_code_first(self):
        doc = ds.promote_form(
            {"summary": "prose", "provenance": {"script_path": "s.py"}})
        assert doc["form"]["kind"] == "code"
        assert doc["form"]["prose"] == "prose"

    def test_verify_playbook_missing_milestone_archives(self):
        r = ds.tpass("playbook", _playbook(), provenance={},
                     fixture={"milestones_reached": ["symbols-mapped"]})
        assert r["action"] == "archived"
        assert r["evidence"]["missing_milestones"] == ["byte-exact"]

    def test_dedup_exact_and_corroboration_merge(self):
        existing = []
        r1 = ds.tpass("playbook", _playbook(), provenance={},
                      fixture={"milestones_reached":
                               ["symbols-mapped", "byte-exact"]},
                      existing=existing)
        existing.append(r1["product"])
        r2 = ds.tpass("playbook", _playbook(name="another"), provenance={},
                      fixture={"milestones_reached":
                               ["symbols-mapped", "byte-exact"]},
                      existing=existing)
        assert r2["action"] == "merged"
        assert existing[0]["corroboration"] == 2


class TestSourceTrust:
    def test_two_falsifications_blacklist_and_demote(self, tmp_path):
        (tmp_path / "runs" / "distill-products").mkdir(parents=True)
        prod = tmp_path / "runs" / "distill-products" / "p.json"
        prod.write_text('{"provenance": {"source": "S1"}, "name": "p"}',
                        encoding="utf-8")
        ds.trust_event(tmp_path, "S1", landed=True)
        ds.trust_event(tmp_path, "S1", landed=False)
        assert not ds.blacklisted(tmp_path, "S1")
        ds.trust_event(tmp_path, "S1", landed=False)
        assert ds.blacklisted(tmp_path, "S1")
        assert '"trust_demoted": true' in prod.read_text(encoding="utf-8")

    def test_dissimilar_source_never_blacklisted(self, tmp_path):
        ds.trust_event(tmp_path, "S2", landed=False)  # one falsification
        assert not ds.blacklisted(tmp_path, "S2")


class TestOrder:
    def test_kind_unknown_rejected(self):
        r = ds.tpass("poem", {}, provenance={}, fixture={})
        assert r["action"] == "rejected"
