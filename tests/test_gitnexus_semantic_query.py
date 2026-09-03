# -*- coding: utf-8 -*-
"""RED tests for issue #692 WP7 — gitnexus registration + lazy semantic_query.

Pins design D9 (acceptance 6): gitnexus is registered per mcp_probe.MANIFEST
(android, HARD, `claude mcp add gitnexus -- gitnexus mcp`) — landed with the
#316-era manifest; this WP adds the LAZY-INDEX contract:

- android:semantic-query resolves ONLY when a VALID marker
  evidence/gitnexus_index.json exists ({source_root, indexed_at, tools}).
- The marker is schema-validated, not existence-checked: a garbage or
  key-less file does NOT un-block the provider (a stale marker must not
  fake an index).
- The selection pass NEVER builds the index (cost tied to demand, no
  pre-run) — no side effects on the workspace.

RED phase: load_workspace_state checks marker existence only; the invalid
marker case un-blocks gitnexus today.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_rc = _load("_route_capability_wp7", SCRIPTS / "route_capability.py")
_mp = _load("_mcp_probe_wp7", SCRIPTS / "mcp_probe.py")


VALID_MARKER = {"source_root": "evidence/jadx-out",
                "indexed_at": "2026-08-25T00:00:00Z", "tools": 16}


def _ws(tmp_path: Path, marker: dict | str | None) -> Path:
    ws = tmp_path / "ws"
    ev = ws / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    if marker is not None:
        content = (marker if isinstance(marker, str) else json.dumps(marker))
        (ev / "gitnexus_index.json").write_text(content, encoding="utf-8")
    return ws


def _semantic(ws: Path) -> dict:
    tools = _rc.load_index(_rc.DEFAULT_INDEX)
    return _rc.select_providers("android:semantic-query", tools,
                                _rc.load_workspace_state(ws))


# ---------- gitnexus MCP registration face (acceptance 6a) ----------

def test_gitnexus_registered_in_android_manifest():
    entry = next(i for i in _mp.MANIFEST if i.name == "gitnexus")
    assert entry.tier == "HARD"
    assert "android" in entry.types
    assert entry.register.startswith("claude mcp add gitnexus")


def test_semantic_query_declared_by_gitnexus_entry():
    import yaml
    data = yaml.safe_load((REPO / "tools" / "_INDEX.yaml")
                          .read_text(encoding="utf-8"))
    gitnexus = next(t for t in data["tools"]
                    if t.get("provider") == "gitnexus")
    assert "android:semantic-query" in gitnexus["produces"]
    assert "gitnexus_index" in gitnexus["requires"]


# ---------- semantic_query resolves ONLY when a valid index exists ----------

def test_no_marker_blocked_no_recommendation(tmp_path):
    sel = _semantic(_ws(tmp_path, None))
    gitnexus = next(p for p in sel["providers"]
                    if p["provider"] == "gitnexus")
    assert gitnexus["status"] == "blocked"
    assert "lazy" in gitnexus["blocked_reason"].lower()
    assert sel["recommendation"] is None  # sole provider blocked


def test_valid_marker_unblocks_and_recommends(tmp_path):
    sel = _semantic(_ws(tmp_path, VALID_MARKER))
    gitnexus = next(p for p in sel["providers"]
                    if p["provider"] == "gitnexus")
    assert gitnexus["status"] == "available"
    assert sel["recommendation"] == "gitnexus-query"


def test_garbage_marker_still_blocked(tmp_path):
    """Schema-validated marker: garbage content must NOT un-block."""
    sel = _semantic(_ws(tmp_path, "{not json"))
    gitnexus = next(p for p in sel["providers"]
                    if p["provider"] == "gitnexus")
    assert gitnexus["status"] == "blocked"


def test_keyless_marker_still_blocked(tmp_path):
    """A marker missing {source_root, indexed_at, tools} is not a marker."""
    sel = _semantic(_ws(tmp_path, {"unrelated": True}))
    gitnexus = next(p for p in sel["providers"]
                    if p["provider"] == "gitnexus")
    assert gitnexus["status"] == "blocked"


# ---------- laziness: selection never builds (no side effects) ----------

def test_selection_never_creates_the_marker(tmp_path):
    ws = _ws(tmp_path, None)
    _semantic(ws)
    assert not (ws / "evidence" / "gitnexus_index.json").exists()
