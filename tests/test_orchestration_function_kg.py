# -*- coding: utf-8 -*-
"""tests/test_orchestration_function_kg.py — #309 minimal function-level KG.

Absorbed idea (Dryxio/auto-re-agent knowledge_graph.py:26-56), re-implemented
for kunglao: build function/string/global nodes + calls/references/accesses
edges from ghidra-recon style records, JSON persistence, and a neighborhood
query for worker context injection. Honest discount per issue: only useful
for whole-function-batch analysis claims — hence minimal implementation.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import function_kg as kg

RECORDS = [
    {"function": "main", "calls": ["decrypt_payload"],
     "strings": ["http://c2.local"], "globals": ["g_key"], "decompiled_chars": 1200},
    {"function": "decrypt_payload", "calls": ["RC4_init"],
     "strings": [], "globals": ["g_key"], "decompiled_chars": 800},
    {"function": "RC4_init", "calls": [],
     "strings": [], "globals": [], "decompiled_chars": 300},
]


def test_build_graph_nodes_and_edges():
    g = kg.build_graph(RECORDS)
    assert g["schema"] == "kunglao-function-kg/1"
    f_nodes = [n for n in g["nodes"].values() if n["kind"] == "function"]
    s_nodes = [n for n in g["nodes"].values() if n["kind"] == "string"]
    g_nodes = [n for n in g["nodes"].values() if n["kind"] == "global"]
    assert len(f_nodes) == 3
    assert len(s_nodes) == 1
    assert len(g_nodes) == 1
    assert kg.node_id("function", "main") in g["nodes"]
    assert set(e["kind"] for e in g["edges"].values()) == {"call", "reference", "access"}
    assert sum(1 for e in g["edges"].values() if e["kind"] == "call") == 2
    assert sum(1 for e in g["edges"].values() if e["kind"] == "reference") == 1
    assert sum(1 for e in g["edges"].values() if e["kind"] == "access") == 2


def test_duplicate_targets_dedup_edges():
    recs = [{"function": "a", "calls": ["b", "b"], "strings": [], "globals": []},
            {"function": "b", "calls": [], "strings": [], "globals": []}]
    g = kg.build_graph(recs)
    assert sum(1 for e in g["edges"].values() if e["kind"] == "call") == 1


def test_missing_targets_still_create_edges_to_synthetic_node():
    """A call to an undecompiled function must not vanish the edge."""
    recs = [{"function": "a", "calls": ["external_helper"], "strings": [],
             "globals": []}]
    g = kg.build_graph(recs)
    calls = [e for e in g["edges"].values() if e["kind"] == "call"]
    assert len(calls) == 1
    dst = calls[0]["dst"]
    assert g["nodes"][dst]["kind"] == "function"


def test_write_and_load_roundtrip(tmp_path):
    g = kg.build_graph(RECORDS)
    out = tmp_path / "kg.json"
    kg.write_graph(g, out)
    g2 = kg.load_graph(out)
    assert g2 == g


def test_neighborhood_radius_one():
    g = kg.build_graph(RECORDS)
    nb = kg.neighborhood(g, "main", radius=1)
    names = {n["name"] for n in nb["nodes"]}
    assert "main" in names
    assert "decrypt_payload" in names
    assert "http://c2.local" in names
    assert "g_key" in names
    assert "RC4_init" not in names  # radius 2 away
    edge_kinds = {e["kind"] for e in nb["edges"]}
    assert "call" in edge_kinds


def test_neighborhood_radius_two_reaches_deeper():
    g = kg.build_graph(RECORDS)
    nb = kg.neighborhood(g, "main", radius=2)
    names = {n["name"] for n in nb["nodes"]}
    assert "RC4_init" in names


def test_neighborhood_missing_function_returns_empty():
    g = kg.build_graph(RECORDS)
    nb = kg.neighborhood(g, "not_there")
    assert nb["nodes"] == []
    assert nb["edges"] == []


def test_cli_build_and_query(tmp_path, capsys):
    inp = tmp_path / "records.json"
    inp.write_text(json.dumps(RECORDS), encoding="utf-8")
    out = tmp_path / "kg.json"
    rc = kg.main(["--input", str(inp), "--out", str(out), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_nodes"] == 5
    assert out.exists()
    rc = kg.main(["--input", str(inp), "--out", str(out),
                  "--neighborhood", "main", "--json"])
    assert rc == 0
    nb = json.loads(capsys.readouterr().out)
    names = {n["name"] for n in nb["nodes"]}
    assert "decrypt_payload" in names


def test_cli_reproduce_prints_field_value(tmp_path, capsys):
    """--reproduce emits field=value input lines (kunglao_verify parseable)."""
    inp = tmp_path / "records.json"
    inp.write_text(json.dumps(RECORDS), encoding="utf-8")
    out = tmp_path / "kg.json"
    rc = kg.main(["--input", str(inp), "--out", str(out),
                  "--neighborhood", "main", "--radius", "2", "--reproduce"])
    assert rc == 0
    text = capsys.readouterr().out
    assert f"input={inp}" in text
    assert f"out={out}" in text
    assert "neighborhood=main" in text
    assert "radius=2" in text
    for line in text.strip().splitlines():
        assert re.match(r"^\w+\s*[:=]\s*.+$", line), line
