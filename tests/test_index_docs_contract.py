# -*- coding: utf-8 -*-
"""tests/test_index_docs_contract.py — issue #339: tools/ 索引文档契约.

设计前提(issue #339): worker 读 tools/_INDEX.md(类目表) → tools/_index-<category>.md
(每工具契约条目) → tools/_INDEX.yaml(机器契约) 即可构造调用, 不需要打开 .py 源码。
任何让 agent 必须读源码才能用的文档都是缺陷 —— 本测试机械断言这一前提。

契约:
1. tools/_INDEX.yaml 每个注册工具(共 28)在对应类目索引 md 有契约条目(H3 `### <name>`)
2. 条目含 6 必填段: 用途 / 用法 / 输入 / 输出 / exit code / when_not
3. 用法段是可直接复制的命令(围栏代码块, 首行 `python tools/...` 或 `mcp__`),
   且 python 命令指向的脚本路径真实存在(可解析命令形式)
4. exit code 段提及三态数字(0/1/2)
5. 格式: 每个 tools/ 内 md 恰好 1 个 H1, 禁止 H4+(条目即 H3)
6. golden invocation 抽查 3 工具: crypto-tool / yara-scan / sanitize-text
   —— 文档中的用法必须能直接构造出调用
7. 空壳处置(#339 A): tools/frida/ 与 tools/t2/ 不得存在(真空壳已删);
   tools/pipelines/ 含 recipes/*.yaml 真实人造物; 动态/T2 能力由外部提供
   (mcp__frida__* + mcp__x64dbg__* 在 dynamic 索引中指向明确,
   T2 模拟指向 /malware-framework 外部 skill)
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

REQUIRED_SEGMENTS = ("用途", "用法", "输入", "输出", "exit code", "when_not")

# (类目目录名, 类目 id 用于 _index-<cat>.md 文件名)
CATEGORY_READMES = [
    ("crypto", "crypto"),
    ("static", "static"),
    ("ghidra", "ghidra"),
    ("auxiliary", "aux"),
    ("pipelines", "pipeline"),
]

# golden invocation 抽查(工具名, 用法首行必须包含的片段)
GOLDEN_INVOCATIONS = [
    ("crypto-tool", ["python tools/crypto/crypto-tool.py", "--in"]),
    ("yara-scan", ["python tools/static/yara-scan.py", "--binary"]),
    ("sanitize-text", ["python tools/auxiliary/sanitize.py", "--in"]),
]


# ---------- helpers ----------

def _yaml_tools() -> list[dict]:
    data = yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))
    return data["tools"]


def _category_md_text(category: str) -> str:
    path = TOOLS / f"_index-{category}.md"
    assert path.is_file(), f"missing category index: {path}"
    return path.read_text(encoding="utf-8")


def _entry_block(text: str, name: str) -> str:
    """从 `### <name>` 标题到下一个 `### ` 标题(或 EOF)之间的文本."""
    m = re.search(rf"^### {re.escape(name)}\s*$", text, re.M)
    assert m, f"no contract entry `### {name}` found"
    rest = text[m.end():]
    nxt = re.search(r"^### \S", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _usage_first_line(entry: str) -> str:
    """提取用法段的围栏代码块首行(命令形式)."""
    m = re.search(
        r"\*\*用法\*\*[^\n]*\n\s*```\w*\n\s*([^\n]+)", entry)
    assert m, "usage segment must be a fenced code block"
    return m.group(1).strip()


def _all_tools_md() -> list[Path]:
    return sorted(TOOLS.rglob("*.md"))


# ---------- 1. 注册工具 → 类目 md 契约条目 ----------

def test_yaml_registry_has_28_tools() -> None:
    tools = _yaml_tools()
    assert len(tools) == 28, f"expected 28 registered tools, got {len(tools)}"
    names = [t["name"] for t in tools]
    assert len(names) == len(set(names)), "duplicate tool names in _INDEX.yaml"


def test_every_registered_tool_has_contract_entry() -> None:
    missing = []
    for tool in _yaml_tools():
        text = _category_md_text(tool["category"])
        if not re.search(rf"^### {re.escape(tool['name'])}\s*$", text, re.M):
            missing.append(f"{tool['name']} (category={tool['category']})")
    assert not missing, f"tools missing contract entry in category md: {missing}"


def test_every_entry_has_required_segments() -> None:
    violations = []
    for tool in _yaml_tools():
        text = _category_md_text(tool["category"])
        entry = _entry_block(text, tool["name"])
        for seg in REQUIRED_SEGMENTS:
            if not re.search(rf"^- \*\*{re.escape(seg)}\*\*", entry, re.M):
                violations.append(f"{tool['name']}: missing segment `{seg}`")
    assert not violations, f"contract entries missing segments:\n" + "\n".join(violations)


def test_usage_is_copyable_command_and_script_exists() -> None:
    violations = []
    for tool in _yaml_tools():
        text = _category_md_text(tool["category"])
        entry = _entry_block(text, tool["name"])
        try:
            first = _usage_first_line(entry)
        except AssertionError as exc:
            violations.append(f"{tool['name']}: {exc}")
            continue
        if not re.match(r"^(python tools/|python -m|mcp__)", first):
            violations.append(f"{tool['name']}: usage first line not a command: {first!r}")
            continue
        argv = shlex.split(first)
        if argv and argv[0] == "python" and len(argv) > 1 and argv[1].startswith("tools/"):
            if not (ROOT / argv[1]).is_file():
                violations.append(f"{tool['name']}: script path does not exist: {argv[1]}")
    assert not violations, "usage not copyable:\n" + "\n".join(violations)


def test_every_entry_mentions_exit_code() -> None:
    violations = []
    for tool in _yaml_tools():
        text = _category_md_text(tool["category"])
        entry = _entry_block(text, tool["name"])
        m = re.search(r"\*\*exit code\*\*[^\n]*(?:\n(?!- \*\*).*)*", entry)
        if not m or not re.search(r"[012]", m.group(0)):
            violations.append(tool["name"])
    assert not violations, f"entries without exit-code digits: {violations}"


# ---------- 2. MD 格式规范(#339 C): 标题层级 ----------

def test_every_tools_md_has_exactly_one_h1_and_no_h4() -> None:
    violations = []
    for path in _all_tools_md():
        text = path.read_text(encoding="utf-8")
        h1 = len(re.findall(r"^# ", text, re.M))
        if h1 != 1:
            violations.append(f"{path.relative_to(ROOT)}: {h1} H1 (want 1)")
        if re.search(r"^####", text, re.M):
            violations.append(f"{path.relative_to(ROOT)}: has H4+ headings")
    assert not violations, "heading-level violations:\n" + "\n".join(violations)


def test_category_readmes_state_relation_to_index_md() -> None:
    missing = []
    for dname, cat in CATEGORY_READMES:
        readme = TOOLS / dname / "README.md"
        assert readme.is_file(), f"missing category README: {readme}"
        text = readme.read_text(encoding="utf-8")
        if f"_index-{cat}.md" not in text:
            missing.append(f"{dname}/README.md -> _index-{cat}.md")
    assert not missing, f"category READMEs not stating index relation: {missing}"


# ---------- 3. golden invocation 抽查(issue #339 C) ----------

def test_golden_invocations_present_in_docs() -> None:
    for tool in _yaml_tools():
        if tool["name"] not in {name for name, _ in GOLDEN_INVOCATIONS}:
            continue
        text = _category_md_text(tool["category"])
        entry = _entry_block(text, tool["name"])
        usage = _usage_first_line(entry)
        expected = dict(GOLDEN_INVOCATIONS)[tool["name"]]
        for fragment in expected:
            assert fragment in usage, (
                f"golden invocation for {tool['name']} missing `{fragment}` in: {usage!r}"
            )


# ---------- 4. 空壳目录处置(#339 A) ----------

def test_vacuum_shell_dirs_removed() -> None:
    assert not (TOOLS / "frida").exists(), (
        "tools/frida/ is a vacuum shell (README only) — must be deleted; "
        "Frida capability is MCP-provided (mcp__frida__*, VM :1337), "
        "templates live in templates/frida/")
    assert not (TOOLS / "t2").exists(), (
        "tools/t2/ is a vacuum shell (README only) — must be deleted; "
        "T2 emulation is provided by the external /malware-framework skill")


def test_pipelines_dir_has_real_artifacts() -> None:
    recipes = TOOLS / "pipelines" / "recipes"
    assert recipes.is_dir(), "tools/pipelines/recipes/ must exist"
    yamls = sorted(p.name for p in recipes.glob("*.yaml"))
    assert len(yamls) == 5, f"expected 5 plan-recipe templates, got {yamls}"


def test_external_capability_pointers_are_explicit() -> None:
    dynamic = _category_md_text("dynamic")
    assert "mcp__x64dbg__" in dynamic, "dynamic index must point to mcp__x64dbg__*"
    assert "mcp__frida__" in dynamic, "dynamic index must point to mcp__frida__*"
    index_md = (TOOLS / "_INDEX.md").read_text(encoding="utf-8")
    assert "malware-framework" in index_md, (
        "tools/_INDEX.md must point T2 emulation to the external /malware-framework skill")


# ---------- 5. 契约条目模板必填段(格式断言, issue #339 C 补) ----------

def test_entry_template_segments_order() -> None:
    """条目模板段顺序固定: 用途 → 用法 → 输入 → 输出 → exit code → when_not."""
    violations = []
    for tool in _yaml_tools():
        text = _category_md_text(tool["category"])
        entry = _entry_block(text, tool["name"])
        positions = []
        for seg in REQUIRED_SEGMENTS:
            m = re.search(rf"^- \*\*{re.escape(seg)}\*\*", entry, re.M)
            positions.append(m.start() if m else -1)
        if positions != sorted(positions) or -1 in positions:
            violations.append(tool["name"])
    assert not violations, f"entries with wrong segment order: {violations}"
