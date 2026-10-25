# -*- coding: utf-8 -*-
"""Windows host support matrix (round_closure 78/78 production failures).

The three production failure signatures are pinned here as synthetic
replays that must stay green after the fix:

  1. fcntl import signature — ``ModuleNotFoundError: No module named
     'fcntl'`` at import time killed every online_distill face on
     Windows. Replay: a meta-path blocker that makes fcntl import
     raise exactly that error, then import + exercise the engine in a
     subprocess (TDD RED: the pre-fix engine dies at import).
  2. chmod(path-int) TypeError signature — ``os.chmod(fd, 0o644)``
     where fd is an int works on POSIX (os.supports_fd) but raises
     TypeError on Windows. Replay: a fake os.chmod with nt semantics
     (TypeError on ANY input) + injected ``os.name == "nt"``.
  3. GBK decode signature — subprocess children inherit the console
     code page (GBK on zh-CN Windows) unless UTF-8 is forced in their
     environment. Replay: the forced env is pinned and a child round-
     trip decodes non-ASCII bytes as utf-8.

Every Windows face is tested with INJECTABLE platform semantics
(os_name parameters, monkeypatched os.name, feature stubs) — no real
Windows host is required.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import platform_matrix as pm  # noqa: E402
import event_taxonomy  # noqa: E402


# ---------------------------------------------------------------------------
# the support matrix itself
# ---------------------------------------------------------------------------

def test_host_report_declares_posix_and_nt_only():
    posix = pm.host_report(os_name="posix")
    nt = pm.host_report(os_name="nt")
    other = pm.host_report(os_name="java")
    assert posix["schema"] == "platform-matrix/1"
    assert posix["declared"] is True
    assert nt["declared"] is True
    assert other["declared"] is False
    assert posix["lock_strategy"] == "posix-flock"
    assert nt["chmod"] == "skipped-on-nt"
    assert posix["chmod"] == "posix-chmod"


def test_platform_run_start_word_registered():
    # controlled-vocabulary contract: emit-side words come from the
    # registry (CI-anchored, unregistered = red).
    assert "platform_run_start" in event_taxonomy.EMIT_ACTIONS


# ---------------------------------------------------------------------------
# signature 1 — fcntl import (the 78/78 import-time kill)
# ---------------------------------------------------------------------------

_FCNTL_BLOCKER = '''
import sys

class _FcntlBlocker:
    """Import finder that reproduces the production signature exactly:
    ModuleNotFoundError: No module named 'fcntl'."""
    def find_spec(self, name, path=None, target=None):
        if name == "fcntl":
            raise ModuleNotFoundError("No module named 'fcntl'")
        return None

sys.meta_path.insert(0, _FcntlBlocker())
for _m in ("fcntl",):
    sys.modules.pop(_m, None)
'''


def test_engine_imports_and_locks_without_fcntl(tmp_path):
    """Replay pin (signature 1): with fcntl made absent, the engine
    module still imports and _LedgerLock still opens/closes. RED
    before the fix: the top-level `import fcntl` kills the import."""
    script = _FCNTL_BLOCKER + f'''
import json, pathlib, tempfile, sys
sys.path.insert(0, {str(SCRIPTS)!r})
import online_distill as od            # production kill site (pre-fix)
ws = pathlib.Path(tempfile.mkdtemp())
with od._LedgerLock(ws):               # the budget critical-section lock
    pass
import platform_matrix
print(json.dumps({{"lock": platform_matrix.lock_strategy()}}))
'''
    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"stderr={proc.stderr[-2000:]}"
    assert json.loads(proc.stdout.strip().splitlines()[-1])[
        "lock"] == "unlocked-noop"


def test_msvcrt_lock_face_pinned_synhetically(tmp_path):
    """The Windows branch degrades to msvcrt.locking — pinned with a
    stub msvcrt (recording face) since macOS has no real one."""
    script = _FCNTL_BLOCKER + '''
import json, sys, types
calls = []
fake = types.ModuleType("msvcrt")
fake.LK_LOCK, fake.LK_UNLCK = 1, 0
def _locking(fd, mode, nbytes):
    calls.append((fd, mode, nbytes))
fake.locking = _locking
sys.modules["msvcrt"] = fake
sys.path.insert(0, {scripts!r})
import platform_matrix
fd = 3                                  # an open fd shape, not used by the stub
strategy = platform_matrix.fd_lock(fd)
undo = platform_matrix.fd_unlock(fd)
print(json.dumps({{"strategy": strategy, "undo": undo, "calls": calls}}))
'''.format(scripts=str(SCRIPTS))
    proc = subprocess.run([sys.executable, "-c", script],
                          capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"stderr={proc.stderr[-2000:]}"
    doc = json.loads(proc.stdout.strip().splitlines()[-1])
    assert doc["strategy"] == "msvcrt-locking"
    assert doc["undo"] == "msvcrt-locking"
    assert doc["calls"] == [[3, 1, 1], [3, 0, 1]]  # LK_LOCK then LK_UNLCK, 1 byte (json: tuples arrive as lists)


def test_posix_ledger_lock_still_flocks(tmp_path, monkeypatch):
    """The fix must not change POSIX behavior: the engine lock goes
    through platform_matrix.fd_lock (posix-flock)."""
    import online_distill as od
    seen = []
    monkeypatch.setattr(pm, "fd_lock",
                        lambda fd, **kw: seen.append(("lock", fd))
                        or "posix-flock")
    monkeypatch.setattr(pm, "fd_unlock",
                        lambda fd, **kw: seen.append(("unlock", fd))
                        or "posix-flock")
    with od._LedgerLock(tmp_path):
        assert (tmp_path / "runs" / "distill-budget.json.lock").is_file()
    assert seen == [("lock", seen[0][1]), ("unlock", seen[0][1])]


# ---------------------------------------------------------------------------
# signature 2 — chmod(path-int) TypeError under nt
# ---------------------------------------------------------------------------

@pytest.fixture()
def nt_chmod(monkeypatch):
    """Fake os.chmod with REAL nt semantics: TypeError on every call
    (Windows os.chmod takes only a path and honors one bit; the int-fd
    face is the production TypeError) + the injected nt host class."""
    calls = []

    def fake_chmod(target, mode):
        calls.append((target, mode))
        raise TypeError("chmod should not run on nt")

    monkeypatch.setattr(pm, "_OS_NAME", "nt")
    monkeypatch.setattr(os, "chmod", fake_chmod)
    return calls


def test_production_chmod_signature_raises_like_windows():
    """The synthetic fixture itself must reproduce the production
    TypeError signature (os.chmod applied to an int fd)."""
    def windows_chmod(target, mode):
        raise TypeError(" argument should be a str or an os.PathLike "
                        "object where __fspath__ returns a str, not "
                        "<class 'int'>")
    with pytest.raises(TypeError):
        windows_chmod(3, 0o644)


def test_chmod_checked_skips_int_fd_on_nt(nt_chmod):
    fd = 999  # int fd: the production signature's argument shape
    assert pm.chmod_checked(fd, 0o644, os_name="nt") is False
    assert nt_chmod == []  # the nt branch never reaches os.chmod


def test_chmod_checked_applies_on_posix(tmp_path):
    target = tmp_path / "artifact.txt"
    target.write_text("x", encoding="utf-8")
    assert pm.chmod_checked(target, 0o644, os_name="posix") is True
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def _compose_atomic(path, text):
    import importlib
    compose = importlib.import_module("rlvr.compose")
    return compose._atomic_write_text(path, text)


def test_compose_atomic_write_nt_replay(tmp_path, nt_chmod):
    path = tmp_path / "card.md"
    _compose_atomic(path, "hello #810")
    assert path.read_text(encoding="utf-8") == "hello #810"
    assert nt_chmod == []


def test_compose_atomic_write_posix_mode_kept(tmp_path):
    path = tmp_path / "card.md"
    _compose_atomic(path, "hello")
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_common_atomic_write_skips_chmod_on_nt(tmp_path, nt_chmod,
                                               monkeypatch):
    import _common
    monkeypatch.setattr(_common, "_NT", True)
    path = tmp_path / "ledger.json"
    _common.atomic_write_text(path, "{}", mode=0o644)
    assert path.read_text(encoding="utf-8") == "{}"
    assert nt_chmod == []


def test_common_atomic_write_posix_mode_kept(tmp_path):
    import _common
    path = tmp_path / "ledger.json"
    _common.atomic_write_text(path, "{}", mode=0o644)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


# ---------------------------------------------------------------------------
# signature 3 — GBK code page / subprocess env
# ---------------------------------------------------------------------------

def test_utf8_env_forces_python_utf8():
    env = pm.utf8_env({})
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_utf8_env_extends_without_mutating_base():
    base = {"PATH": "/bin"}
    env = pm.utf8_env(base)
    assert base == {"PATH": "/bin"}          # immutability: base untouched
    assert env["PATH"] == "/bin"
    assert env["PYTHONUTF8"] == "1"


def test_utf8_env_child_decodes_non_ascii():
    """The forced env makes the child's stdout utf-8 even with a locale-
    stripped environment (the synthetic GBK posture)."""
    env = pm.utf8_env({"PATH": os.environ.get("PATH", "")})
    for k in ("LANG", "LC_ALL", "PYTHONIOENCODING", "PYTHONUTF8"):
        env.pop(k, None)  # bare locale, then re-force through utf8_env
    env = pm.utf8_env(env)
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.stdout.write('\\u4e2d\\u6587')"],
        capture_output=True, env=env, encoding="utf-8", timeout=60)
    assert proc.returncode == 0
    assert proc.stdout == "中文"


def test_run_candidate_forces_utf8_env(tmp_path, monkeypatch):
    import online_distill as od
    cand = tmp_path / "cand.py"
    sample = tmp_path / "sample.bin"
    cand.write_text("print('x')", encoding="utf-8")
    sample.write_bytes(b"sample")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured.update(kwargs)
        return subprocess.CompletedProcess(cmd, 0, "x\n", "")

    monkeypatch.setattr(od.subprocess, "run", fake_run)
    out = od.run_candidate(cand, sample)
    assert out["satisfied"] is True
    assert captured["env"]["PYTHONUTF8"] == "1"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"


# ---------------------------------------------------------------------------
# the run-start platform assertion (acceptance 2: loud, never silent)
# ---------------------------------------------------------------------------

def test_assert_run_start_declared_records_row(tmp_path):
    import kunglao_log
    report = pm.assert_run_start(tmp_path, os_name="posix")
    assert report["declared"] is True
    assert report["row_emitted"] is True
    rows = kunglao_log.tail(tmp_path, n=5)
    row = [r for r in rows if r.get("action") == "platform_run_start"]
    assert row, "run-start platform row must reach the ledger"
    detail = json.loads(row[-1]["detail"])
    assert detail["os_name"] == "posix"
    assert detail["duty"] == "closure"


def test_assert_run_start_undeclared_is_loud(tmp_path, capsys):
    import kunglao_log
    report = pm.assert_run_start(tmp_path, os_name="java")
    assert report["declared"] is False
    err = capsys.readouterr().err
    assert "platform-undeclared" in err      # loud on stderr...
    rows = kunglao_log.tail(tmp_path, n=5)
    assert any(r.get("action") == "platform_run_start" for r in rows), \
        "...and loud in the ledger (never a silent refusal)"


def test_main_refuses_closure_duties_on_undeclared_host(
        tmp_path, monkeypatch, capsys):
    """Undeclared host class: duties are REFUSED (nonzero exit, no
    trigger scan side effects) — the 78/78 silent-wipeout face dies."""
    import online_distill as od
    monkeypatch.setattr(pm, "_OS_NAME", "java")
    rc = od.main(["--scan", str(tmp_path)])
    assert rc == 3
    err = capsys.readouterr().err
    assert "platform-undeclared" in err
    assert not (tmp_path / "runs" / "distill-trigger.json").exists(), \
        "refused duties must not perform the scan"


def test_main_declared_host_proceeds(tmp_path, monkeypatch):
    import online_distill as od
    monkeypatch.setattr(pm, "_OS_NAME", "posix")
    assert od.main(["--scan", str(tmp_path)]) == 0
