# -*- coding: utf-8 -*-
"""tests/test_recipes.py — issue #278 P4-b: tools/pipelines/recipes/*.yaml contract.

Recipe schema (documented in tools/pipelines/README.md):
  id, title, description, steps: [{tool, input, output}],
  fallback: [tool names or capability queries], verify: hook name,
  reuse_check: description.

Vocabulary contract: every step.tool / fallback entry must be a tool name
registered in tools/_INDEX.yaml, or a capability query that exact/prefix
matches an index capability tag (same semantics as tools/tool-search.py).
Recipes are TEMPLATES for runs/plan-C<NN>.md generation — data only, no
executor code.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RECIPES_DIR = ROOT / "tools" / "pipelines" / "recipes"
INDEX = ROOT / "tools" / "_INDEX.yaml"

EXPECTED = {"stage-unpack", "crypto-decrypt", "syscall-chain",
            "iat-chain", "go-recovery"}
SCHEMA_KEYS = {"id", "title", "description", "steps", "fallback",
               "verify", "reuse_check"}


def _recipes() -> list[Path]:
    return sorted(RECIPES_DIR.glob("*.yaml"))


def _index_vocabulary() -> tuple[set[str], set[str]]:
    data = yaml.safe_load(INDEX.read_text(encoding="utf-8"))
    tools = data["tools"]
    names = {t["name"] for t in tools}
    caps = {t["capability"] for t in tools}
    return names, caps


def _valid_entry(entry: str, names: set[str], caps: set[str]) -> bool:
    """Tool name from the index, or capability query (exact/prefix match)."""
    if ":" in entry:
        return any(c == entry or c.startswith(entry) for c in caps)
    return entry in names


def test_all_five_recipes_present():
    assert {p.stem for p in _recipes()} == EXPECTED


def test_recipes_parse_with_documented_schema():
    for p in _recipes():
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        missing = SCHEMA_KEYS - set(data)
        assert not missing, f"{p.name}: missing keys {missing}"
        assert isinstance(data["steps"], list) and data["steps"], \
            f"{p.name}: steps must be a non-empty list"
        for step in data["steps"]:
            for k in ("tool", "input", "output"):
                assert step.get(k), f"{p.name}: step missing {k}: {step}"
        assert isinstance(data["fallback"], list), \
            f"{p.name}: fallback must be a list"
        assert data["verify"], f"{p.name}: verify hook name required"
        assert data["reuse_check"], f"{p.name}: reuse_check required"


def test_recipe_vocabulary_matches_index():
    names, caps = _index_vocabulary()
    for p in _recipes():
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        entries = [s["tool"] for s in data["steps"]] + list(data["fallback"])
        for entry in entries:
            assert _valid_entry(entry, names, caps), \
                f"{p.name}: {entry!r} not in index (tool name or " \
                f"capability query required)"
