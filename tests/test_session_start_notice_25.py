# -*- coding: utf-8 -*-
"""Issue #25 D4 — hooks-only-in-workspace is a silent assumption failure.

Kunglao hooks are deployed PROJECT-scoped (<ws>/.claude/settings.json,
#258): a Claude session opened OUTSIDE the workspace never loads them, so
the gates silently don't fire — while the user believes kunglao is active
because it is "installed". Fix = documentation + detection (NOT new hook
plumbing): hooks/session_start.py already had a workspace-resolution
failure path (`.kunglao` missing) that printed a quiet internal skip line;
it now emits a clear one-line notice that kunglao hooks are NOT active in
this session plus the activation hint.

Contract:
  * non-workspace session (hook entry runs, no .kunglao) -> the notice,
    exit 0 (non-fatal, same as before);
  * workspace session (.kunglao present) -> NO notice; the normal
    always_arm/renew output is unchanged.

TDD RED phase: written BEFORE the notice exists (2026-09-04).
"""
from __future__ import annotations

import session_start as ss  # pytest.ini pythonpath includes hooks/

NOTICE_TOKEN = "kunglao hooks are NOT active"
ACTIVATE_TOKEN = "/kunglao-agent:init"


def test_non_workspace_session_emits_notice(tmp_path, capsys):
    """No .kunglao -> one-line notice: hooks NOT active + how to activate."""
    ws = tmp_path / "not-a-kunglao-ws"
    ws.mkdir()
    rc = ss.session_start(ws)
    out = capsys.readouterr().out
    assert rc == 0, "non-workspace session must stay non-fatal"
    assert NOTICE_TOKEN in out, f"notice missing from output: {out!r}"
    assert ACTIVATE_TOKEN in out, f"activation hint missing: {out!r}"
    # one line — SessionStart output should stay a single context line
    notice_lines = [ln for ln in out.splitlines() if NOTICE_TOKEN in ln]
    assert len(notice_lines) == 1, f"expected exactly one notice line: {out!r}"


def test_workspace_session_emits_no_notice(tmp_path, capsys):
    """A real kunglao workspace keeps the normal arm/renew output — the
    notice must never fire there."""
    ws = tmp_path / "ws"
    (ws / ".kunglao").mkdir(parents=True)
    rc = ss.session_start(ws)
    out = capsys.readouterr().out
    assert rc == 0
    assert NOTICE_TOKEN not in out, f"notice must not fire in-workspace: {out!r}"
    assert "always_arm" in out, f"normal arm output missing: {out!r}"


def test_notice_names_the_workspace_path(tmp_path, capsys):
    """The notice points at the resolved path so a user can see WHERE the
    workspace was expected."""
    ws = tmp_path / "some-other-dir"
    ws.mkdir()
    ss.session_start(ws)
    out = capsys.readouterr().out
    assert str(ws) in out, f"notice must cite the checked path: {out!r}"
