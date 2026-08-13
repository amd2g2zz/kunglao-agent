# -*- coding: utf-8 -*-
"""tests/test_references_recall.py — #229 references recall tool.

Covers the issue-#229 contract:
  - scene keyword -> scene map -> files (incl. CJK scene labels)
  - category word -> category column (incl. separator-normalized queries
    like "dynamic analysis" == "dynamic-analysis")
  - file-name word -> path column
  - no match degrades to a closest-category listing, CLI exit 1
  - --list-categories / --scene-map auxiliary outputs
  - progressive disclosure: output carries INDEX rows, never file contents
  - alignment with the real #227 references/INDEX.md (52 rows / 14 scenes)
"""
from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest

import references_recall as rr

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = SCRIPTS / "references_recall.py"
REAL_INDEX = SCRIPT.parent.parent / "references" / "INDEX.md"

# ---- synthetic INDEX.md fixture (mirrors the #227 table format exactly) ----

FIXTURE = """# references/ Index

## Scenario → file (progressive disclosure triggers)

| 场景 | 主文件 | 补充 |
|------|--------|------|
| 动态分析 (x64dbg / Frida / Qiling / VM) | re-library: `tools-dynamic` + 顶层 `dynamic-re-tool-priority` | re-library: `field-notes`; `operational-mechanics` |
| 加密 / 编码 / 哈希解码 | re-library: `tools-crypto` | — |

## Top-level references

| 文件 | 类别 | 用途一句话 | 何时读(渐进披露触发条件) |
|------|------|-----------|--------------------------|
| `dynamic-re-tool-priority.md` | dynamic-analysis | Specifies tool-priority order for dynamic RE dispatch. | Before dispatching a worker for dynamic RE. |
| `guardrails.md` | governance | The full backing reference for orchestrator guardrails. | When the inline summary is insufficient. |
| `operational-mechanics.md` | mechanics | Provides the HOW behind the VM-channel launch sequence. | When launching x64dbg in the VM. |

## re-library/ (Reverse Engineering Knowledge Base)

| 文件 | 类别 | 用途一句话 | 何时读(渐进披露触发条件) |
|------|------|-----------|--------------------------|
| `re-library/tools-dynamic.md` | tools | Dynamic analysis tooling reference covering Frida hooking and x64dbg automation. | When performing runtime analysis. |
| `re-library/tools-crypto.md` | tools | Encryption/encoding/hashing tools quick reference. | When decoding encoded data. |
| `re-library/field-notes.md` | field-notes | Operational quick-notes on binary type quirks. | After initial triage. |
"""

# Body markers — must NEVER leak into recall output (progressive disclosure).
BODY = {
    "dynamic-re-tool-priority.md": "BODY-SECRET-DYNAMIC-PRIORITY",
    "guardrails.md": "BODY-SECRET-GUARDRAILS",
    "operational-mechanics.md": "BODY-SECRET-MECHANICS",
    "re-library/tools-dynamic.md": "BODY-SECRET-TOOLS-DYNAMIC",
    "re-library/tools-crypto.md": "BODY-SECRET-TOOLS-CRYPTO",
    "re-library/field-notes.md": "BODY-SECRET-FIELD-NOTES",
}


@pytest.fixture
def index_dir(tmp_path: Path) -> Path:
    """Synthetic references/ dir with the fixture INDEX.md and real stub files."""
    refs = tmp_path / "references"
    for rel, body in BODY.items():
        p = refs / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {body}\n", encoding="utf-8")
    (refs / "INDEX.md").write_text(FIXTURE, encoding="utf-8")
    return refs


def _parse(index_dir: Path) -> tuple[list[rr.Entry], list[rr.Scene]]:
    return rr.parse_index(index_dir / "INDEX.md")


def _cli(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI against the real repo index (CLI resolves INDEX.md from its
    own location; unit tests above cover the synthetic fixture)."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


# ---------- parser ----------

class TestParse:
    def test_parse_counts(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        assert len(entries) == 6
        assert len(scenes) == 2

    def test_scene_resolves_mixed_sections(self, index_dir: Path) -> None:
        """A re-library-scoped cell may still name a top-level file."""
        _, scenes = _parse(index_dir)
        dyn = next(s for s in scenes if "动态分析" in s.label)
        assert dyn.primary == ("re-library/tools-dynamic.md", "dynamic-re-tool-priority.md")
        assert dyn.supplementary == ("re-library/field-notes.md", "operational-mechanics.md")

    def test_scene_dash_supplementary_is_empty(self, index_dir: Path) -> None:
        _, scenes = _parse(index_dir)
        crypto = next(s for s in scenes if "解码" in s.label)
        assert crypto.primary == ("re-library/tools-crypto.md",)
        assert crypto.supplementary == ()

    def test_scene_output_cites_existing_files_only(self, index_dir: Path) -> None:
        _, scenes = _parse(index_dir)
        for s in scenes:
            for p in (*s.primary, *s.supplementary):
                assert (index_dir / p).is_file(), f"scene cites ghost file {p}"


# ---------- recall matching (precedence: scene > category > filename) ----------

class TestRecall:
    def test_scene_query_hits(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        r = rr.recall(entries, scenes, "frida")
        assert r.kind == "scene"
        assert r.files == (
            "re-library/tools-dynamic.md", "dynamic-re-tool-priority.md",
            "re-library/field-notes.md", "operational-mechanics.md",
        )

    def test_cjk_scene_query_hits(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        r = rr.recall(entries, scenes, "解码")
        assert r.kind == "scene"
        assert r.files == ("re-library/tools-crypto.md",)

    def test_category_query_exact(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        r = rr.recall(entries, scenes, "tools")
        assert r.kind == "category"
        assert {e.path for e in r.entries} == {
            "re-library/tools-dynamic.md", "re-library/tools-crypto.md",
        }

    def test_category_query_separator_normalized(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        r = rr.recall(entries, scenes, "dynamic analysis")
        assert r.kind == "category"
        assert [e.path for e in r.entries] == ["dynamic-re-tool-priority.md"]

    def test_filename_query_hits(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        r = rr.recall(entries, scenes, "guardrails")
        assert r.kind == "filename"
        assert [e.path for e in r.entries] == ["guardrails.md"]

    def test_no_match_kind_none(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        r = rr.recall(entries, scenes, "zzz-nonsense")
        assert r.kind == "none"
        assert r.files == ()

    def test_norm_equivalence(self) -> None:
        assert rr._norm("dynamic analysis") == rr._norm("dynamic-analysis")
        assert rr._norm("re-library/tools-dynamic.md") == rr._norm("Re-Library\\tools-dynamic.md")


# ---------- CLI ----------

class TestCli:
    def test_cli_scene_query_exit_zero(self) -> None:
        r = _cli("解码")
        assert r.returncode == 0
        assert "re-library/tools-crypto.md" in r.stdout

    def test_cli_category_query_exit_zero(self) -> None:
        r = _cli("malware")
        assert r.returncode == 0
        assert "re-library/malware-analysis.md" in r.stdout

    def test_cli_no_match_exit_one_lists_categories(self) -> None:
        r = _cli("zzz-nonsense")
        assert r.returncode == 1
        assert "no match" in r.stdout
        assert "dynamic-analysis" in r.stdout  # closest-category listing

    def test_cli_list_categories(self) -> None:
        r = _cli("--list-categories")
        assert r.returncode == 0
        assert "tools (5)" in r.stdout
        assert "governance (3)" in r.stdout

    def test_cli_scene_map(self) -> None:
        r = _cli("--scene-map")
        assert r.returncode == 0
        assert "动态调试 / 运行时分析" in r.stdout
        assert "dynamic-re-tool-priority.md" in r.stdout

    def test_cli_help_exit_zero(self) -> None:
        assert _cli("--help").returncode == 0

    def test_cli_no_args_usage_exit_two(self) -> None:
        assert _cli().returncode == 2


# ---------- progressive disclosure (INDEX rows, never file contents) ----------

class TestProgressiveDisclosure:
    def test_scene_output_never_dumps_file_contents(self, index_dir: Path) -> None:
        entries, scenes = _parse(index_dir)
        r = rr.recall(entries, scenes, "frida")
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rr.print_result(r, entries)
        finally:
            sys.stdout = old
        out = buf.getvalue()
        for body in BODY.values():
            assert body not in out, f"file content leaked into recall output: {body}"
        # Index rows (purpose/when) ARE the disclosure point and must be present.
        assert "Dynamic analysis tooling reference" in out


# ---------- real-index alignment (#227 layered index) ----------

@pytest.mark.skipif(not REAL_INDEX.is_file(), reason="repo references/INDEX.md missing")
class TestRealIndexAlignment:
    def test_real_index_parse_bounds(self) -> None:
        entries, scenes = rr.parse_index(REAL_INDEX)
        assert len(entries) >= 50, "INDEX.md must still index the full library"
        assert len(scenes) >= 14, "INDEX.md scenario map must still parse"
        # every scene-cited file must be an indexed entry (no ghosts)
        indexed = {e.path for e in entries}
        for s in scenes:
            for p in (*s.primary, *s.supplementary):
                assert p in indexed, f"scene cites unindexed file {p}"

    def test_go_scene_leads_to_languages_go(self) -> None:
        entries, scenes = rr.parse_index(REAL_INDEX)
        r = rr.recall(entries, scenes, "Go")
        assert r.kind == "scene"
        assert "re-library/languages-go.md" in r.files

    def test_dynamic_analysis_category_hits_priority_file(self) -> None:
        entries, scenes = rr.parse_index(REAL_INDEX)
        r = rr.recall(entries, scenes, "dynamic analysis")
        assert r.kind == "category"
        assert [e.path for e in r.entries] == ["dynamic-re-tool-priority.md"]
