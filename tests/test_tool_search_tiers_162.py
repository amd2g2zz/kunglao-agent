# -*- coding: utf-8 -*-
"""tests/test_tool_search_tiers_162.py — issue #162 Unit 2: tool-search.py
is the SINGLE search entry over all three data sources.

  1. tools/_INDEX.yaml       (internal registry)  -> type=tool, consume=invoke
  2. tools/_INDEX.ext.yaml   (typed ext entries)  -> type/consume as generated
  3. references/_INDEX.yaml  (its own generator's file list) -> type/consume
     DERIVED at query time (type=reference, consume=read) — the references
     index itself is NOT touched (it has its own generator and schema).

A hit must let the agent decide what to do without opening the file:
every find projection carries name + type + consume + source + usage +
one-line description, and the text mode prints
name / type / consume / source / description.

Dedup: a re-library card is enumerated by BOTH the ext index and the
references index; the typed ext entry wins (same source path appears once).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "tool-search.py"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace",
    )


# ---------------------------------------------------------------------------
# tier 1 — internal registry: typed tool/invoke
# ---------------------------------------------------------------------------

def test_internal_tier_hit_is_tool_invoke():
    r = run_cli("--find", "yara", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    yara_hits = [h for h in hits if str(h.get("name", "")).startswith("yara")]
    assert yara_hits, f"no yara hits: {hits}"
    for h in yara_hits:
        assert h["kind"] == "internal"
        assert h["type"] == "tool"
        assert h["consume"] == "invoke"
        assert h["source"] == "tools/_INDEX.yaml"
        assert h["description"], "internal hit must carry a description"


# ---------------------------------------------------------------------------
# tier 2 — ext index: templates carry their generated type/consume
# ---------------------------------------------------------------------------

def test_template_tier_hit_is_typed():
    r = run_cli("--find", "cfg-hook", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    tmpl = [h for h in hits
            if h.get("source") == "templates/frida/cfg-hook.js.tmpl"]
    assert tmpl, f"template tier invisible to search: {hits}"
    h = tmpl[0]
    assert h["type"] == "template"
    assert h["consume"] == "fill"
    assert h["description"], "template hit must carry a description"


def test_reference_tier_hit_derived_at_query_time():
    """A reference card that is NOT in the ext index (references/_INDEX.yaml
    only — e.g. wal-protocol.md) still surfaces, typed at query time."""
    r = run_cli("--find", "wal-protocol", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    ref = [h for h in hits if h.get("source") == "references/wal-protocol.md"]
    assert ref, f"references source not queried: {hits}"
    h = ref[0]
    assert h["type"] == "reference"
    assert h["consume"] == "read"
    assert h["description"], "reference hit must carry a description"


def test_reference_tier_re_library_card_deduped_against_ext_entry():
    """re-library cards exist in BOTH sources; the typed ext entry wins and
    the same source path appears exactly once per query."""
    r = run_cli("--find", "deobfuscation", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    card = "references/re-library/vm-deobfuscation-routing.md"
    srcs = [h.get("source") for h in hits if h.get("source") == card]
    assert len(srcs) == 1, f"dedup failed: {srcs}"
    winner = [h for h in hits if h.get("source") == card][0]
    assert winner["type"] == "reference" and winner["consume"] == "read"


# ---------------------------------------------------------------------------
# display contract — a hit decides without opening the file
# ---------------------------------------------------------------------------

def test_text_mode_prints_name_type_consume_source_description():
    r = run_cli("--find", "cfg-hook")
    assert r.returncode == 0, r.stderr
    assert r.stdout, "text mode produced no output"
    for line in r.stdout.rstrip("\n").splitlines():
        cols = line.split("\t")
        assert len(cols) == 5, f"expected 5 columns, got: {line!r}"


def test_text_mode_reference_hit_readable():
    r = run_cli("--find", "wal-protocol")
    assert r.returncode == 0
    assert "wal-protocol" in r.stdout
    assert "reference" in r.stdout


# ---------------------------------------------------------------------------
# degraded environments — missing references index must not brick the query
# ---------------------------------------------------------------------------

def test_missing_references_index_degrades_to_empty(tmp_path):
    root = tmp_path
    (root / "tools").mkdir()
    (root / "tools" / "_INDEX.yaml").write_text(
        "tools:\n  - name: crypto-tool\n    capability: crypto:decode\n"
        "    description: decoder\n", encoding="utf-8")
    r = run_cli("--find", "crypto", "--json", str(root / "tools" / "_INDEX.yaml"))
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    assert any(h["name"] == "crypto-tool" for h in hits)
    assert all(h.get("source") != "" for h in hits)


def test_sandbox_references_index_searched(tmp_path):
    root = tmp_path
    (root / "tools").mkdir()
    (root / "references").mkdir()
    (root / "tools" / "_INDEX.yaml").write_text(
        "tools: []\n", encoding="utf-8")
    (root / "references" / "_INDEX.yaml").write_text(
        "files:\n  references/my-card.md: " + "0" * 64 + "\n",
        encoding="utf-8")
    (root / "references" / "my-card.md").write_text(
        "# My Card\n\nquantum flux capacitor lore\n", encoding="utf-8")
    r = run_cli("--find", "quantum", "--json",
                str(root / "tools" / "_INDEX.yaml"))
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    assert len(hits) == 1 and hits[0]["name"] == "my-card"
    assert hits[0]["type"] == "reference" and hits[0]["consume"] == "read"
