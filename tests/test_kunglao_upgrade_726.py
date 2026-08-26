#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_kunglao_upgrade_726.py — workspace scaffold upgrade (#726).

Synthesizes a v0.1.2-shaped workspace in tmp_path (old stamp, 9-hook
settings, .hook_state.json missing completion_gate, user data) and pins the
upgrade contract: five declarative repair items, byte-invariant user data
(stamp-line normalized), dry-run zero-write, idempotence, unknown-version
refusal, snapshot + kunglao_log events, and the iron-rule guard.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import template_version  # noqa: E402
from event_taxonomy import EMIT_ACTIONS  # noqa: E402

UGRADE_PATH = SCRIPTS / "kunglao_upgrade.py"


def _load_upgrade():
    spec = importlib.util.spec_from_file_location("kunglao_upgrade", UGRADE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stamp_line(v: str) -> str:
    return f"# {template_version.STAMP_KEY}: {v}"


# Old-shape hook set: v0.1.2's 9 hooks (no orchestrator_tool_guard /
# violation_capture — those are v0.1.3 additions).
V012_HOOKS = [
    "env_check_gate.py", "worker_budget.py", "dispatch_gate.py",
    "recall_inject.py", "heartbeat_touch.py", "worker_pulse.py",
    "state_anchor.py", "completion_gate.py", "write_guard.py",
]


def synth_v012_ws(tmp: Path) -> Path:
    """A minimal v0.1.2-shaped workspace. Everything under tmp_path."""
    ws = tmp / "ws"
    ws.mkdir()
    # stamp carriers @0.1.2
    (ws / "CLAUDE.md").write_text(
        _stamp_line("0.1.2") + "\n\n# old workspace\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        _stamp_line("0.1.2") + "\n# facts\nF001 | PROVEN | C-1 | keep me\n",
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        _stamp_line("0.1.2") + "\nclaims: []\n# [initialized] 2026-08-01\n",
        encoding="utf-8")
    # user data across all seven iron-rule dirs
    for d, f, body in [
        ("claims", "C-001.md", "claim body"), ("facts", "F001.md", "fact body"),
        ("runs", "worker-status-C001.txt", "status line"),
        ("hypotheses", "H-001.md", "hyp body"), ("notes", "N-1.md", "note"),
        ("evidence", "e.txt", "ev"), ("oracle", "o.txt", "or"),
    ]:
        p = ws / d
        p.mkdir(exist_ok=True)
        (p / f).write_text(body, encoding="utf-8")
    # old 9-hook settings (v0.1.2 shape)
    settings = {"hooks": {"PreToolUse": [{"type": "command",
                 "command": f"python {h}"} for h in V012_HOOKS]}}
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8")
    # .hook_state.json WITHOUT completion_gate (the #717 L1 disease)
    (ws / ".hook_state.json").write_text(json.dumps({
        "phase": "IDLE", "state": "active",
        "active_hooks": ["active_intervention"],
        "paused_hooks": [], "user_override": {},
    }), encoding="utf-8")
    return ws


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def up():
    return _load_upgrade()


# ---------------------------------------------------------------- tests

def test_vocab_has_upgrade_actions():
    assert "upgrade" in EMIT_ACTIONS
    assert "upgrade_item" in EMIT_ACTIONS
    assert "git_snapshot_skipped" in EMIT_ACTIONS  # #739 WARN face


def test_old_workspace_is_repaired(up, tmp_path):
    ws = synth_v012_ws(tmp_path)
    rc = up.main([str(ws)])
    assert rc == 0, "upgrade of a v0.1.2 workspace must succeed"
    # hooks re-registered to the full current registry
    settings = json.loads((ws / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    blob = json.dumps(settings)
    assert "violation_capture.py" in blob
    assert "orchestrator_tool_guard.py" in blob
    # ALWAYS_ARMED repaired
    state = json.loads((ws / ".hook_state.json").read_text(encoding="utf-8"))
    assert "completion_gate" in state.get("active_hooks", [])
    # #758 G4 — the synthesized body ("# old workspace", hand-written) is
    # NOT the template frame; refreshing its stamp would be the lying class
    # (#758 root cause 2: fresh stamp over stale body amplified #717). All
    # three carriers keep their honest v0.1.2 stamp until Wave-2 G3's
    # collect-and-merge brings the body forward.
    cur = template_version.read_skill_version()
    for rel in ("CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"):
        text = (ws / rel).read_text(encoding="utf-8")
        assert f"{template_version.STAMP_KEY}: 0.1.2" in text, rel
        assert f"{template_version.STAMP_KEY}: {cur}" not in text, rel
    # init-report upgrade record
    report = json.loads((ws / "runs" / ".init-report.json")
                        .read_text(encoding="utf-8"))
    hist = report.get("upgrade_history", [])
    assert hist and hist[-1].get("to") == cur
    # .agent metadata seeded
    assert (ws / ".agent" / "specs.yaml").is_file()


def test_user_data_byte_invariant(up, tmp_path):
    ws = synth_v012_ws(tmp_path)
    pre = up.user_data_digest(ws)
    assert up.main([str(ws)]) == 0
    assert up.user_data_digest(ws) == pre, "iron rule: user data must not move"


def test_dry_run_writes_nothing(up, tmp_path):
    ws = synth_v012_ws(tmp_path)
    before = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    rc = up.main([str(ws), "--dry-run"])
    assert rc == 0
    after = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    assert before == after, "dry-run must not write a single byte"
    assert not list((ws / "runs").glob("upgrade-snapshot.*")), \
        "dry-run must not write a snapshot"


def test_dry_run_prints_plan(up, tmp_path, capsys):
    ws = synth_v012_ws(tmp_path)
    up.main([str(ws), "--dry-run"])
    out = capsys.readouterr().out
    assert "0.1.3" in out
    assert "hooks_rewire" in out


def test_already_current_is_noop(up, tmp_path, capsys):
    """#755 T6 note: this pins the DRIVER fast-path print. The registry now
    keeps patch entries above the release stamp reachable ("0.1.4"), so a
    stamped-cur workspace plans migrations by design; isolating the
    fast-path contract with an empty registry is the honest unit here."""
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws)]) == 0
    cur = template_version.read_skill_version()
    (ws / "CLAUDE.md").write_text(
        _stamp_line(cur) + "\n# fresh\n", encoding="utf-8")
    saved, up.MIGRATIONS = up.MIGRATIONS, []
    try:
        rc = up.main([str(ws)])
    finally:
        up.MIGRATIONS = saved
    assert rc == 0
    assert "already" in capsys.readouterr().out.lower()


def test_unknown_version_refused(up, tmp_path, capsys):
    ws = synth_v012_ws(tmp_path)
    (ws / "CLAUDE.md").write_text("# no stamp here\n", encoding="utf-8")
    rc = up.main([str(ws)])
    assert rc == 3
    combined = capsys.readouterr()
    assert "init" in (combined.out + combined.err).lower()


def test_snapshot_written(up, tmp_path):
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws)]) == 0
    snaps = list((ws / "runs").glob("upgrade-snapshot.*.json"))
    assert len(snaps) == 1
    data = json.loads(snaps[0].read_text(encoding="utf-8"))
    assert "CLAUDE.md" in data


def test_events_emitted(up, tmp_path):
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws)]) == 0
    actions: list[str] = []
    for log in (ws / "runs" / "logs").glob("kunglao-*.jsonl"):
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                actions.append(json.loads(line).get("action"))
    assert "upgrade" in actions
    assert actions.count("upgrade_item") >= 5


def test_iron_rule_guard_selftest(up, tmp_path, capsys):
    """The guard itself is under test: a migration that touches user data
    must flip the exit code to 4 (fail loudly, keep the snapshot)."""
    ws = synth_v012_ws(tmp_path)

    def evil(ws: Path, dry: bool):
        if not dry:
            (ws / "facts" / "F001.md").write_text(
                "tampered", encoding="utf-8")
        return ["evil_touch"]

    up.MIGRATIONS = [("9.9.9", evil)]
    rc = up.main([str(ws)])
    assert rc == 4, "user-data mutation under upgrade must exit 4"
    assert list((ws / "runs").glob("upgrade-snapshot.*.json")), \
        "snapshot must survive an iron-rule failure"


# ------------------------------------------------------------- #739 git snapshot

def _git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *args],
                          capture_output=True, text=True)


def test_no_git_workspace_gets_git_snapshot(up, tmp_path, capsys):
    """#739 + #753 — a legacy no-git workspace is anchored BEFORE migration:
    the FIRST commit is the pre-upgrade anchor, the hygiene .gitignore is in
    place, and the usage banner (log / revert / checkout -b exp) prints. The
    migrated state lands as the second (post-upgrade state) commit."""
    ws = synth_v012_ws(tmp_path)
    assert not (ws / ".git").exists()
    assert up.main([str(ws)]) == 0
    assert (ws / ".git").is_dir()
    subjects = [s for s in _git(ws, "log", "--format=%s").stdout.splitlines()
                if s.strip()]
    assert len(subjects) == 2
    # git log is newest-first: [0] = post-upgrade state, [-1] = the anchor
    assert "pre-upgrade anchor" in subjects[-1]
    assert "post-upgrade state" in subjects[0]
    gi = (ws / ".gitignore").read_text(encoding="utf-8")
    for pat in ("bins/", "__pycache__/", "*.pyc", "*.log", "runs/"):
        assert pat in gi, pat
    out = capsys.readouterr().out
    assert "git -C" in out
    assert "log --oneline" in out
    assert "revert --no-edit" in out
    assert "checkout -b exp" in out
    assert "ground truth" in out, "banner must mark git as snapshot-only"


def test_existing_git_repo_is_left_alone(up, tmp_path):
    """#739 — an existing repo is never re-initialized: no snapshot commit
    is layered on top, no .gitignore is written into it."""
    ws = synth_v012_ws(tmp_path)
    for args in (("init",), ("add", "-A"),
                 ("-c", "user.name=t", "-c", "user.email=t@localhost",
                  "commit", "--no-gpg-sign", "-m", "pre-existing")):
        _git(ws, *args)
    assert up.main([str(ws)]) == 0
    assert _git(ws, "log", "--format=%s").stdout.splitlines() == \
        ["pre-existing"]
    assert up.ensure_git_snapshot(ws) == {"status": "existing"}
    assert not (ws / ".gitignore").exists()


def test_git_missing_warns_but_upgrade_succeeds(
        up, tmp_path, capsys, monkeypatch):
    """#739 — git binary missing: one-line WARN to stderr +
    git_snapshot_skipped event, no .git — and the upgrade rc stays 0."""
    ws = synth_v012_ws(tmp_path)

    def no_git(*_a, **_k):
        raise FileNotFoundError("git binary not found")

    monkeypatch.setattr(up, "_run_git", no_git)
    assert up.main([str(ws)]) == 0
    assert not (ws / ".git").exists()
    captured = capsys.readouterr()
    assert "WARN" in captured.err
    assert "git" in captured.err
    actions = [json.loads(line).get("action")
               for log in (ws / "runs" / "logs").glob("kunglao-*.jsonl")
               for line in log.read_text(encoding="utf-8").splitlines()
               if line.strip()]
    assert "git_snapshot_skipped" in actions


def test_dry_run_leaves_no_git(up, tmp_path):
    """#739 — dry-run produces no write side effects: neither .git nor
    .gitignore may appear."""
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws), "--dry-run"]) == 0
    assert not (ws / ".git").exists()
    assert not (ws / ".gitignore").exists()
