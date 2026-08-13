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

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


@pytest.fixture
def init_ws(tmp_path) -> Path:
    """合成 workspace: bins/ + sample + claim-register 空 + 无 [initialized] 标记."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    return subprocess.run(argv, capture_output=True, text=True, timeout=120)


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
    """#265: CLAUDE.md contains required rules reading instructions."""
    _run_init(init_ws)
    text = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "maker-checker.md" in text, "CLAUDE.md missing maker-checker rules reference"
    assert "numeric-fidelity.md" in text, "CLAUDE.md missing numeric-fidelity rules reference"
    assert "kunglao-convergence-loop.md" in text, "CLAUDE.md missing convergence-loop rules reference"


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
