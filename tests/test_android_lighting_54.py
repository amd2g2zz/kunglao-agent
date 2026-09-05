#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_android_lighting_54.py — issue #54 Android toolchain visibility.

VERIFIED ROOT CAUSE (prior session):
  - scripts/route_capability.py: keyword tables only trigger android tools on
    literal "android"/"java-source"; the live dispatch "分析这个APK的登录加密逻辑"
    (and its English variant) fell to the static:disasm fallback with
    "no feature/claim rule fired" — android tools invisible.
  - hooks/worker_budget_gates.py _load_tool_index_keywords derives gate
    keywords from tools/_INDEX.yaml category + capability halves, so android
    tools contribute compound halves ("android:java-source") that literal
    prose never matches — a dispatch CITING jadx/baksmali can never reach
    mode='matched' (the #46 self-attestation lock shape, android edition).

OWNER RULING (#54 anchor): 不能强制 — we cannot force tool choice; LIGHTING
ONLY. The agent may ignore every recommendation; there must be ZERO new
REJECT paths. These tests pin exactly that:
  - route(): android-flavored dispatches gain a non-binding
    `capability_suggestions` entry (the SAME prior shape as the #692 WP6
    deobf prior: exactly {capability, rationale}, rationale naming the
    concrete registered android tool + the WHY); the recommendation
    chain/confidence are identical with and without the lighting.
  - gate: android alias keywords join the tool-first keyword map (provider
    names + distinctive CJK android-RE compounds), while an android-flavored
    dispatch WITHOUT a tool-catalog marker still passes silently (no_match) —
    existing REJECT semantics untouched, only keyword coverage enriched.

RED phase: no android alias tables exist — the route repro fires no android
suggestion and the gate keyword map lacks the android aliases.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import route_capability as rc  # noqa: E402  (pytest pythonpath: scripts)
import worker_budget_gates as wbg  # noqa: E402  (pytest pythonpath: hooks)

REPO = Path(__file__).resolve().parents[1]
ROUTE_CLI = REPO / "scripts" / "route_capability.py"

# the live failing repros from the issue #54 report
REPRO_ZH = "分析这个APK的登录加密逻辑"
REPRO_EN = "analyze login encryption in this APK"

# registered android toolchain providers (tools/_INDEX.yaml)
ANDROID_TOOLS = ("jadx-decompile", "baksmali-xref", "apkid-prescan",
                 "gitnexus-query", "dexdc-decompile")


def _route(claim_text: str, features: dict | None = None) -> dict:
    return rc.route(features or {}, claim_text, rc.DEFAULT_INDEX)


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROUTE_CLI), *args],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
    )


# ---------------------------------------------------------------------------
# RED: the live repros must light android tools in the route output
# ---------------------------------------------------------------------------

def test_repro_zh_route_carries_android_suggestions():
    result = _route(REPRO_ZH)
    sugs = result.get("capability_suggestions") or []
    assert sugs, ("android-flavored dispatch must light android suggestions "
                  "(#54 RED: 'no feature/claim rule fired' hid the toolchain)")
    caps = {s["capability"] for s in sugs}
    assert caps
    assert all(c.startswith("android:") for c in caps), caps
    # android TOOLS present in the result: the rationale names the concrete
    # registered tool, and each capability resolves to registered tools
    blob = json.dumps(result, ensure_ascii=False)
    assert any(t in blob for t in ANDROID_TOOLS), blob
    tools = rc.load_index(rc.DEFAULT_INDEX)
    resolved = {t for s in sugs
                for t in rc.resolve_capability(s["capability"], tools)}
    assert resolved & set(ANDROID_TOOLS), resolved


def test_repro_en_route_carries_android_suggestion():
    sugs = _route(REPRO_EN).get("capability_suggestions") or []
    assert sugs, "English variant must light android suggestions too (#54)"
    assert any(s["capability"].startswith("android:") for s in sugs)


def test_suggestion_shape_matches_deobf_prior_shape():
    """Exactly {capability, rationale} — the #692 WP6 prior shape. The
    exact-keys pin in test_deobf_composition must keep holding."""
    for s in _route(REPRO_ZH).get("capability_suggestions") or []:
        assert set(s) == {"capability", "rationale"}, (
            f"suggestion must be prior-shaped, got keys {sorted(s)}")


def test_suggestion_rationale_carries_the_why():
    """Rationale-bearing lighting: one plain line naming WHY + the concrete
    registered android tool (e.g. 'APK 样本 → apkid-prescan 先识别加固器')."""
    for s in _route(REPRO_ZH).get("capability_suggestions") or []:
        why = s["rationale"]
        assert why and "\n" not in why, why
        assert any(t in why for t in ANDROID_TOOLS), why


# ---------------------------------------------------------------------------
# zero-enforcement: lighting never touches the route
# ---------------------------------------------------------------------------

def test_lighting_never_touches_fallback_chain_or_confidence():
    """Both dispatches fall back (no feature/claim rule) — the fallback route
    must be IDENTICAL with and without android lighting; the lighting is
    additive only (不能强制: the agent may ignore it)."""
    neutral = _route("summarize the workspace state")
    android = _route(REPRO_ZH)
    assert android["recommendation"]["confidence"] == \
        neutral["recommendation"]["confidence"] == 0.4
    assert android["recommendation"]["chain"] == \
        neutral["recommendation"]["chain"]
    assert "fallback" in " ".join(android["rationale"])


def test_confident_route_keeps_chain_with_lighting():
    """A dispatch that fires a REAL rule ('unpack' → static:overlay) AND an
    android alias keeps the exact rule-driven route; suggestions add nothing
    to chain/confidence."""
    baseline = _route("unpack it", {"machine": "AMD64"})
    lit = _route("unpack this apk", {"machine": "AMD64"})
    assert lit["recommendation"]["chain"] == baseline["recommendation"]["chain"]
    assert lit["recommendation"]["confidence"] == \
        baseline["recommendation"]["confidence"]
    assert lit.get("capability_suggestions")


def test_non_android_dispatch_has_no_suggestions():
    assert not (_route("static overview of imports")
                .get("capability_suggestions"))
    assert not (_route("decode the string table", {"machine": "AMD64"})
                .get("capability_suggestions"))
    assert not (_route("").get("capability_suggestions"))


# ---------------------------------------------------------------------------
# CLI faces (stdout lighting): JSON + text
# ---------------------------------------------------------------------------

def test_route_cli_json_face_carries_suggestions():
    r = _run_cli("--features", "{}", "--claim-text", REPRO_ZH, "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out.get("capability_suggestions"), out
    blob = json.dumps(out, ensure_ascii=False)
    assert any(t in blob for t in ANDROID_TOOLS)


def test_route_cli_text_face_renders_lighting():
    r = _run_cli("--features", "{}", "--claim-text", REPRO_ZH)
    assert r.returncode == 0, r.stderr
    assert "capability_suggestions" in r.stdout
    assert any(t in r.stdout for t in ANDROID_TOOLS), r.stdout


# ---------------------------------------------------------------------------
# gate keyword derivation: android aliases join the tool-first keyword map
# (lighting data — coverage, NOT new enforcement)
# ---------------------------------------------------------------------------

def test_android_aliases_in_gate_keyword_map():
    kw = wbg._load_tool_index_keywords(wbg._SKILL_ROOT)
    # provider names (derived from the registry's own provider: field)
    assert kw.get("jadx") == "jadx-decompile"
    assert kw.get("baksmali") == "baksmali-xref"
    assert kw.get("apkid") == "apkid-prescan"
    assert kw.get("gitnexus") == "gitnexus-query"
    assert kw.get("dexdc") == "dexdc-decompile"
    # distinctive CJK android-RE compounds
    assert kw.get("反编译") == "jadx-decompile"
    assert kw.get("加固") == "apkid-prescan"
    assert kw.get("smali") == "baksmali-xref"
    # pre-existing halves stay put (first-registered wins, unchanged)
    assert kw.get("android") == "jadx-decompile"
    assert kw.get("java-source") == "jadx-decompile"
    assert kw.get("crypto") == "crypto-tool"
    assert kw.get("ida") == "ida-decompile"


def test_gate_map_keeps_generic_words_out():
    """_TOOLFIRST_STOPWORDS discipline: generic prose never joins the gate
    trigger set — ambiguous terms are route-side lighting ONLY."""
    kw = wbg._load_tool_index_keywords(wbg._SKILL_ROOT)
    for generic in ("app", "apk", "java", "加密", "登录", "tls", "okhttp",
                    "frida", "xposed", "certificate", "network library",
                    "login encryption"):
        assert generic not in kw, generic


def test_android_citing_dispatch_reaches_matched():
    """The enrichment's purpose: a dispatch that RUNS a registered android
    tool and CITES it has a compliant path — the #46 self-attestation lock
    must not reappear for the android toolchain."""
    ev = wbg._toolfirst_evaluate(
        "use jadx for the java-source pass", "jadx-decompile")
    assert ev["mode"] == "matched", ev
    assert ev["tool"] == "jadx-decompile"
    assert "jadx" in ev["keywords"]


def test_verify_tool_catalog_resolves_android_citation(tmp_path):
    """A done worker's `tool-catalog: jadx-decompile` must resolve (and a
    fabricated name must not) — the #630 liveness proxy covers android."""
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "worker-status-android-ok.md").write_text(
        "status: done\ntool-catalog: jadx-decompile\n", encoding="utf-8")
    (runs / "worker-status-android-bad.md").write_text(
        "status: done\ntool-catalog: totally-made-up-tool\n", encoding="utf-8")
    violations = wbg.verify_tool_catalog(tmp_path)
    assert len(violations) == 1
    assert violations[0]["worker"] == "worker-status-android-bad"


# ---------------------------------------------------------------------------
# ZERO-enforcement red line (#54 owner ruling 不能强制) — pinned explicitly
# ---------------------------------------------------------------------------

def test_redline_android_dispatch_without_marker_still_passes():
    """THE acceptance red line: an android-flavored dispatch WITHOUT a
    tool-catalog marker still PASSES silently (no_match), exactly as today.
    No new REJECT path may exist for android dispatches."""
    ok, reason = wbg.check_tool_first(
        {}, f"[T1 tools=grep] claim C-001 {REPRO_ZH}", "")
    assert ok is True, f"ZERO new REJECT paths (#54): {reason}"
    ev = wbg._toolfirst_evaluate(REPRO_ZH.lower(), None)
    assert ev["mode"] == "no_match", ev


def test_redline_english_variant_without_marker_still_passes():
    ok, reason = wbg.check_tool_first(
        {}, f"[T1 tools=grep] claim C-001 {REPRO_EN}", "")
    assert ok is True, f"ZERO new REJECT paths (#54): {reason}"
    ev = wbg._toolfirst_evaluate(REPRO_EN.lower(), None)
    assert ev["mode"] == "no_match", ev


def test_redline_existing_reject_semantics_unchanged():
    """The pre-#54 faces fire exactly as before: keyword hit without marker
    still rejects (existing semantics — only WHICH keywords are visible
    changed), stopword discipline intact."""
    ok, reason = wbg.check_tool_first({}, "decode the crypto layer", "")
    assert ok is False
    assert "tool-catalog" in reason
    ok2, _msg = wbg.check_tool_first(
        {}, "[T1 tools=grep] claim C-001 static overview of imports", "")
    assert ok2, "stopword discipline must be unchanged"


def test_redline_optout_still_honored_on_android_keyword_hit():
    """The explicit `tool-catalog: none (reasoning: ...)` opt-out keeps
    passing even when an android alias hit — the agent may always decline."""
    ok, reason = wbg.check_tool_first(
        {}, "反编译这个dex",
        "tool-catalog: none (reasoning: sample is a stub, jadx adds nothing)")
    assert ok is True, reason
