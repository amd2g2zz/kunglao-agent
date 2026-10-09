# -*- coding: utf-8 -*-
"""Issue 584 — the optional hypothesis-view renderer face.

scripts/hypothesis_view.py projects facts that carry an open
`uncertainty` into the owner's structured analysis object shape
{identity, object, hypothesis, supporting, counter, status, next} —
read-only over the fact base, never a parallel truth. Pins: the exact
7-key shape, invisibility of facts without uncertainty, read-only
guarantee, and both output faces.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import yaml  # noqa: E402


def _make_ws(tmp_path: Path, facts: list[dict]) -> Path:
    d = tmp_path / "facts"
    d.mkdir(parents=True)
    for fm in facts:
        head = yaml.safe_dump(fm, sort_keys=False)
        (d / f"{fm['id']}.md").write_text(f"---\n{head}---\n\nbody\n",
                                          encoding="utf-8")
    return tmp_path


def _base_fm(fid: str, **over) -> dict:
    fm = {
        "id": fid, "type": "fact", "title": "neutral title",
        "status": "INFERRED", "created": "2026-10-09",
        "last_reviewed": "2026-10-09", "claim_id": "C-001",
        "boundary_type": "source_derived",
        "promotion_gate": "a second sample decoding under the derived key",
        "provenance": [{"role": "decompiled_c", "path": "x.c",
                        "content_sha256": "a" * 64, "credibility": "B2"}],
        "source": "static-decompile", "confidence": "medium",
        "claim": "the constant is a key seed",
    }
    fm.update(over)
    return fm


VIEW_SHAPE = {"identity", "object", "hypothesis", "supporting",
              "counter", "status", "next"}


def _run_view(tmp_path: Path, *extra: str):
    import hypothesis_view as hv
    out = hv.main([str(tmp_path), *extra])
    return out


def test_view_projects_the_seven_field_shape(tmp_path, capsys):
    ws = _make_ws(tmp_path, [_base_fm(
        "F584-20",
        uncertainty="the constant could also be a checksum",
        next_probe="mutate one seed byte and re-derive")])
    rc = _run_view(ws, "--json")
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    entries = data["facts"]
    assert len(entries) == 1
    e = entries[0]
    assert set(e) == VIEW_SHAPE
    assert e["identity"] == "F584-20"
    assert e["object"] == "neutral title"
    assert e["hypothesis"] == "the constant is a key seed"
    assert e["counter"] == "the constant could also be a checksum"
    assert e["status"] == "INFERRED"
    assert e["next"] == "mutate one seed byte and re-derive"
    assert e["supporting"] == [
        {"role": "decompiled_c", "where": "x.c", "credibility": "B2"}]


def test_facts_without_uncertainty_are_invisible(tmp_path, capsys):
    ws = _make_ws(tmp_path, [_base_fm("F584-21"),
                             _base_fm("F584-22", uncertainty="open question")])
    rc = _run_view(ws, "--json")
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 1
    assert data["facts"][0]["identity"] == "F584-22"


def test_view_is_read_only_over_the_workspace(tmp_path, capsys):
    ws = _make_ws(tmp_path, [_base_fm("F584-23", uncertainty="x")])

    def snapshot(root: Path) -> set:
        return {(str(p.relative_to(root)), p.stat().st_mtime_ns,
                 p.stat().st_size) for p in root.rglob("*") if p.is_file()}

    before = snapshot(ws)
    rc = _run_view(ws)
    assert rc == 0
    capsys.readouterr()
    assert snapshot(ws) == before


def test_human_face_names_identity_and_counter(tmp_path, capsys):
    ws = _make_ws(tmp_path, [_base_fm(
        "F584-24", uncertainty="unconfirmed on second sample")])
    rc = _run_view(ws)
    assert rc == 0
    out = capsys.readouterr().out
    assert "F584-24" in out
    assert "unconfirmed on second sample" in out


def test_empty_workspace_yields_empty_view(tmp_path, capsys):
    rc = _run_view(_make_ws(tmp_path, []), "--json")
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["count"] == 0
    assert data["facts"] == []


def test_view_output_carries_schema_rev(tmp_path, capsys):
    ws = _make_ws(tmp_path, [_base_fm("F584-25", uncertainty="x")])
    _run_view(ws, "--json")
    data = json.loads(capsys.readouterr().out)
    assert data["active_schema_rev"] >= 2
