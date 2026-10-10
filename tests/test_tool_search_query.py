# -*- coding: utf-8 -*-
"""tests/test_tool_search_query.py — the query grammar pins (owner ruling
2026-10-08: bare space-splitting is ambiguous; the search needs logic).
Quoted phrases are ATOMIC; AND/OR/NOT + parens; bare terms default to the
forgiving OR group (--match all flips to AND)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TOOLS = ROOT / "tools"
for p in (SCRIPTS, TOOLS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("tool_search", TOOLS / "tool-search.py")
ts = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(ts)


def q(query: str, mode: str = "any"):
    return ts.compile_query(query, mode)


def hit(query: str, text: str, mode: str = "any") -> bool:
    return ts._haystack_hit(text, q(query, mode))


# ------------------------------------------------------------ atoms

def test_phrase_is_atomic_no_word_splitting():
    ast = q('"unicorn engine"')
    assert ts._ast_leaves(ast) == ["unicorn engine"]
    assert hit('"unicorn engine"', "the unicorn engine emulator")
    assert not hit('"unicorn engine"', "unicorn and an engine")  # NOT contiguous


def test_bare_terms_default_to_or_match_all_flips_to_and():
    assert hit("emulator unicorn", "a unicorn here")
    assert hit("emulator unicorn", "an emulator there")
    assert not hit("emulator unicorn", "neither", mode="all")
    assert hit("emulator unicorn", "unicorn emulator", mode="all")


# ------------------------------------------------------------ operators

def test_and_or_not_and_precedence():
    assert hit("ghidra AND jadx", "ghidra with jadx")
    assert not hit("ghidra AND jadx", "ghidra alone")
    assert hit("ghidra OR jadx", "jadx only")
    assert not hit("ghidra NOT windows", "ghidra on windows")
    assert hit("ghidra NOT windows", "ghidra on linux")
    # AND binds tighter than OR (single letters collide as substrings —
    # use real words)
    assert hit("apple OR banana AND cherry", "banana cherry")
    assert not hit("apple OR banana AND cherry", "banana durian")


def test_parentheses_group():
    assert hit("(ghidra OR jadx) AND windows", "jadx on windows")
    assert not hit("(ghidra OR jadx) AND windows", "jadx on linux")
    assert hit("(a AND b) OR (c AND d)", "c d")


def test_operator_synonyms_and_comma_is_or():
    assert hit("ghidra && jadx", "ghidra jadx")
    assert hit("ghidra || jadx", "jadx")
    assert not hit("!strings", "strings everywhere")
    assert hit("!strings", "no s-word here")
    assert hit("ghidra, jadx", "jadx")  # comma = OR (back-compat)


def test_degenerate_queries_never_crash():
    for bad in ("", "   ", "AND", "NOT", "((", '"unclosed'):
        ast = q(bad)
        assert isinstance(ast, tuple)
    assert hit('"unclosed', "unclosed")  # unterminated quote degrades to term
    assert not hit("AND", "anything")    # dangling operator never matches


def test_leaves_feed_the_scorer():
    assert ts._ast_leaves(q('(ghidra OR jadx) AND "dex parser" NOT strings')) \
        == ["ghidra", "jadx", "dex parser", "strings"]


# ------------------------------------------------------------ CLI face

def test_cli_expression_end_to_end():
    import subprocess
    r = subprocess.run(
        [sys.executable, str(TOOLS / "tool-search.py"),
         "--find", "(ghidra OR jadx) NOT windows"],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    assert "ghidra" in r.stdout.lower() or "jadx" in r.stdout.lower()
