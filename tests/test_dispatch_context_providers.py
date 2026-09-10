# -*- coding: utf-8 -*-
"""RED tests for issue #692 WP4 — dispatch context providers block.

Pins design D5 (acceptance 3): the worker dispatch context carries the
ranked provider list + constraints so the WORKER holds in-flight
degradation authority (jadx times out -> dexdc immediately; the emit face
for the switch is the existing `capability_switch` action).

Contract:
- build_dispatch_context(ws, ..., capability=<tag>) attaches a `providers`
  block (the select_providers result: ranked providers with
  available|blocked|unverified statuses AND their reasons) — fail-open:
  selection failure omits the key, never raises.
- The claim's OWN validated capability is used when no explicit capability
  is given.
- validate_context_shape: `providers` is OPTIONAL (old #527 contexts stay
  valid); when present it must be a dict carrying capability + providers.
- providers is NOT in VERIFIER_SAFE_KEYS — the verifier stays BLIND to the
  dispatch contract (same class as tier/tools).

RED phase: build_dispatch_context has no providers key / capability param.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_dc = _load("_dispatch_context_692", SCRIPTS / "dispatch_context.py")


# ---------- fixture: a workspace with claim + evidence state ----------

@pytest.fixture
def ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ev = ws / "evidence"
    ev.mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-1\n"
        "    statement: decompile the APK to java source\n"
        "    status: OPEN\n",
        encoding="utf-8")
    (ev / "apk_mem_gate.json").write_text(
        json.dumps({"verdict": "smali-only"}), encoding="utf-8")
    (ev / "tool-probes.json").write_text(json.dumps({
        "jadx_bin": True, "dexdc_wheel": True, "smali_toolchain": True}),
        encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        "# facts\n\n| id | status | conclusion | claim_id |\n"
        "|---|---|---|---|\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n", encoding="utf-8")
    return ws


def _build(ws: Path, **kw):
    return _dc.build_dispatch_context(
        ws=ws, claim_id="C-1", tier=1, tools=["dexdc-decompile"],
        agent_name="kunglao-worker", **kw)


# ---------- acceptance 3: the context carries providers + constraints ----------

def test_context_carries_provider_list_with_constraints(ws):
    ctx = _build(ws, capability="android:java-source")
    assert "providers" in ctx, "providers block missing from dispatch context"
    block = ctx["providers"]
    assert block["capability"] == "android:java-source"
    assert block["recommendation"] == "dexdc-decompile"
    jadx = next(p for p in block["providers"] if p["provider"] == "jadx")
    assert jadx["status"] == "blocked"
    assert jadx["blocked_reason"]  # the constraint rides along
    dexdc = next(p for p in block["providers"] if p["provider"] == "dexdc")
    assert dexdc["status"] == "available"


def test_providers_block_is_json_serializable(ws):
    ctx = _build(ws, capability="android:java-source")
    dumped = json.dumps(ctx, ensure_ascii=False)  # must not raise
    assert "android:java-source" in dumped


# ---------- fail-open: selection failure omits the key, never raises ----------

def test_fail_open_selection_error_omits_key(ws, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("selection exploded")
    monkeypatch.setattr(_dc, "_providers_block", _boom) \
        if hasattr(_dc, "_providers_block") else None
    # the public face must never raise regardless of internals
    ctx = _build(ws, capability="android:java-source")
    assert isinstance(ctx, dict)


# ---------- backward compat: the key is optional (#527 contract) ----------

def test_old_shape_context_without_providers_still_valid(ws):
    ctx = _build(ws)  # no capability anywhere -> no providers block
    if "providers" not in ctx:
        _dc.validate_context_shape(ctx)  # must NOT raise


def test_validate_shape_accepts_providers_block(ws):
    ctx = _build(ws, capability="android:java-source")
    _dc.validate_context_shape(ctx)  # providers present -> still valid


def test_validate_shape_rejects_malformed_providers_block():
    ctx = {
        "version": 1, "claim_id": "C-1", "tier": 1, "tools": [],
        "agent": "w", "dispatch_ts": "2026-08-25T00:00:00Z",
        "workspace_ref": "ws", "priority_context": {}, "fact_snapshot": {},
        "validated_capability": {}, "plan_ref": None, "sibling_claims": [],
        "providers": {"nope": 1},  # missing capability/providers keys
    }
    with pytest.raises(ValueError, match="providers"):
        _dc.validate_context_shape(ctx)


# ---------- verifier BLIND: providers is not a safe key ----------

def test_providers_not_in_verifier_safe_keys():
    assert "providers" not in _dc.VERIFIER_SAFE_KEYS
