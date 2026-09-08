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

def test_text_mode_prints_name_score_type_consume_source_description():
    r = run_cli("--find", "cfg-hook")
    assert r.returncode == 0, r.stderr
    assert r.stdout, "text mode produced no output"
    for line in r.stdout.rstrip("\n").splitlines():
        cols = line.split("\t")
        assert len(cols) == 6, f"expected 6 columns, got: {line!r}"
        # score column parses as a 0-1 float (reference-only signal)
        score = float(cols[1])
        assert 0.0 <= score <= 1.0, f"score out of range: {line!r}"


def test_text_mode_reference_hit_readable():
    r = run_cli("--find", "wal-protocol")
    assert r.returncode == 0
    assert "wal-protocol" in r.stdout
    assert "reference" in r.stdout


# ---------------------------------------------------------------------------
# #162 addendum — keyword match score: lexical, not semantic, never a gate
# ---------------------------------------------------------------------------

def test_help_states_lexical_not_semantic_label():
    """Owner ruling: the score is ONLY keyword/lexical matching degree —
    the help text must say so exactly, never 'similarity'/'relevance'."""
    r = run_cli("--find", "yara", "--help")
    assert r.returncode == 0
    flat = " ".join((r.stdout + r.stderr).split())
    assert "LEXICAL, NOT SEMANTIC" in flat
    assert "NOT that the hit is relevant" in flat, \
        "help must state the honest high-score reading"
    assert "does NOT mean irrelevant" in flat, \
        "help must state the low-score reading"
    assert "NEVER gates surfacing" in flat, \
        "help must state the no-threshold contract"


def test_every_hit_carries_normalized_score():
    r = run_cli("--find", "converg", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    assert hits, "fixture lost: converg should hit"
    for h in hits:
        assert isinstance(h.get("score"), (int, float)), h
        assert 0.0 <= h["score"] <= 1.0, h


def test_low_scoring_hits_still_surfaced_no_threshold():
    """A keyword that only grazes long descriptions scores low but every
    substring match must still surface — the score ranks, never gates."""
    r = run_cli("--find", "the", "--json")
    hits = json.loads(r.stdout)["tools"]
    assert len(hits) >= 20, "wide boundary shrank (thresholding?)"
    scores = [h["score"] for h in hits]
    assert min(scores) <= 0.2, \
        f"low-scoring hits missing from the surface: {min(scores)}"
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_name_match_scores_higher_than_description_match():
    """The score is an honest strength signal: a keyword hitting the name
    outranks one buried in a long description (lexical ranking only —
    both stay surfaced; the wide boundary is pinned by the no-threshold
    test above)."""
    r = run_cli("--find", "yara", "--json")
    hits = json.loads(r.stdout)["tools"]
    name_hits = [h for h in hits if "yara" in str(h.get("name", "")).lower()]
    other_hits = [h for h in hits
                  if "yara" not in str(h.get("name", "")).lower()]
    assert name_hits and other_hits, hits
    assert min(h["score"] for h in name_hits) > \
        max(h["score"] for h in other_hits)


def test_hits_sorted_by_score_descending():
    r = run_cli("--find", "converg", "--json")
    hits = json.loads(r.stdout)["tools"]
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True), scores


def test_score_is_deterministic():
    r1 = run_cli("--find", "converg", "--json")
    r2 = run_cli("--find", "converg", "--json")
    assert r1.stdout == r2.stdout


# ---------------------------------------------------------------------------
# #162 addendum 3 — type filter + multi-keyword boolean logic
# ---------------------------------------------------------------------------

def test_type_filter_narrows_unified_query():
    r = run_cli("--find", "deobfuscation", "--type", "reference", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    assert hits, "reference hits expected"
    assert all(h["type"] == "reference" for h in hits)


def test_type_filter_can_yield_empty_validly():
    r = run_cli("--find", "yara", "--type", "template", "--json")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"count": 0, "tools": []}


def test_type_filter_invalid_value_usage_error():
    r = run_cli("--find", "yara", "--type", "templateX")
    assert r.returncode == 2


def test_type_filter_composes_with_internal_filters():
    r = run_cli("--capability", "crypto:decode", "--type", "tool", "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["count"] == 1 and out["tools"][0]["name"] == "crypto-tool"
    r2 = run_cli("--capability", "crypto:decode", "--type", "reference",
                 "--json")
    assert r2.returncode == 0
    assert json.loads(r2.stdout) == {"count": 0, "tools": []}


def test_multi_keyword_or_default():
    """Comma-separated terms default to OR: hits from both term groups."""
    r = run_cli("--find", "wal-protocol,yara", "--json")
    assert r.returncode == 0, r.stderr
    hits = json.loads(r.stdout)["tools"]
    names = {h.get("name") for h in hits}
    assert "wal-protocol" in names
    assert any(str(n).startswith("yara") for n in names)


def test_multi_keyword_all_requires_every_term():
    """--match all = boolean AND: every returned hit must independently
    match BOTH single-term queries (verified via the per-term query), so
    single-term-only matches leak nothing into the AND face."""
    r = run_cli("--find", "stalker,windowed", "--match", "all", "--json")
    assert r.returncode == 0, r.stderr
    all_hits = json.loads(r.stdout)["tools"]
    assert all_hits, "both-terms matches expected"
    s = run_cli("--find", "stalker", "--json")
    w = run_cli("--find", "windowed", "--json")
    s_names = {h["name"] for h in json.loads(s.stdout)["tools"]}
    w_names = {h["name"] for h in json.loads(w.stdout)["tools"]}
    both = s_names & w_names
    got = {h["name"] for h in all_hits}
    assert got == both, f"AND face diverges from the per-term intersection: {got ^ both}"


def test_multi_keyword_or_superset_of_all():
    r_all = run_cli("--find", "stalker,windowed", "--match", "all", "--json")
    r_any = run_cli("--find", "stalker,windowed", "--match", "any", "--json")
    all_names = {h["name"] for h in json.loads(r_all.stdout)["tools"]}
    any_names = {h["name"] for h in json.loads(r_any.stdout)["tools"]}
    assert all_names <= any_names
    assert len(any_names) >= len(all_names)


def test_match_invalid_value_usage_error():
    r = run_cli("--find", "yara", "--match", "xor")
    assert r.returncode == 2


def test_match_requires_find():
    r = run_cli("--capability", "crypto:decode", "--match", "all")
    assert r.returncode == 2


def test_help_documents_addendum3_surface():
    r = run_cli("--find", "yara", "--help")
    flat = " ".join((r.stdout + r.stderr).split())
    for needle in ("--type", "--match any = OR (default), --match all = AND",
                   "LEXICAL, NOT SEMANTIC", "Boolean syntax"):
        assert needle in flat, f"help missing: {needle!r}"


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
