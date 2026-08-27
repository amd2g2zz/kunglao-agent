# -*- coding: utf-8 -*-
"""TDD RED — toolchain.FIXES → structured ToolMeta (#680).

User feedback (2026-08-25): tool addresses + descriptions were missing, so
agents hunting install info waste cycles and may pick the wrong package.
#669/#670 inlined URLs for two entries (apkid, baksmali); this change gives
every FIXES entry a structured ToolMeta (url/description/repo/package/
verify_cmd) while keeping the legacy string face working.

Spec: openspec/changes/issue-680-toolmeta-fixes/specs/toolmeta-fixes/spec.md
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

_HERE = Path(__file__).parent
SCRIPTS = _HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import toolchain  # noqa: E402  (scripts/ sibling)
import toolchain_install  # noqa: E402  (scripts/ sibling — install plans)

# The ToolMeta contract fields (issue #680), exact set.
EXPECTED_FIELDS = ("fix", "description", "url", "repo", "package", "verify_cmd")

# mcp:<name> entries are derived from mcp_probe.MANIFEST and are OUT OF
# SCOPE for tool metadata (#680) — the url-coverage contract applies to the
# static registry only.
STATIC_ENTRIES = tuple(
    name for name in toolchain.FIXES if not name.startswith("mcp:"))


# ---------------------------------------------------------------------------
# RED1 — schema shape
# ---------------------------------------------------------------------------

def test_red1_schema_shape():
    """ToolMeta exists with the 6 contract fields; every FIXES value is a
    ToolMeta whose fix + description are non-empty strings."""
    assert hasattr(toolchain, "ToolMeta"), (
        "toolchain.ToolMeta missing — FIXES is still dict[str, str]")
    field_names = {f.name for f in dataclasses.fields(toolchain.ToolMeta)}
    assert field_names == set(EXPECTED_FIELDS), (
        f"ToolMeta fields {sorted(field_names)} != {sorted(EXPECTED_FIELDS)}")
    assert len(STATIC_ENTRIES) >= 20, (
        f"expected the ~20-entry static registry, got {len(STATIC_ENTRIES)}")
    for name, meta in toolchain.FIXES.items():
        assert isinstance(meta, toolchain.ToolMeta), (
            f"{name}: FIXES value is {type(meta).__name__}, not ToolMeta")
        assert isinstance(meta.fix, str) and meta.fix, f"{name}: empty fix"
        assert isinstance(meta.description, str) and meta.description, (
            f"{name}: empty description")


# ---------------------------------------------------------------------------
# RED2 — every static entry has a URL (+ issue-given anchors survive)
# ---------------------------------------------------------------------------

def test_red2_static_entries_have_url():
    """All static FIXES entries carry an http(s) URL; the apkid/baksmali
    URLs shipped inline by #669/#670 survive the refactor byte-identical."""
    for name in STATIC_ENTRIES:
        meta = toolchain.FIXES[name]
        url = getattr(meta, "url", None)
        assert isinstance(url, str) and url.startswith("http"), (
            f"{name}: url missing/not http(s): {url!r}")
        assert isinstance(meta.description, str) and meta.description, (
            f"{name}: description missing")
    assert toolchain.FIXES["apkid"].url == "https://github.com/rednaga/APKiD"
    assert toolchain.FIXES["baksmali"].url == (
        "https://github.com/baksmali/smali/releases")


# ---------------------------------------------------------------------------
# RED3 — install-able tools carry a verify command
# ---------------------------------------------------------------------------

def test_red3_installable_tools_carry_verify_cmd():
    """Every FIXES entry that toolchain_install can auto-install (kind=auto)
    carries a verify_cmd the operator/agent can run after install."""
    installable = sorted(
        name for name, plan in toolchain_install.INSTALL_PLANS.items()
        if plan.kind == "auto" and name in toolchain.FIXES)
    assert installable, "FIXES x auto-install plans intersection is empty?"
    for name in installable:
        meta = toolchain.FIXES[name]
        verify = getattr(meta, "verify_cmd", None)
        assert isinstance(verify, str) and verify.strip(), (
            f"{name}: install-able tool must carry a verify_cmd, got "
            f"{verify!r}")


# ---------------------------------------------------------------------------
# RED4 — rendering: URL on its own line; unknown URL degrades, never crashes
# ---------------------------------------------------------------------------

def test_red4_render_url_own_line_and_unknown_fallback():
    """Operator-rendered guidance puts the URL on its own line; a url=None
    entry (mcp:<name>, out of scope) simply omits the line — no crash, no
    fabricated address."""
    jadx = toolchain.CheckResult(name="jadx", status=toolchain.Status.FAIL,
                                 tier=toolchain.Tier.HARD, detail="not found")
    mcp = toolchain.CheckResult(name="mcp:ghidra",
                                status=toolchain.Status.FAIL,
                                tier=toolchain.Tier.HARD,
                                detail="not registered")
    report = toolchain.ToolchainReport(project_type="android",
                                       items=[jadx, mcp])
    out = toolchain.format_human(report)  # must not raise (url=None path)
    lines = [ln.strip() for ln in out.splitlines()]
    # known URL -> exactly one url line, directly under its fix line
    fix_line = "fix: install jadx and add it to PATH"
    url_line = "url: https://github.com/skylot/jadx"
    assert fix_line in lines, f"fix line missing from human output: {out}"
    assert url_line in lines, (
        f"url line missing (must be its own line): {out}")
    assert lines.index(url_line) == lines.index(fix_line) + 1, (
        "url line must directly follow the fix line")
    # unknown URL (mcp entry) -> degraded: NO url line for it
    assert [ln for ln in lines if ln.startswith("url:")] == [url_line], (
        f"mcp entry must omit its unknown url, got: {out}")
    # json face: fix stays a string (schema stability), fix_url is additive
    data = json.loads(toolchain.format_json(report))
    j = next(c for c in data["checks"] if c["name"] == "jadx")
    assert j["fix"] == fix_line.replace("fix: ", ""), j
    assert j["fix_url"] == "https://github.com/skylot/jadx", j
    g = next(c for c in data["checks"] if c["name"] == "mcp:ghidra")
    assert g["fix_url"] is None, g
    # entirely unknown name -> typed accessor degrades to None (old .get
    # default semantics hold via `fix_text(name) or default`)
    assert toolchain.fix_text("no-such-tool") is None
    assert toolchain.fix_text("no-such-tool") or "fallback" == "fallback"


# ---------------------------------------------------------------------------
# RED5 — backward compatibility with old string callers
# ---------------------------------------------------------------------------

def test_red5_backward_compat_with_old_string_callers():
    """str(FIXES[name]) renders the legacy guidance text (never a dataclass
    repr) and equals the typed accessor fix_text(name)."""
    legacy = str(toolchain.FIXES["pefile"])
    assert "pip install pefile" in legacy, (
        f"legacy guidance text lost: {legacy!r}")
    assert f"{toolchain.FIXES['pefile']}" == legacy, (
        "f-string interpolation must render the fix text")
    assert legacy == toolchain.fix_text("pefile"), (
        "fix_text() must be the same string surface as __str__")
    assert toolchain.fix_text("apkid").startswith("install apkid"), (
        "fix_text must expose the legacy fix prose for known names")
