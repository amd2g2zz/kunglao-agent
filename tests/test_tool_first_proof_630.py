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

def test_marker_naming_wrong_tool_rejected():
    ok, reason = wbg.check_tool_first(
        {}, "decompile the binary", "tool-catalog: not-the-matched-tool")
    assert ok is False, "marker must name the MATCHED tool (or none+reasoning)"


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


def test_bare_marker_without_payload_rejected():
    ok, _ = wbg.check_tool_first({}, "decompile x", "tool-catalog:")
    assert ok is False, "bare marker (no tool, no none-reasoning) is self-attestation"


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
