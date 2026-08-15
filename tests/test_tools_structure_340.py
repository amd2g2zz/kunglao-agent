# -*- coding: utf-8 -*-
"""tests/test_tools_structure_340.py — issue #340: tools/ directory structure normalization.

Target-structure contract (documented in tools/README.md "Structure rules (#340)"):

R1 root-level placement: the tools/ root may only hold (a) index/doc files
   (_INDEX.md/_INDEX.yaml/_index-*.md/README.md), (b) the two toolshelf
   meta-tools (tool-search.py / validate_index.py — they operate on tools/
   itself, not on samples, documented exception), (c) directories.
   Every registered tool script lives in `tools/<category>/`; cross-category
   shared libraries live in `tools/_lib/` (single point for shared code).
R2 category id == directory name: each category value in _INDEX.yaml must
   match the tools/<category>/ directory name; the only exception is
   dynamic (its capability is provided by MCP + VM channels, #339 deleted
   the empty shell directory and forbids recreating it). Legacy ids
   aux/pipeline must not remain.
R3 one shared module per category: the static category has exactly one
   shared helper module (common.py); a second module (_common.py) must not
   regress.
R4 merged common keeps the full public surface: after the merge common.py
   must expose every public name of both old modules (CLI plumbing +
   byte-scan helpers).
R5 no __pycache__ in the repo: .gitignore covers __pycache__ and *.pyc at
   any depth under tools/ (verified mechanically via git check-ignore).
R6 full import path after migration: each moved CLI answers --help with
   exit 0 from its new location; tool-search works end to end (query result
   count == registry entry count).
R7 zero stale references to old paths: live docs/code/manifests must not
   reference old root-level paths or old category filenames
   (openspec/changes/ is a frozen historical change record, exempt;
   docs/devlog/ was removed by #355).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

# ---- target layout constants (single source for this contract) ----

META_TOOLS = {"tool-search.py", "validate_index.py"}

MOVED_TOOLS = {
    "tools/auxiliary/audit_legacy_proven.py": "tools/audit_legacy_proven.py",
    "tools/auxiliary/capture_golden.py": "tools/capture_golden.py",
    "tools/auxiliary/measure_blind_coverage.py": "tools/measure_blind_coverage.py",
    "tools/auxiliary/measure_cold_start.py": "tools/measure_cold_start.py",
    "tools/pipelines/build_evidence_index.py": "tools/build_evidence_index.py",
    "tools/static/disasm_constant_check.py": "tools/disasm_constant_check.py",
    "tools/_lib/lib_disasm.py": "tools/lib_disasm.py",
}

# names that must be importable from the merged tools/static/common.py
COMMON_CLI_PLUMBING = (
    "EXIT_OK", "EXIT_NEGATIVE", "EXIT_ERROR", "L1_FIELD_RE",
    "error", "add_common_flags", "read_bytes", "read_text",
    "parse_int", "sha256", "parse_line", "report", "negative",
)
COMMON_BYTE_SCAN = (
    "EXE_SIGNATURES", "X64_PROLOG_PATTERNS", "PEB_ACCESS_PATTERNS",
    "GO_PCLNTAB_MAGICS", "MAX_NFUNC",
    "find_all", "signature_hits", "ascii_strings", "x64_prolog_offsets",
    "byte_entropy", "uniform_variance", "scan_valid_pclntab",
)

# live surfaces scanned for stale references (R7) — historical change logs
# (openspec/changes/ is a frozen record set and is exempt; docs/devlog/
# was removed entirely by #355).
LEGACY_REFS = [
    "tools/lib_disasm.py", "tools/measure_cold_start.py",
    "tools/audit_legacy_proven.py", "tools/build_evidence_index.py",
    "tools/measure_blind_coverage.py", "tools/disasm_constant_check.py",
    "tools/capture_golden.py", "tools/_index-aux.md",
    "tools/_index-pipeline.md", "tools/static/_common.py",
]
REF_SCAN_GLOBS = (
    "*.py", "*.md", "*.yaml", "*.yml", "*.tmpl", "*.toml", "*.ini",
)
REF_SCAN_DIRS = ("tools", "tests", "scripts", "hooks", "templates",
                 "references", "specs", "eval", "pipelines", ".")


def _yaml_data() -> dict:
    return yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))


# ---------- R1: root-level placement ----------

def test_tools_root_holds_only_index_docs_and_meta_tools() -> None:
    """The tools/ root .py set == {tool-search.py, validate_index.py} (meta-tool
    exception), every other .py belongs in a category directory or _lib/."""
    root_py = {p.name for p in TOOLS.glob("*.py")}
    assert root_py == META_TOOLS, (
        f"tools/ root .py must be exactly the meta-tools {sorted(META_TOOLS)}, "
        f"got: {sorted(root_py)} — registered tool scripts belong in category dirs, shared libs in _lib/")


def test_moved_tools_exist_at_new_locations_only() -> None:
    missing = [new for new in MOVED_TOOLS if not (ROOT / new).is_file()]
    stale = [old for old in MOVED_TOOLS.values() if (ROOT / old).is_file()]
    assert not missing, f"migration gaps (new location missing): {missing}"
    assert not stale, f"old locations still have leftovers (migration incomplete): {stale}"


# ---------- R2: category id == directory name ----------

def test_every_category_matches_directory_name() -> None:
    categories = {t["category"] for t in _yaml_data()["tools"]}
    offenders = sorted(
        c for c in categories
        if c != "dynamic" and not (TOOLS / c).is_dir())
    assert not offenders, (
        f"category id and directory name out of alignment (beyond the dynamic external-capability exception): {offenders}")


def test_legacy_category_ids_are_gone() -> None:
    categories = {t["category"] for t in _yaml_data()["tools"]}
    assert "aux" not in categories, "stale category id `aux` — should be auxiliary"
    assert "pipeline" not in categories, "stale category id `pipeline` — should be pipelines"
    assert "auxiliary" in categories and "pipelines" in categories, (
        "auxiliary/pipelines category ids missing")


def test_category_index_files_align_with_ids() -> None:
    """Each category (incl. dynamic) has its _index-<category>.md present; no stale old filenames remain."""
    categories = {t["category"] for t in _yaml_data()["tools"]} | {"dynamic"}
    missing = [c for c in sorted(categories)
               if not (TOOLS / f"_index-{c}.md").is_file()]
    assert not missing, f"missing _index-<category>.md: {missing}"
    assert not (TOOLS / "_index-aux.md").exists(), "stale _index-aux.md remains"
    assert not (TOOLS / "_index-pipeline.md").exists(), "stale _index-pipeline.md remains"


def test_validator_categories_pin_new_enum() -> None:
    sys.path.insert(0, str(TOOLS))
    import validate_index as vi  # noqa: E402
    assert vi.CATEGORIES == (
        "crypto", "static", "ghidra", "dynamic", "auxiliary", "pipelines"), (
        f"validate_index.CATEGORIES must be the id==dirname enum, got: {vi.CATEGORIES}")
    data = {"tools": [{"name": "t-a", "category": "auxiliary",
                       "capability": "aux:sanitize", "tier": "T1",
                       "cost_tier": "probe", "input_output": "x",
                       "description": "minimal fixture entry"}]}  # #356 W1: description required
    assert vi.validate_index(data) == [], "auxiliary should be a legal category"
    data["tools"][0]["category"] = "pipelines"
    assert vi.validate_index(data) == [], "pipelines should be a legal category"


# ---------- R3/R4: one shared module per category + merged common keeps the full public surface ----------

def test_static_has_single_shared_module() -> None:
    assert (TOOLS / "static" / "common.py").is_file(), "static shared module common.py missing"
    assert not (TOOLS / "static" / "_common.py").exists(), (
        "tools/static/_common.py still present — dual shared modules must not regress (#340 merge)")


def test_merged_common_exposes_full_union_surface() -> None:
    static = TOOLS / "static"
    sys.path.insert(0, str(static))
    import common  # noqa: E402
    missing = [n for n in COMMON_CLI_PLUMBING + COMMON_BYTE_SCAN
               if not hasattr(common, n)]
    assert not missing, f"common.py public surface incomplete after the merge: {missing}"


def test_no_static_cli_imports_the_retired_module() -> None:
    offenders = [
        p.name for p in (TOOLS / "static").glob("*.py")
        if re.search(r"^\s*(from|import)\s+_common\b",
                     p.read_text(encoding="utf-8"), re.M)]
    assert not offenders, f"static CLI still imports the merged-away _common: {offenders}"


# ---------- R5: __pycache__ gitignore ----------

def test_pycache_is_gitignored_at_any_depth() -> None:
    probe = TOOLS / "auxiliary" / "__pycache__" / "mod.cpython-311.pyc"
    r = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", str(probe)],
        capture_output=True)
    assert r.returncode == 0, (
        f"{probe} not covered by gitignore (check-ignore exit {r.returncode}) — "
        ".gitignore must contain __pycache__/ and *.pyc and apply at any depth under tools/")


# ---------- R6: full import path + tool-search end-to-end availability ----------

def _run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, cwd=str(ROOT))


def test_all_moved_clis_answer_help_at_new_locations() -> None:
    offenders = []
    for new in MOVED_TOOLS:
        if not new.endswith(".py"):
            continue
        r = _run(ROOT / new, "--help")
        if r.returncode != 0:
            offenders.append(f"{new}: --help exit {r.returncode} {r.stderr[:120]}")
    assert not offenders, "CLI import chains broken after migration:\n" + "\n".join(offenders)


def test_meta_tools_answer_help_at_root() -> None:
    for name in META_TOOLS:
        r = _run(TOOLS / name, "--help")
        assert r.returncode == 0, f"{name}: --help exit {r.returncode}"


def test_tool_search_full_catalog_query_works() -> None:
    registered = len(_yaml_data()["tools"])
    r = _run(TOOLS / "tool-search.py", "--tier", "T1", "--json")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["count"] == registered, (
        f"tool-search full-catalog query count {out['count']} != registered count {registered}")


def test_validator_passes_on_shipped_index() -> None:
    r = _run(TOOLS / "validate_index.py")
    assert r.returncode == 0, r.stderr


# ---------- R7: zero stale references to old paths ----------

def test_no_legacy_path_references_in_live_surfaces() -> None:
    offenders = []
    for d in REF_SCAN_DIRS:
        base = ROOT if d == "." else ROOT / d
        if not base.is_dir():
            continue
        for p in base.iterdir():
            if not p.is_file() or p.suffix.lstrip(".") not in {
                    s.lstrip("*").lstrip(".") for s in REF_SCAN_GLOBS}:
                continue
            rel = p.relative_to(ROOT).as_posix()
            if rel == "release-manifest.yaml" or rel.startswith((
                    "pyproject", "uv.lock")):
                continue  # checked precisely below / not text-scannable
            if p.resolve() == Path(__file__).resolve():
                continue  # this contract's own legacy-name fixtures, not refs
            text = p.read_text(encoding="utf-8", errors="replace")
            for legacy in LEGACY_REFS:
                if legacy in text:
                    offenders.append(f"{rel}: `{legacy}`")
    assert not offenders, "stale old-path references (must be synced to the new location):\n" + "\n".join(offenders)


def test_manifest_declares_new_paths_and_drops_old() -> None:
    manifest = yaml.safe_load(
        (ROOT / "release-manifest.yaml").read_text(encoding="utf-8"))
    declared = set(manifest["assets"]["tools"])
    missing = [new for new in MOVED_TOOLS if new not in declared]
    stale = [old for old in MOVED_TOOLS.values() if old in declared]
    assert not missing, f"manifest does not declare new paths: {missing}"
    assert not stale, f"manifest still declares old paths: {stale}"


def test_manifest_declares_merged_common_only() -> None:
    declared = yaml.safe_load(
        (ROOT / "release-manifest.yaml").read_text(encoding="utf-8"))["assets"]["tools"]
    assert "tools/static/common.py" in declared
    assert "tools/static/_common.py" not in declared


# ---------- README documents the structure rules ----------

def test_readme_documents_structure_rules() -> None:
    text = (TOOLS / "README.md").read_text(encoding="utf-8")
    for marker in (
        "tools/_lib",            # shared-library single point
        "id == directory name",  # category alignment rule (R2) — R3 #357 English marker
        "tool-search.py",        # meta-tool exception documented
        "validate_index.py",
        "__pycache__",           # gitignore rule (R5)
    ):
        assert marker in text, f"tools/README.md missing structure-rule marker: {marker!r}"
