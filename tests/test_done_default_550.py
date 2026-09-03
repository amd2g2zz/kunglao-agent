# -*- coding: utf-8 -*-
"""tests/test_done_default_550.py — #550: done-without-artifacts stops being
silently exempt.

RED (adjudicated): the W-15 machine check EXISTS (scan_done_artifact_violations,
#444) — the production hole (C-400: status done, no F400.md, trusted) fell into
the LEGACY-EXEMPT gap: a done line without an `artifacts:` declaration is
never checked. Adjudicated fix: tighten the default — done + NO declaration →
violation kind `done-undeclared` (a worker that reports done must say WHAT it
delivered); explicit `artifacts: legacy` keeps the old exemption for genuine
legacy files. Declaration-vs-disk checking unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# #770: this suite exercises the hooks TWIN of lib_kunglao
# (scan_done_artifact_violations lives only there). Bind it by path under an
# isolated module name instead of relying on sys.path race order (#762).
import importlib.util

_lk_spec = importlib.util.spec_from_file_location(
    "hooks_lib_kunglao", ROOT / "hooks" / "lib_kunglao.py")
lib_kunglao = importlib.util.module_from_spec(_lk_spec)
sys.modules["hooks_lib_kunglao"] = lib_kunglao
_lk_spec.loader.exec_module(lib_kunglao)


def _mk_done(ws: Path, stem: str, tail: str = "", artifacts: str | None = None) -> Path:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f"worker-status-{stem}.md"
    body = "[10:00] step: start | status: in-progress\n[11:00] step: end | status: done\n"
    if tail:
        body += tail + "\n"
    if artifacts is not None:
        body += f"artifacts: {artifacts}\n"
    p.write_text(body, encoding="utf-8")
    return p


def test_done_without_declaration_is_violation(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_done(ws, "C400")  # the production shape: bare done, no artifacts line
    v = lib_kunglao.scan_done_artifact_violations(ws)
    assert any(x["kind"] == "done-undeclared" and "C400" in x["worker"] for x in v), \
        "done must declare its deliverables (default tightened)"


def test_done_with_declared_and_present_ok(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    facts = ws / "facts"; facts.mkdir()
    (facts / "F401.md").write_text("# f\n", encoding="utf-8")
    _mk_done(ws, "C401", artifacts="facts/F401.md")
    assert lib_kunglao.scan_done_artifact_violations(ws) == []


def test_done_with_declared_missing_still_violation(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_done(ws, "C402", artifacts="facts/F402.md")
    v = lib_kunglao.scan_done_artifact_violations(ws)
    assert any(x["kind"] == "declared-missing" for x in v)


def test_legacy_marker_is_not_an_exemption(tmp_path):
    """User ruling 2026-08-25: NO legacy-compat path — legacy done also fails."""
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_done(ws, "C403", artifacts="legacy")
    v = lib_kunglao.scan_done_artifact_violations(ws)
    assert any("C403" in x["worker"] for x in v), "no legacy escape hatch"



def test_explicit_none_still_fails(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    _mk_done(ws, "C404", artifacts="none")
    v = lib_kunglao.scan_done_artifact_violations(ws)
    assert any(x["kind"] == "done-no-files" for x in v), \
        "artifacts: none keeps its W-15 failure semantics"


def test_in_progress_untouched(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    runs = ws / "runs"; runs.mkdir(parents=True)
    (runs / "worker-status-C405.md").write_text(
        "[10:00] step: mid | status: in-progress\n", encoding="utf-8")
    assert lib_kunglao.scan_done_artifact_violations(ws) == []
