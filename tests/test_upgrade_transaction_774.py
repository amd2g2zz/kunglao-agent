#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_upgrade_transaction_774.py — upgrade-as-transaction contract.

Pins the owner's seven-step shape on the migration path:

  step 1  git snapshot first — the rollback point precedes every mutation
  step 2  manifest-unknown deployed files REMOVED outright (git restorable)
  step 3  full manifest deployment (deploy_workspace_copy, fail-loud)
  step 4  config faces (the version migration items) + the stamp tail
  step 5  hooks_selfcheck in strict mode gates the outcome
  step 6  the success summary says a session reload is required
  step 7  any failure in steps 2-5 rolls back byte-identical to the snapshot

The selfcheck success path needs a green component table: the synthesized
workspace declares the labs project type (no HARD MCP members) and carries
a registered task oracle.
"""
from __future__ import annotations

import hashlib
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
import hooks_selfcheck  # noqa: E402
from _factories import write_hook_state  # noqa: E402

UPGRADE_PATH = SCRIPTS / "kunglao_upgrade.py"
HOOK_ACT_PATH = SCRIPTS / "hook_activation.py"

EVENT_RE = re.compile(
    r"^\[event\] name=(?P<name>\S+) "
    r"status=(?P<status>ok|warn|fail)"
    r"(?: detail=(?P<detail>.*))?$")

IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@localhost")

V012_HOOKS = [
    "env_check_gate.py", "worker_budget.py", "dispatch_gate.py",
    "recall_inject.py", "heartbeat_touch.py", "worker_pulse.py",
    "state_anchor.py", "completion_gate.py", "write_guard.py",
]


@pytest.fixture(autouse=True)
def _isolated_upgrade_home(tmp_path, monkeypatch):
    """Bind Path.home to a bare tmp home so the user-global settings purge
    and the selfcheck's user-level reads can never touch the operator's
    real home (the established upgrade-test seam)."""
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _load_upgrade():
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade_774", UPGRADE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def up():
    return _load_upgrade()


def _stamp_line(v: str) -> str:
    return f"# {template_version.STAMP_KEY}: {v}"


def synth_v012_ws(tmp: Path) -> Path:
    """Minimal v0.1.2-shaped workspace, selfcheck-green by construction:
    labs project type (no HARD MCP members) + a registered task oracle."""
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
        {"matcher": "Agent", "hooks": [
            {"type": "command", "command": f"python {h}"}]} for h in V012_HOOKS
    ]}}
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8")
    write_hook_state(ws, active_hooks=["active_intervention"],
                     phase="IDLE", user_override={},
                     extra={"state": "active"})
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: legacy goal\n"
        "success_criterion: legacy criterion\n"
        "verification_method: manual\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=web\n", encoding="utf-8")
    (ws / "task-oracle.yaml").write_text(
        "goal_verbatim: legacy goal\n", encoding="utf-8")
    return ws


def _git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *IDENTITY, *args],
                          capture_output=True, text=True)


def _subjects(ws: Path) -> list[str]:
    return [ln for ln in _git(ws, "log", "--format=%s")
            .stdout.splitlines() if ln.strip()]


def _events(err: str) -> list[dict]:
    evs = []
    for line in err.splitlines():
        m = EVENT_RE.match(line.strip())
        if m:
            evs.append(m.groupdict())
    return evs


def _tree_digest(ws: Path) -> str:
    """Recursive content digest of the workspace, excluding the git layer
    and the transaction's own bookkeeping: .git/, the git-ignored runtime
    dirs (runs/ — forensic + telemetry writes survive a rollback by
    design) and the anchor's .gitignore (written by step 1's bootstrap
    and committed INSIDE the snapshot, so the git-level truth — a clean
    status — is unaffected)."""
    h = hashlib.sha256()
    for f in sorted(ws.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(ws).as_posix()
        if (rel == ".git" or rel.startswith(".git/")
                or rel == "runs" or rel.startswith("runs/")
                or rel == ".gitignore"):
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


# ------------------------------------------------------------------ step order

def test_seven_steps_execute_in_order(up, tmp_path, capsys):
    """The transaction's critical nodes ride the stderr trail in contract
    order: snapshot -> tx-prune -> tx-deploy -> items -> tx-selfcheck ->
    summary; the reload prompt names the session reload + dormant hooks."""
    ws = synth_v012_ws(tmp_path)
    rc = up.main([str(ws)])
    assert rc == 0
    captured = capsys.readouterr()
    evs = _events(captured.err)
    names = [e["name"] for e in evs]
    seq = [n for n in names if n in
           ("snapshot", "tx-prune", "tx-deploy", "tx-selfcheck", "summary")]
    assert seq == ["snapshot", "tx-prune", "tx-deploy", "tx-selfcheck",
                   "summary"], names
    by_detail = {e["name"]: e["detail"] for e in evs}
    assert by_detail["tx-prune"].startswith("tx_prune_removed=")
    assert by_detail["tx-deploy"].startswith("tx_deploy copied=")
    out = captured.out
    assert "run /reload-plugins in Claude Code to activate" in out
    assert "RELOAD REQUIRED" in out
    assert "session reload is required" in out
    assert "dormant" in out


def test_dry_run_lists_transaction_faces(up, tmp_path, capsys):
    """The plan prints the transaction faces (prune/deploy/selfcheck) in
    execution order and writes nothing."""
    ws = synth_v012_ws(tmp_path)
    assert up.main([str(ws), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "tx_prune(dry)" in out
    assert "tx_deploy(dry)" in out
    assert "tx_selfcheck(dry)" in out
    assert out.index("tx_prune(dry)") < out.index("tx_deploy(dry)") \
        < out.index("tx_selfcheck(dry)")
    assert not (ws / ".git").exists()


# ------------------------------------------------------------------ step 2 prune

def test_prune_removes_planted_orphan_git_restorable(up, tmp_path):
    """A planted manifest-unknown file in a deployed tree is REMOVED by the
    transaction (no backup step) and stays restorable from the snapshot
    commit."""
    ws = synth_v012_ws(tmp_path)
    intruder = ws / ".claude" / "hooks" / "intruder.py"
    intruder.parent.mkdir(parents=True, exist_ok=True)
    intruder.write_text("print('not part of any manifest')\n",
                        encoding="utf-8")
    rc = up.main([str(ws)])
    assert rc == 0
    assert not intruder.exists(), "outright prune must remove the orphan"
    assert not (ws / "runs" / "deploy-backup-orphan").exists(), (
        "the transaction's REMOVE step deletes outright — the backup face "
        "is redundant under the guaranteed snapshot anchor")
    snap_sha = _git(ws, "log", "--format=%H", "--grep",
                    "kunglao upgrade snapshot: pre", "--fixed-strings",
                    "-1").stdout.strip()
    assert snap_sha
    assert _git(ws, "cat-file", "-e", f"{snap_sha}:.claude/hooks/intruder.py") \
        .returncode == 0, "the orphan must be restorable from the snapshot"


# ------------------------------------------------------------------ step 3 deploy

def test_deploy_failure_rolls_back_byte_identical(up, tmp_path, monkeypatch,
                                                  capsys):
    """A failure injected at the deploy face (step 3) rolls the tree back
    to the snapshot: byte-identical digest, clean git status, no success
    commit on top of the snapshot."""
    ws = synth_v012_ws(tmp_path)
    before = _tree_digest(ws)

    def _boom(ws_path):
        raise RuntimeError("injected deploy failure")

    monkeypatch.setattr(up, "deploy_workspace_copy", _boom)
    rc = up.main([str(ws)])
    assert rc == 7
    captured = capsys.readouterr()
    assert "injected deploy failure" in captured.err
    assert "INCOMPLETE" in captured.err
    evs = _events(captured.err)
    fails = [(e["name"], e["status"]) for e in evs]
    assert ("tx-deploy", "fail") in fails
    assert ("tx-prune", "ok") in fails
    assert ("rollback", "ok") in fails
    assert _tree_digest(ws) == before, "rollback must be byte-identical"
    status = _git(ws, "status", "--porcelain")
    assert status.stdout.strip() == "", status.stdout
    subjects = _subjects(ws)
    assert len(subjects) == 1
    assert "kunglao upgrade snapshot: pre" in subjects[0]


# ------------------------------------------------------------------ step 5 gate

def test_surviving_blocker_reds_gate_and_rolls_back(up, tmp_path,
                                                    monkeypatch, capsys):
    """A planted broken hook wiring that the repair faces cannot fix
    (the rewire is beyond repair, the rebuild subprocess fails) reds the
    selfcheck's hook-chain verdict: the transaction rolls back
    byte-identically and exits incomplete — a red deployment never
    reaches the reload prompt."""
    ws = synth_v012_ws(tmp_path)
    # plant the broken wiring: one orphan hook entry, most of the KONG
    # chain missing — a partial wiring the transaction's step 4 rewire
    # cannot heal in this scenario. The digest baseline is taken AFTER the
    # plant: the rollback point is the snapshot, which contains the plant.
    broken = {"hooks": {"PreToolUse": [
        {"matcher": "Agent", "hooks": [
            {"type": "command", "command": "python env_check_gate.py"}]}]}}
    (ws / ".claude" / "settings.json").write_text(
        json.dumps(broken), encoding="utf-8")
    before = _tree_digest(ws)

    def _no_rewire(ws_path):
        return 0  # the repair face cannot fix this wiring

    def _rebuild_fail(ws_path):
        return {"rebuilt": True, "rc": 1}

    monkeypatch.setattr(up, "register_hooks", _no_rewire)
    monkeypatch.setattr(hooks_selfcheck, "rebuild_project_level",
                        _rebuild_fail)
    rc = up.main([str(ws)])
    assert rc == 7
    captured = capsys.readouterr()
    evs = _events(captured.err)
    fails = [(e["name"], e["status"]) for e in evs]
    assert ("tx-selfcheck", "fail") in fails
    assert ("rollback", "ok") in fails
    assert "TxSelfcheckFailure" in captured.err
    assert "RELOAD REQUIRED" not in captured.out
    assert _tree_digest(ws) == before, "rollback must be byte-identical"
    assert _git(ws, "status", "--porcelain").stdout.strip() == ""


def test_green_gate_passes_hook_chain_face(up, tmp_path):
    """The face the transaction calls is the hook-chain liveness verdict —
    the seam stays silent on a workspace whose wiring is complete (the
    deployment's own deliverable), regardless of unrelated operational
    rows (MCP supply, oracle registration)."""
    ws = synth_v012_ws(tmp_path)
    import deployed_refresh as dr
    dr.refresh(ws)  # materialize the deployed trees (wiring reads them)
    up._tx_selfcheck(ws)  # must not raise


# ------------------------------------------------------------------ help text

def test_help_text_states_transaction_coverage():
    """The sub-faces keep their names; their help states exactly which
    transaction steps they cover and points at the full flow."""
    src = HOOK_ACT_PATH.read_text(encoding="utf-8")

    def _arg_block(flag: str) -> str:
        start = src.index(f'parser.add_argument("{flag}"')
        nxt = src.find("parser.add_argument", start + 1)
        return src[start:nxt if nxt > start else len(src)]

    # the wire-up face: config/wiring coverage only
    wire_up = _arg_block("--wire-up")
    assert "transaction step" in wire_up
    assert "kunglao-agent:upgrade" in wire_up
    # the deploy-local face: copy + register coverage, no snapshot/prune/gate
    deploy_local = _arg_block("--deploy-local")
    assert "transaction step" in deploy_local
    assert "kunglao-agent:upgrade" in deploy_local
    # (source-wrapped literals: assert on wrap-free fragments)
    assert "git snapshot" in deploy_local
    assert "selfcheck gate" in deploy_local


def test_transaction_faces_registered_in_source(up):
    """The three transaction faces exist as named seams (prune, deploy,
    selfcheck) on the upgrade module."""
    for fn in ("_tx_prune_old_files", "_tx_deploy_files", "_tx_selfcheck"):
        assert callable(getattr(up, fn)), fn
