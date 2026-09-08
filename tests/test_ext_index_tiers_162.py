# -*- coding: utf-8 -*-
"""tests/test_ext_index_tiers_162.py — issue #162: typed three-tier ext index.

Unit 1 of #162: tools/ext-scan.py ALSO scans templates/**/*.tmpl and every
regenerated entry carries two typed fields:

  type:    tool | template | reference
  consume: invoke | fill | adapt | read

Classification is mechanical (criteria 1-3 recorded in ext-scan.py):

  1. Parameter dimensionality (tool vs template): zero varying dimensions
     — CLI flags suffice → tool. scripts/ + hooks/ entry points are tools;
     templates/**/*.tmpl are templates.
  2. Placeholder enumerability (fill vs adapt): varying dimensions
     enumerable as {{PLACEHOLDER}} keys → fill; structural variance →
     adapt. An adapt-expected template DECLARES itself via a
     `consume: adapt` marker line in its leading header comment (its desc
     must name the known-variance regions).
  3. Adaptation labor (template vs reference): the whole implementation is
     the agent's job → reference. references/re-library/*.md are
     references (consume=read).

The index stays GENERATED — zero hand-edited lines (byte determinism
already pinned by tests/test_ext_index.py TestExtScan).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXT_INDEX = ROOT / "tools" / "_INDEX.ext.yaml"
EXT_SCAN = ROOT / "tools" / "ext-scan.py"

VALID_TYPES = {"tool", "template", "reference"}
VALID_CONSUMES = {"invoke", "fill", "adapt", "read"}

CLI_FIXTURE = '''#!/usr/bin/env python3
"""alpha_tool.py - fixture CLI with a usage block."""
if __name__ == "__main__":
    raise SystemExit(0)
'''

HOOK_FIXTURE = '''#!/usr/bin/env python3
"""omega_gate.py - fixture hook gate."""
if __name__ == "__main__":
    raise SystemExit(0)
'''

REF_FIXTURE = """---
name: cap-doc
description: Fixture capability declaration doc.
---
# Cap Doc
prose body
"""

FILL_TMPL_FIXTURE = """/**
 * beta_hook.js — fixture fill template ({{KEY_A}} substitution only).
 */
var a = '{{KEY_A}}';
var b = '{{KEY_B}}';
"""

ADAPT_TMPL_FIXTURE = """/**
 * gamma_hook.js — fixture adapt-expected template.
 * consume: adapt
 * Known-variance regions: module set, offset resolution path, filter
 * predicate.
 */
var m = '{{KEY_C}}';
"""


def load_ext() -> list[dict]:
    data = yaml.safe_load(EXT_INDEX.read_text(encoding="utf-8"))
    return data["ext"]


def run_py(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args],
        capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        encoding="utf-8", errors="replace",
    )


def _sandbox_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "hooks").mkdir()
    (root / "references" / "re-library").mkdir(parents=True)
    (root / "templates" / "frida").mkdir(parents=True)
    (root / "tools").mkdir()
    (root / "scripts" / "alpha_tool.py").write_text(CLI_FIXTURE, encoding="utf-8")
    (root / "hooks" / "omega_gate.py").write_text(HOOK_FIXTURE, encoding="utf-8")
    (root / "references" / "re-library" / "cap-doc.md").write_text(
        REF_FIXTURE, encoding="utf-8")
    (root / "templates" / "frida" / "beta_hook.js.tmpl").write_text(
        FILL_TMPL_FIXTURE, encoding="utf-8")
    (root / "templates" / "frida" / "gamma_hook.js.tmpl").write_text(
        ADAPT_TMPL_FIXTURE, encoding="utf-8")
    return root


# ------------------------- generator behavior (sandbox) --------------------

class TestTierTypingSandbox:
    def test_tool_tier_typed_invoke(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        assert r.returncode == 0, r.stderr
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        for name in ("alpha_tool", "omega_gate"):
            assert entries[name]["type"] == "tool", name
            assert entries[name]["consume"] == "invoke", name

    def test_template_tier_typed_fill_by_default(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        assert r.returncode == 0, r.stderr
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        # raw-stem identity: beta_hook.js.tmpl -> stem "beta_hook.js"
        e = entries["beta_hook.js"]
        assert e["type"] == "template"
        assert e["consume"] == "fill"
        assert e["source"] == "templates/frida/beta_hook.js.tmpl"

    def test_template_tier_adapt_marker_declared(self, tmp_path: Path) -> None:
        """Criterion 2, structural variance: a template that declares
        `consume: adapt` in its leading header comment is adapt-expected."""
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        assert r.returncode == 0, r.stderr
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        e = entries["gamma_hook.js"]
        assert e["type"] == "template"
        assert e["consume"] == "adapt"

    def test_reference_tier_typed_read(self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        assert r.returncode == 0, r.stderr
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        e = entries["cap-doc"]
        assert e["type"] == "reference"
        assert e["consume"] == "read"

    def test_template_usage_names_the_consumption_shape(
            self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        assert r.returncode == 0, r.stderr
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        assert "fill" in entries["beta_hook.js"]["usage"]
        assert "adapt" in entries["gamma_hook.js"]["usage"]

    def test_template_description_derived_from_header_comment(
            self, tmp_path: Path) -> None:
        root = _sandbox_root(tmp_path)
        r = run_py(EXT_SCAN, "--root", str(root), "--stdout")
        assert r.returncode == 0, r.stderr
        entries = {e["name"]: e for e in yaml.safe_load(r.stdout)["ext"]}
        assert "fixture fill template" in entries["beta_hook.js"]["description"]


# ------------------------- shipped index (real repo) ------------------------

class TestShippedIndexTyped:
    def test_every_entry_typed(self) -> None:
        for e in load_ext():
            assert e.get("type") in VALID_TYPES, (
                f"{e.get('name')}: bad type {e.get('type')!r}")
            assert e.get("consume") in VALID_CONSUMES, (
                f"{e.get('name')}: bad consume {e.get('consume')!r}")

    def test_all_three_tiers_present(self) -> None:
        entries = load_ext()
        by_type = {e["type"] for e in entries}
        assert by_type == VALID_TYPES, (
            "typed index must cover all three tiers: "
            f"got {sorted(by_type)}")

    def test_type_matches_source_dir(self) -> None:
        for e in load_ext():
            src = e["source"]
            if src.startswith(("scripts/", "hooks/")):
                assert e["type"] == "tool" and e["consume"] == "invoke", e
            elif src.startswith("templates/"):
                assert e["type"] == "template", e
                assert e["consume"] in ("fill", "adapt"), e
            elif src.startswith("references/re-library/"):
                assert e["type"] == "reference" and e["consume"] == "read", e

    def test_templates_enumerated(self) -> None:
        srcs = [e["source"] for e in load_ext()
                if e["source"].startswith("templates/")]
        tmpl = {p.relative_to(ROOT).as_posix()
                for p in (ROOT / "templates").rglob("*.tmpl")}
        assert tmpl, "fixture lost: repo carries no .tmpl templates"
        assert set(srcs) == tmpl, (
            f"templates tier drift: only-index={sorted(set(srcs) - tmpl)} "
            f"only-disk={sorted(tmpl - set(srcs))}")

    def test_check_passes_with_typed_schema(self) -> None:
        r = run_py(EXT_SCAN, "--check")
        assert r.returncode == 0, (
            f"shipped ext index is stale — regenerate via "
            f"`python tools/ext-scan.py`. stderr: {r.stderr}")


# ------------------------- criteria recorded in-repo ------------------------

class TestCriteriaRecorded:
    def test_criteria_block_present_in_generator(self) -> None:
        src = EXT_SCAN.read_text(encoding="utf-8")
        for needle in ("Tier classification criteria",
                       "Parameter dimensionality",
                       "Placeholder enumerability",
                       "Adaptation labor"):
            assert needle in src, (
                f"criteria 1-3 must be recorded in ext-scan.py: {needle!r} "
                "missing")
