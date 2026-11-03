# -*- coding: utf-8 -*-
"""tests/test_distill_schema_365.py — the StandardDistillItem schema
`distill-item/1` (issue 365, the distillation domain of the unified model).

The item is an ADDITIVE `distill` block on an `episode/1` pool document
(A2: one pool, no parallel store). The lint is fail-closed: a block
failing any field rule raises with the offending field named — an item
that can't fill the schema doesn't exist.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rlvr.episode_schema as es  # noqa: E402
import distill_schema as ds  # noqa: E402


def _block(**over) -> dict:
    blk = {
        "schema": "distill-item/1",
        "source_strategy": "self",
        "source_refs": ["notes/why-frida-first.md"],
        "collection_ts": "2026-10-27T00:00:00Z",
        "content": {
            "branch_table": ["when hooked then the gadget repack applies"],
            "verdict_algebra": ["pass := replay matches bytes"],
            "pseudocode_groups": ["attach_and_verify()"],
        },
        "scoring": {"generality": 0.8, "self_inspiring": 0.6,
                    "methodology": 0.7, "novelty": 0.5, "total": 0.67,
                    "assessor": "assessor-dispatch/1"},
        "epistemic_class": "evidence-derived",
        "lineage": {"supersedes": "", "superseded_by": ""},
        "optimization_rounds": 0,
    }
    blk.update(over)
    return blk


def _episode(distill: dict, claim: str = "D-test-item") -> dict:
    return {
        "schema": "episode/1",
        "id": f"E-{claim}",
        "claim": claim,
        "created": "2026-10-27T00:00:00Z",
        "updated": "2026-10-27T00:00:00Z",
        "context_features": ["android", "frida"],
        "commits": [
            {"seq": 1, "action": "select", "summary": "distill act"},
            {"seq": 2, "action": "deliver", "summary": "item landed"},
        ],
        "outcome": {"status": "completed", "verified": True,
                    "evidence_ref": ""},
        "cost": {"tokens": 0.0, "seconds": 0.0},
        "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
        "reusable_fragments": ["repack the gadget before attach"],
        "milestones": [],
        "distill": distill,
    }


class TestBlockLint:
    def test_well_formed_block_validates(self):
        out = ds.lint_block(_block())
        assert out["source_strategy"] == "self"
        assert out["schema"] == "distill-item/1"

    @pytest.mark.parametrize("mutate,field", [
        ({"source_strategy": "web"}, "source_strategy"),
        ({"source_refs": []}, "source_refs"),
        ({"collection_ts": "not-a-ts"}, "collection_ts"),
        ({"epistemic_class": "gut-feel"}, "epistemic_class"),
        ({"optimization_rounds": -1}, "optimization_rounds"),
        ({"content": {"branch_table": [], "verdict_algebra": [],
                      "pseudocode_groups": []}}, "content"),
    ])
    def test_bad_fields_are_red(self, mutate, field):
        with pytest.raises(ds.DistillSchemaError) as ei:
            ds.lint_block(_block(**mutate))
        assert field in str(ei.value)

    @pytest.mark.parametrize("mutate,field", [
        ({"generality": 1.2}, "generality"),
        ({"total": -0.1}, "total"),
        ({"assessor": ""}, "assessor"),
        ({"novelty": "high"}, "novelty"),
    ])
    def test_bad_scoring_is_red(self, mutate, field):
        scoring = {"generality": 0.5, "self_inspiring": 0.5,
                   "methodology": 0.5, "novelty": 0.5, "total": 0.5,
                   "assessor": "a/1"}
        scoring.update(mutate)
        with pytest.raises(ds.DistillSchemaError) as ei:
            ds.lint_block(_block(scoring=scoring))
        assert field in str(ei.value)

    def test_missing_block_is_red(self):
        with pytest.raises(ds.DistillSchemaError):
            ds.lint_block(None)

    def test_json_schema_covers_field_table(self):
        schema = ds.json_schema()
        props = schema["properties"]
        for f in ("source_strategy", "source_refs", "collection_ts",
                  "content", "scoring", "epistemic_class", "lineage",
                  "optimization_rounds"):
            assert f in props, f
        assert schema["required"] == list(ds.REQUIRED_FIELDS)


class TestEpisodeProjection:
    def test_additive_block_rides_episode_schema(self):
        doc = _episode(_block())
        assert es.validate_episode(doc)["distill"]["schema"] \
            == "distill-item/1"

    def test_render_read_round_trip(self, tmp_path):
        doc = _episode(_block())
        payload = es.render_episode(doc, body="summary body")
        p = tmp_path / "episode-D-test-item.md"
        p.write_bytes(payload)
        back, body = es.read_episode_file(p)
        assert back["distill"]["epistemic_class"] == "evidence-derived"
        assert "summary" in body

    def test_item_from_episode(self):
        doc = _episode(_block())
        item = ds.item_from_episode(doc)
        assert item.source_strategy == "self"
        assert item.claim == "D-test-item"
        assert item.block["scoring"]["total"] == pytest.approx(0.67)

    def test_item_from_episode_without_block_is_red(self):
        doc = _episode(_block())
        del doc["distill"]
        with pytest.raises(ds.DistillSchemaError):
            ds.item_from_episode(doc)

    def test_dataclass_round_trip(self):
        item = ds.StandardDistillItem(
            claim="D-x", block=_block(source_strategy="hybrid"))
        assert item.source_strategy == "hybrid"
        doc = _episode(item.block)
        ds.lint_block(doc["distill"])
