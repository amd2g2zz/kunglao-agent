#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_dispatch_tools_760.py — issue #760 Group I: dispatch tool-face +
TRY-ladder boundary + macos type + web-re-worker.

Sections (added per task, TDD order):
  1. I1 — hooks/dispatch_gate.py tools= mechanical validation against the
     target agent's frontmatter allowedTools + the §1c write-capability floor.
  2. I2 — TRY-ladder boundary clause in agents/kunglao-worker.md +
     references/operational-mechanics.md (capability mismatch -> ESCALATE).
  3. I3 — macos project type: VALID_TYPES x3 layers, WARN-only toolchain face,
     OS_SECTIONS template, guidance-string union sync, Mach-O feature routing.
  4. I4 — agents/web-re-worker.md structure/routing/registration.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
AGENTS_DIR = REPO_ROOT / "agents"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import route_capability as rc  # noqa: E402
from _factories import write_hook_state


# ---------- shared harness (shape mirrors tests/test_decision_teeth.py) ------

def _activate(ws: Path) -> None:
    """Arm dispatch_gate via the shared factory (863-h Family L)."""
    write_hook_state(ws, active_hooks=["dispatch_gate"])


def _minimal_ws(root: Path, *, activate: bool = True,
                statement: str = "background work") -> Path:
    ws = root / "malware-analysis-workspace"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "OPEN", "statement": statement},
        ]}, allow_unicode=True), encoding="utf-8")
    (ws / "claim_deps.yaml").write_text(
        "depends_on: {}\ncompetitor_groups: {}\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text("primary_questions: []\n",
                                       encoding="utf-8")
    if activate:
        _activate(ws)
    return ws


def _run_gate(root: Path, prompt: str, *, subagent_type: str | None = None,
              extra_input: dict | None = None) -> subprocess.CompletedProcess:
    """Feed hooks/dispatch_gate.py one PreToolUse Agent payload."""
    tool_input = {"prompt": prompt}
    if subagent_type is not None:
        tool_input["subagent_type"] = subagent_type
    if extra_input:
        tool_input.update(extra_input)
    payload = json.dumps({
        "cwd": str(root),
        "workspace": str(root / "malware-analysis-workspace"),
        "tool_input": tool_input,
    })
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "hooks" / "dispatch_gate.py")],
        input=payload, capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), errors="replace",
    )


# ==========================================================================
# 1. I1 — dispatch tools= validation (#760)
# ==========================================================================

class TestI1ToolsContract:
    def test_out_of_whitelist_tool_rejected(self, tmp_path) -> None:
        """tools=pefile-signature to kunglao-worker -> REJECT: the name is a
        specialist handle, not in the worker's allowedTools (the mm_x86
        incident shape: free-text narrowing zero-checked)."""
        root = tmp_path / "a"
        ws = _minimal_ws(root)
        r = _run_gate(root, "[T1 tools=pefile-signature] claim C-1 sweep",
                      subagent_type="kunglao-worker")
        assert r.returncode == 2, (
            f"out-of-whitelist tool must REJECT; stderr={r.stderr!r}")
        assert "not in kunglao-worker allowedTools" in (r.stderr + r.stdout)

    def test_read_only_rack_missing_write_rejected(self, tmp_path) -> None:
        """tools=Read,Grep -> every tool IS whitelisted but the rack has no
        Write/Edit: the §1c file contract can never be fulfilled."""
        root = tmp_path / "b"
        _minimal_ws(root)
        r = _run_gate(root, "[T1 tools=Read,Grep] claim C-1 sweep",
                      subagent_type="kunglao-worker")
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        blob = r.stderr + r.stdout
        assert "missing write-capable tool" in blob
        assert "(§1c)" in blob or "1c" in blob

    def test_whitelisted_rack_with_write_passes(self, tmp_path) -> None:
        root = tmp_path / "c"
        _minimal_ws(root)
        r = _run_gate(root, "[T1 tools=Read,Write,Grep] claim C-1 sweep",
                      subagent_type="kunglao-worker")
        assert r.returncode == 0, f"stderr={r.stderr!r} stdout={r.stdout!r}"
        assert "REJECT" not in r.stderr

    def test_lowercase_alias_matches_case_insensitively(self, tmp_path) -> None:
        """Historical v0 dispatches self-restrict with lowercase names
        (`grep`); the subset match is case-insensitive against allowedTools
        entries so `grep` resolves to Grep. Write still missing -> REJECT on
        the §1c floor, proving aliasing ran before the floor check."""
        root = tmp_path / "d"
        _minimal_ws(root)
        r = _run_gate(root, "[T1 tools=grep] claim C-1 background work",
                      subagent_type="kunglao-worker")
        assert r.returncode == 2
        assert "missing write-capable tool" in (r.stderr + r.stdout)

    def test_unknown_agent_name_passes_through(self, tmp_path) -> None:
        """No agents/<name>.md -> 既不认识就不拦 (existing path untouched)."""
        root = tmp_path / "e"
        _minimal_ws(root)
        r = _run_gate(root, "[T1 tools=some-future-tool] claim C-1 work",
                      subagent_type="brand-new-agent-nobody-knows")
        assert r.returncode == 0, f"stderr={r.stderr!r}"

    def test_no_agent_identity_legacy_v0_untouched(self, tmp_path) -> None:
        """Legacy v0 text-only payloads (no subagent_type/name/meta.agent)
        keep the pre-#760 behavior byte-identically — every historical
        dispatch-gate test depends on this."""
        root = tmp_path / "f"
        _minimal_ws(root)
        r = _run_gate(root, "[T1 tools=grep] claim C-1 background work")
        assert r.returncode == 0, f"stderr={r.stderr!r}"

    def test_v1_json_meta_agent_enforced(self, tmp_path) -> None:
        """v1 JSON envelope carrying meta.agent=kunglao-worker with an
        out-of-whitelist rack -> REJECT even without subagent_type."""
        root = tmp_path / "g"
        _minimal_ws(root)
        prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-1", '
                  '"tier": 1, "tools": ["ida-pro-mcp"], '
                  '"agent": "kunglao-worker"}}\n'
                  'decipher config blob')
        r = _run_gate(root, prompt)
        assert r.returncode == 2, f"stderr={r.stderr!r}"
        blob = r.stderr + r.stdout
        assert "not in kunglao-worker allowedTools" in blob

    def test_mcp_wildcard_family_match(self, tmp_path) -> None:
        """mcp__ghidra__decompile satisfies ghidra-light's mcp__ghidra__*
        pattern; combined with Write the rack passes both checks."""
        root = tmp_path / "h"
        _minimal_ws(root)
        r = _run_gate(root,
                      "[T1 tools=mcp__ghidra__decompile,Write] claim C-1 xref",
                      subagent_type="ghidra-light")
        assert r.returncode == 0, f"stderr={r.stderr!r} stdout={r.stdout!r}"

    def test_bash_is_not_a_file_contract_tool(self, tmp_path) -> None:
        """§1c is literally about file-write tools; Bash (indirect writes)
        does not satisfy the floor."""
        root = tmp_path / "i"
        _minimal_ws(root)
        r = _run_gate(root, "[T1 tools=Read,Bash] claim C-1 run script",
                      subagent_type="kunglao-worker")
        assert r.returncode == 2
        assert "missing write-capable tool" in (r.stderr + r.stdout)


class TestI1FrontmatterHelperUnit:
    """Pure-function unit face of the helpers added to dispatch_gate."""

    @staticmethod
    def _load_gate_module():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_gate_for_760", REPO_ROOT / "hooks" / "dispatch_gate.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_allowed_tools_parsed_for_real_agents(self) -> None:
        gate = self._load_gate_module()
        tools = gate._agent_allowed_tools("kunglao-worker")
        assert "Write" in tools and "Bash" in tools
        assert any(t.endswith("*") for t in tools)  # mcp wildcard present

    def test_unknown_agent_returns_none(self) -> None:
        gate = self._load_gate_module()
        assert gate._agent_allowed_tools("no-such-agent") is None

    @pytest.mark.parametrize("pattern,tool,want", [
        ("Read", "Read", True),
        ("Read", "read", True),          # case-insensitive family
        ("Grep", "ripgrep", False),
        ("mcp__ghidra__*", "mcp__ghidra__decompile", True),
        ("mcp__ghidra__*", "mcp__frida__spawn", False),
        ("mcp__context7__query-docs", "mcp__context7__QUERY-DOCS", True),
    ])
    def test_tool_matches_pattern_semantics(self, pattern, tool, want) -> None:
        gate = self._load_gate_module()
        assert gate._tool_matches_allowed(pattern, tool) is want

    def test_violation_report_shape(self) -> None:
        gate = self._load_gate_module()
        v = gate._tools_contract_violation(["pefile-signature"], "kunglao-worker")
        assert v is not None and "not in kunglao-worker allowedTools" in v
        v2 = gate._tools_contract_violation(["Read", "Grep"], "kunglao-worker")
        assert v2 is not None and "missing write-capable tool" in v2
        assert gate._tools_contract_violation([], "kunglao-worker") is None


# ==========================================================================
# 2. I2 — TRY ladder boundary clause (#760)
# ==========================================================================

WORKER_MD = AGENTS_DIR / "kunglao-worker.md"
MECHANICS_MD = REPO_ROOT / "references" / "operational-mechanics.md"


class TestI2LadderBoundary:
    @pytest.mark.parametrize("path", [WORKER_MD, MECHANICS_MD],
                             ids=["worker-md", "operational-mechanics"])
    def test_boundary_clause_present(self, path: Path) -> None:
        text = path.read_text(encoding="utf-8")
        for keyword in ("capability mismatch", "makeshift"):
            assert keyword.lower() in text.lower(), (
                f"{path.name}: missing {keyword!r}")

    def test_worker_clause_names_the_incident_shaped_forbidden_pair(self) -> None:
        text = WORKER_MD.read_text(encoding="utf-8")
        assert "py_eval" in text and "ESCALATE" in text

    def test_clause_attaches_to_try_step_context(self) -> None:
        text = WORKER_MD.read_text(encoding="utf-8")
        # The boundary lands inside/near the LEARN->TRY->ESCALATE section.
        idx_ladder = text.find("LEARN→TRY→ESCALATE")
        assert idx_ladder >= 0
        window = text[idx_ladder:idx_ladder + 2000]
        assert 'capability mismatch' in window.lower()


# ==========================================================================
# 3. I3 — macos type (#760)
# ==========================================================================

sys.path.insert(0, str(SCRIPTS))
import init_state as init_state_mod  # noqa: E402
import toolchain as tc  # noqa: E402
import mcp_probe  # noqa: E402

MACOS_SECTION_MARKERS = (
    "## Hard constraints (macos)",
    "Mach-O",
    "Darwin",
)


def _load_init():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_760", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestI3MacosTypeUnion:
    def test_valid_types_layers_include_macos(self):
        assert "macos" in init_state_mod.VALID_TYPES
        assert "macos" in tc.VALID_TYPES
        assert "macos" in mcp_probe.VALID_TYPES

    def test_init_marker_accepts_macos(self, tmp_path):
        rec = init_state_mod.write_init_marker(
            tmp_path, state_hash="a" * 64, project_type="macos", seed_count=0)
        assert rec["project_type"] == "macos"


class TestI3MacosToolchain:
    def test_macos_face_has_zero_hard_items(self):
        report = tc.check(REPO_ROOT, "macos")
        hard = [i.name for i in report.items if i.tier == tc.Tier.HARD]
        assert hard == [], f"labs macos must carry no HARD items: {hard}"

    def test_macos_faces_probe_macho_tools_and_darwin_runtime(self):
        report = tc.check(REPO_ROOT, "macos")
        names = {i.name for i in report.items}
        assert {"otool", "class-dump", "swift-demangle"} <= names

    def test_check_sets_contract_declares_macos(self):
        macos = {"otool", "class-dump", "swift-demangle"}
        assert macos <= tc.CHECK_SETS.get("macos", frozenset()), (
            f"CHECK_SETS['macos'] missing {macos - set(tc.CHECK_SETS.get('macos', []))}")
        # VM channel pair is windows/linux-only by #455/#698 contract.
        assert not ({"vm_reachable"} & tc.CHECK_SETS.get("macos", frozenset()))
        never = getattr(tc, "NEVER_CHECKS", {})
        assert "vm_reachable" in never.get("macos", frozenset())

    def test_mach_o_fixture_toolchain_reproduce_line(self, tmp_path):
        """A minimal-but-real Mach-O header fixture drives the whole face."""
        macho = tmp_path / "sample.dylib"
        # MH_MAGIC_64 (0xfeedfacf LE) + cputype ARM64(0x0100000C) payload.
        macho.write_bytes(
            b"\xcf\xfa\xed\xfe" + b"\x0c\x00\x00\x01" + b"\x02\x00\x00\x00"
            + b"\x00" * 32)
        report = tc.check(tmp_path, "macos")
        assert report.project_type == "macos"
        assert tc.format_reproduce(report).startswith("type=macos")


class TestI3MacosTemplateAndCli:
    def test_os_section_macos_hard_constraints(self):
        kunglao_init = _load_init()
        section = kunglao_init.os_section("macos")
        for marker in MACOS_SECTION_MARKERS:
            assert marker in section, marker

    def test_os_section_other_types_untouched(self):
        kunglao_init = _load_init()
        assert kunglao_init.os_section(None) == ""
        assert "## Hard constraints (windows)" in kunglao_init.os_section("windows")

    def test_init_cli_accepts_macos(self):
        kunglao_init = _load_init()
        args = kunglao_init.parse_args(["ws", "--type", "macos"])
        assert args.type == "macos"

    def test_init_cli_still_rejects_bogus(self):
        kunglao_init = _load_init()
        with pytest.raises(SystemExit):
            kunglao_init.parse_args(["ws", "--type", "bogus"])

    def test_guidance_strings_list_macos(self):
        # env_check_gate renders the enum inside angle brackets
        # ("--type <windows|...>"); the bare union substring covers both forms.
        union = "windows|linux|android|web|macos"
        for rel in (
            "scripts/kunglao-init.py",
            "scripts/kunglao_resume.py",
            "hooks/env_check_gate.py",
            "scripts/init_state.py",
        ):
            assert union in (REPO_ROOT / rel).read_text(encoding="utf-8"), rel

    def test_skill_md_argument_hint_lists_macos(self):
        hint = "<workspace> [--type windows|linux|android|web|macos]"
        text = (REPO_ROOT / "SKILL.md").read_text(encoding="utf-8")
        assert hint in text

    def test_macho_fixture_full_init_walkthrough(self, tmp_path):
        """mach-o fixture: init --type macos walks type-check -> scaffold ->
        CLAUDE.md render end to end through composed init steps (the CLI's
        interactive intake gates are out of scope; every artifact-side step
        runs exactly as production)."""
        kunglao_init = _load_init()
        ws = tmp_path / "ws"
        ws.mkdir()
        sample = tmp_path / "mm_x86_fixture.dylib"
        sample.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x0c\x00\x00\x01"
                           + b"\x02\x00\x00\x00" + b"\x00" * 16)
        # artifact-side steps in production order
        report = tc.check(ws, "macos")
        assert report.exit_code != 1, \
            "zero-HARD labs face must not FAIL the toolchain gate"
        (ws / "analysis_state.txt").write_text("project_type=macos\n",
                                               encoding="utf-8")
        init_state_mod.write_init_marker(
            ws, state_hash=init_state_mod.state_hash_of(ws)
            if hasattr(init_state_mod, "state_hash_of") else "b" * 64,
            project_type="macos", seed_count=0)
        ok, detail = init_state_mod.init_complete(ws)
        assert ok, detail
        out = kunglao_init.write_claudemd(ws, sample.name, "c" * 64,
                                          project_type="macos")
        assert out is not None
        claudemd = (ws / "CLAUDE.md").read_text(encoding="utf-8")
        assert "Hard constraints (macos)" in claudemd
        assert "otool" in claudemd

    def test_feature_routing_macho_signals_hit_ghidra_light(self):
        table = rc.load_specialist_table(AGENTS_DIR)
        feats = {"language": ["Dylib"], "machine": ["mach-o arm64"]}
        agent, rationale = rc.recommend_agent_type(feats, "", table)
        assert agent == "ghidra-light", rationale


# ==========================================================================
# 4. I4 — web-re-worker (#760)
# ==========================================================================

WEB_WORKER = AGENTS_DIR / "web-re-worker.md"
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)


class TestI4WebReWorkerStructure:
    @pytest.fixture(scope="class")
    def frontmatter(self) -> dict:
        text = WEB_WORKER.read_text(encoding="utf-8")
        m = FRONTMATTER_RE.match(text)
        assert m, "frontmatter missing"
        data = yaml.safe_load(m.group(1))
        assert isinstance(data, dict)
        return data

    def test_file_exists_with_valid_frontmatter(self, frontmatter):
        assert frontmatter.get("name") == "web-re-worker"
        assert isinstance(frontmatter.get("allowedTools"), list)
        required_tools = {
            "Read", "Write", "Edit", "Glob", "Grep", "Bash",
            "WebFetch", "WebSearch",
            "mcp__camoufox-reverse__*", "mcp__gitnexus__*",
            "mcp__sequential-thinking__sequentialthinking",
        }
        assert required_tools <= set(frontmatter["allowedTools"])

    def test_trigger_table_declared(self, frontmatter):
        trig = frontmatter.get("triggers")
        assert isinstance(trig, dict)
        assert trig.get("pipeline_order") == 5
        intent = trig.get("intent") or {}
        must_any = " ".join(intent.get("must_any") or [])
        for token in ("signature", "webhook", "bundler", "deobfuscate",
                      "风控"):
            assert token in must_any, token
        exclude = " ".join(intent.get("exclude") or [])
        for token in ("apk", "dex", "smali"):
            assert token in exclude, token

    def test_description_encodes_user_rulings(self, frontmatter):
        desc = str(frontmatter.get("description", ""))
        assert "headless" in desc.lower()          # 无头优先裁决
        headfull_ctx = re.search(r"headless(.{0,120})", desc, re.IGNORECASE)
        assert headfull_ctx, desc[:400]
        assert "instrument" in desc.lower() or "hook" in desc.lower()

    def test_three_contract_markers_pass_lint(self):
        sys.path.insert(0, str(REPO_ROOT / "devkit"))
        import agents_lint as al  # noqa: E402
        report = al.lint_dir(AGENTS_DIR)
        assert report["ok"] is True, report["violations"]

    def test_registered_in_release_manifest_roster(self):
        manifest = yaml.safe_load(
            (REPO_ROOT / "release-manifest.yaml").read_text(encoding="utf-8"))
        agents = manifest["assets"]["agents"]
        assert "agents/web-re-worker.md" in agents
        # and the receipt roster pin stays in lockstep
        receipt_src = (REPO_ROOT / "tests" / "test_release_receipt.py"
                       ).read_text(encoding="utf-8")
        assert '"web-re-worker.md"' in receipt_src


class TestI4WebReWorkerRouting:
    @pytest.fixture(scope="class")
    def table(self):
        return rc.load_specialist_table(AGENTS_DIR)

    @pytest.mark.parametrize("claim", [
        "定位页面 js 里 webhook 的签名参数生成逻辑",
        "风控接口参数逆向：前端加密桩分析",
        "解包 webpack bundler 产物并去混淆",
        "unpack deobfuscate the packed page bundle",
    ])
    def test_web_claims_route_to_web_re_worker(self, table, claim):
        agent, why = rc.recommend_agent_type({}, claim, table)
        assert agent == "web-re-worker", f"{claim!r}: {why}"

    def test_pe_signature_claim_stays_with_pefile_specialist(self, table):
        agent, _ = rc.recommend_agent_type({}, "verify Authenticode 证书链",
                                           table)
        assert agent == "pefile-signature"

    def test_android_tokens_excluded(self, table):
        agent, _ = rc.recommend_agent_type({}, "js bundle 线索但样本是 apk dex smali",
                                           table)
        assert agent != "web-re-worker", "apk/dex/smali must exclude"

    def test_web_worker_vs_binary_order_no_collision(self, table):
        """Precedence doc: for a claim naming BOTH domains the lower-order
        specialist wins mechanically; this pins the ordering contract."""
        orders = {s["name"]: s["pipeline_order"] for s in table}
        assert orders["pefile-signature"] < orders["web-re-worker"]
