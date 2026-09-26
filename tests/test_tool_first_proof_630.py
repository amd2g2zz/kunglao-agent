# -*- coding: utf-8 -*-
"""tests/test_tool_first_proof_630.py — #630: the tool-first marker stops
accepting self-attestation.

RED (adjudicated): check_tool_first accepted the literal string
`tool-catalog:` regardless of WHAT followed — `tool-catalog: whatever` passed
without naming the matched tool (violating the gate's own docstring), and a
pre-dispatch gate can never observe execution. Adjudicated fix:
(a) minimal hardening: the marker must name the MATCHED tool (or carry the
explicit `none (reasoning: ...)` shape) — self-declared contract closed;
(b) post-side companion: NEW verify_tool_catalog() — on a done worker whose
status file cites `tool-catalog: <name>`, the name must resolve in
tools/_INDEX.yaml (LIVENESS-tier proxy; fail-open when the index is absent).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import worker_budget_gates as wbg  # noqa: E402


# ---------- (a) marker validation ----------

# H1 (autoresearch thin-base): REJECT is demoted to ADVISORY — the gate
# proceeds on every dispatch; a keyword hit without a marker (or a marker
# naming an unmatched tool) emits a toolfirst_advisory row instead.

def test_marker_naming_wrong_tool_advisory_proceeds():
    ok, reason = wbg.check_tool_first(
        {}, "decompile the binary", "tool-catalog: not-the-matched-tool")
    assert ok is True, "H1: self_attestation is advisory — dispatch proceeds"
    assert "does not actually match" in reason


def test_marker_naming_matched_tool_passes():
    ok, reason = wbg.check_tool_first({}, "decompile x", "tool-catalog:")
    if not ok:
        import re as _re
        m = _re.search(r"tool-catalog: (\S+)", reason)
        tool = m.group(1)
        ok2, _ = wbg.check_tool_first({}, "decompile x", f"tool-catalog: {tool}")
        assert ok2, f"naming the matched tool ({tool}) must pass"


def test_explicit_none_reasoning_passes():
    ok, _ = wbg.check_tool_first(
        {}, "decompile x", "tool-catalog: none (reasoning: sample too small)")
    assert ok is True


def test_bare_marker_without_payload_advisory_proceeds():
    ok, _ = wbg.check_tool_first({}, "decompile x", "tool-catalog:")
    assert ok is True, "H1: bare marker (self_attestation) is advisory, not a reject"


# ---------- (a.1) H1 misfire regression: the campaign fixture ----------

# The campaign's exact fixture: web-pack-sign-l1a is javascript-obfuscator
# STRONG, NOT JSVMP. Pre-H1 the generic keyword "web" (the unit name hits it
# ASCII-bounded) mapped to jsvmp_triage, so this dispatch text drew a
# `tool-catalog: jsvmp_triage` demand. Post-H1: no jsvmp_triage demand ever;
# the text evaluates matched/no_match.

WEB_PACK_SIGN_DISPATCH = (
    "Dispatch analysis worker for web-pack-sign-l1a (claim C-1): "
    "target/web_sign_bundle.js is javascript-obfuscator STRONG (bundler + "
    "obfuscator.io-style string array + control-flow flattening). Unpack "
    "the bundler-obfuscated signer, recover the embedded key and canonical "
    "form, re-expose sign(request) reproducing the captured signatures."
)


def test_web_pack_sign_dispatch_never_demands_jsvmp_triage():
    ev = wbg._toolfirst_evaluate(WEB_PACK_SIGN_DISPATCH.lower(), None)
    assert ev['tool'] != 'jsvmp_triage', (
        "H1 misfire: generic 'web' prose must not map to jsvmp_triage")
    assert ev['mode'] in ('no_match', 'matched'), ev
    ok, reason = wbg.check_tool_first({}, WEB_PACK_SIGN_DISPATCH,
                                      WEB_PACK_SIGN_DISPATCH)
    assert ok is True
    assert 'jsvmp_triage' not in reason


def test_missing_marker_mode_is_advisory_proceed():
    """The demotion pin: a keyword hit with no marker proceeds."""
    ok, reason = wbg.check_tool_first(
        {}, "decompile the binary with ghidra and report exports", "")
    assert ok is True, "H1: missing_marker is advisory — dispatch proceeds"
    assert reason  # the advisory reason still explains the citation hint


# ---------- (b) post-side companion ----------

def test_verify_tool_catalog_flags_unknown_name(tmp_path):
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    runs = ws / "runs"
    (runs / "worker-status-C500.md").write_text(
        "[10:00] step: done | status: done\n"
        "tool-catalog: totally-made-up-tool\n", encoding="utf-8")
    violations = wbg.verify_tool_catalog(ws)
    assert any("C500" in v["worker"] for v in violations), \
        "cited tool must resolve in tools/_INDEX.yaml"


def test_verify_failopen_without_index(tmp_path, monkeypatch):
    ws = tmp_path / "ws"; (ws / "runs").mkdir(parents=True)
    (ws / "runs" / "worker-status-C501.md").write_text(
        "status: done\ntool-catalog: anything\n", encoding="utf-8")
    # the loader reads the ABSOLUTE skill root (36 keywords always present in
    # a dev checkout) — simulate index-absence by stubbing the loader
    monkeypatch.setattr(wbg, "_load_tool_index_keywords", lambda root: {})
    assert wbg.verify_tool_catalog(ws) == []


def test_jsvmp_triage_keeps_one_distinctive_keyword():
    """H1 follow-up: jsvmp_triage retains its name-carried technical term as
    its single trigger — text literally about JSVMP maps to it, while the
    campaign's generic obfuscated-bundler prose never does."""
    ev = wbg._toolfirst_evaluate(
        "triage the jsvmp dispatch loop in the deobfuscated bundle", None)
    assert ev['tool'] == 'jsvmp_triage' and ev['keywords'] == ['jsvmp']
    # the misfire fixture stays clean
    ev2 = wbg._toolfirst_evaluate(WEB_PACK_SIGN_DISPATCH.lower(), None)
    assert ev2['tool'] != 'jsvmp_triage'
