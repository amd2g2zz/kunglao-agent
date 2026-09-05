# -*- coding: utf-8 -*-
"""Issue #25 D2 — the init skill-deployment flag naming clash.

`--skills` reads as "deploy these skills into my workspace", but it only
accepts kunglao-INTERNAL bundled names (skills/<name> under the package).
Issue evidence (2026-08-23): `--skills malware-analysis-claude-skills,
re-baseline-looper` — both valid globally-installed skills — failed with
"unknown --skills name(s): ... (available: analysis, help, init,
kunglao-agent, resume)". The name collides with its intuitive semantic.

Owner no-backcompat ruling (2026-09-01): rename directly, no compat alias.
New name: `--builtin-skills` — the flag deploys kunglao's BUILT-IN
auxiliary skills; plural matches the comma-list arity (`A,B`). The global/
workspace-skill semantic is a different, future feature — it must not
inherit this name.

TDD RED phase: written BEFORE the rename (2026-09-04).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
SKILL_INIT = ROOT / "skills" / "init" / "SKILL.md"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
RC_OK = 0
RC_ERROR = 1

# Built here so this file's own source never carries the retired literal.
OLD_FLAG = "--" + "skills"
NEW_FLAG = "--builtin-skills"


# ---------- rename hygiene: the retired name is gone everywhere ----------

def test_old_flag_name_has_zero_references():
    """No compat alias: the old name must grep ZERO on its live surfaces
    (scripts/, the init SKILL.md, tests/). openspec/archive/ is historical
    record and deliberately out of scope."""
    scan = list((ROOT / "scripts").glob("*.py"))
    scan.append(SKILL_INIT)
    scan.extend(p for p in (ROOT / "tests").glob("*.py")
                if p.name != Path(__file__).name)
    hits = [str(p) for p in scan
            if OLD_FLAG in p.read_text(encoding="utf-8")]
    assert not hits, f"retired {OLD_FLAG} still referenced in: {hits}"


def test_new_flag_name_declared_on_cli_and_docs():
    """The new name exists on the argparse surface AND is documented where
    init describes skill deployment."""
    init_src = (SCRIPTS / "kunglao-init.py").read_text(encoding="utf-8")
    assert NEW_FLAG in init_src, "kunglao-init.py must declare --builtin-skills"
    doc = SKILL_INIT.read_text(encoding="utf-8")
    assert NEW_FLAG in doc, "skills/init/SKILL.md must document --builtin-skills"


# ---------- e2e: the renamed flag keeps the #478 L4 contract ----------

def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess:
    """Hermetic CLI run (same shape as test_init_deploy_env._run_init)."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            *(extra or [])]
    argv += ["--type", "windows", "--skip-toolchain",
             "--host-exec-protection", "enabled",
             "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PATH"] = str(ws.parent / "empty-bin")
    (ws.parent / "empty-bin").mkdir(exist_ok=True)
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    env["KUNGLAO_CLAUDE_JSON"] = str(ws.parent / "fake-claude.json")
    if not (ws.parent / "fake-claude.json").exists():
        (ws.parent / "fake-claude.json").write_text("{}", encoding="utf-8")
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


def test_builtin_skills_flag_deploys_named_dir(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws, [NEW_FLAG, "analysis"])
    assert r.returncode == RC_OK, (
        f"{NEW_FLAG} analysis must deploy: {r.stdout}{r.stderr}")
    dst = ws / ".claude" / "skills" / "analysis"
    assert dst.is_dir(), "skills/analysis not deployed"
    assert (dst / "SKILL.md").exists(), "deployed skill lost SKILL.md"


def test_builtin_skills_unknown_name_fails_fast(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws, [NEW_FLAG, "definitely-not-a-skill"])
    assert r.returncode == RC_ERROR, (
        f"unknown {NEW_FLAG} name must fail RC_ERROR=1: {r.stdout}{r.stderr}")
    combined = r.stdout + r.stderr
    assert "definitely-not-a-skill" in combined
    assert NEW_FLAG in combined, "error must name the NEW flag, not the old one"


def test_builtin_skills_no_flag_deploys_nothing(tmp_path):
    ws = _mk_ws(tmp_path)
    r = _run_init(ws)
    assert r.returncode == RC_OK, r.stderr
    skills_dir = ws / ".claude" / "skills"
    assert not skills_dir.exists() or not any(skills_dir.iterdir()), (
        f"no {NEW_FLAG} flag must install nothing")
