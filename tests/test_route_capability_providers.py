# -*- coding: utf-8 -*-
"""RED tests for issue #692 WP3 — provider selection pass in route_capability.

Pins design D3/D4:

- select_providers(capability, tools, state): rank providers quality ->
  cost_hint.mem_gb -> registry order; evaluate `requires` tokens against
  WORKSPACE STATE only (no live environment probes — unresolved tokens are
  `unverified`, never `blocked`); recommend the first available.
- Acceptance 2 (two states, different providers): budget-tight -> dexdc;
  budget-rich + no source -> jadx; source tree present -> gitnexus wins
  android:call-graph.
- Acceptance 4 (failure memory): a recorded jadx failure flips the next
  round's preference to dexdc; a failure older than 24h expires.
- scripts/provider_health.py: fail-open record/query of
  <ws>/provider_health.json.
- Mem-gate demotion: the #670 verdict annotates the jadx provider row
  (blocked: mem budget), it is NOT a pipeline stage anywhere.

RED phase: route_capability has no select_providers / load_workspace_state;
provider_health.py does not exist.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_rc = _load("_route_capability_692", SCRIPTS / "route_capability.py")


# ---------- workspace state helpers ----------

def _ws(tmp_path: Path, mem_verdict: str | None = None,
        source_tree: bool = False, gitnexus_index: bool = False,
        tool_probes: bool = False) -> Path:
    ws = tmp_path / "ws"
    ev = ws / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    if mem_verdict:
        (ev / "apk_mem_gate.json").write_text(
            json.dumps({"verdict": mem_verdict}), encoding="utf-8")
    if source_tree:
        src = ev / "jadx-out" / "com" / "example"
        src.mkdir(parents=True)
        (src / "Main.java").write_text("class Main {}", encoding="utf-8")
    if gitnexus_index:
        (ev / "gitnexus_index.json").write_text(json.dumps({
            "source_root": "evidence/jadx-out",
            "indexed_at": "2026-08-25T00:00:00Z", "tools": 16}),
            encoding="utf-8")
    if tool_probes:
        (ev / "tool-probes.json").write_text(json.dumps({
            "jadx_bin": True, "dexdc_wheel": True, "smali_toolchain": True}),
            encoding="utf-8")
    return ws


def _select(ws: Path, capability: str = "android:java-source") -> dict:
    tools = _rc.load_index(_rc.DEFAULT_INDEX)
    state = _rc.load_workspace_state(ws)
    return _rc.select_providers(capability, tools, state)


def _rec(provider: str) -> dict:
    for p in _select()["providers"]:
        if p["name"] == provider:
            return p
    raise AssertionError(f"provider {provider} not in list")


# ---------- acceptance 2: same query, different states ----------

def test_budget_tight_recommends_dexdc_not_jadx(tmp_path):
    """Mem-gate verdict smali-only => jadx BLOCKED (the #670 gate is this
    provider's precondition annotation, not a pipeline stage)."""
    ws = _ws(tmp_path, mem_verdict="smali-only", tool_probes=True)
    sel = _select(ws)
    jadx = next(p for p in sel["providers"] if p["provider"] == "jadx")
    assert jadx["status"] == "blocked"
    assert "mem" in jadx["blocked_reason"].lower()
    assert sel["recommendation"] == "dexdc-decompile"


def test_budget_rich_no_source_recommends_jadx(tmp_path):
    ws = _ws(tmp_path, mem_verdict="jadx-ok", tool_probes=True)
    sel = _select(ws)
    jadx = next(p for p in sel["providers"] if p["provider"] == "jadx")
    assert jadx["status"] == "available"
    assert sel["recommendation"] == "jadx-decompile"  # high beats mid


def test_source_tree_flips_call_graph_to_gitnexus(tmp_path):
    ws = _ws(tmp_path, tool_probes=True)
    sel = _select(ws, "android:call-graph")
    assert sel["recommendation"] != "gitnexus-query"  # no index -> dexdc mid
    assert sel["recommendation"] == "dexdc-decompile"

    ws2 = _ws(tmp_path, source_tree=True, gitnexus_index=True,
              tool_probes=True)
    sel2 = _select(ws2, "android:call-graph")
    assert sel2["recommendation"] == "gitnexus-query"


def test_ranking_is_quality_then_cost(tmp_path):
    ws = _ws(tmp_path, mem_verdict="jadx-ok", tool_probes=True)
    order = [p["provider"] for p in _select(ws)["providers"]]
    assert order == ["jadx", "dexdc", "baksmali"]


# ---------- unverified never blocks (no live probes in selection) ----------

def test_missing_probe_evidence_is_unverified_not_blocked(tmp_path):
    ws = _ws(tmp_path, mem_verdict="jadx-ok")  # no tool-probes.json
    jadx = next(p for p in _select(ws)["providers"]
                if p["provider"] == "jadx")
    assert jadx["status"] == "unverified"
    assert "jadx_bin" in jadx["unverified_reason"]


def test_selection_never_runs_environment_probes(tmp_path):
    """load_workspace_state reads FILES only — no import/which side effects
    observable via monkeypatched importlib/shutil raising."""
    import importlib as _il
    import shutil
    ws = _ws(tmp_path, mem_verdict="jadx-ok")
    orig_import, orig_which = _il.import_module, shutil.which

    def _boom(*a, **k):
        raise AssertionError("selection must not probe the environment")

    _il.import_module = _boom
    shutil.which = _boom
    try:
        _rc.load_workspace_state(ws)
        _select(ws)
    finally:
        _il.import_module = orig_import
        shutil.which = orig_which


# ---------- acceptance 4: failure memory flips the next round ----------

def _ph():
    return _load("_provider_health_692", SCRIPTS / "provider_health.py")


def test_jadx_failure_flips_preference_to_dexdc(tmp_path):
    ws = _ws(tmp_path, mem_verdict="jadx-ok", tool_probes=True)
    assert _select(ws)["recommendation"] == "jadx-decompile"  # before

    _ph().record(ws, provider="jadx", outcome="fail", reason="timeout")
    sel = _select(ws)  # next round
    assert sel["recommendation"] == "dexdc-decompile"
    jadx = next(p for p in sel["providers"] if p["provider"] == "jadx")
    assert jadx.get("recent_failure") is True
    assert any("recent failure" in r.lower() for r in sel["rationale"])


def test_old_failure_expires_after_24h(tmp_path):
    ws = _ws(tmp_path, mem_verdict="jadx-ok", tool_probes=True)
    ph = _ph()
    ph.record(ws, provider="jadx", outcome="fail", reason="timeout")
    # age the entry past the window
    path = ws / "provider_health.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    old = (datetime.now(timezone.utc) - timedelta(hours=25)
           ).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["jadx"][0]["ts"] = old
    path.write_text(json.dumps(data), encoding="utf-8")

    sel = _select(ws)
    assert sel["recommendation"] == "jadx-decompile"


def test_provider_health_fail_open_on_corrupt_file(tmp_path):
    ph = _ph()
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "provider_health.json").write_text("{not json", encoding="utf-8")
    assert ph.recent_failures(ws) == {}


# ---------- CLI: --capability direct query mode ----------

def test_cli_capability_direct_query(tmp_path, capsys):
    ws = _ws(tmp_path, mem_verdict="smali-only", tool_probes=True)
    rc = _rc.main(["--features", "{}", "--capability", "android:java-source",
                   "--workspace", str(ws), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["providers"]["capability"] == "android:java-source"
    assert out["providers"]["recommendation"] == "dexdc-decompile"
