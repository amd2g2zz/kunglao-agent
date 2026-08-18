# -*- coding: utf-8 -*-
"""Phase 3.5 contract tests: kunglao-init re-init protection.

Step 1 RED — current state: kunglao-init.py absent → the import itself is RED.

GREEN targets (phase 3.5 criteria, E-init.1-4):
- E-init.1 anti-reinit: of two consecutive runs, the second is resume mode; claim-register has no duplicate seeds
- E-init.2 idempotent: hook deployment does not duplicate (no duplicate entries in the hooks section after re-run)
- E-init.3 drift: [initialized] state_hash change → a warning, never silent
- E-init.4 recovery: --force rebuild backs up first
"""
from __future__ import annotations

import json
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
    """Synthetic workspace: bins/ + sample + empty claim-register + no [initialized] marker."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    (ws / "runs").mkdir()
    return ws


def _run_init(ws: Path, extra: list[str] | None = None,
              profile_root: Path | None = None,
              flag: str | None = "0") -> subprocess.CompletedProcess:
    """Run kunglao-init (hermetic):
    --profile-root defaults to a tmp dir (production profiles are never touched);
    flag defaults to "0" (#276 default-disabled; the outer session may be
    contaminated by 2026-08-12 flag=1); flag=None means the subprocess env
    carries no such variable.
    --skip-toolchain: after the #304 fix the toolchain gate precedes scaffold —
    this file's tests focus on reinit/idempotency/drift; gate semantics are
    covered exclusively by test_init_toolchain_gate.py."""
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    if "--skip-toolchain" not in argv:
        argv.append("--skip-toolchain")
    # #455: without a type the run pends (exit 8, agent --resolve loop) — this
    # file owns re-init/idempotency semantics, not type semantics, so the
    # default run pins the PE fixture's type explicitly (type semantics live
    # in test_init_typeaware.py / test_target_alignment.py).
    if "--type" not in argv and "--resolve" not in argv:
        argv += ["--type", "windows"]
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
    """kunglao-init.py exists and runs."""
    assert (SCRIPTS / "kunglao-init.py").exists(), "kunglao-init.py missing"


def test_second_run_resumes(init_ws: Path) -> None:
    """E-init.1: first run initializes; the second is resume mode with no duplicate seeds in claim-register."""
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
    """E-init.2: no duplicate entries in the hooks section after a re-run."""
    _run_init(init_ws)
    settings = isolated_home / ".claude" / "settings.json"
    if not settings.exists():
        pytest.skip("no settings.json deployed (hooks outside home)")
    before = settings.read_text(encoding="utf-8")
    _run_init(init_ws)
    after = settings.read_text(encoding="utf-8")
    assert after == before, "second init modified settings.json (not idempotent)"


# ---------- #389 F2: init-only re-run upgrades legacy bare-python entries ----------

def _seed_hooks_json(init_ws: Path, pre_command: str, post_command: str) -> Path:
    """settings.json copy carrying one Agent worker_budget entry per event."""
    target = init_ws / "seeded-settings.json"
    target.write_text(json.dumps({"hooks": {
        "PreToolUse": [{"matcher": "Agent",
                        "hooks": [{"type": "command", "command": pre_command}]}],
        "PostToolUse": [{"matcher": "Agent",
                         "hooks": [{"type": "command", "command": post_command}]}],
    }}, indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def test_init_rerun_upgrades_legacy_bare_python_hook(init_ws: Path, isolated_home) -> None:
    """#389 F2: init hook deployment REPLACES a legacy bare-python
    worker_budget entry with the uv form — the same-name skip must not leave
    the stale entry (bare python is 2.x on this machine)."""
    hook_file = ROOT / "hooks" / "worker_budget.py"
    uv_form = f"uv run --project {ROOT.as_posix()} {hook_file.as_posix()}"
    legacy = f"python {hook_file.as_posix()}"
    hooks_json = _seed_hooks_json(init_ws, legacy, legacy)
    r = _run_init(init_ws, ["--hooks-json", str(hooks_json)])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    for event in ("PreToolUse", "PostToolUse"):
        entries = data["hooks"][event]
        assert len(entries) == 1, f"{event}: replaced entry must stay in place (no append): {entries}"
        assert entries[0]["hooks"][0]["command"] == uv_form, \
            f"{event}: legacy entry not upgraded: {entries[0]['hooks'][0]['command']}"


def test_init_rerun_keeps_uv_form_hook_untouched(init_ws: Path, isolated_home) -> None:
    """#389 F2 pin: an already-uv worker_budget entry survives re-running the
    init hook deployment byte-identical (fixed point, no duplicate append)."""
    hook_file = ROOT / "hooks" / "worker_budget.py"
    uv_form = f"uv run --project {ROOT.as_posix()} {hook_file.as_posix()}"
    hooks_json = _seed_hooks_json(init_ws, uv_form, uv_form)
    r1 = _run_init(init_ws, ["--hooks-json", str(hooks_json)])
    assert r1.returncode == 0, f"init failed: {r1.stderr}"
    after_first = hooks_json.read_text(encoding="utf-8")
    # --force: an init-only re-run on an initialized workspace resumes and
    # never reaches deploy_hooks; the rebuild path re-runs it.
    r2 = _run_init(init_ws, ["--force", "--hooks-json", str(hooks_json)])
    assert r2.returncode == 0, f"second init failed: {r2.stderr}"
    assert hooks_json.read_text(encoding="utf-8") == after_first, \
        "re-run modified a healthy uv-form entry (not idempotent)"
    data = json.loads(hooks_json.read_text(encoding="utf-8"))
    assert len(data["hooks"]["PreToolUse"]) == 1, "PreToolUse duplicated on re-run"
    assert len(data["hooks"]["PostToolUse"]) == 1, "PostToolUse duplicated on re-run"


def test_state_hash_drift_warns(init_ws: Path) -> None:
    """E-init.3: modify claim-register then re-run → a warning, not silent."""
    _run_init(init_ws)
    reg = init_ws / "claim-register.yaml"
    reg.write_text(reg.read_text(encoding="utf-8") + "\n# tampered\n", encoding="utf-8")
    r = _run_init(init_ws)
    assert "drift" in (r.stdout + r.stderr).lower() or "warn" in (r.stdout + r.stderr).lower(), \
        f"drift not warned: {r.stdout}{r.stderr}"


def test_force_backs_up_first(init_ws: Path) -> None:
    """E-init.4: --force rebuild backs up first (claim-register backup exists)."""
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
    # #455: human logs live on stderr (stdout is the machine channel)
    assert "appended" in (r1.stdout + r1.stderr), \
        f"init must record the profile action: {r1.stdout}{r1.stderr}"

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
    # #455: human logs live on stderr (stdout is the machine channel)
    assert "rewritten" in (r.stdout + r.stderr), \
        f"init must record the rewrite: {r.stdout}{r.stderr}"


def test_claudemd_documents_env_and_script_discipline(init_ws: Path) -> None:
    """#276: generated CLAUDE.md carries (1) the env-variable doc section and
    (2) the tool-script-discipline section (reusable CLI, no ad-hoc inline)."""
    _run_init(init_ws)
    text = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert FLAG_NAME in text, "CLAUDE.md missing agent-teams flag env doc"
    assert "KUNGLAO_VM_HOST" in text, "CLAUDE.md missing KUNGLAO_VM_HOST doc"
    assert "GHIDRA_HOME" in text, "CLAUDE.md missing GHIDRA_HOME doc"
    assert "scripts/" in text, "CLAUDE.md missing scripts/ CLI discipline"
    assert "ad-hoc" in text.lower() or "Ad-hoc" in text, \
        "CLAUDE.md must ban ad-hoc inline execution"


# ---------- #411: workspace-path shape validation ----------

RC_NO_SAMPLE = 5     # bins/ empty — friendly prompt (place a sample into bins/)
RC_PATH_SHAPE = 6    # target is a sample dir / file, not a workspace root — refuse


def _snapshot(ws: Path) -> set[str]:
    """Recursive relative-path snapshot of every entry under ws (dirs + files)."""
    if not ws.is_dir():
        return set()
    return {str(p.relative_to(ws)) for p in ws.rglob("*")}


def test_init_refuses_sample_dir_without_bins(tmp_path: Path) -> None:
    """#411: init on a sample directory (has bin/ but NO bins/) refuses with
    guidance, exits non-zero, and writes ZERO files (no .claude/, no
    claim-register, nothing)."""
    sample_dir = tmp_path / "sample-root"
    (sample_dir / "bin").mkdir(parents=True)
    (sample_dir / "bin" / "malware.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    before = _snapshot(sample_dir)
    r = _run_init(sample_dir)
    assert r.returncode == RC_PATH_SHAPE, \
        f"init on a sample dir must refuse with {RC_PATH_SHAPE}: {r.returncode}: {r.stdout}{r.stderr}"
    assert "bins/" in (r.stdout + r.stderr), \
        f"refusal must point at bins/: {r.stderr}"
    assert _snapshot(sample_dir) == before, \
        f"init on a sample dir must write ZERO files; created: {_snapshot(sample_dir) - before}"


def test_init_refuses_sample_dir_itself_named_bin(tmp_path: Path) -> None:
    """#411 observed case: init called ON the sample container (a directory
    literally named bin/, e.g. ~/Downloads/Sysdiag/bin) must refuse and write
    NOTHING — .claude/ must never land inside the sample dir."""
    container = tmp_path / "Sysdiag" / "bin"
    container.mkdir(parents=True)
    (container / "malware.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    before = _snapshot(tmp_path)
    r = _run_init(container)
    assert r.returncode == RC_PATH_SHAPE, \
        f"init on the sample container must refuse with {RC_PATH_SHAPE}: {r.returncode}: {r.stdout}{r.stderr}"
    assert "bins/" in (r.stdout + r.stderr), \
        f"refusal must point at bins/: {r.stderr}"
    assert _snapshot(tmp_path) == before, \
        f"init on the sample container must write ZERO files; created: {_snapshot(tmp_path) - before}"
    assert not (container / ".claude").exists(), ".claude/ must never be created inside the sample dir"


def test_init_refuses_sample_file(tmp_path: Path) -> None:
    """#411: init on a sample FILE (not a directory) refuses — a file cannot be
    a workspace root."""
    sample = tmp_path / "malware.exe"
    sample.write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    before = _snapshot(tmp_path)
    r = _run_init(sample)
    assert r.returncode == RC_PATH_SHAPE, \
        f"init on a sample file must refuse with {RC_PATH_SHAPE}: {r.returncode}: {r.stdout}{r.stderr}"
    assert _snapshot(tmp_path) == before, \
        f"init on a sample file must write ZERO files; created: {_snapshot(tmp_path) - before}"


def test_init_accepts_workspace_with_bins(tmp_path: Path) -> None:
    """#411: init on a valid workspace (bins/ present) proceeds normally."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    r = _run_init(ws)
    assert r.returncode == 0, f"init on a valid workspace must proceed: {r.stderr}"
    assert (ws / "claim-register.yaml").exists(), "valid workspace must initialize"


def test_init_accepts_creatable_empty_dir(tmp_path: Path) -> None:
    """#411: init on a new empty directory (can hold bins/) is NOT a path-shape
    refusal — it proceeds to the normal cold-start gate (no-sample prompt,
    exit 5), never the sample-dir refusal (exit 6)."""
    ws = tmp_path / "fresh-ws"
    ws.mkdir()
    r = _run_init(ws, ["--type", "windows"])
    assert r.returncode == RC_NO_SAMPLE, \
        f"empty dir must reach the no-sample cold-start gate ({RC_NO_SAMPLE}), not be shape-refused: {r.returncode}: {r.stdout}{r.stderr}"
    assert "place a sample into bins/" in r.stderr, \
        f"cold-start prompt missing: {r.stderr}"
    assert "sample directory" not in r.stderr, \
        f"empty dir is not a sample dir — must not be shape-refused: {r.stderr}"


def test_bins_wins_over_bin_sniff(tmp_path: Path) -> None:
    """#411: when a directory has both bin/ (sample dir) and bins/ (workspace),
    init treats it as a workspace — the type sniffer reads bins/ ONLY."""
    ws = tmp_path / "ws"
    (ws / "bin").mkdir(parents=True)
    (ws / "bin" / "malware.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)  # decoy
    (ws / "bins").mkdir()
    (ws / "bins" / "sample.elf").write_bytes(b"\x7fELF" + b"\x00" * 64)
    r = _run_init(ws, ["--type", "windows"])
    assert r.returncode == 0, f"init must proceed (bins/ workspace): {r.stderr}"
    assert (ws / "claim-register.yaml").exists()
    assert (ws / "CLAUDE.md").exists()
    text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "sample.elf" in text, "CLAUDE.md must reference the bins/ sample, not the bin/ decoy"
    assert "malware.exe" not in text, "sniffer must ignore bin/ (decoy) and only read bins/"
