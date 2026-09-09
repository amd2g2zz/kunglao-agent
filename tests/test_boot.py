# -*- coding: utf-8 -*-
"""Contract tests for scripts/_boot.py — the single CLI boot module.

_boot owns the entry-time insurance that used to be scattered across a
utf8_boot module plus per-script try/reconfigure and sys.path prologues:
UTF-8 stdio, and the script-directory path bootstrap. Pure unit — no
OS-process spawning, no network, no heavy IO.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _boot  # noqa: E402


def test_utf8_boot_module_is_gone():
    """The boot module is _boot; the former utf8_boot module is deleted
    (single boot module, no-backcompat)."""
    assert not (SCRIPTS / "utf8_boot.py").exists()


def test_force_utf8_is_idempotent():
    _boot.force_utf8()
    _boot.force_utf8()  # second call: no-op, never raises


def test_force_utf8_sets_pythonutf8_env(monkeypatch):
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    # reset the module-level guard so the setdefault runs again
    monkeypatch.setattr(_boot, "_APPLIED", False)
    _boot.force_utf8()
    import os
    assert os.environ.get("PYTHONUTF8") == "1"


def test_ensure_utf8_stderr_reconfigures_fake_stream():
    class FakeStream:
        def __init__(self):
            self.called = None

        def reconfigure(self, **kwargs):
            self.called = kwargs
            return None

    fake = FakeStream()
    assert _boot.ensure_utf8_stderr(fake) is True
    assert fake.called == {"encoding": "utf-8", "errors": "replace"}


def test_ensure_utf8_stderr_fail_open_without_reconfigure():
    assert _boot.ensure_utf8_stderr(io.BytesIO()) is False


def test_reconfigure_stdout_tolerates_captured_streams(capsys):
    # under capsys the stream is captured; the helper must never raise
    assert _boot.reconfigure_stdout() in (True, False)


def test_ensure_own_dir_on_path_puts_scripts_first():
    _boot.ensure_own_dir_on_path()
    assert str(SCRIPTS) in sys.path


def test_ensure_own_dir_on_path_is_idempotent():
    _boot.ensure_own_dir_on_path()
    first = list(sys.path)
    _boot.ensure_own_dir_on_path()
    assert sys.path.count(str(SCRIPTS)) == 1, "absolute entry must not duplicate"
    assert sys.path[0] == str(SCRIPTS), "guard-insert keeps the dir at [0]"
    assert first.count(str(SCRIPTS)) == sys.path.count(str(SCRIPTS))
