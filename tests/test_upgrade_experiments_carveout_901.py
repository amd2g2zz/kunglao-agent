#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Upgrade purge carve-out: experiments/** is never unknown scaffolding
(issue 901).

The rl-v2 learning system lives under experiments/learning-loop/ in the
source repo — deliberately OUTSIDE the deploy manifest ("experiments are
local-only, never deployed"). The upgrade transaction's prune step
removes every manifest-unknown file in the deployed trees; without the
experiments carve-out a workspace-local experiments tree staged under a
deployed root is indistinguishable from superseded scaffolding and gets
deleted. Three pins:

  1. the transaction prune (deployed_refresh.prune_outright) never
     removes a path carrying an experiments segment, wherever the scan
     meets it — and still removes genuine manifest-unknown junk;
  2. the standalone refresh face (backup-then-remove) obeys the same
     carve-out;
  3. a full legacy-workspace upgrade ends with the experiments tree and
     the loop ledger byte-intact (the ledger is loop-owned substrate —
     init never seeds it, upgrade never sweeps it).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import template_version as tv  # noqa: E402
from _factories import stamp_current, write_hook_state  # noqa: E402

UPGRADE_PATH = SCRIPTS / "kunglao_upgrade.py"

CUR = tv.read_skill_version()
OLDER = "0.1.4"

#: the loop faces' repo shape, copied verbatim into the workspace-local
#: trees the purge must learn to respect
LOOP_FILES = (
    ("loop.py", "# the unified decision loop face\n"),
    ("state/belief.py", "# the belief aggregation face\n"),
    ("policy/terminator.py", "# the dynamic step-count face\n"),
)
LEDGER_ROW = '{"schema": "rollout-row", "note": "loop-owned substrate"}\n'


def _load_upgrade():
    spec = importlib.util.spec_from_file_location("kunglao_upgrade_exp901",
                                                  UPGRADE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _isolated_upgrade_home(tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("KUNGLAO_UPGRADE_NO_UV_SYNC", "1")
    return home


def _write_loop_trees(ws: Path) -> dict[Path, bytes]:
    """Both experiments shapes a target workspace can carry: the repo-
    clone root tree and a staging copy under a deployed root (inside the
    scan's manifest-dest-parent reach) — plus the loop-owned ledger under
    runs/. Returns {path: expected bytes} for the survive-pins."""
    out: dict[Path, bytes] = {}
    for base in (ws / "experiments" / "learning-loop",
                 ws / ".claude" / "scripts" / "experiments"
                 / "learning-loop"):
        for rel, body in LOOP_FILES:
            p = base / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            out[p] = p.read_bytes()
    ledger = ws / "runs" / "experience.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(LEDGER_ROW, encoding="utf-8")
    out[ledger] = LEDGER_ROW.encode("utf-8")
    return out


def _write_junk(ws: Path) -> Path:
    junk = ws / ".claude" / "templates" / "state" / "superseded-v04.md"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_text("# superseded scaffolding\n", encoding="utf-8")
    return junk


# --------------------------------------------------------------------------
# 1. the transaction prune face (prune_outright)
# --------------------------------------------------------------------------

def test_prune_never_sweeps_experiments_trees(tmp_path):
    import deployed_refresh as dr
    ws = tmp_path / "ws"
    ws.mkdir()
    expected = _write_loop_trees(ws)
    junk = _write_junk(ws)
    removed = dr.prune_outright(ws)
    assert all(p.exists() for p in expected), \
        "the purge deleted the learning system's local tree"
    for p, want in expected.items():
        assert p.read_bytes() == want, str(p)
    assert not junk.exists(), "genuine manifest-unknown junk must still go"
    assert removed == [junk.relative_to(ws).as_posix()], removed


# --------------------------------------------------------------------------
# 2. the standalone refresh face (backup-then-remove)
# --------------------------------------------------------------------------

def test_refresh_orphan_guard_respects_the_carve_out(tmp_path, monkeypatch):
    import deployed_refresh as dr
    ws = tmp_path / "ws"
    ws.mkdir()
    expected = _write_loop_trees(ws)
    junk = _write_junk(ws)
    detail = dr.refresh(ws)
    assert all(p.exists() for p in expected), \
        "the refresh orphan guard deleted the learning system's local tree"
    for p, want in expected.items():
        assert p.read_bytes() == want, str(p)
    assert not junk.exists()
    backup = ws / "runs" / "deploy-backup-orphan"
    assert any(backup.rglob("superseded-v04.md")), detail


# --------------------------------------------------------------------------
# 3. the full upgrade transaction over a legacy workspace
# --------------------------------------------------------------------------

def _synth_legacy_ws(tmp: Path) -> Path:
    """A 0.1.4-stamped workspace carrying the experiments tree + the loop
    ledger (adapted from the sweep fixture in
    test_upgrade_016_sweep.py — the proven minimal shape the upgrade
    transaction accepts end-to-end)."""
    import hook_activation as ha
    import claudemd_frame
    u = _load_upgrade()
    ws = tmp / "ws"
    ws.mkdir(parents=True)
    stamp_line = f"# {tv.STAMP_KEY}: {OLDER}"
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        stamp_line + "\n# facts\nF001 | PROVEN | C-1 | keep me\n",
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        stamp_line + "\nclaims: []\n# [initialized] 2026-08-01\n",
        encoding="utf-8")
    frame = claudemd_frame.wrap_frame(
        u._build_current_frame(ws, "# old\n", None))
    (ws / "CLAUDE.md").write_text(
        stamp_line + "\n" + frame, encoding="utf-8")
    for d, f, body in [
        ("claims", "C-001.md", "claim body"), ("facts", "F001.md", "fact body"),
        ("runs", "worker-status-C001.txt", "status line"),
        ("hypotheses", "H-001.md", "hyp body"), ("notes", "N-1.md", "note"),
        ("evidence", "e.txt", "ev"), ("oracle", "o.txt", "or"),
    ]:
        p = ws / d
        p.mkdir(exist_ok=True)
        (p / f).write_text(body, encoding="utf-8")
    expected = _write_loop_trees(ws)
    junk = _write_junk(ws)
    ha.deploy_workspace_copy(ws)
    settings = {"hooks": {"PreToolUse": [
        {"type": "command",
         "command": f"python {SCRIPTS.name}/{h}"} for h in (
             "env_check_gate.py", "worker_budget.py")]}}
    (ws / ".claude").mkdir(exist_ok=True)
    (ws / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8")
    ha.register_statusline(ws)
    write_hook_state(ws, active_hooks=["active_intervention"],
                     phase="IDLE", user_override={},
                     extra={"state": "active"})
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: legacy goal\n"
        "success_criterion: legacy criterion\n"
        "verification_method: manual\n", encoding="utf-8")
    (ws / "env-manifest.yaml").write_text(
        "generated: 2026-09-01T00:00:00Z\n"
        f"project_type: windows\nkunglao_version: {OLDER}\n"
        "components: []\n", encoding="utf-8")
    (ws / "runs" / ".init-report.json").write_text(
        json.dumps({"skill_version": OLDER}), encoding="utf-8")
    return ws, expected, junk


def test_upgrade_survives_the_experiments_tree_end_to_end(tmp_path):
    u = _load_upgrade()
    ws, expected, junk = _synth_legacy_ws(tmp_path)
    assert u.main([str(ws)]) == 0
    assert all(p.exists() for p in expected), \
        "the upgrade swept the learning system's tree or ledger"
    for p, want in expected.items():
        assert p.read_bytes() == want, str(p)
    assert not junk.exists(), "manifest-unknown junk must still be pruned"
    # the version carry still ran (the carve-out is not a skip-everything)
    assert (ws / "env-manifest.yaml").read_text(encoding="utf-8") \
        .count(f"kunglao_version: {CUR}") == 1


def test_experiments_survival_is_byte_identity_not_recreation(tmp_path):
    """The carve-out is passive: upgrade neither reads nor rewrites the
    loop files — their bytes and mtimes are exactly the operator's."""
    import os
    u = _load_upgrade()
    ws, expected, _junk = _synth_legacy_ws(tmp_path)
    before = {p: (p.read_bytes(), os.stat(p).st_mtime_ns)
              for p in expected}
    assert u.main([str(ws)]) == 0
    for p, (want_bytes, want_mtime) in before.items():
        assert p.read_bytes() == want_bytes, str(p)
        assert os.stat(p).st_mtime_ns == want_mtime, \
            f"touched: {p}"
