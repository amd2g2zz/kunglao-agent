#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_upgrade_safety_753.py — upgrade 执行序安全 (issue #753).

User ruling (2026-08-27): "升级前要先检测 git 检测未提交，然后 commit 之后再执行
upgrade，不然坏掉了都无法回滚". Pins:

  B1  git-first snapshot — the migration path commits the workspace state
      (dirty included) AS the pre-migration snapshot; repo-less workspaces
      get git init + snapshot first; the migrated state lands as the
      second commit so `git revert HEAD` restores the snapshot. (0.1.6
      sweep: the RC 6 dirty refusal survives only on the already-current
      early-exit refresh.)
  B2  structured stderr events `[event] name=<n> status=<s> detail=<d>` at
      every critical node (landed with the emitter wiring).
  B3  /reload-plugins hint on the success path (upgrade + init tail).
  B4  tail atomicity — a lost summary event yields RC_INCOMPLETE=7 AND the
      0.1.6 transactional rollback (byte-identical pre-upgrade tree).
"""
from __future__ import annotations

import importlib.util
import json
import re
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
from _factories import write_hook_state

UPGRADE_PATH = SCRIPTS / "kunglao_upgrade.py"
INIT_PATH = SCRIPTS / "kunglao-init.py"

EVENT_RE = re.compile(
    r"^\[event\] name=(?P<name>\S+) "
    r"status=(?P<status>ok|warn|fail)"
    r"(?: detail=(?P<detail>.*))?$")

IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@localhost")


# ---------------------------------------------------------------- #143 home isolation
# The upgrade now purges the user-global ~/.claude/settings.json (#143 item).
# Every real-run upgrade test in this file binds Path.home to a bare tmp home
# (the established monkeypatch seam, canonical_install_root precedent) plus
# HOME/USERPROFILE for subprocess children, so a pytest run can never purge
# the production global file — same protection class as conftest.isolated_home.


@pytest.fixture(autouse=True)
def _isolated_upgrade_home(tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _load_upgrade():
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade_753", UPGRADE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stamp_line(v: str) -> str:
    return f"# {template_version.STAMP_KEY}: {v}"


V012_HOOKS = [
    "env_check_gate.py", "worker_budget.py", "dispatch_gate.py",
    "recall_inject.py", "heartbeat_touch.py", "worker_pulse.py",
    "state_anchor.py", "completion_gate.py", "write_guard.py",
]


def synth_v012_ws(tmp: Path) -> Path:
    """Minimal v0.1.2-shaped workspace (same synthesis contract as #726)."""
    ws = tmp / "ws"
    ws.mkdir(parents=True)
    (ws / "CLAUDE.md").write_text(
        _stamp_line("0.1.2") + "\n\n# old workspace\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        _stamp_line("0.1.2") + "\n# facts\nF001 | PROVEN | C-1 | keep me\n",
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        _stamp_line("0.1.2") + "\nclaims: []\n# [initialized] 2026-08-01\n",
        encoding="utf-8")
    for d, f, body in [
        ("claims", "C-001.md", "claim body"), ("facts", "F001.md", "fact body"),
        ("runs", "worker-status-C001.txt", "status line"),
        ("hypotheses", "H-001.md", "hyp body"), ("notes", "N-1.md", "note"),
        ("evidence", "e.txt", "ev"), ("oracle", "o.txt", "or"),
    ]:
        p = ws / d
        p.mkdir(exist_ok=True)
        (p / f).write_text(body, encoding="utf-8")
    settings = {"hooks": {"PreToolUse": [
        {"type": "command", "command": f"python {h}"} for h in V012_HOOKS]}}
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8")
    write_hook_state(ws, active_hooks=["active_intervention"],
                     phase="IDLE", user_override={},
                     extra={"state": "active"})
    # the three required intake answers (present: the tests below pin
    # migration semantics, not the anchor interview)
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: legacy goal\n"
        "success_criterion: legacy criterion\n"
        "verification_method: manual\n", encoding="utf-8")
    return ws


def _git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *IDENTITY, *args],
                          capture_output=True, text=True)


def _subjects(ws: Path) -> list[str]:
    out = []
    for line in _git(ws, "log", "--format=%s").stdout.splitlines():
        if line.strip():
            out.append(line)
    return out


def _events(err: str) -> list[dict]:
    evs = []
    for line in err.splitlines():
        m = EVENT_RE.match(line.strip())
        if m:
            evs.append(m.groupdict())
    return evs


def _joined_source(path: Path) -> str:
    """Source text with adjacent string-literal line continuations merged,
    so runtime phrases that are wrapped for line length stay searchable."""
    return re.sub(r'"\s*\n\s*"', "", path.read_text(encoding="utf-8"))


@pytest.fixture
def up():
    return _load_upgrade()


# ------------------------------------------------------------------ B1 tests

def test_dirty_owned_repo_snapshot_committed(up, tmp_path, capsys):
    """Transactional migration (0.1.6 sweep): an uncommitted owned repo is
    no longer refused — its state is committed AS the pre-migration git
    snapshot (the rollback point), then the migration runs. The old RC 6
    refusal survives only on the already-current early-exit refresh."""
    ws = synth_v012_ws(tmp_path)
    for args in (("init",), ("add", "-A"), ("commit", "--no-gpg-sign",
                                             "-m", "pre-existing")):
        assert _git(ws, *args).returncode == 0
    # make the tree dirty AFTER the baseline commit
    (ws / "CLAUDE.md").write_text(
        _stamp_line("0.1.2") + "\nuncommitted local edit\n", encoding="utf-8")
    rc = up.main([str(ws)])
    assert rc == 0, "dirty state must be snapshot-committed, never refused"
    subs = _subjects(ws)
    # newest-first: success commit, snapshot commit, the operator's baseline
    assert "kunglao upgrade: 0.1.2 ->" in subs[0], subs
    assert "kunglao upgrade snapshot: pre" in subs[1], subs
    assert subs[-1] == "pre-existing", subs
    sha = _git(ws, "log", "--format=%H", "--grep",
               "kunglao upgrade snapshot: pre", "--fixed-strings",
               "-1").stdout.strip()
    show = _git(ws, "show", "--name-only", "--format=", sha)
    assert "CLAUDE.md" in show.stdout, \
        "the uncommitted edit must ride INSIDE the snapshot commit"


def test_no_git_workspace_anchored_before_migration(up, tmp_path):
    """Legacy no-git workspace: upgrade leaves .git whose FIRST commit is the
    pre-upgrade snapshot; the migrated state rides on top as the second
    commit; reverting it restores the exact pre-upgrade scaffold."""
    ws = synth_v012_ws(tmp_path)
    assert not (ws / ".git").exists()
    assert up.main([str(ws)]) == 0
    assert (ws / ".git").exists()
    subs = _subjects(ws)
    assert len(subs) == 2, subs
    # `git log` is newest-first: the migrated state sits on top, the
    # chronologically-FIRST commit (the snapshot) is last in the listing
    assert "kunglao upgrade: 0.1.2 ->" in subs[0], subs
    assert "kunglao upgrade snapshot: pre" in subs[-1], subs
    rev = _git(ws, "revert", "--no-edit", "HEAD")
    assert rev.returncode == 0, rev.stderr
    claudemd = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert _stamp_line("0.1.2") in claudemd
    settings = json.loads((ws / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    assert "violation_capture.py" not in json.dumps(settings)
    # user data never moved anywhere
    assert (ws / "facts" / "F001.md").read_text(encoding="utf-8") == "fact body"


def test_re_run_after_anchor_stays_clean(up, tmp_path):
    """A follow-up upgrade never trips RC_DIRTY_WORKSPACE and never stacks
    another SNAPSHOT commit: the second run starts from a clean tree, so
    HEAD (the first run's success commit) is its snapshot and only the
    renewed framework state (TTL timestamps etc.) lands as a fresh success
    commit — honest history, no refusal, no snapshot spam."""
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws)]) == 0
    subs = _subjects(ws)
    assert up.main([str(ws)]) == 0
    subs2 = _subjects(ws)
    assert subs2[:2] == [subs[0], subs[0]], \
        "run 2 may land a success commit but must reuse run 1's history"
    # exactly ONE snapshot commit across both runs (run 2 started clean)
    assert sum(1 for s in subs2
               if "kunglao upgrade snapshot: pre" in s) == 1, subs2


def test_dry_run_still_never_touches_git(up, tmp_path):
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws), "--dry-run"]) == 0
    assert not (ws / ".git").exists()
    assert not (ws / ".gitignore").exists()


def test_unknown_origin_refused_before_anything(up, tmp_path):
    """rc=3 unstamped refusal precedes the git gate entirely — no .git is
    spawned for a workspace we refuse to understand."""
    ws = synth_v012_ws(tmp_path)
    (ws / "CLAUDE.md").write_text("# no stamp here\n", encoding="utf-8")
    assert up.main([str(ws)]) == 3
    assert not (ws / ".git").exists()


def test_anchor_skip_word_registered():
    """A skipped anchor gets its own audit vocabulary next to #739's skip."""
    assert "git_anchor_skipped" in EMIT_ACTIONS


# ------------------------------------------------------------------ B2 tests

def test_success_stderr_has_structured_event_trail(up, tmp_path, capsys):
    """Every critical node leaves exactly one flushed `[event]` line on
    stderr; the human-readable summary stays on stdout."""
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws)]) == 0
    captured = capsys.readouterr()
    evs = _events(captured.err)
    assert len(evs) >= 6, f"need >=6 structured events, got {len(evs)}"
    names = [e["name"] for e in evs]
    for node in ("migration-start", "item", "iron-rule", "stamp", "summary",
                 "git-snapshot"):
        assert node in names, f"missing node {node}: {names}"
    order = {n: i for i, n in enumerate(names)}
    assert order["stamp"] < order["summary"], "summary trails the stamp"
    # stdout stays the human-readable channel
    assert "kunglao-upgrade: 0.1.2 ->" in captured.out
    assert "[event]" not in captured.out, "events belong on stderr only"


def test_interrupted_item_rolls_back_and_keeps_last_event(up, tmp_path,
                                                          capsys):
    """Kill simulation A: a migration item explodes mid-flight. The git
    snapshot must already exist, the tree is ROLLED BACK to it (0.1.6
    transactional requirement), and the stderr trail ends at the exact
    last completed node — no fake completion events after the crash."""
    ws = synth_v012_ws(tmp_path)
    pre_claudemd = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    pre_settings = (ws / ".claude" / "settings.json").read_bytes()

    def exploding(ws: Path, dry: bool):
        raise RuntimeError("simulated kill mid-migration")

    up.MIGRATIONS = [("9.9.9", exploding)]
    rc = up.main([str(ws)])
    assert rc == 7, "a raised item maps to RC_INCOMPLETE with rollback"
    assert (ws / ".git").exists(), "snapshot must exist before items ever run"
    subs = _subjects(ws)
    assert len(subs) == 1, "no success commit after a rolled-back run"
    assert "kunglao upgrade snapshot: pre" in subs[-1], subs
    # rollback restored the pre-migration framework scaffold
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == pre_claudemd
    assert (ws / ".claude" / "settings.json").read_bytes() == pre_settings
    evs = _events(capsys.readouterr().err)
    names = [e["name"] for e in evs]
    assert "migration-start" in names, f"start marker missing: {names}"
    assert "rollback" in names, "the rollback must leave its own event"
    assert "stamp" not in names and "summary" not in names


# ------------------------------------------------------------------ B3 tests

def test_success_prints_reload_plugins_hint(up, tmp_path, capsys):
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws)]) == 0
    out = capsys.readouterr().out
    assert "/reload-plugins" in out
    assert "run /reload-plugins in Claude Code to activate" in out


def test_already_current_prints_no_reload_hint(up, tmp_path, capsys):
    """The package did not move on an already-current workspace — telling the
    user to reload would be noise."""
    ws = synth_v012_ws(tmp_path)
    cur = template_version.read_skill_version()
    (ws / "CLAUDE.md").write_text(_stamp_line(cur) + "\n", encoding="utf-8")
    (ws / "facts" / "_INDEX.md").write_text(
        _stamp_line(cur) + "\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        _stamp_line(cur) + "\n", encoding="utf-8")
    # Natural behavior since the carry became the planner's universal tail:
    # an already-current workspace plans nothing (no registry isolation).
    assert up.main([str(ws)]) == 0
    out = capsys.readouterr().out
    assert "already" in out.lower()
    assert "/reload-plugins" not in out


def test_init_success_tail_carries_same_hint():
    """kunglao-init.py prints the same activation hint on its fresh-init
    success tail (inside the #461 heartbeat-bootstrap function body)."""
    text = _joined_source(INIT_PATH)
    marker = "# #461: heartbeat bootstrap — LAST step of the init success path"
    seg = text[text.index(marker):]
    body = seg[:seg.index("\ndef ")]
    assert "bootstrap_observability(" in body
    assert "run /reload-plugins in Claude Code to activate" in body


def test_init_reload_hint_in_claude_code_activation_form():
    text = _joined_source(INIT_PATH)
    assert "kunglao-init:" in text
    assert "run /reload-plugins in Claude Code to activate" in text


# ------------------------------------------------------------------ B4 tests

def test_lost_summary_event_yields_rc_incomplete_7(up, tmp_path, capsys,
                                                   monkeypatch):
    """Kill simulation B: the telemetry seam dies exactly where #753's
    incident died — between stamp and the `upgrade` summary event. main must
    surface RC_INCOMPLETE=7 (never a silent RC_OK) and — the 0.1.6
    transactional requirement — ROLL BACK to the snapshot: the workspace
    ends byte-identical to pre-upgrade, re-run starts clean."""
    ws = synth_v012_ws(tmp_path)
    pre_settings = (ws / ".claude" / "settings.json").read_bytes()

    def seam_kill(_ws, action, _detail):
        if action == "upgrade":
            raise RuntimeError("telemetry seam killed")

    monkeypatch.setattr(up, "_emit", seam_kill)
    rc = up.main([str(ws)])
    assert rc == 7, "lost summary must map to RC_INCOMPLETE"
    evs = _events(capsys.readouterr().err)
    names = [e["name"] for e in evs]
    assert "stamp" in names and "summary" in names
    idx_stamp = len(names) - 1 - names[::-1].index("stamp")
    idx_summary = len(names) - 1 - names[::-1].index("summary")
    assert idx_stamp < idx_summary, f"trail order broken: {evs}"
    assert evs[idx_summary]["status"] == "fail"
    # transactional: the migrations did NOT survive the finish abort — the
    # rollback restored the pre-upgrade scaffold (hooks rewire reverted).
    settings = json.loads((ws / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    assert "violation_capture.py" not in json.dumps(settings)
    assert (ws / ".claude" / "settings.json").read_bytes() == pre_settings


def test_json_envelope_labels_for_new_rcs(up, tmp_path, capsys, monkeypatch):
    """rc7 -> incomplete in the --json envelope (the rc6 refused-dirty
    mapping persists for the already-current early-exit refresh face; the
    migration path itself no longer produces rc6 — see the B1 tests)."""
    ws_int = synth_v012_ws(tmp_path / "i")

    def dead(_ws, action, _detail):
        if action == "upgrade":
            raise RuntimeError("x")

    monkeypatch.setattr(up, "_emit", dead)
    assert up.main([str(ws_int), "--json"]) == 7
    env = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert env["status"] == "incomplete"
    assert env["rc"] == 7


def test_incomplete_rolls_back_not_just_skips_commit(up, tmp_path,
                                                     monkeypatch):
    """When the finish sequence dies, the transaction ROLLS BACK: the
    snapshot layer holds the snapshot alone and the tree is back to the
    pre-upgrade scaffold."""
    ws = synth_v012_ws(tmp_path)
    pre_settings = (ws / ".claude" / "settings.json").read_bytes()

    def dead(_ws, action, _detail):
        if action == "upgrade":
            raise RuntimeError("x")

    monkeypatch.setattr(up, "_emit", dead)
    assert up.main([str(ws)]) == 7
    subs = _subjects(ws)
    assert len(subs) == 1, subs
    assert "kunglao upgrade snapshot: pre" in subs[-1]
    assert (ws / ".claude" / "settings.json").read_bytes() == pre_settings
