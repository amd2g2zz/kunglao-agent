# -*- coding: utf-8 -*-
"""tests/test_orchestration_chunker.py — #309 length-measured batch chunking.

Absorbed idea (amruth-sn/kong supervisor.py:332-362), re-implemented for the
kunglao tool/worker contract: split a large batch (e.g. 500 decompiled
functions) so that every chunk's MEASURED prompt length stays within the
model character budget. Measured = framing overhead + per-item overhead +
actual text length; estimate uses 3.5 chars/token (kong reference).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import chunker


def _item(name, chars):
    return {"name": name, "text": "a" * chars}


def test_500_function_batch_every_chunk_within_budget():
    items = [_item(f"func_{i}", 800) for i in range(500)]
    chunks = chunker.chunk_items(items, budget_tokens=4096)
    assert sum(len(c["items"]) for c in chunks) == 500
    budget_chars = 4096 * chunker.CHARS_PER_TOKEN_DEFAULT
    for c in chunks:
        assert c["measured_chars"] <= budget_chars
        assert c["overflow"] is False


def test_oversize_item_gets_own_flagged_chunk():
    items = [_item("small", 100), _item("huge", 100000)]
    chunks = chunker.chunk_items(items, budget_tokens=1000)
    overflow = [c for c in chunks if c["overflow"]]
    assert len(overflow) == 1
    assert overflow[0]["items"][0]["name"] == "huge"
    # the small item must still be in a within-budget chunk
    ok = [c for c in chunks if not c["overflow"]]
    assert ok and ok[0]["measured_chars"] <= 1000 * chunker.CHARS_PER_TOKEN_DEFAULT


def test_empty_input_returns_no_chunks():
    assert chunker.chunk_items([], budget_tokens=1000) == []


def test_chars_per_token_affects_fill():
    items = [_item(f"f{i}", 500) for i in range(20)]
    tight = chunker.chunk_items(items, budget_tokens=2000, chars_per_token=2.0)
    loose = chunker.chunk_items(items, budget_tokens=2000, chars_per_token=4.0)
    assert len(tight) > len(loose)


def test_measured_length_includes_framing_overhead():
    chunks = chunker.chunk_items([_item("f", 0)], budget_tokens=100)
    c = chunks[0]
    expected = (chunker.PER_CHUNK_OVERHEAD_CHARS
                + chunker.PER_ITEM_OVERHEAD_CHARS + len("f"))
    assert c["measured_chars"] == expected


def test_chunk_indexes_and_budgets_reported():
    items = [_item(f"f{i}", 300) for i in range(10)]
    chunks = chunker.chunk_items(items, budget_tokens=500)
    for i, c in enumerate(chunks):
        assert c["index"] == i
        assert c["estimated_tokens"] == c["measured_chars"] / 3.5
        assert c["budget_chars"] == 500 * 3.5


def test_deterministic_chunking():
    items = [_item(f"f{i}", 300) for i in range(10)]
    a = chunker.chunk_items(items, budget_tokens=500)
    b = chunker.chunk_items(items, budget_tokens=500)
    assert a == b


def test_cli_json(tmp_path, capsys):
    data = {"functions": [_item(f"f{i}", 300) for i in range(30)]}
    inp = tmp_path / "functions.json"
    inp.write_text(json.dumps(data), encoding="utf-8")
    rc = chunker.main(["--input", str(inp), "--budget-tokens", "1000", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_items"] == 30
    assert payload["n_chunks"] >= 1
    for c in payload["chunks"]:
        assert c["measured_chars"] <= 1000 * chunker.CHARS_PER_TOKEN_DEFAULT


def test_cli_missing_input_errors(tmp_path, capsys):
    rc = chunker.main(["--input", str(tmp_path / "nope.json"),
                       "--budget-tokens", "100", "--json"])
    assert rc != 0


def test_cli_reproduce_prints_field_value(tmp_path, capsys):
    """--reproduce emits field=value input lines (kunglao_verify parseable)."""
    inp = tmp_path / "functions.json"
    inp.write_text(json.dumps({"functions": []}), encoding="utf-8")
    rc = chunker.main(["--input", str(inp), "--budget-tokens", "1000",
                       "--reproduce"])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"input={inp}" in out
    assert "budget_tokens=1000" in out
    assert "chars_per_token=3.5" in out
    for line in out.strip().splitlines():
        assert re.match(r"^\w+\s*[:=]\s*.+$", line), line
