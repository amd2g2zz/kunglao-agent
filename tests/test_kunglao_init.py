# -*- coding: utf-8 -*-
"""阶段 3.5 契约测试: kunglao-init 防二次初始化.

Step 1 RED — 当前状态: kunglao-init.py 不存在 → import 即 RED。

GREEN 目标(阶段 3.5 判据, E-init.1-4):
- E-init.1 防重: 连续 2 次运行第 2 次为续接模式, claim-register 无重复 seed
- E-init.2 幂等: hooks 部署不重复(重跑后 hooks 段无重复条目)
- E-init.3 漂移: [initialized] state_hash 变化 → 警告不静默
- E-init.4 恢复: --force 重建先备份
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


@pytest.fixture
def init_ws(tmp_path) -> Path:
    """合成 workspace: bins/ + sample + claim-register 空 + 无 [initialized] 标记."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None,
              profile_root: Path | None = None,
              flag: str | None = "0") -> subprocess.CompletedProcess:
    """运行 kunglao-init (hermetic):
    --profile-root 默认指向 tmp(绝不触碰生产 profile);
    flag 默认 "0"(#276 默认禁用态; 外层会话可能被 2026-08-12 flag=1 污染),
    传 flag=None 表示子进程 env 不携带该变量。
    --skip-toolchain: #304 修正后 toolchain 门禁在 scaffold 前置 —
    本文件的测试聚焦防重/幂等/漂移行为, 门禁语义由 test_init_toolchain_gate.py 专测."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    if "--skip-toolchain" not in argv:
        argv.append("--skip-toolchain")
    if profile_root is None:
        profile_root = ws.parent / "profile-root"
    argv += ["--profile-root", str(profile_root)]
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env["PYTHONIOENCODING"] = "utf-8"  # kunglao-init emits UTF-8 (toolchain import reconfigures stdout)
    if flag is not None:
        env[FLAG_NAME] = flag
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, env=env,
                           errors="replace")


def test_kunglao_init_script_exists() -> None:
    """kunglao-init.py 存在可运行."""
    assert (SCRIPTS / "kunglao-init.py").exists(), "kunglao-init.py missing"


def test_second_run_resumes(init_ws: Path) -> None:
    """E-init.1: 第 1 次初始化, 第 2 次续接模式且 claim-register 无重复 seed."""
    r1 = _run_init(init_ws)
    assert r1.returncode == 0, f"first init failed: {r1.stderr}"
    reg1 = (init_ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "[initialized]" in reg1, "initialized marker missing"
    seed_count = reg1.count("id: C-")
    r2 = _run_init(init_ws)
    assert r2.returncode == 0, f"second init failed: {r2.stderr}"
    reg2 = (init_ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert reg2.count("id: C-") == seed_count, \
        f"second run duplicated seeds: {seed_count} -> {reg2.count('id: C-')}"


def test_hooks_idempotent(init_ws: Path, isolated_home) -> None:
    """E-init.2: 重跑后 hooks 段无重复条目."""
    _run_init(init_ws)
    settings = isolated_home / ".claude" / "settings.json"
    if not settings.exists():
        pytest.skip("no settings.json deployed (hooks outside home)")
    before = settings.read_text(encoding="utf-8")
    _run_init(init_ws)
    after = settings.read_text(encoding="utf-8")
    assert after == before, "second init modified settings.json (not idempotent)"


def test_state_hash_drift_warns(init_ws: Path) -> None:
    """E-init.3: 改 claim-register 后重跑 → 警告不静默."""
    _run_init(init_ws)
    reg = init_ws / "claim-register.yaml"
    reg.write_text(reg.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    r = _run_init(init_ws)
    assert "drift" in (r.stdout + r.stderr).lower() or "warn" in (r.stdout + r.stderr).lower(), \
        f"drift not warned: {r.stdout}{r.stderr}"


def test_force_backs_up_first(init_ws: Path) -> None:
    """E-init.4: --force 重建先备份(claim-register 备份存在)."""
    _run_init(init_ws)
    r = _run_init(init_ws, ["--force"])
    assert r.returncode == 0, f"--force failed: {r.stderr}"
    backups = list(init_ws.glob("claim-register*.bak*"))
    assert backups, "no backup created before --force rebuild"


# ---------- #265: CLAUDE.md generation ----------

def test_init_writes_claudemd(init_ws: Path) -> None:
    """#265: init writes CLAUDE.md to workspace root."""
    r = _run_init(init_ws)
    assert r.returncode == 0, f"init failed: {r.stderr}"
    claude = init_ws / "CLAUDE.md"
    assert claude.exists(), "CLAUDE.md not created by init"


def test_claudemd_contains_sample_info(init_ws: Path) -> None:
    """#265: CLAUDE.md contains sample SHA1 and path references."""
    _run_init(init_ws)
    text = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "sample.exe" in text, "CLAUDE.md missing sample filename"
    assert "bins/" in text, "CLAUDE.md missing sample path prefix"


def test_claudemd_contains_rules_requirement(init_ws: Path) -> None:
    """#356 W2: the hallucinated ~/.claude/rules/common/ reference section is
    GONE from generated CLAUDE.md (those files don't exist on a fresh clone;
    the rules themselves are carried by SKILL.md + references/). The
    maker-checker behavior baseline stays as a Hard-constraints bullet."""
    _run_init(init_ws)
    text = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "~/.claude/rules/common/" not in text, \
        "CLAUDE.md still references the hallucinated ~/.claude/rules/common/ section"
    assert "maker-checker" in text.lower(), \
        "CLAUDE.md missing maker-checker behavior baseline (hard constraints)"


def test_claudemd_contains_hard_constraints(init_ws: Path) -> None:
    """#265: CLAUDE.md contains hard constraints section."""
    _run_init(init_ws)
    text = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "VM-only" in text or "VM only" in text, "CLAUDE.md missing VM-only constraint"
    assert "Maker-checker" in text, "CLAUDE.md missing maker-checker constraint"


def test_claudemd_idempotent_no_clobber(init_ws: Path) -> None:
    """#265: second init does not clobber existing CLAUDE.md."""
    _run_init(init_ws)
    original = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    # Manually modify CLAUDE.md to detect clobber
    (init_ws / "CLAUDE.md").write_text(
        original + "\n# CUSTOM USER CONTENT\n", encoding="utf-8"
    )
    _run_init(init_ws)
    after = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "CUSTOM USER CONTENT" in after, \
        "CLAUDE.md was clobbered on second init (idempotent violation)"


def test_claudemd_contains_state_file_map(init_ws: Path) -> None:
    """#265: CLAUDE.md contains state file reference table."""
    _run_init(init_ws)
    text = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "claim-register.yaml" in text, "CLAUDE.md missing claim-register reference"
    assert "facts/_INDEX.md" in text, "CLAUDE.md missing facts/_INDEX reference"
    assert "runs/" in text, "CLAUDE.md missing runs/ reference"


# ---------- #276: Phase 0 env guard (agent-teams flag default 0) ----------

def test_polluted_flag_1_hard_rejects_scaffold(init_ws: Path) -> None:
    """#276: process env flag truthy (1) -> HARD reject: non-zero exit, NO scaffold
    (no claim-register.yaml), fix guidance on stderr."""
    r = _run_init(init_ws, flag="1")
    assert r.returncode != 0, f"polluted init must fail: {r.stdout}{r.stderr}"
    assert not (init_ws / "claim-register.yaml").exists(), \
        "polluted init must not scaffold claim-register.yaml"
    assert "unset" in r.stderr, f"fix guidance missing 'unset': {r.stderr}"
    assert "RESTART" in r.stderr or "restart" in r.stderr, \
        f"fix guidance missing restart: {r.stderr}"


def test_polluted_flag_true_rejects(init_ws: Path) -> None:
    """Truthy values beyond '1' ('true') also reject."""
    r = _run_init(init_ws, flag="true")
    assert r.returncode != 0
    assert not (init_ws / "claim-register.yaml").exists()


def test_flag_zero_proceeds_and_records_state(init_ws: Path) -> None:
    """flag=0 -> proceeds; analysis_state.txt records agent_teams_flag=0 (default disabled)."""
    r = _run_init(init_ws, flag="0")
    assert r.returncode == 0, f"init failed with flag=0: {r.stdout}{r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "agent_teams_flag=0 (default disabled)" in state, state


def test_flag_unset_proceeds_default_disabled(init_ws: Path) -> None:
    """flag unset -> proceeds with default-disabled semantics recorded."""
    r = _run_init(init_ws, flag=None)
    assert r.returncode == 0, f"init failed: {r.stdout}{r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "agent_teams_flag=0" in state, state


def test_profile_inclusion_idempotent(init_ws: Path, tmp_path: Path) -> None:
    """#276: existing PowerShell profile gets the flag=0 default line via
    shell_defaults; second init leaves the profile byte-identical (idempotent)."""
    profile_root = tmp_path / "profile-home"
    profile = (profile_root / "Documents" / "PowerShell"
               / "Microsoft.PowerShell_profile.ps1")
    profile.parent.mkdir(parents=True)
    profile.write_text("# my profile\n", encoding="utf-8")

    r1 = _run_init(init_ws, profile_root=profile_root)
    assert r1.returncode == 0, f"first init failed: {r1.stdout}{r1.stderr}"
    text = profile.read_text(encoding="utf-8")
    assert f'$env:{FLAG_NAME} = "0"' in text, f"profile not patched: {text}"
    assert "# my profile" in text, "unrelated profile content must survive"
    assert "appended" in r1.stdout, f"init must record the profile action: {r1.stdout}"

    before = profile.read_bytes()
    r2 = _run_init(init_ws, profile_root=profile_root)
    assert r2.returncode == 0, f"second init failed: {r2.stdout}{r2.stderr}"
    assert profile.read_bytes() == before, \
        "second init must not rewrite an already-correct profile (idempotent)"


def test_profile_inclusion_rewrites_truthy(init_ws: Path, tmp_path: Path) -> None:
    """Existing profile carrying the truthy flag line is rewritten to 0."""
    profile_root = tmp_path / "profile-home"
    profile = (profile_root / "Documents" / "WindowsPowerShell"
               / "Microsoft.PowerShell_profile.ps1")
    profile.parent.mkdir(parents=True)
    profile.write_text(f'$env:{FLAG_NAME} = "1"\n', encoding="utf-8")

    r = _run_init(init_ws, profile_root=profile_root)
    assert r.returncode == 0, f"init failed: {r.stdout}{r.stderr}"
    text = profile.read_text(encoding="utf-8")
    assert f'$env:{FLAG_NAME} = "0"' in text
    assert f'$env:{FLAG_NAME} = "1"' not in text
    assert "rewritten" in r.stdout, f"init must record the rewrite: {r.stdout}"


def test_claudemd_documents_env_and_script_discipline(init_ws: Path) -> None:
    """#276: generated CLAUDE.md carries (1) the env-variable doc section and
    (2) the tool-script-discipline section (reusable CLI, no ad-hoc inline)."""
    _run_init(init_ws)
    text = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert FLAG_NAME in text, "CLAUDE.md missing agent-teams flag env doc"
    assert "KUNGLAO_VM_HOST" in text, "CLAUDE.md missing KUNGLAO_VM_HOST doc"
    assert "GHIDRA_HOME" in text, "CLAUDE.md missing GHIDRA_HOME doc"
    assert "scripts/" in text, "CLAUDE.md missing scripts/ CLI discipline"
    assert "ad-hoc" in text, \
        "CLAUDE.md must ban ad-hoc inline execution"
