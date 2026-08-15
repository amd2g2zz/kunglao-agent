# -*- coding: utf-8 -*-
"""tests/test_declaration_scan.py — issue #320 声明体系修复 (SDD+TDD).

Four consistency contracts under test:

1. Reverse scan (存在→declared): every shipped file under
   agents/ hooks/ templates/ tools/ must be declared in
   release-manifest.yaml — doc/index-class files (README.md, _INDEX.md,
   _INDEX.yaml, _index-*.md) and runtime/hidden files are exempt.
   release_receipt.validate_manifest fails on undeclared assets.
2. Reference pins: references/_INDEX.yaml files: sha256 pins must match
   disk (re-pin via scripts/re_pin_references.py after any references/ edit).
3. scripts/README.md catalogs every scripts/*.py (inventory map completeness).
4. Human tool index rows (tools/_index-<category>.md) each have a machine
   entry in tools/_INDEX.yaml and vice versa (人类索引 = 机器索引).
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import release_receipt  # noqa: E402
import re_pin_references  # noqa: E402


def _write(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x", encoding="utf-8")
    return p


def _mini_manifest(section: str, paths: list[str]) -> dict:
    return {"assets": {section: paths}}


def _repo_manifest() -> dict:
    return yaml.safe_load((ROOT / "release-manifest.yaml").read_text(encoding="utf-8"))


# ---------- 1. reverse scan (存在→declared) ----------

class TestReverseScan:
    def test_undeclared_file_flagged(self, tmp_path):
        _write(tmp_path, "agents/declared.md")
        _write(tmp_path, "agents/undeclared.md")
        errors = release_receipt.reverse_scan(
            tmp_path, _mini_manifest("agents", ["agents/declared.md"]))
        assert any("agents/undeclared.md" in e for e in errors), errors
        assert any("release-manifest.yaml" in e for e in errors), (
            "error must carry the fix guidance (补 release-manifest.yaml)")

    def test_fully_declared_tree_passes(self, tmp_path):
        _write(tmp_path, "agents/a.md")
        _write(tmp_path, "hooks/b.py")
        _write(tmp_path, "templates/state/c.yaml")
        _write(tmp_path, "tools/d.py")
        manifest = {"assets": {
            "agents": ["agents/a.md"], "hooks": ["hooks/b.py"],
            "templates": ["templates/state/c.yaml"], "tools": ["tools/d.py"]}}
        assert release_receipt.reverse_scan(tmp_path, manifest) == []

    def test_doc_and_index_whitelist_exempt(self, tmp_path):
        for rel in ("tools/README.md", "tools/_INDEX.md", "tools/_INDEX.yaml",
                    "tools/_index-auxiliary.md", "templates/frida/README.md",
                    "hooks/README.md", "agents/_index-x.md"):
            _write(tmp_path, rel)
        assert release_receipt.reverse_scan(tmp_path, {}) == []

    def test_runtime_and_hidden_files_skipped(self, tmp_path):
        _write(tmp_path, "tools/__pycache__/mod.cpython-311.pyc")
        _write(tmp_path, "tools/.hidden.py")
        assert release_receipt.reverse_scan(tmp_path, {}) == []

    def test_missing_manifest_section_flags_every_file(self, tmp_path):
        _write(tmp_path, "tools/x.py")
        errors = release_receipt.reverse_scan(tmp_path, {"assets": {"agents": []}})
        assert any("tools/x.py" in e and "assets.tools" in e for e in errors), errors

    def test_nested_undeclared_template_flagged(self, tmp_path):
        _write(tmp_path, "templates/frida/cfg-hook.js.tmpl")
        errors = release_receipt.reverse_scan(tmp_path, {"assets": {"templates": []}})
        assert any("templates/frida/cfg-hook.js.tmpl" in e for e in errors), errors

    def test_repo_is_fully_declared(self):
        """Acceptance gate: the real tree declares every shipped asset."""
        errors = release_receipt.reverse_scan(ROOT, _repo_manifest())
        assert not errors, "undeclared assets:\n" + "\n".join(errors)

    def test_every_declared_asset_exists(self):
        manifest = _repo_manifest()
        missing = []
        for section in ("agents", "hooks", "templates", "tools"):
            for rel in manifest["assets"].get(section, []):
                if not (ROOT / rel).exists():
                    missing.append(rel)
        assert not missing, f"declared assets missing from tree: {missing}"


# ---------- 2. reference pins ----------

class TestReferencePins:
    def _index(self) -> dict:
        return yaml.safe_load(
            (ROOT / "references" / "_INDEX.yaml").read_text(encoding="utf-8"))

    def test_pins_match_disk(self):
        bad = []
        for rel, want in sorted(self._index()["files"].items()):
            p = ROOT / rel
            if not p.exists():
                bad.append(f"{rel}: missing")
                continue
            got = hashlib.sha256(p.read_bytes()).hexdigest()
            if got != want:
                bad.append(f"{rel}: pin={want[:12]} disk={got[:12]}")
        assert not bad, ("pin drift — run `python scripts/re_pin_references.py`:\n"
                         + "\n".join(bad))

    def test_every_reference_md_is_pinned(self):
        pinned = set(self._index()["files"].keys())
        unpinned = sorted({
            str(p.relative_to(ROOT)).replace("\\", "/")
            for p in (ROOT / "references").rglob("*.md")
        } - pinned)
        assert not unpinned, f"unpinned reference files: {unpinned}"

    def test_repin_fixes_drifted_index_and_is_idempotent(self, tmp_path, monkeypatch):
        refs = tmp_path / "references"
        refs.mkdir()
        (refs / "a.md").write_text("hello", encoding="utf-8")
        idx = refs / "_INDEX.yaml"
        idx.write_text(
            "files:\n  references/a.md: " + "0" * 64
            + "\nsymptom_map:\n  F1: references/a.md\n", encoding="utf-8")
        monkeypatch.setattr(re_pin_references, "ROOT", tmp_path)
        monkeypatch.setattr(re_pin_references, "INDEX", idx)
        monkeypatch.setattr(re_pin_references, "REFS", refs)

        changed, pins = re_pin_references.repin()
        assert changed == 1, "drifted index must be re-pinned"
        want = hashlib.sha256((refs / "a.md").read_bytes()).hexdigest()
        assert pins == [f"  references/a.md: {want}"]
        text = idx.read_text(encoding="utf-8")
        assert "symptom_map:" in text, "symptom_map block must be preserved"
        assert re_pin_references.repin()[0] == 0, "second repin must be a no-op"


# ---------- 3. scripts/README.md catalog ----------

class TestScriptsReadmeCatalog:
    def _catalogued(self) -> set[str]:
        text = (SCRIPTS / "README.md").read_text(encoding="utf-8")
        return set(re.findall(r"`([\w-]+\.py)`", text))

    def test_every_script_catalogued(self):
        actual = {p.name for p in SCRIPTS.glob("*.py")}
        missing = sorted(actual - self._catalogued())
        assert not missing, f"scripts missing from scripts/README.md: {missing}"

    def test_no_ghost_catalog_entries(self):
        actual = {p.name for p in SCRIPTS.glob("*.py")}
        ghosts = sorted(self._catalogued() - actual)
        assert not ghosts, f"README catalogs nonexistent scripts: {ghosts}"


# ---------- 4. human tool index = machine index ----------

class TestHumanIndexConsistency:
    def _machine_names(self) -> set[str]:
        data = yaml.safe_load(
            (ROOT / "tools" / "_INDEX.yaml").read_text(encoding="utf-8"))
        return {t["name"] for t in data.get("tools", [])}

    def _human_rows(self) -> dict[str, set[str]]:
        rows: dict[str, set[str]] = {}
        for f in sorted((ROOT / "tools").glob("_index-*.md")):
            names = set()
            for m in re.finditer(r"^\|\s*`([^`]+)`\s*\|",
                                 f.read_text(encoding="utf-8"), re.MULTILINE):
                names.add(m.group(1))
            rows[f.name] = names
        return rows

    @staticmethod
    def _mcp_channel_names() -> set[str]:
        """Names whose 契约条目 usage line starts with `mcp__` (#339 format
        contract: 用法首行 `python tools/...` 或 `mcp__`) — externally
        provided MCP-channel tools, deliberately NOT registered in
        tools/_INDEX.yaml (e.g. _index-dynamic.md x64dbg/frida)."""
        names: set[str] = set()
        for f in (ROOT / "tools").glob("_index-*.md"):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(
                    r"^###\s+([^\n]+)\n(?:(?!^### ).)*?^[ \t]*```[^\n]*\n[ \t]*mcp__",
                    text, re.MULTILINE | re.DOTALL):
                names.add(m.group(1).strip())
        return names

    def test_human_rows_have_machine_entries(self):
        machine = self._machine_names()
        mcp_channel = self._mcp_channel_names()
        ghosts = []
        for fname, names in self._human_rows().items():
            for n in sorted(names - machine - mcp_channel):
                ghosts.append(f"{fname}: `{n}` (no machine entry in tools/_INDEX.yaml)")
        assert not ghosts, "human index has unregistered entries (delete the line or register the tool):\n" + "\n".join(ghosts)

    def test_mcp_channel_exemptions_are_real(self):
        """The MCP exemption may not leak: every exempted name must actually
        carry an `mcp__` usage line in its contract entry (guards against a
        stale exemption set silently swallowing future ghosts)."""
        mcp_channel = self._mcp_channel_names()
        assert mcp_channel, "exemption set empty — _mcp_channel_names broke"
        human = set().union(*self._human_rows().values())
        stale = mcp_channel - human
        assert not stale, f"mcp__ exemption names no longer listed: {stale}"

    def test_machine_entries_have_human_rows(self):
        machine = self._machine_names()
        human = set().union(*self._human_rows().values())
        missing = sorted(machine - human)
        assert not missing, f"machine entries missing a human index row: {missing}"
