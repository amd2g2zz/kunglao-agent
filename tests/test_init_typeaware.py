# -*- coding: utf-8 -*-
"""Tests for kunglao-init.py --type extension (#304).

TDD RED phase: tests for type determination, magic sniffing, interactive confirm,
type written to analysis_state.txt, template selection by type, init-completeness
(marker + project_type), resume behavior.

#455 amendment: the interactive confirm channel is GONE — a sniffed type is
a pending-decision suggestion only; these tests drive types via --resolve
answers files (structured pending list + re-entry, see test_target_alignment.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMPLATES = ROOT / "templates"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


@pytest.fixture
def init_ws(tmp_path: Path) -> Path:
    """Minimal workspace: bins/ + runs/."""
    ws = tmp_path / "ws"
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    return ws


def _run_init(ws: Path, extra: list[str] | None = None,
              profile_root: Path | None = None,
              flag: str | None = "0") -> subprocess.CompletedProcess:
    """Run kunglao-init hermetically. --skip-toolchain by default (#304 fix:
    the toolchain gate runs before the scaffold, covered separately by test_init_toolchain_gate.py —
    this file's tests focus on type detection/template selection/completeness).

    #455: no stdin channel — interactive confirm is gone; tests drive the
    type via --resolve answers files."""
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
    if not any(a.startswith("--host-exec-protection") for a in argv) \
            and "--resolve" not in argv:
        # #919: non-interactive tests answer the host-exec ask explicitly.
        argv += ["--host-exec-protection", "enabled"]
    return subprocess.run(
        argv, capture_output=True, text=True, timeout=120, env=env,
        errors="replace",
    )


def _write_answers(init_ws: Path, payload: dict) -> str:
    """Answers file for --resolve (lives beside the workspace's tmp root)."""
    payload.setdefault("host_exec_protection", "enabled")  # #919 non-interactive
    f = init_ws.parent / "answers.json"
    import json as _json
    f.write_text(_json.dumps(payload), encoding="utf-8")
    return str(f)


# ---------- fixture builders for binary types ----------

def _make_pe(ws: Path, name: str = "sample.exe") -> Path:
    """Create a minimal PE (MZ header) sample file."""
    p = ws / "bins" / name
    p.write_bytes(b"MZ\x90\x00" + b"\x00" * 128)
    return p


def _make_elf(ws: Path, name: str = "sample.elf") -> Path:
    """Create a minimal ELF sample file."""
    p = ws / "bins" / name
    p.write_bytes(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 128)
    return p


def _make_apk(ws: Path, name: str = "sample.apk") -> Path:
    """Create a minimal REAL zip APK (classes.dex first).

    #455: an APK is a container — the contents inventory comes from a real
    zip central directory (a bare 'PK + zeros' blob is unparseable and
    yields an empty inventory)."""
    import zipfile
    p = ws / "bins" / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("classes.dex", b"dex\n035\x00" + b"\x00" * 32)
        zf.writestr("AndroidManifest.xml", b"<manifest/>")
    return p


# ---------- --type explicit precedence ----------

def test_type_windows_explicit(init_ws: Path):
    """--type windows writes project_type=windows to analysis_state.txt."""
    _make_pe(init_ws)
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state, f"type not written: {state}"


def test_type_linux_explicit(init_ws: Path):
    """--type linux writes project_type=linux to analysis_state.txt."""
    _make_elf(init_ws)
    r = _run_init(init_ws, ["--type", "linux"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=linux" in state


def test_type_android_explicit(init_ws: Path):
    """--type android writes project_type=android to analysis_state.txt.

    #455: the APK is a CONTAINER — the embedded analysis object is its own
    pending decision even when the type is explicit (type is not guessed
    here, but the target object still is)."""
    _make_apk(init_ws)
    r = _run_init(init_ws, ["--type", "android"])
    assert r.returncode == 8, \
        f"container target_object must pend even with explicit type: {r.stdout}{r.stderr}"
    r2 = _run_init(init_ws, ["--type", "android",
                             "--resolve", _write_answers(init_ws, {"target_object": "classes.dex"})])
    assert r2.returncode == 0, f"init failed: {r2.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=android" in state


# ---------- magic sniff suggestion (#455: pending context only, never adopted) ----------

def test_sniff_pe_suggestion_needs_resolve(init_ws: Path):
    """PE (MZ) in bins/, no --type: the sniff suggestion ('windows') is NOT
    adopted — a pending list exits 8; a --resolve type answer completes."""
    _make_pe(init_ws)
    r = _run_init(init_ws)
    assert r.returncode == 8, f"sniff must not be silently adopted (#455): {r.stdout}{r.stderr}"
    import json as _json
    pending = _json.loads(r.stdout)
    type_dec = next(d for d in pending["decisions"] if d["decision_id"] == "type")
    assert type_dec["context"]["suggested_type"] == "windows"
    r2 = _run_init(init_ws, ["--resolve", _write_answers(init_ws, {"type": "windows"})])
    assert r2.returncode == 0, f"init failed: {r2.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state, f"PE not sniffed as windows: {state}"


def test_sniff_elf_resolves_linux(init_ws: Path):
    """ELF in bins/ -> --resolve linux completes."""
    _make_elf(init_ws)
    r = _run_init(init_ws, ["--resolve", _write_answers(init_ws, {"type": "linux"})])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=linux" in state


def test_sniff_apk_resolves_android(init_ws: Path):
    """APK (PK + classes.dex) in bins/: the APK is a CONTAINER (#455) — the
    type is never guessed; --resolve supplies target_object + type."""
    _make_apk(init_ws)
    r = _run_init(init_ws)
    assert r.returncode == 8, f"container type must pend: {r.stdout}{r.stderr}"
    r2 = _run_init(init_ws, ["--resolve", _write_answers(
        init_ws, {"target_object": "classes.dex", "type": "android"})])
    assert r2.returncode == 0, f"init failed: {r2.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=android" in state


def test_sniff_unknown_resolves_by_answer(init_ws: Path):
    """Unknown binary type -> the type comes from the --resolve answer."""
    (init_ws / "bins" / "unknown.bin").write_bytes(b"RANDOM" + b"\x00" * 128)
    r = _run_init(init_ws, ["--resolve", _write_answers(init_ws, {"type": "linux"})])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=linux" in state


# ---------- --type overrides sniff ----------

def test_explicit_type_overrides_sniff(init_ws: Path):
    """--type linux on a PE sample -> linux (explicit wins over sniff)."""
    _make_pe(init_ws)  # PE header, but we say linux
    r = _run_init(init_ws, ["--type", "linux"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=linux" in state


# ---------- template selection ----------

def test_windows_template_selected(init_ws: Path):
    """--type windows -> CLAUDE.md uses windows template."""
    _make_pe(init_ws)
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    # Windows template should have Windows-specific constraints
    assert "x64dbg" in claude or "windows" in claude.lower()


def test_linux_template_selected(init_ws: Path):
    """--type linux -> CLAUDE.md uses linux template."""
    _make_elf(init_ws)
    r = _run_init(init_ws, ["--type", "linux"])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "gdbserver" in claude or "eBPF" in claude or "linux" in claude.lower()


def test_android_template_selected(init_ws: Path):
    """--type android -> CLAUDE.md uses android template."""
    _make_apk(init_ws)
    r = _run_init(init_ws, ["--type", "android",
                            "--resolve", _write_answers(init_ws, {"target_object": "classes.dex"})])
    assert r.returncode == 0, f"init failed: {r.stderr}"
    claude = (init_ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "adb" in claude.lower() or "android" in claude.lower()


# ---------- resume with type ----------

def test_resume_preserves_type(init_ws: Path):
    """Second init on typed workspace preserves existing project_type."""
    _make_pe(init_ws)
    r1 = _run_init(init_ws, ["--type", "windows"])
    assert r1.returncode == 0
    state1 = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state1

    r2 = _run_init(init_ws)
    assert r2.returncode == 0, f"resume failed: {r2.stderr}"
    state2 = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state2


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen in name blocks direct import)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- F1 (#304 review): marker without project_type — upgrade path ----------

def test_marker_without_type_upgrade_writes_type(init_ws: Path):
    """F1: [initialized] marker present but NO project_type (pre-#304
    workspace) -> `init --type windows` must WRITE project_type and exit 0
    (breaks the env_check_gate reject loop), preserving marker + seeds."""
    _make_pe(init_ws)
    (init_ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (init_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\n", encoding="utf-8",
    )
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"upgrade run failed: {r.stdout}{r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state, f"type not written on upgrade: {state}"
    reg = (init_ws / "claim-register.yaml").read_text(encoding="utf-8")
    assert "[initialized]" in reg, "upgrade must preserve the [initialized] marker"
    assert "C-001" in reg, "upgrade must preserve seed claims"


def test_marker_without_type_upgrade_restores_gate_pass(init_ws: Path):
    """F1: after the upgrade run is_init_complete() is True — the gate reject
    loop is mechanically closed (no human edit required)."""
    _make_pe(init_ws)
    (init_ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (init_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\n", encoding="utf-8",
    )
    mod = _load_init_module()
    assert not mod.is_init_complete(init_ws), "precondition: workspace incomplete"
    r = _run_init(init_ws, ["--type", "windows"])
    assert r.returncode == 0, f"upgrade run failed: {r.stdout}{r.stderr}"
    assert mod.is_init_complete(init_ws), "gate must pass after the upgrade run"


def test_marker_without_type_upgrade_via_resolve(init_ws: Path):
    """F1 (#455): upgrade without --type resolves the type via the
    --resolve answer (the old stdin-confirm path is gone)."""
    _make_pe(init_ws)
    (init_ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (init_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\n", encoding="utf-8",
    )
    r = _run_init(init_ws, ["--resolve", _write_answers(init_ws, {"type": "windows"})])
    assert r.returncode == 0, f"upgrade via resolve failed: {r.stdout}{r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=windows" in state


def test_marker_with_invalid_type_upgrade_fixes_type(init_ws: Path):
    """F1: an invalid project_type (typo) is corrected by an explicit --type."""
    _make_pe(init_ws)
    (init_ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (init_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=banana\n", encoding="utf-8",
    )
    r = _run_init(init_ws, ["--type", "linux"])
    assert r.returncode == 0, f"upgrade fix failed: {r.stdout}{r.stderr}"
    state = (init_ws / "analysis_state.txt").read_text(encoding="utf-8")
    assert "project_type=linux" in state
    assert "project_type=banana" not in state


# ---------- init-completeness: marker + type ----------

def test_init_without_type_is_incomplete(init_ws: Path):
    """Workspace with [initialized] marker but NO project_type is incomplete.
    (Old workspaces upgraded from pre-#304 init.)"""
    _make_pe(init_ws)
    (init_ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (init_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\n", encoding="utf-8",
    )
    mod = _load_init_module()
    assert not mod.is_init_complete(init_ws), \
        "workspace without project_type should be incomplete"


def test_init_with_type_is_complete(init_ws: Path):
    """Workspace with marker AND project_type is complete."""
    _make_pe(init_ws)
    (init_ws / "claim-register.yaml").write_text(
        "# [initialized] state_hash=abc seeds=3\n"
        "claims:\n- id: C-001\n  status: OPEN\n",
        encoding="utf-8",
    )
    (init_ws / "analysis_state.txt").write_text(
        "agent_teams_flag=0\nproject_type=windows\n", encoding="utf-8",
    )
    (init_ws / "runs").mkdir(parents=True, exist_ok=True)
    mod = _load_init_module()
    assert mod.is_init_complete(init_ws), \
        "workspace with marker + type should be complete"


# ---------- five-layer analysis principle in the single-source template ----------

def test_template_contains_five_layer_principle():
    """#356 W2: the single-source base template carries the five-layer
    analysis principle (absorbed back from the retired OS variants)."""
    tmpl = TEMPLATES / "CLAUDE.md.base.tmpl"
    assert tmpl.exists(), "template CLAUDE.md.base.tmpl missing"
    text = tmpl.read_text(encoding="utf-8")
    # Five-layer principle keywords
    assert "static" in text.lower(), "base template: missing 'static' layer"
    assert "debug" in text.lower(), "base template: missing 'debug' layer"
    assert "simulate" in text.lower() or "unidbg" in text.lower(), \
        "base template: missing simulation layer"


# ---------- env var table in the single-source template ----------

def test_base_template_env_vars():
    """Base template documents GHIDRA_HOME literally (#356 W2); the VM-channel
    rows are #919 type-conditional data on the init side (VM_ENV_ROWS) — a
    desktop-VM-only surface must not render into adb/browser workspaces."""
    tmpl = TEMPLATES / "CLAUDE.md.base.tmpl"
    text = tmpl.read_text(encoding="utf-8")
    assert "GHIDRA_HOME" in text
    assert "KUNGLAO_VM_HOST" not in text

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_envvars", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "KUNGLAO_VM_HOST" in mod.VM_ENV_ROWS
    assert "KUNGLAO_VM_HOST" in mod.vm_env_rows("windows")
    assert mod.vm_env_rows("android") == ""


def test_android_os_section_env_vars():
    """Android OS section (injected) documents ADB-related constraints."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_os", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    android = mod.os_section("android")
    assert "adb" in android.lower(), "android OS section missing adb constraints"
    linux = mod.os_section("linux")
    assert "gdbserver" in linux, "linux OS section missing gdbserver"
    windows = mod.os_section("windows")
    assert "x64dbg" in windows, "windows OS section missing x64dbg"
