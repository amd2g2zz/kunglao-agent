# -*- coding: utf-8 -*-
"""tests/test_references_recall.py — #275 scored recall over the layered references index.

Covers the rebuilt #229/#275 contract on the #261 layered index:
  - domain-table parsing (_INDEX.md) + per-domain index loading (_index-<domain>.md)
  - scenario -> Domain expression -> Scene(primary, supplementary) resolution
  - scored retrieval: query tokens (ASCII + CJK, equal weight) -> top-K by
    relevance score, each result carrying its score and matched fields
  - scene-label match (incl. CJK labels) takes precedence over scored entries
  - CLI surface unchanged: <query> / --list-categories / --scene-map / --help
  - progressive disclosure: output carries index rows + scores, never file contents
  - alignment with the real layered references/_INDEX.md (>=50 entries / 9 scenes)
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
REAL_INDEX = SCRIPT.parent.parent / "references" / "_INDEX.md"

# ---- synthetic layered-index fixture (mirrors the #261 format exactly) ----

FIXTURE_INDEX = """# references/ Domain Index

## Domain table

| Domain | Files (re-library/) | Purpose |
|---|---|---|
| tools | tools-dynamic, tools-crypto | Static/dynamic/crypto tooling quick-reference |
| patterns | patterns-debugging | Debugging and dynamic-analysis patterns |
| methodology | malware-analysis, field-notes | Analysis methods and malware application domain |

| Scenario | Domain |
|---|---|
| 动态分析 (x64dbg / Frida / Qiling / VM) | tools-dynamic + patterns-debugging |
| 解码 / 加密 / 哈希 | tools-crypto |
| 恶意软件分析 | methodology (malware-analysis, field-notes) |

## Per-domain index files

| File | Domain | Purpose | When to read |
|------|--------|---------|-------------|
| `_index-tools.md` | tools | File-level index for the tools domain. | When a worker is dispatched to tooling. |
| `_index-patterns.md` | patterns | File-level index for the patterns domain. | When a worker needs pattern references. |
| `_index-methodology.md` | methodology | File-level index for the methodology domain. | When a worker starts a malware task. |

## Top-level references

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `dynamic-re-tool-priority.md` | dynamic-analysis | Tool-priority order for dynamic RE dispatch. | Before dispatching for dynamic RE. |
| `guardrails.md` | governance | Full backing reference for orchestrator guardrails. | When the inline summary is insufficient. |

## re-library/

| File | Category | Purpose | When to read |
|------|----------|---------|-------------|
| `re-library/tools-dynamic.md` | tools | Dynamic analysis tooling (Frida, x64dbg, Qiling). | When performing runtime analysis. |
| `re-library/tools-crypto.md` | tools | Encryption/encoding/hashing tools quick-reference. | When decoding encoded data. |
| `re-library/patterns-debugging.md` | patterns | Debugging and dynamic-analysis patterns. | When validation logic is hidden. |
| `re-library/malware-analysis.md` | malware | Six-phase malware analysis methodology. | When performing end-to-end malware analysis. |
| `re-library/field-notes.md` | field-notes | Binary type quirks and anti-debug bypasses. | After initial triage. |
"""

PER_DOMAIN = {
    "_index-tools.md": """# tools 领域索引(文件层)
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [tools-dynamic.md](re-library/tools-dynamic.md) | 动态分析工具:Frida/x64dbg/Qiling | 运行时分析 |
| [tools-crypto.md](re-library/tools-crypto.md) | 加解密/编解码/哈希工具速查 | 解码加密数据 |
""",
    "_index-patterns.md": """# patterns 领域索引(文件层)
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [patterns-debugging.md](re-library/patterns-debugging.md) | 调试与动态分析模式 | 验证逻辑隐藏时 |
""",
    "_index-methodology.md": """# methodology 领域索引(文件层)
| 文件 | 一句话摘要 | 何时读 |
|---|---|---|
| [malware-analysis.md](re-library/malware-analysis.md) | 六阶段恶意软件分析方法论 | 端到端分析 |
| [field-notes.md](re-library/field-notes.md) | 二进制类型怪癖与反调试绕过 | 初始 triage 后 |
""",
}

# Body markers — must NEVER leak into recall output (progressive disclosure).
BODY = {
    "dynamic-re-tool-priority.md": "BODY-SECRET-DYNAMIC-PRIORITY",
    "guardrails.md": "BODY-SECRET-GUARDRAILS",
    "re-library/tools-dynamic.md": "BODY-SECRET-TOOLS-DYNAMIC",
    "re-library/tools-crypto.md": "BODY-SECRET-TOOLS-CRYPTO",
    "re-library/patterns-debugging.md": "BODY-SECRET-PATTERNS-DEBUGGING",
    "re-library/malware-analysis.md": "BODY-SECRET-MALWARE-ANALYSIS",
    "re-library/field-notes.md": "BODY-SECRET-FIELD-NOTES",
}


@pytest.fixture
def index_dir(tmp_path: Path) -> Path:
    """Synthetic references/ dir: layered _INDEX.md + per-domain indexes + stubs."""
    refs = tmp_path / "references"
    for rel, body in BODY.items():
        p = refs / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"# {body}\n", encoding="utf-8")
    for fname, content in PER_DOMAIN.items():
        (refs / fname).write_text(content, encoding="utf-8")
    (refs / "_INDEX.md").write_text(FIXTURE_INDEX, encoding="utf-8")
    return refs


def _index(index_dir: Path) -> rr.Index:
    return rr.build_index(index_dir / "_INDEX.md")


def _cli(*args: str) -> subprocess.CompletedProcess:
    """Run the CLI against the real repo index (CLI resolves _INDEX.md from its
    own location; unit tests above cover the synthetic fixture)."""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


# ---------- parser: domain table / scenario map / per-domain files ----------

class TestParse:
    def test_parse_counts(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        assert len(idx.entries) == 7          # 2 top-level + 5 re-library
        assert len(idx.scenes) == 3
        assert set(idx.domains) == {"tools", "patterns", "methodology"}

    def test_scene_dynamic_primary_supplementary(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        s = next(x for x in idx.scenes if "动态分析" in x.label)
        assert s.primary == (
            "re-library/tools-dynamic.md", "re-library/patterns-debugging.md",
        )
        # supplementary = remaining files of the owning domains (tools-crypto)
        assert s.supplementary == ("re-library/tools-crypto.md",)

    def test_scene_single_file_supplementary_is_rest_of_domain(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        s = next(x for x in idx.scenes if "解码" in x.label)
        assert s.primary == ("re-library/tools-crypto.md",)
        assert s.supplementary == ("re-library/tools-dynamic.md",)

    def test_scene_domain_with_parens_splits_primary(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        s = next(x for x in idx.scenes if "恶意软件分析" in x.label)
        assert s.primary == ("re-library/malware-analysis.md", "re-library/field-notes.md")
        assert s.supplementary == ()

    def test_scene_output_cites_existing_files_only(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        for s in idx.scenes:
            for p in (*s.primary, *s.supplementary):
                assert (index_dir / p).is_file(), f"scene cites ghost file {p}"


class TestDomainEnrichment:
    def test_per_domain_summary_loaded(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        e = next(x for x in idx.entries if x.path == "re-library/tools-crypto.md")
        assert "编解码" in e.summary          # from _index-tools.md
        assert "哈希" in e.summary

    def test_domain_attached_to_entry(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        e = next(x for x in idx.entries if x.path == "re-library/tools-dynamic.md")
        assert e.domain == "tools"
        e2 = next(x for x in idx.entries if x.path == "re-library/malware-analysis.md")
        assert e2.domain == "methodology"

    def test_symptom_tags_loaded_when_yaml_present(self, tmp_path: Path) -> None:
        refs = tmp_path / "references"
        refs.mkdir()
        (refs / "convergence-loop.md").write_text("# c\n", encoding="utf-8")
        (refs / "_INDEX.md").write_text(FIXTURE_INDEX.replace(
            "| `guardrails.md` | governance | Full backing reference for orchestrator guardrails. | When the inline summary is insufficient. |\n",
            "| `convergence-loop.md` | contracts | Convergence behaviours. | When spinning. |\n",
        ), encoding="utf-8")
        for fname, content in PER_DOMAIN.items():
            (refs / fname).write_text(content, encoding="utf-8")
        for rel, body in BODY.items():
            p = refs / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(f"# {body}\n", encoding="utf-8")
        (refs / "_INDEX.yaml").write_text(
            "schema: references-index/1\n"
            "files: {}\n"
            "symptom_map:\n"
            "  spinning: references/convergence-loop.md\n"
            "  drift: references/convergence-loop.md\n",
            encoding="utf-8",
        )
        idx = rr.build_index(refs / "_INDEX.md")
        e = next(x for x in idx.entries if x.path == "convergence-loop.md")
        assert set(e.symptoms) == {"spinning", "drift"}


# ---------- recall: scene label precedence, then scored top-K ----------

class TestRecall:
    def test_scene_query_hits(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "frida")
        assert r.kind == "scene"
        assert r.files == (
            "re-library/tools-dynamic.md", "re-library/patterns-debugging.md",
            "re-library/tools-crypto.md",
        )

    def test_cjk_scene_query_hits(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "解码")
        assert r.kind == "scene"
        assert r.files == ("re-library/tools-crypto.md", "re-library/tools-dynamic.md")

    def test_dynamic_analysis_is_scored_priority_file(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "dynamic analysis")
        assert r.kind == "scored"
        assert r.scored[0].entry.path == "dynamic-re-tool-priority.md"
        assert r.scored[0].score > 0

    def test_category_query_returns_tools_files(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "tools")
        assert r.kind == "scored"
        assert {e.path for e in r.entries} == {
            "re-library/tools-dynamic.md", "re-library/tools-crypto.md",
        }

    def test_filename_query_hits(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "guardrails")
        assert r.kind == "scored"
        assert r.scored[0].entry.path == "guardrails.md"

    def test_cjk_keyword_scored_with_score(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "编解码")
        # #814 去污染合同演进：purpose-only CJK 单词碰撞被阻尼，curated
        # scene 可以胜出——但文档必须仍然可达（两种 kind 都暴露 files）。
        assert r.kind in ("scored", "scene")
        assert "re-library/tools-crypto.md" in r.files
        if r.kind == "scored":
            assert r.scored[0].score > 0
            assert r.scored[0].reasons

    def test_scored_results_are_sorted_descending(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "analysis")
        assert r.kind == "scored"
        scores = [se.score for se in r.scored]
        assert scores == sorted(scores, reverse=True)

    def test_no_match_kind_none(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "zzz-nonsense")
        assert r.kind == "none"
        assert r.files == ()

    def test_norm_equivalence(self) -> None:
        assert rr._norm("dynamic analysis") == rr._norm("dynamic-analysis")
        assert rr._norm("re-library/tools-dynamic.md") == rr._norm("Re-Library\\tools-dynamic.md")


# ---------- CLI ----------

class TestCli:
    def test_cli_scene_query_exit_zero(self) -> None:
        r = _cli("frida")
        assert r.returncode == 0
        assert "Dynamic debugging" in r.stdout
        assert "re-library/tools-dynamic.md" in r.stdout

    def test_cli_scored_query_exit_zero_with_score(self) -> None:
        r = _cli("malware")
        assert r.returncode == 0
        assert "score=" in r.stdout
        assert "re-library/malware-analysis.md" in r.stdout

    def test_cli_cjk_query_handled_on_english_index(self) -> None:
        """R3 #357: the real index is now all-English, so a CJK query no
        longer scores a match — but it must still tokenize cleanly (UTF-8
        contract) and exit 1 via the no-match path, not crash."""
        r = _cli("解码")
        assert r.returncode == 1
        assert "no match" in r.stdout

    def test_cli_no_match_exit_one_lists_categories(self) -> None:
        r = _cli("zzz-nonsense")
        assert r.returncode == 1
        assert "no match" in r.stdout
        assert "dynamic-analysis" in r.stdout  # closest-category listing

    def test_cli_list_categories(self) -> None:
        r = _cli("--list-categories")
        assert r.returncode == 0
        assert "tools (5)" in r.stdout
        assert "governance (4)" in r.stdout  # +1: mechanisms.md cataloged 2026-08-25

    def test_cli_scene_map(self) -> None:
        r = _cli("--scene-map")
        assert r.returncode == 0
        assert "Dynamic debugging" in r.stdout
        assert "tools-dynamic" in r.stdout

    def test_cli_help_exit_zero(self) -> None:
        assert _cli("--help").returncode == 0

    def test_cli_no_args_usage_exit_two(self) -> None:
        assert _cli().returncode == 2


# ---------- progressive disclosure (index rows + scores, never file contents) ----------

class TestProgressiveDisclosure:
    def test_output_never_dumps_file_contents(self, index_dir: Path) -> None:
        idx = _index(index_dir)
        r = rr.recall(list(idx.entries), list(idx.scenes), "frida")
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rr.print_result(r, list(idx.entries))
        finally:
            sys.stdout = old
        out = buf.getvalue()
        for body in BODY.values():
            assert body not in out, f"file content leaked into recall output: {body}"
        # Index rows (path/purpose/when) ARE the disclosure point and must be present.
        assert "Dynamic analysis tooling" in out
        assert "re-library/tools-dynamic.md" in out


# ---------- real-index alignment (#261 layered index) ----------

@pytest.mark.skipif(not REAL_INDEX.is_file(), reason="repo references/_INDEX.md missing")
class TestRealIndexAlignment:
    def test_real_index_parse_bounds(self) -> None:
        idx = rr.build_index(REAL_INDEX)
        assert len(idx.entries) >= 50, "_INDEX.md must still index the full library"
        assert len(idx.scenes) >= 9, "_INDEX.md scenario map must still parse"
        assert len(idx.domains) >= 8, "_INDEX.md domain table must still parse"

    def test_real_index_no_ghost_scene_files(self) -> None:
        idx = rr.build_index(REAL_INDEX)
        for s in idx.scenes:
            for p in (*s.primary, *s.supplementary):
                assert (REAL_INDEX.parent / p).is_file(), f"scene cites ghost file {p}"

    def test_go_query_returns_languages_go(self) -> None:
        idx = rr.build_index(REAL_INDEX)
        r = rr.recall(list(idx.entries), list(idx.scenes), "Go")
        assert r.kind == "scored"
        assert "re-library/languages-go.md" in r.files

    def test_dynamic_analysis_returns_priority_file(self) -> None:
        idx = rr.build_index(REAL_INDEX)
        r = rr.recall(list(idx.entries), list(idx.scenes), "dynamic analysis")
        assert r.kind == "scored"
        assert r.scored[0].entry.path == "dynamic-re-tool-priority.md"

    def test_spinning_symptom_returns_convergence_loop(self) -> None:
        idx = rr.build_index(REAL_INDEX)
        r = rr.recall(list(idx.entries), list(idx.scenes), "spinning")
        assert r.kind == "scored"
        assert "convergence-loop.md" in r.files
