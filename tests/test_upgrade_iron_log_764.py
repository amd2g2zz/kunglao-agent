# -*- coding: utf-8 -*-
"""tests/test_upgrade_iron_log_764.py — the iron rule must tolerate live
appends to the kunglao event log (issue #764).

The upgrade runs inside a live session: between the pre and post digest,
the parent session's hooks append telemetry rows (their own actors) to
today's runs/logs/kunglao-*.jsonl. The pre-#764 whole-sha verdict read
any such append as "user data moved" and rolled the whole workspace
back. The contract is append-tolerance: the pre-side filtered lines
must be an order-preserving prefix of the post-side filtered lines;
rewrites, reorders, and deletions of protected lines still violate.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

UGRADE_PATH = SCRIPTS / "kunglao_upgrade.py"


def _load_upgrade():
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade", UGRADE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def up():
    return _load_upgrade()


def _log_row(actor: str, action: str) -> str:
    return json.dumps({"actor": actor, "action": action, "detail": "syn"})


def _ws_with_log(tmp_path: Path, rows: list[str]) -> Path:
    ws = tmp_path / "ws"
    log_dir = ws / "runs" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "kunglao-2026-10-18.jsonl").write_text(
        "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    return ws


def _append(ws: Path, row: str) -> None:
    log = ws / "runs" / "logs" / "kunglao-2026-10-18.jsonl"
    with log.open("a", encoding="utf-8") as f:
        f.write(row + "\n")


def test_foreign_actor_append_passes_window(up, tmp_path):
    ws = _ws_with_log(tmp_path,
                      [_log_row("orchestrator", "analysis_started")])
    pre_logs: dict = {}
    pre = up.user_data_digest(ws, log_lines_out=pre_logs)
    _append(ws, _log_row("hook:bash_fact_guard", "guard_tripped"))
    post = up.user_data_digest(ws)
    assert pre != post, "the append must change the naive digest"
    assert up._iron_violations(pre, post, pre_logs, ws) == []


def test_rewrite_of_existing_line_still_violates(up, tmp_path):
    ws = _ws_with_log(tmp_path,
                      [_log_row("orchestrator", "analysis_started"),
                       _log_row("operator", "note")])
    pre_logs: dict = {}
    pre = up.user_data_digest(ws, log_lines_out=pre_logs)
    log = ws / "runs" / "logs" / "kunglao-2026-10-18.jsonl"
    lines = log.read_text(encoding="utf-8").splitlines()
    lines[0] = _log_row("orchestrator", "REWRITTEN")
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    post = up.user_data_digest(ws)
    assert up._iron_violations(pre, post, pre_logs, ws) != []


def test_window_created_log_passes(up, tmp_path):
    ws = _ws_with_log(tmp_path, [])
    (ws / "runs" / "logs" / "kunglao-2026-10-18.jsonl").unlink()
    pre_logs: dict = {}
    pre = up.user_data_digest(ws, log_lines_out=pre_logs)
    assert pre == {}
    log = ws / "runs" / "logs" / "kunglao-2026-10-18.jsonl"
    log.write_text(_log_row("orchestrator", "first_row") + "\n",
                   encoding="utf-8")
    post = up.user_data_digest(ws)
    assert post
    assert up._iron_violations(pre, post, pre_logs, ws) == []


def test_window_deleted_log_violates(up, tmp_path):
    ws = _ws_with_log(tmp_path,
                      [_log_row("orchestrator", "analysis_started")])
    pre_logs: dict = {}
    pre = up.user_data_digest(ws, log_lines_out=pre_logs)
    (ws / "runs" / "logs" / "kunglao-2026-10-18.jsonl").unlink()
    post = up.user_data_digest(ws)
    assert up._iron_violations(pre, post, pre_logs, ws) != []


def test_non_log_change_still_violates(up, tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "F001.md").write_text("fact body\n", encoding="utf-8")
    pre = up.user_data_digest(ws)
    (ws / "facts" / "F001.md").write_text("rewritten body\n",
                                          encoding="utf-8")
    post = up.user_data_digest(ws)
    assert pre != post
    assert up._iron_violations(pre, post, {}, ws) == ["facts/F001.md"]


def test_capture_cap_falls_back_to_strict(up, tmp_path, monkeypatch):
    ws = _ws_with_log(tmp_path,
                      [_log_row("orchestrator", "analysis_started")])
    monkeypatch.setattr(up, "LOG_CAPTURE_MAX_BYTES", 4)
    pre_logs: dict = {}
    pre = up.user_data_digest(ws, log_lines_out=pre_logs)
    rel = "runs/logs/kunglao-2026-10-18.jsonl"
    assert pre_logs[rel] is None, "over-cap capture must store None"
    _append(ws, _log_row("orchestrator", "appended"))
    post = up.user_data_digest(ws)
    assert up._iron_violations(pre, post, pre_logs, ws) != []


def test_filter_spares_only_upgrade_and_renew(up):
    rows = [_log_row("kunglao_upgrade", "upgrade"),
            _log_row("orchestrator", "renew"),
            _log_row("orchestrator", "analysis_started"),
            _log_row("hook:completion_gate", "settle"),
            "not-json-garbage"]
    kept = up._filtered_log_lines(("\n".join(rows) + "\n").encode("utf-8"))
    assert kept == [rows[2], rows[3], rows[4]], (
        "only actor=kunglao_upgrade and action=renew lines are dropped")


def test_full_upgrade_survives_a_live_today_log(up, tmp_path, monkeypatch):
    from test_kunglao_upgrade_726 import synth_v012_ws
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    ws = synth_v012_ws(tmp_path)
    log_dir = ws / "runs" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "kunglao-2026-10-18.jsonl").write_text(
        _log_row("orchestrator", "analysis_started") + "\n",
        encoding="utf-8")
    assert up.main([str(ws)]) == 0, (
        "live telemetry rows in today's log must not abort the upgrade")
