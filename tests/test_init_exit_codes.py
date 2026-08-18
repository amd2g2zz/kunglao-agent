# -*- coding: utf-8 -*-
"""Issue #414 (v0.1.1): exit-code semantics audit — RC matrix test.

Every kunglao-init exit path must return the RC documented in the module
docstring / RC_* constants (0/1/2/3/4/5, +7 hook wiring #445 / +8 pending decisions #455). A caller that branches on the
exit code (kunglao-init-worker, orchestrator harness) must never be able to
read 0 as success from a refused init, and must never confuse two failure
modes. The observed harness surface printed "exit=0" for the flag-reject
refusal (M4) — this matrix pins each failure mode to its documented RC.

Documented codes:
  RC_OK = 0               success (fresh init / resume / upgrade)
  RC_ERROR = 1            generic (malformed flags / template defect / bad --resolve)
  RC_FATAL_VERIFY = 2     post-init idempotency verify failed
  RC_FLAG_REJECT = 3      Phase 0 agent-teams flag truthy
  RC_TOOLCHAIN_REFUSE = 4 toolchain HARD FAIL — human must install
  RC_NO_SAMPLE = 5        bins/ empty — friendly prompt
  RC_PENDING_DECISIONS = 8 #455: undecided intake item — pending list on
                          stdout, agent re-enters with --resolve

Note on argparse: Python's argparse exits 2 on usage errors by default.
kunglao-init documents RC_ERROR=1 as the generic code (malformed flags
included), so a usage error must be normalized to 1 before sys.exit —
otherwise a caller sees the fatal-verify code 2 for a trivial invocation
mistake. A MISSING workspace is NOT a usage error anymore (#455): it is
the defined zero-arg entry -> pending decision, exit 8.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

# Documented RC constants (mirror scripts/kunglao-init.py; kept local so the
# matrix test does not depend on the module under test to define the codes it
# must assert — a deleted/moved constant fails the test instead of being read
# as its own ground truth).
RC_OK = 0
RC_ERROR = 1
RC_FATAL_VERIFY = 2
RC_FLAG_REJECT = 3
RC_TOOLCHAIN_REFUSE = 4
RC_NO_SAMPLE = 5
RC_PENDING_DECISIONS = 8  # #455: undecided intake item -> pending list + --resolve

# Every documented RC must be asserted at least once in this file.
DOCUMENTED_RCS = (RC_OK, RC_ERROR, RC_FATAL_VERIFY, RC_FLAG_REJECT,
                  RC_TOOLCHAIN_REFUSE, RC_NO_SAMPLE, RC_PENDING_DECISIONS)


def _load_init_module():
    """Load kunglao-init.py via importlib (hyphen in name blocks direct import)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_rc_matrix_under_test", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_ws(tmp_path: Path, name: str, sample: bool) -> Path:
    """Workspace with optional PE sample in bins/ and runs/ pre-created."""
    ws = tmp_path / name
    (ws / "bins").mkdir(parents=True)
    (ws / "runs").mkdir()
    if sample:
        (ws / "bins" / "sample.exe").write_bytes(b"MZ\x90\x00" + b"\x00" * 64)
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    return ws


def _run_init_cli(ws: Path, extra: list[str] | None = None,
                  profile_root: Path | None = None,
                  flag: str | None = "0") -> subprocess.CompletedProcess:
    """Run kunglao-init as a subprocess (the CLI surface sys.exit(main())).

    Default env is hermetic: PATH -> empty dir (toolchain HARD checks fail
    deterministically), GHIDRA_HOME / KUNGLAO_VM_HOST stripped, profile-root
    injected so production profiles are never touched.
    """
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws), *(extra or [])]
    if profile_root is None:
        profile_root = ws.parent / "profile-root"
    argv += ["--profile-root", str(profile_root)]
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PATH"] = str(ws.parent / "empty-bin")
    env["PYTHONIOENCODING"] = "utf-8"
    if flag is not None:
        env[FLAG_NAME] = flag
    return subprocess.run(argv, capture_output=True, text=True, timeout=120,
                          env=env, errors="replace")


# ---------- RC matrix: each failure mode returns its documented RC ----------

def test_rc_matrix_flag_reject_3(tmp_path):
    """flag-reject (agent-teams flag truthy) -> RC_FLAG_REJECT=3, NO scaffold."""
    ws = _mk_ws(tmp_path, "ws", sample=True)
    r = _run_init_cli(ws, ["--type", "windows"], flag="1")
    assert r.returncode == RC_FLAG_REJECT, \
        f"flag-reject must exit {RC_FLAG_REJECT}, got {r.returncode}: {r.stdout}{r.stderr}"
    assert not (ws / "claim-register.yaml").exists(), \
        "flag-reject must not scaffold claim-register.yaml"


def test_rc_matrix_no_sample_5(tmp_path):
    """no-sample (bins/ empty) -> RC_NO_SAMPLE=5, friendly prompt, no scaffold."""
    ws = _mk_ws(tmp_path, "ws", sample=False)
    r = _run_init_cli(ws, ["--type", "windows"])
    assert r.returncode == RC_NO_SAMPLE, \
        f"no-sample must exit {RC_NO_SAMPLE}, got {r.returncode}: {r.stdout}{r.stderr}"
    assert "bins/" in (r.stdout + r.stderr), "friendly prompt must mention bins/"
    assert not (ws / "claim-register.yaml").exists()


def test_rc_matrix_toolchain_refuse_4(tmp_path):
    """toolchain-refuse (hostile PATH -> HARD FAIL) -> RC_TOOLCHAIN_REFUSE=4."""
    ws = _mk_ws(tmp_path, "ws", sample=True)
    r = _run_init_cli(ws, ["--type", "windows"])
    assert r.returncode == RC_TOOLCHAIN_REFUSE, \
        f"toolchain-refuse must exit {RC_TOOLCHAIN_REFUSE}, got {r.returncode}: {r.stdout}{r.stderr}"
    assert not (ws / "claim-register.yaml").exists(), \
        "toolchain-refuse must not leave a [initialized] marker"


def test_rc_matrix_ok_0(tmp_path):
    """successful init (--skip-toolchain) -> RC_OK=0, [initialized] marker."""
    ws = _mk_ws(tmp_path, "ws", sample=True)
    r = _run_init_cli(ws, ["--type", "windows", "--skip-toolchain"])
    assert r.returncode == RC_OK, \
        f"successful init must exit {RC_OK}, got {r.returncode}: {r.stdout}{r.stderr}"
    assert "[initialized]" in (ws / "claim-register.yaml").read_text(encoding="utf-8")


def test_rc_matrix_resume_0(tmp_path):
    """second run on an initialized workspace (resume) -> RC_OK=0."""
    ws = _mk_ws(tmp_path, "ws", sample=True)
    extra = ["--type", "windows", "--skip-toolchain"]
    r1 = _run_init_cli(ws, extra)
    assert r1.returncode == RC_OK
    r2 = _run_init_cli(ws, extra)
    assert r2.returncode == RC_OK, \
        f"resume must exit {RC_OK}, got {r2.returncode}: {r2.stdout}{r2.stderr}"


def _hermetic_env() -> dict:
    """Env for raw argv runs: flag pinned off, VM/Ghidra probes disabled."""
    env = {k: v for k, v in os.environ.items()
           if k not in (FLAG_NAME, "GHIDRA_HOME", "KUNGLAO_VM_HOST")}
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    return env


def test_rc_matrix_zero_arg_pending_8(tmp_path):
    """#455: zero-arg invocation is the defined intake entry, NOT an argparse
    usage error — it exits RC_PENDING_DECISIONS=8 with a machine-parseable
    pending list whose FIRST decision is the workspace path."""
    import json
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"),
            "--profile-root", str(tmp_path / "profile-root")]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                       env=_hermetic_env(), errors="replace")
    assert r.returncode == RC_PENDING_DECISIONS, \
        f"zero-arg must exit {RC_PENDING_DECISIONS} (pending), got {r.returncode}: {r.stdout}{r.stderr}"
    pending = json.loads(r.stdout)  # stdout is the machine channel
    assert pending["decisions"], "pending list must carry at least one decision"
    assert pending["decisions"][0]["decision_id"] == "workspace", \
        f"interaction order: workspace is the first pending decision, got {pending['decisions'][0]}"


def test_rc_matrix_argparse_usage_1(tmp_path):
    """argparse usage error (unknown flag) -> RC_ERROR=1, NOT 2 (fatal-verify).

    #455 note: a MISSING workspace is no longer a usage error (see
    test_rc_matrix_zero_arg_pending_8); a genuinely malformed argv still hits
    argparse's usage path, which kunglao-init normalizes 2 -> 1 so a caller
    must not read an invocation mistake as the post-init fatal-verify code 2.
    """
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"),
            "--definitely-not-a-flag",
            "--profile-root", str(tmp_path / "profile-root")]
    r = subprocess.run(argv, capture_output=True, text=True, timeout=120,
                       env=_hermetic_env(), errors="replace")
    assert r.returncode == RC_ERROR, \
        f"argparse usage error must exit {RC_ERROR} (generic), got {r.returncode}: {r.stderr}"


def test_rc_matrix_fatal_verify_2(tmp_path, monkeypatch):
    """post-init idempotency verify failure -> RC_FATAL_VERIFY=2.

    Library-level: initialize() recomputes the marker/seed count after writing
    claim-register; a monkeypatched claim_register_text that emits a broken
    register (no [initialized] marker) makes the verify fail deterministically.
    """
    ws = _mk_ws(tmp_path, "ws", sample=True)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init_module()

    def broken_register_text(sample, sample_sha, state_hash, project_type=None):
        return "# broken register — no [initialized] marker, no seeds\n"

    monkeypatch.setattr(mod, "claim_register_text", broken_register_text)
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root",
                 skip_toolchain=True)
    assert rc == RC_FATAL_VERIFY, \
        f"fatal-verify must return {RC_FATAL_VERIFY}, got {rc}"


def test_rc_matrix_template_defect_1(tmp_path, monkeypatch):
    """template-render defect (unfilled {{placeholder}}) -> RC_ERROR=1.

    Library-level: a monkeypatched template_render.render_strict that raises
    TemplateRenderError drives the run() except-branch. The refuse must return
    RC_ERROR=1 AND clean up ONLY this run's scaffold entries (L2: a refused
    init leaves no half-initialized state; pre-existing content survives).
    """
    ws = _mk_ws(tmp_path, "ws", sample=True)
    monkeypatch.setenv(FLAG_NAME, "0")
    mod = _load_init_module()
    import template_render as tr

    def broken_render(tmpl, params, source=None):
        raise tr.TemplateRenderError("unfilled {{PLACEHOLDER}}")

    monkeypatch.setattr(mod.template_render, "render_strict", broken_render)
    rc = mod.run(ws, project_type="windows",
                 profile_root=tmp_path / "profile-root",
                 skip_toolchain=True)
    assert rc == RC_ERROR, \
        f"template defect must return {RC_ERROR}, got {rc}"
    # This run's scaffold entries are removed (verify-first symmetry).
    assert not (ws / "claim-register.yaml").exists(), \
        "template-defect cleanup must not leave a [initialized] marker"
    assert not (ws / "analysis_state.txt").exists(), \
        "this-run analysis_state.txt must be removed by cleanup"
    assert not (ws / "global_plan.txt").exists(), \
        "this-run global_plan.txt must be removed by cleanup"
    assert not (ws / "facts" / "_INDEX.md").exists(), \
        "this-run facts/_INDEX.md must be removed by cleanup"
    # Pre-existing content survives.
    assert (ws / "runs").is_dir(), "pre-existing runs/ must survive cleanup"
    assert (ws / "bins" / "sample.exe").exists(), "bins/ must survive cleanup"


def test_rc_matrix_module_constants_match_documented_contract():
    """kunglao-init's RC_* constants are exactly the documented 0/1/2/3/4/5/7.

    If a future edit adds a new documented code, this matrix must grow a
    per-mode assertion for it — the #414 acceptance is 'per-mode RC matrix
    test green (0/1/2/3/4/5)', extended by #455 with the pending code 8.
    """
    mod = _load_init_module()
    observed = {
        mod.RC_OK: "RC_OK",
        mod.RC_ERROR: "RC_ERROR",
        mod.RC_FATAL_VERIFY: "RC_FATAL_VERIFY",
        mod.RC_FLAG_REJECT: "RC_FLAG_REJECT",
        mod.RC_TOOLCHAIN_REFUSE: "RC_TOOLCHAIN_REFUSE",
        mod.RC_NO_SAMPLE: "RC_NO_SAMPLE",
        mod.RC_PENDING_DECISIONS: "RC_PENDING_DECISIONS",
    }
    assert set(observed) == set(DOCUMENTED_RCS), \
        f"RC constants drifted from documented contract: {observed}"
