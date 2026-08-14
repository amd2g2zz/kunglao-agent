# -*- coding: utf-8 -*-
"""tests/test_tools_structure_340.py — issue #340: tools/ 目录结构规范化.

Target-structure contract (documented in tools/README.md "结构规则(#340)"):

R1 根层归位: tools/ 根层只允许 (a) 索引/文档文件(_INDEX.md/_INDEX.yaml/
   _index-*.md/README.md), (b) 两个 toolshelf 元工具(tool-search.py /
   validate_index.py — 操作 tools/ 自身而非样本, 文档化例外), (c) 目录。
   一切注册工具脚本一律住在 `tools/<category>/`; 跨类目共享库一律住在
   `tools/_lib/`(共享库单点)。
R2 类目 id == 目录名: _INDEX.yaml 的每个 category 值必须同名于
   tools/<category>/ 目录; 唯一例外 dynamic(能力由 MCP + VM 通道提供,
   #339 已删真空壳目录且禁止重建)。旧 id aux/pipeline 不得残留。
R3 一类目一共享模块: static 类目的共享助手模块只有一个(common.py);
   双模块(_common.py)不得回归。
R4 双 common 合并保留全部公共面: 合并后 common.py 必须同时暴露两个
   旧模块的全部公共名(CLI plumbing + byte-scan helpers)。
R5 __pycache__ 不入库: .gitignore 覆盖 tools/ 任意深度的 __pycache__
   与 *.pyc(git check-ignore 机械验证)。
R6 迁移后 import 全链路: 每个被移动 CLI 在新位置以 --help 应答 exit 0;
   tool-search 全量可用(查询结果计数 == 注册表条数)。
R7 旧路径引用清零: 活文档/代码/清单不得再引用旧根层路径与旧类目文件名
   (openspec/changes/ 是冻结的历史变更记录, 豁免; docs/devlog/ 已于 #355 删除)。
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


# ---------- R1: 根层归位 ----------

def test_tools_root_holds_only_index_docs_and_meta_tools() -> None:
    """tools/ 根层 .py 集合 == {tool-search.py, validate_index.py}(元工具例外),
    其余一切 .py 一律入类目目录或 _lib/。"""
    root_py = {p.name for p in TOOLS.glob("*.py")}
    assert root_py == META_TOOLS, (
        f"tools/ 根层 .py 必须恰好是元工具 {sorted(META_TOOLS)}, "
        f"实得: {sorted(root_py)} — 注册工具脚本须归位类目目录, 共享库归位 _lib/")


def test_moved_tools_exist_at_new_locations_only() -> None:
    missing = [new for new in MOVED_TOOLS if not (ROOT / new).is_file()]
    stale = [old for old in MOVED_TOOLS.values() if (ROOT / old).is_file()]
    assert not missing, f"迁移缺失(新位置不存在): {missing}"
    assert not stale, f"旧位置仍有残留(未迁移干净): {stale}"


# ---------- R2: 类目 id == 目录名 ----------

def test_every_category_matches_directory_name() -> None:
    categories = {t["category"] for t in _yaml_data()["tools"]}
    offenders = sorted(
        c for c in categories
        if c != "dynamic" and not (TOOLS / c).is_dir())
    assert not offenders, (
        f"类目 id 与目录名不对齐(且非 dynamic 外部能力例外): {offenders}")


def test_legacy_category_ids_are_gone() -> None:
    categories = {t["category"] for t in _yaml_data()["tools"]}
    assert "aux" not in categories, "旧类目 id `aux` 残留 — 应为 auxiliary"
    assert "pipeline" not in categories, "旧类目 id `pipeline` 残留 — 应为 pipelines"
    assert "auxiliary" in categories and "pipelines" in categories, (
        "auxiliary/pipelines 类目 id 缺失")


def test_category_index_files_align_with_ids() -> None:
    """每个类目(含 dynamic)的 _index-<category>.md 存在; 旧文件名不残留。"""
    categories = {t["category"] for t in _yaml_data()["tools"]} | {"dynamic"}
    missing = [c for c in sorted(categories)
               if not (TOOLS / f"_index-{c}.md").is_file()]
    assert not missing, f"缺 _index-<category>.md: {missing}"
    assert not (TOOLS / "_index-aux.md").exists(), "旧 _index-aux.md 残留"
    assert not (TOOLS / "_index-pipeline.md").exists(), "旧 _index-pipeline.md 残留"


def test_validator_categories_pin_new_enum() -> None:
    sys.path.insert(0, str(TOOLS))
    import validate_index as vi  # noqa: E402
    assert vi.CATEGORIES == (
        "crypto", "static", "ghidra", "dynamic", "auxiliary", "pipelines"), (
        f"validate_index.CATEGORIES 必须为 id==dirname 枚举, 实得: {vi.CATEGORIES}")
    data = {"tools": [{"name": "t-a", "category": "auxiliary",
                       "capability": "aux:sanitize", "tier": "T1",
                       "cost_tier": "probe", "input_output": "x"}]}
    assert vi.validate_index(data) == [], "auxiliary 应为合法类目"
    data["tools"][0]["category"] = "pipelines"
    assert vi.validate_index(data) == [], "pipelines 应为合法类目"


# ---------- R3/R4: 一类目一共享模块 + 合并保留全部公共面 ----------

def test_static_has_single_shared_module() -> None:
    assert (TOOLS / "static" / "common.py").is_file(), "static 共享模块 common.py 缺失"
    assert not (TOOLS / "static" / "_common.py").exists(), (
        "tools/static/_common.py 残留 — 双共享模块不得回归(#340 合并)")


def test_merged_common_exposes_full_union_surface() -> None:
    static = TOOLS / "static"
    sys.path.insert(0, str(static))
    import common  # noqa: E402
    missing = [n for n in COMMON_CLI_PLUMBING + COMMON_BYTE_SCAN
               if not hasattr(common, n)]
    assert not missing, f"合并后 common.py 公共面缺失: {missing}"


def test_no_static_cli_imports_the_retired_module() -> None:
    offenders = [
        p.name for p in (TOOLS / "static").glob("*.py")
        if re.search(r"^\s*(from|import)\s+_common\b",
                     p.read_text(encoding="utf-8"), re.M)]
    assert not offenders, f"static CLI 仍 import 已合并的 _common: {offenders}"


# ---------- R5: __pycache__ gitignore ----------

def test_pycache_is_gitignored_at_any_depth() -> None:
    probe = TOOLS / "auxiliary" / "__pycache__" / "mod.cpython-311.pyc"
    r = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", str(probe)],
        capture_output=True)
    assert r.returncode == 0, (
        f"{probe} 未被 gitignore 覆盖(check-ignore exit {r.returncode}) — "
        ".gitignore 须含 __pycache__/ 与 *.pyc 且对 tools/ 任意深度生效")


# ---------- R6: import 全链路 + tool-search 全量可用 ----------

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
    assert not offenders, "迁移后 CLI import 链断裂:\n" + "\n".join(offenders)


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
        f"tool-search 全量查询计数 {out['count']} != 注册条数 {registered}")


def test_validator_passes_on_shipped_index() -> None:
    r = _run(TOOLS / "validate_index.py")
    assert r.returncode == 0, r.stderr


# ---------- R7: 旧路径引用清零 ----------

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
    assert not offenders, "旧路径引用残留(须同步到新位置):\n" + "\n".join(offenders)


def test_manifest_declares_new_paths_and_drops_old() -> None:
    manifest = yaml.safe_load(
        (ROOT / "release-manifest.yaml").read_text(encoding="utf-8"))
    declared = set(manifest["assets"]["tools"])
    missing = [new for new in MOVED_TOOLS if new not in declared]
    stale = [old for old in MOVED_TOOLS.values() if old in declared]
    assert not missing, f"manifest 未声明新路径: {missing}"
    assert not stale, f"manifest 仍声明旧路径: {stale}"


def test_manifest_declares_merged_common_only() -> None:
    declared = yaml.safe_load(
        (ROOT / "release-manifest.yaml").read_text(encoding="utf-8"))["assets"]["tools"]
    assert "tools/static/common.py" in declared
    assert "tools/static/_common.py" not in declared


# ---------- README 结构规则文档化 ----------

def test_readme_documents_structure_rules() -> None:
    text = (TOOLS / "README.md").read_text(encoding="utf-8")
    for marker in (
        "tools/_lib",            # 共享库单点
        "id == 目录名",           # 类目对齐规则(R2)
        "tool-search.py",        # 元工具例外文档化
        "validate_index.py",
        "__pycache__",           # gitignore 规则(R5)
    ):
        assert marker in text, f"tools/README.md 缺结构规则标记: {marker!r}"
