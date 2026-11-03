#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb4_migrate_facts_pins_818.py — #818 climb segment 4L.

Behavior pins for scripts/migrate_facts.py — the one-shot pre-migration
facts tool (10.7% measured): the tolerant frontmatter parser (yaml-first,
kv fallback, date coercion, both fence errors), the scalar/credibility/
slug primitives, the inline-provenance frontmatter renderer (the #332
parse contract), both claim-map readers (facts/_INDEX.md rows and the
claim-register fact edges), the workflow-status mapping, the opt-in
--map loader, and the workspace sample fingerprint.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import migrate_facts as mf  # noqa: E402


class TestFrontmatterParser:
    def test_no_fence_is_an_error(self) -> None:
        fm, body, err = mf._parse_frontmatter("just body\n")
        assert (fm, body, err) == ({}, "just body\n", "no-frontmatter")

    def test_unclosed_fence_is_an_error(self) -> None:
        fm, body, err = mf._parse_frontmatter("---\nid: F001\n")
        assert err == "no-closing-fence" and fm == {}

    def test_yaml_face_coerces_dates(self) -> None:
        text = "---\nid: F001\ncreated: 2026-01-02\n---\nbody line\n"
        fm, body, err = mf._parse_frontmatter(text)
        assert err is None
        assert fm["id"] == "F001"
        assert fm["created"] == "2026-01-02"  # date -> iso string
        assert body == "body line"

    def test_kv_fallback_for_unparseable_yaml(self) -> None:
        text = ("---\nid: F001\nstatus: PROVEN\nbad: [unclosed\n"
                "---\nbody\n")
        fm, body, err = mf._parse_frontmatter(text)
        assert err == "yaml-unparseable"
        assert fm.get("id") == "F001"  # the kv fallback still reads shapes


class TestPrimitives:
    def test_sha256_file_and_missing(self, tmp_path) -> None:
        p = tmp_path / "f.bin"
        p.write_bytes(b"payload")
        assert len(mf._sha256_file(p)) == 64
        assert mf._sha256_file(tmp_path / "gone") is None

    def test_default_credibility_tiers(self) -> None:
        assert mf._default_credibility("sample_raw", "bins/dump.bin") == "A1"
        assert mf._default_credibility("other", "anything") == "B3"
        assert mf._default_credibility("public_doc", "refs/cti-123") == "C5"

    def test_slugify_truncates_and_strips(self) -> None:
        assert mf._slugify("Frida Gadget Injection!") == \
            "frida-gadget-injection"
        long = mf._slugify("w" * 80)
        assert len(long) <= 48 and not long.endswith("-")

    def test_yaml_scalar_shapes(self) -> None:
        assert mf._yaml_scalar(None) == "null"
        assert mf._yaml_scalar(True) == "true"
        assert mf._yaml_scalar(7) == "7"
        assert mf._yaml_scalar("") == '""'
        assert mf._yaml_scalar("plain-path/k") == "plain-path/k"
        assert mf._yaml_scalar('has "quotes"') == '"has \\"quotes\\""'

    def test_prov_entry_renders_the_inline_shape(self) -> None:
        row = mf._render_prov_entry({
            "role": "recompute_script", "path": "scripts/recompute.py",
            "content_sha256": "ab12", "credibility": "A2"})
        assert row.startswith("{ role: recompute_script")
        assert "path: scripts/recompute.py" in row
        assert row.endswith("credibility: A2 }")


class TestFrontmatterRenderer:
    def test_render_preserves_field_order_and_inline_prov(self) -> None:
        fm = {
            "provenance": [{"role": "sample_raw", "path": "bins/dump.bin",
                            "content_sha256": "cd34",
                            "credibility": "A1"}],
            "alternatives": [{"hypothesis": "H2", "status": "refuted"},
                             "plain string alt"],
            "claim": "C-001", "id": "F001", "status": "PROVEN",
            "verify_status": "passes", "unknown_key": "dropped",
        }
        text = mf.render_frontmatter(fm)
        lines = text.splitlines()
        assert lines[0] == "---" and lines[-1] == "---"
        keys = [l.split(":")[0] for l in lines[1:-1]
                if l and not l.startswith(" ")]
        assert keys == sorted(keys, key=lambda k: [
            "id", "type", "title", "status", "verify_status",
            "created", "last_reviewed", "source", "confidence", "claim_id",
            "boundary_type", "promotion_gate", "confidence_zh",
            "provenance", "alternatives", "depends_on", "claim", "reproduce",
            "expected", "verified"].index(k))
        assert "unknown_key" not in text
        # the #332 inline-shape contract: prov entries are flow mappings
        assert "  - { role: sample_raw" in text
        assert "  - { hypothesis: H2" in text
        # scalar strings with spaces render quoted
        assert '  - "plain string alt"' in text

    def test_rendered_frontmatter_roundtrips_through_the_parser(
            self) -> None:
        fm = {"id": "F009", "status": "INFERRED", "claim": "C-002",
              "verify_status": "partial",
              "provenance": [{"role": "public_doc", "url":
                              "https://example.test/a",
                              "content_sha256": "beef", "credibility":
                              "C5"}]}
        parsed, body, err = mf._parse_frontmatter(
            mf.render_frontmatter(fm) + "body\n")
        assert err is None and body == "body"
        assert parsed["id"] == "F009"
        assert parsed["provenance"][0]["credibility"] == "C5"


class TestClaimMaps:
    def test_index_rows_build_the_fact_map(self, tmp_path) -> None:
        ws = tmp_path
        (ws / "facts").mkdir()
        (ws / "facts" / "_INDEX.md").write_text(
            "# index\n"
            "F001 | PROVEN | C-001 | first\n"
            "garbage line\n"
            "F002 | INFERRED | not-a-claim | x\n"
            "F003 | INFERRED | C-003 | third\n", encoding="utf-8")
        assert mf._read_index_claim_map(ws) == {"F001": "C-001",
                                                "F003": "C-003"}

    def test_register_fact_edges_build_the_map(self, tmp_path) -> None:
        import yaml
        ws = tmp_path
        (ws / "claim-register.yaml").write_text(yaml.safe_dump({
            "claims": [{"id": "C-1", "fact": "F001"},
                       {"id": "C-2", "fact": "bad"},
                       {"id": "C-3"}]}), encoding="utf-8")
        assert mf._read_register_claim_map(ws) == {"F001": "C-1"}

    def test_missing_sources_read_empty(self, tmp_path) -> None:
        assert mf._read_index_claim_map(tmp_path) == {}
        assert mf._read_register_claim_map(tmp_path) == {}


class TestWorkflowAndMap:
    def test_workflow_status_mapping(self) -> None:
        assert mf._workflow_status({"status": "PROVEN",
                                    "verify_status": "passes"}) == "PROVEN"
        assert mf._workflow_status({"status": "INFERRED",
                                    "verify_status": "partial"}) == \
            "PARTIALLY-VERIFIED"
        assert mf._workflow_status({"status": "NEGATIVE"}) == "NEGATIVE"
        assert mf._workflow_status({"status": "DEFERRED"}) == "DEFERRED"
        assert mf._workflow_status({}) == "OPEN"
        assert mf._workflow_status({"status": "WEIRD"}) == "WEIRD"

    def test_opt_in_map_loader_validates_the_shape(self, tmp_path) -> None:
        p = tmp_path / "map.json"
        p.write_text('{"sample_sha256": "ab", "facts": {"F001": {}}}',
                     encoding="utf-8")
        assert mf._load_map(p)["facts"] == {"F001": {}}
        bad = tmp_path / "bad.json"
        bad.write_text('{"nope": true}', encoding="utf-8")
        with pytest.raises(ValueError, match="map JSON must be"):
            mf._load_map(bad)

    def test_workspace_sample_fingerprint_is_order_stable(
            self, tmp_path) -> None:
        ws = tmp_path / "ws"
        (ws / "bins").mkdir(parents=True)
        (ws / "bins" / "a.bin").write_bytes(b"AAAA")
        (ws / "bins" / "sub").mkdir()
        (ws / "bins" / "sub" / "b.bin").write_bytes(b"BB")
        one = mf._workspace_sample_sha256(ws)
        # rename-shuffle: sorted order keeps the digest stable
        (ws / "bins" / "a.bin").write_bytes(b"AAAA")
        assert mf._workspace_sample_sha256(ws) == one
        assert mf._workspace_sample_sha256(tmp_path / "bare") is None
        empty = tmp_path / "empty"
        (empty / "bins").mkdir(parents=True)
        assert mf._workspace_sample_sha256(empty) is None
