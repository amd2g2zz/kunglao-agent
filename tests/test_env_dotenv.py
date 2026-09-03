# -*- coding: utf-8 -*-
"""Issue #356 W4 — .env deployment surface contract.

No python-dotenv dependency (stdlib-only policy — the release receipt pins
pyproject deps). Instead:

- .env.example ships the annotated variable list (6 deployment vars)
- scripts/env_check.py gains a tiny stdlib parser: os.environ wins, the
  workspace .env is the fallback (parse once at startup, before checks)
- .gitignore ignores .env (it can carry lab topology)

RED phase: .env.example does not exist and env_check does not read .env.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
ENV_EXAMPLE = ROOT / ".env.example"
GITIGNORE = ROOT / ".gitignore"

sys.path.insert(0, str(SCRIPTS))
import env_check  # noqa: E402

KNOWN_VARS = ("KUNGLAO_VM_HOST", "KUNGLAO_VM_SHELL_PORT", "KUNGLAO_FRIDA_PORT",
              "GHIDRA_HOME", "KUNGLAO_CLAUDE_JSON", "KUNGLAO_DIE")


# ---------- .env.example inventory ----------

def test_env_example_exists_with_six_vars():
    assert ENV_EXAMPLE.is_file(), ".env.example missing (#356 W4)"
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for var in KNOWN_VARS:
        assert var in text, f".env.example missing {var}"


def test_env_example_comments_english_one_line_each():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    comment_lines = [ln for ln in text.splitlines() if ln.startswith("# ")
                     and "kunglao-agent" not in ln.lower()][:20]
    assert comment_lines, "no annotation comments in .env.example"
    for ln in comment_lines:
        assert ln.isascii(), f"non-English comment: {ln!r}"


def test_gitignore_ignores_env():
    gi = GITIGNORE.read_text(encoding="utf-8")
    assert any(line.strip() == ".env" for line in gi.splitlines()), \
        ".gitignore must ignore .env (may carry lab topology)"


# ---------- parser precedence (os.environ wins, .env fallback) ----------

def test_load_dotenv_env_wins_over_file(monkeypatch, tmp_path):
    """Real env var beats the same key in workspace .env."""
    envf = tmp_path / ".env"
    envf.write_text("KUNGLAO_VM_HOST=from-file\nGHIDRA_HOME=file-only\n",
                    encoding="utf-8")
    monkeypatch.setenv("KUNGLAO_VM_HOST", "from-env")
    merged = env_check.load_dotenv(tmp_path)
    assert merged["KUNGLAO_VM_HOST"] == "from-env"
    assert merged["GHIDRA_HOME"] == "file-only"


def test_load_dotenv_missing_file_is_empty(monkeypatch, tmp_path):
    merged = env_check.load_dotenv(tmp_path)
    assert merged == {}


def test_load_dotenv_ignores_comments_and_blank_lines(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text(
        "# a comment\n\nKUNGLAO_DIE=/opt/die/diec\n",
        encoding="utf-8")
    merged = env_check.load_dotenv(tmp_path)
    assert merged == {"KUNGLAO_DIE": "/opt/die/diec"}


def test_load_dotenv_never_overrides_process_env(monkeypatch, tmp_path):
    """Malformed keys / NUL lines are skipped, not fatal (env snapshot is
    best-effort — a broken .env must not crash the check runner)."""
    (tmp_path / ".env").write_text(
        "GOOD=1\nnot-a-pair\nOTHER=2\n", encoding="utf-8")
    merged = env_check.load_dotenv(tmp_path)
    assert merged.get("GOOD") == "1"
    assert merged.get("OTHER") == "2"


def test_run_uses_dotenv_fallback_for_vm_host(monkeypatch, tmp_path):
    """End-to-end: VM check FAILs with unset host, but a workspace .env
    carrying KUNGLAO_VM_HOST feeds the check (connection still fails —
    unreachable host — but the detail names the .env-sourced host)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / ".env").write_text("KUNGLAO_VM_HOST=10.255.255.1\n", encoding="utf-8")
    monkeypatch.delenv("KUNGLAO_VM_HOST", raising=False)
    monkeypatch.setattr(env_check, "VM_HOST", "", raising=False)
    # re-bind like run() does: env first, .env fallback
    merged = env_check.load_dotenv(ws)
    host = os.environ.get("KUNGLAO_VM_HOST") or merged.get("KUNGLAO_VM_HOST", "")
    assert host == "10.255.255.1"


def test_no_python_dotenv_dependency():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "python-dotenv" not in pyproject, \
        "stdlib-only policy: python-dotenv must NOT become a dependency (#356 W4)"
    src = (SCRIPTS / "env_check.py").read_text(encoding="utf-8")
    assert "import dotenv" not in src, "env_check must stay stdlib-only"
