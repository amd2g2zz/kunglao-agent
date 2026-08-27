# -*- coding: utf-8 -*-
"""RED tests for issue #692 WP6 — deobfuscation as capability COMPOSITION.

Pins design D8: the agent composes string_decrypt (dexdc emulator) +
dex_rewrite (dexlib2 rename, the only persistent form) + re-decompile +
re-index per claim, in whatever order the claim needs. apkid's obfuscator
tag merely raises the PRIOR:

- route_capability.route() gains `capability_suggestions` when
  evidence/apkid.json reports obfuscator rules — android:string-decrypt and
  android:dex-rewrite listed as wanted-prior capabilities, rationale naming
  the apkid rule.
- A PRIOR only: suggestions never reorder the recommendation/chain.
- No apkid obfuscator -> no suggestions.
- No fixed deobf stage sequence exists anywhere (negative pin: the
  suggestion list carries capabilities + rationale, never an ordered
  pipeline).

RED phase: route() has no capability_suggestions.
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


_rc = _load("_route_capability_wp6", SCRIPTS / "route_capability.py")

OBFUSCATED = {
    "tool": "apkid", "status": "ok",
    "summary": {"packer": [], "compiler": ["dex"],
                "obfuscator": ["obfuscator/proguard-eval"],
                "anti_vm": [], "anti_debug": [], "total": 2},
}
CLEAN = {
    "tool": "apkid", "status": "ok",
    "summary": {"packer": [], "compiler": ["dex"], "obfuscator": [],
                "anti_vm": [], "anti_debug": [], "total": 1},
}


def _ws(tmp_path: Path, apkid: dict | None) -> Path:
    ws = tmp_path / "ws"
    ev = ws / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    if apkid is not None:
        (ev / "apkid.json").write_text(json.dumps(apkid), encoding="utf-8")
    return ws


def _route(ws: Path | None) -> dict:
    return _rc.route(
        {"machine": "AMD64"}, "deobfuscate the hidden strings",
        _rc.DEFAULT_INDEX,
        ws=ws,
    )


# ---------- obfuscator tag raises the prior ----------

def test_obfuscator_tag_raises_deobf_prior(tmp_path):
    ws = _ws(tmp_path, OBFUSCATED)
    result = _route(ws)
    suggestions = result.get("capability_suggestions") or []
    caps = {s["capability"] for s in suggestions}
    assert "android:string-decrypt" in caps
    assert "android:dex-rewrite" in caps
    # the rationale names the apkid rule (evidence-traceable prior)
    joined = " ".join(s["rationale"] for s in suggestions)
    assert "obfuscator/proguard-eval" in joined


def test_no_obfuscator_no_suggestions(tmp_path):
    ws = _ws(tmp_path, CLEAN)
    result = _route(ws)
    assert not (result.get("capability_suggestions") or [])


def test_no_apkid_evidence_no_suggestions(tmp_path):
    ws = _ws(tmp_path, None)
    result = _route(ws)
    assert not (result.get("capability_suggestions") or [])


# ---------- a PRIOR only: never reorders the routing ----------

def test_prior_does_not_touch_chain_or_confidence(tmp_path):
    plain = _route(_ws(tmp_path, CLEAN))
    obfus = _route(_ws(tmp_path, OBFUSCATED))
    assert plain["recommendation"]["chain"] == \
        obfus["recommendation"]["chain"]
    assert plain["recommendation"]["confidence"] == \
        obfus["recommendation"]["confidence"]


# ---------- no fixed stage sequence (negative pin) ----------

def test_suggestions_carry_capabilities_not_a_pipeline(tmp_path):
    ws = _ws(tmp_path, OBFUSCATED)
    for s in _route(ws).get("capability_suggestions") or []:
        # prior face: capability + rationale ONLY — an ordered "step" /
        # "stage" / "sequence" field would be the pipeline regression #692
        # exists to remove
        assert set(s) == {"capability", "rationale"}, (
            f"suggestion must be prior-shaped, got keys {sorted(s)}")


def test_route_signature_accepts_none_workspace_backcompat():
    """ws=None (all pre-#692 callers) must keep working unchanged."""
    result = _rc.route({"machine": "AMD64"}, "decrypt", _rc.DEFAULT_INDEX)
    assert "recommendation" in result
    assert "capability_suggestions" not in result
