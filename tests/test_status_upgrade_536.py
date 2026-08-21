# -*- coding: utf-8 -*-
"""#536 Task 4 — upgrade detection surfaces.

kunglao-status appends a one-line warning when the workspace stamp is
older than the active skill version; kunglao-resume carries the same
warning as advice. Both surfaces are read-only: the warning never moves
rc (env_check's template_version row is the hard gate).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import template_version as tv  # noqa: E402


def _ws_with_stamp(tmp_path: Path, ws_version: str | None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    text = tv.stamp_line(ws_version) + "\n" if ws_version else ""
    (ws / "CLAUDE.md").write_text(text + "# ws\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        text + "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    return ws


def test_status_no_warning_when_aligned(tmp_path: Path, monkeypatch) -> None:
    """Equal stamp → silent. Fixture has no stamp (legacy) → also silent."""
    monkeypatch.setattr(tv, "read_skill_version", lambda: "9.9.9")
    ws = _ws_with_stamp(tmp_path, "9.9.9")
    from kunglao_status import render_status
    out = render_status(ws, color=False)
    assert "older than the skill version" not in out


def test_status_no_warning_on_legacy_unstamped(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tv, "read_skill_version", lambda: "9.9.9")
    ws = _ws_with_stamp(tmp_path, ws_version=None)
    from kunglao_status import render_status
    out = render_status(ws, color=False)
    assert "older than the skill version" not in out


def test_status_warns_when_workspace_behind(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tv, "read_skill_version", lambda: "0.2.0")
    ws = _ws_with_stamp(tmp_path, "0.1.1")
    from kunglao_status import render_status
    out = render_status(ws, color=False)
    assert "older than the skill version" in out, out
    assert "0.1.1" in out and "0.2.0" in out


def test_resume_brief_carries_upgrade_advice(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tv, "read_skill_version", lambda: "0.2.0")
    ws = _ws_with_stamp(tmp_path, "0.1.1")
    import kunglao_resume
    brief = kunglao_resume.build_brief(ws)
    assert any("older than the skill version" in a for a in brief["advice"]), \
        brief["advice"]


def test_resume_brief_silent_when_aligned(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tv, "read_skill_version", lambda: "0.2.0")
    ws = _ws_with_stamp(tmp_path, "0.2.0")
    import kunglao_resume
    brief = kunglao_resume.build_brief(ws)
    assert not any("older than the skill version" in a
                   for a in brief["advice"])


def test_upgrade_warning_never_moves_resume_rc(tmp_path: Path, monkeypatch) -> None:
    """Advice is read-only: a behind workspace still gets a normal verdict."""
    monkeypatch.setattr(tv, "read_skill_version", lambda: "0.2.0")
    ws = _ws_with_stamp(tmp_path, "0.1.1")
    import kunglao_resume
    brief = kunglao_resume.build_brief(ws)
    # NO-STATE / RESUMABLE / NEEDS-MANUAL decided by state, not the stamp
    assert brief["rc"] in (kunglao_resume.RC_NO_STATE,
                           kunglao_resume.RC_RESUMABLE,
                           kunglao_resume.RC_MANUAL)
