# -*- coding: utf-8 -*-
"""Tests for scripts/shell_defaults.py — reusable CLI for shell env default lines (#276).

Acceptance (#276 task 1):
  - subcommands check (OK / TRUTHY / ABSENT) / apply / remove
  - fully parameterized: --var / --value / --profile / --shell powershell|bash
    (no hardcoded var or profile path)
  - Windows PowerShell (`$env:NAME = "V"`) + bash (`export NAME="V"`) formats
  - truthy detection (1/true/yes/on, case-insensitive) with warning
  - apply idempotent: target line already present -> skip; truthy line ->
    rewrite to target value; no line -> append with comment
  - profile path injectable (tests use tmp files); exit codes distinguish states
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "shell_defaults.py"
VAR = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace",
        env={"PYTHONIOENCODING": "utf-8", **os.environ},
    )


def _profile(tmp_path: Path, content: str = "") -> Path:
    p = tmp_path / "profile.ps1"
    p.write_text(content, encoding="utf-8")
    return p


# ---------- check: three states ----------

def test_check_absent_exit_2(tmp_path):
    """Empty profile -> ABSENT, exit 2."""
    p = _profile(tmp_path)
    r = _run("check", "--var", VAR, "--profile", str(p))
    assert r.returncode == 2, f"rc={r.returncode} out={r.stdout} err={r.stderr}"
    assert "ABSENT" in r.stdout
    assert VAR in r.stdout


def test_check_absent_when_profile_missing(tmp_path):
    """Profile file does not exist -> ABSENT (no line anywhere), exit 2."""
    p = tmp_path / "nope.ps1"
    r = _run("check", "--var", VAR, "--profile", str(p))
    assert r.returncode == 2
    assert "ABSENT" in r.stdout


def test_check_ok_exit_0(tmp_path):
    """PowerShell target line $env:VAR = "0" -> OK, exit 0."""
    p = _profile(tmp_path, f'$env:{VAR} = "0"\n')
    r = _run("check", "--var", VAR, "--profile", str(p))
    assert r.returncode == 0, f"rc={r.returncode} out={r.stdout} err={r.stderr}"
    assert "OK" in r.stdout


def test_check_false_off_values_are_ok(tmp_path):
    """'false'/'off' (non-truthy) values -> OK, exit 0 (default-disabled semantics)."""
    for value in ("false", "off"):
        p = _profile(tmp_path, f'$env:{VAR} = "{value}"\n')
        r = _run("check", "--var", VAR, "--profile", str(p))
        assert r.returncode == 0, f"{value}: rc={r.returncode} {r.stdout}"
        assert "OK" in r.stdout


def test_check_truthy_exit_1(tmp_path):
    """Truthy '1' -> TRUTHY, exit 1 (pollution — the 2026-08-12 shape)."""
    p = _profile(tmp_path, f'$env:{VAR} = "1"\n')
    r = _run("check", "--var", VAR, "--profile", str(p))
    assert r.returncode == 1, f"rc={r.returncode} out={r.stdout} err={r.stderr}"
    assert "TRUTHY" in r.stdout
    assert "1" in r.stdout


def test_check_truthy_case_insensitive(tmp_path):
    """1/true/yes/on case-insensitive: TRUE / Yes / ON all TRUTHY."""
    for value in ("TRUE", "Yes", "ON"):
        p = _profile(tmp_path, f'$env:{VAR} = "{value}"\n')
        r = _run("check", "--var", VAR, "--profile", str(p))
        assert r.returncode == 1, f"{value}: rc={r.returncode} {r.stdout}"
        assert "TRUTHY" in r.stdout


def test_check_truthy_unquoted(tmp_path):
    """Unquoted truthy (export VAR=1 shape) also detected."""
    p = _profile(tmp_path, f"export {VAR}=1\n")
    r = _run("check", "--var", VAR, "--profile", str(p), "--shell", "bash")
    assert r.returncode == 1
    assert "TRUTHY" in r.stdout


def test_check_json_output(tmp_path):
    """--json -> parseable output carrying status."""
    p = _profile(tmp_path, f'$env:{VAR} = "0"\n')
    r = _run("check", "--var", VAR, "--profile", str(p), "--json")
    out = json.loads(r.stdout)
    assert out["status"] == "OK"
    assert out["var"] == VAR
    assert out["value"] == "0"


# ---------- bash format ----------

def test_check_bash_ok(tmp_path):
    """bash format: export VAR="0" -> OK."""
    p = _profile(tmp_path, f'export {VAR}="0"\n')
    r = _run("check", "--var", VAR, "--profile", str(p), "--shell", "bash")
    assert r.returncode == 0
    assert "OK" in r.stdout


# ---------- apply ----------

def test_apply_appends_with_comment(tmp_path):
    """Empty profile -> appended with a comment line above the target line."""
    p = _profile(tmp_path, "")
    r = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p))
    assert r.returncode == 0, f"rc={r.returncode} out={r.stdout} err={r.stderr}"
    assert "appended" in r.stdout
    text = p.read_text(encoding="utf-8")
    assert f'$env:{VAR} = "0"' in text, text
    assert "# shell_defaults:" in text, "appended line must carry a comment"


def test_apply_creates_missing_profile(tmp_path):
    """Profile file missing -> created with comment + target line."""
    p = tmp_path / "new" / "profile.ps1"
    r = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p))
    assert r.returncode == 0
    assert p.exists()
    assert f'$env:{VAR} = "0"' in p.read_text(encoding="utf-8")


def test_apply_idempotent_unchanged(tmp_path):
    """Target line already present -> second run 'unchanged', file byte-identical."""
    p = _profile(tmp_path, f'$env:{VAR} = "0"\n')
    r1 = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p))
    assert "unchanged" in r1.stdout
    before = p.read_bytes()
    r2 = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p))
    assert r2.returncode == 0
    assert "unchanged" in r2.stdout
    assert p.read_bytes() == before, "apply must not rewrite an already-correct line"


def test_apply_rewrites_truthy(tmp_path):
    """Truthy line -> rewritten to the target value (the pollution fix)."""
    p = _profile(tmp_path, f'$env:{VAR} = "1"\n')
    r = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p))
    assert r.returncode == 0
    assert "rewritten" in r.stdout
    assert "1" in r.stdout, "output should note the old truthy value"
    text = p.read_text(encoding="utf-8")
    assert f'$env:{VAR} = "0"' in text
    assert f'$env:{VAR} = "1"' not in text


def test_apply_rewrites_other_value(tmp_path):
    """Non-target non-truthy value (e.g. '2') -> rewritten to target (converges to ONE line)."""
    p = _profile(tmp_path, f'$env:{VAR} = "2"\n')
    r = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p))
    assert r.returncode == 0
    assert "rewritten" in r.stdout
    assert f'$env:{VAR} = "0"' in p.read_text(encoding="utf-8")


def test_apply_preserves_unrelated_lines(tmp_path):
    """Other profile content (comments, other vars) must survive apply."""
    p = _profile(tmp_path, "# my profile\n$env:OTHER = \"x\"\n")
    r = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p))
    assert r.returncode == 0
    text = p.read_text(encoding="utf-8")
    assert "# my profile" in text
    assert '$env:OTHER = "x"' in text
    assert f'$env:{VAR} = "0"' in text


def test_apply_bash_format(tmp_path):
    """bash: apply writes export VAR="0"."""
    p = _profile(tmp_path, "")
    r = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p), "--shell", "bash")
    assert r.returncode == 0
    assert f'export {VAR}="0"' in p.read_text(encoding="utf-8")


def test_apply_json_output(tmp_path):
    """--json apply -> change field."""
    p = _profile(tmp_path, "")
    r = _run("apply", "--var", VAR, "--value", "0", "--profile", str(p), "--json")
    out = json.loads(r.stdout)
    assert out["change"] == "appended"
    assert out["var"] == VAR


# ---------- remove ----------

def test_remove_removes_line_and_comment(tmp_path):
    """remove drops the var line and its shell_defaults comment; other lines stay."""
    p = _profile(tmp_path, f"# shell_defaults: {VAR}=0 (managed)\n$env:{VAR} = \"0\"\n# keep me\n")
    r = _run("remove", "--var", VAR, "--profile", str(p))
    assert r.returncode == 0
    assert "removed" in r.stdout
    text = p.read_text(encoding="utf-8")
    assert VAR not in text, text
    assert "# keep me" in text, "unrelated lines must survive remove"


def test_remove_absent_is_noop(tmp_path):
    """remove on a profile without the var -> exit 0, 'not present', file unchanged."""
    p = _profile(tmp_path, "$env:OTHER = \"x\"\n")
    before = p.read_bytes()
    r = _run("remove", "--var", VAR, "--profile", str(p))
    assert r.returncode == 0
    assert p.read_bytes() == before


# ---------- CLI hygiene ----------

def test_missing_required_arg_is_error(tmp_path):
    """check without --var -> argparse error (exit 2), not a silent pass."""
    p = _profile(tmp_path, "")
    r = _run("check", "--profile", str(p))
    assert r.returncode == 2
    assert "--var" in r.stderr


def test_apply_without_value_is_error(tmp_path):
    """apply without --value -> argparse error."""
    p = _profile(tmp_path, "")
    r = _run("apply", "--var", VAR, "--profile", str(p))
    assert r.returncode == 2
    assert "--value" in r.stderr
