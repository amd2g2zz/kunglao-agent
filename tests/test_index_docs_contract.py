# -*- coding: utf-8 -*-
"""tests/test_index_docs_contract.py — issue #339: tools/ index-doc contract.

Design premise (issue #339): a worker reads tools/_INDEX.md (category table)
-> tools/_index-<category>.md (per-tool contract entry) ->
tools/_INDEX.yaml (machine contract) and can already construct the call —
no need to open any .py source. Any doc that forces the agent to read source
to use it is a defect — this test mechanically asserts that premise.

Contract:
1. Every registered tool in tools/_INDEX.yaml (29 total) has a contract entry
   (H3 `### <name>`) in its category index md
2. An entry has 6 required segments: Purpose / Usage / Inputs / Outputs /
   exit code / when_not (REQUIRED_SEGMENTS) — the segment names are shared
   vocabulary between tools/_index-*.md and this test; doc and pin must move
   in the same commit
3. The usage segment is a directly copyable command (fenced code block whose
   first line is `python tools/...` or `mcp__`), and the script path the
   python command points at really exists (resolvable command form)
4. The exit-code segment mentions the three-state numbers (0/1/2)
5. Format: every md under tools/ has exactly 1 H1; H4+ forbidden (entries are H3)
6. Golden-invocation spot check of 3 tools: crypto-tool / yara-scan /
   sanitize-text — the documented usage must directly construct a working call
7. Empty-shell disposition (#339 A): tools/frida/ and tools/t2/ must not
   exist (true shells deleted); tools/pipelines/ contains the real registered
   tool build_evidence_index.py (#352 deleted the plan-template dead end —
   zero runtime consumers); dynamic/T2 capability is externally provided
   (mcp__frida__* + mcp__x64dbg__* clearly pointed in the dynamic index; T2
   simulation points at the external skill /malware-framework)
"""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"

REQUIRED_SEGMENTS = ("Purpose", "Usage", "Inputs", "Outputs", "exit code", "when_not")

# (category dir name == category id, #340: _index-<category>.md filename matches the id)
CATEGORY_READMES = [
    ("crypto", "crypto"),
    ("static", "static"),
    ("ghidra", "ghidra"),
    ("auxiliary", "auxiliary"),
    ("pipelines", "pipelines"),
    ("web", "web"),
]

# golden-invocation spot checks (tool name, fragment the usage first line must contain)
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
    """Text between the `### <name>` heading and the next `### ` heading (or EOF)."""
    m = re.search(rf"^### {re.escape(name)}\s*$", text, re.M)
    assert m, f"no contract entry `### {name}` found"
    rest = text[m.end():]
    nxt = re.search(r"^### \S", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def _usage_first_line(entry: str) -> str:
    """Extract the first line of the usage segment's fenced code block (command form)."""
    m = re.search(
        r"\*\*Usage\*\*[^\n]*\n\s*```\w*\n\s*([^\n]+)", entry)
    assert m, "usage segment must be a fenced code block"
    return m.group(1).strip()


def _all_tools_md() -> list[Path]:
    return sorted(TOOLS.rglob("*.md"))


# ---------- 1. registered tool -> category-md contract entry ----------

def test_yaml_registry_has_29_tools() -> None:
    tools = _yaml_tools()
    assert len(tools) == 38, f"expected 38 registered tools, got {len(tools)}"  # 38 since #866-b (ghidra_diff registration); 37 since #884 (jsvmp-triage, web category; 36 since #728 wakaru-unbundle/webcrack-deobfuscate; 34 since #692)
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


# ---------- 2. MD format rules (#339 C): heading levels ----------

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


# ---------- 3. golden-invocation spot checks (issue #339 C) ----------

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


# ---------- 4. empty-shell directory disposition (#339 A) ----------

def test_vacuum_shell_dirs_removed() -> None:
    assert not (TOOLS / "frida").exists(), (
        "tools/frida/ is a vacuum shell (README only) — must be deleted; "
        "Frida capability is MCP-provided (mcp__frida__*, VM :1337), "
        "templates live in templates/frida/")
    assert not (TOOLS / "t2").exists(), (
        "tools/t2/ is a vacuum shell (README only) — must be deleted; "
        "T2 emulation is provided by the external /malware-framework skill")


def test_pipelines_dir_has_real_artifacts() -> None:
    """tools/pipelines/ must hold the real registered tool (#352 removed the
    plan templates — zero runtime consumers; build-evidence-index remains)."""
    tool = TOOLS / "pipelines" / "build_evidence_index.py"
    assert tool.is_file(), "tools/pipelines/build_evidence_index.py must exist"
    assert not (TOOLS / "pipelines" / "recipes").exists(), (
        "tools/pipelines/recipes/ must be deleted (#352)")


def test_external_capability_pointers_are_explicit() -> None:
    dynamic = _category_md_text("dynamic")
    assert "mcp__x64dbg__" in dynamic, "dynamic index must point to mcp__x64dbg__*"
    assert "mcp__frida__" in dynamic, "dynamic index must point to mcp__frida__*"
    index_md = (TOOLS / "_INDEX.md").read_text(encoding="utf-8")
    assert "malware-framework" in index_md, (
        "tools/_INDEX.md must point T2 emulation to the external /malware-framework skill")


# ---------- 5. contract-entry template required segments (format assertion, #339 C addendum) ----------

def test_entry_template_segments_order() -> None:
    """Entry-template segment order is fixed: purpose -> usage -> inputs -> outputs -> exit code -> when_not."""
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
