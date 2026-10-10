#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_upgrade_016_sweep.py — v0.1.6 init/upgrade/config sweep.

Pins the three owner HARD requirements for the 0.1.6 release train:

  1. MIGRATIONS registry carries ("0.1.6", migrate_to_0_1_6) after the
     0.1.4 entry; a 0.1.4/0.1.5-origin workspace ends FULLY in 0.1.6 form
     (deployed copies refreshed to current install bytes, superseded
     deployed files pruned as orphans, ledger/report version stamps
     advanced, frame + stamp carried by the universal tail).
  2. Transactional migration: the upgrade commits a pre-migration git
     snapshot FIRST (dirty state included — no more RC 6 refusal on the
     migration path), lands the migrated state as a second commit on
     success ("kunglao upgrade: <origin> -> <target>"), and on ANY failure
     (mid-item raise / iron-rule violation / finish-sequence abort) rolls
     the tree back byte-identical to the snapshot.
  3. Version-consistency gate: analysis/decide entry points
     (convergence_check, init resume intake, /loop birth, check-stale)
     REFUSE a workspace whose format stamp != the executing skill version
     — older AND newer — with structured guidance pointing at
     kunglao_upgrade; only exact match proceeds.
"""
from __future__ import annotations

import hashlib
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

import template_version as tv  # noqa: E402
from _factories import stamp_current, write_hook_state  # noqa: E402

UPGRADE_PATH = SCRIPTS / "kunglao_upgrade.py"

GIT_IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@localhost")

CUR = tv.read_skill_version()
OLDER = "0.1.4"


def _load_upgrade():
    spec = importlib.util.spec_from_file_location("kunglao_upgrade_sweep",
                                                  UPGRADE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _stamp_line(v: str) -> str:
    return f"# {tv.STAMP_KEY}: {v}"


@pytest.fixture(autouse=True)
def _isolated_upgrade_home(tmp_path, monkeypatch):
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("KUNGLAO_UPGRADE_NO_UV_SYNC", "1")
    return home


@pytest.fixture
def up():
    return _load_upgrade()


def _git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *GIT_IDENTITY, *args],
                          capture_output=True, text=True)


def _subjects(ws: Path) -> list[str]:
    return [s for s in _git(ws, "log", "--format=%s")
            .stdout.splitlines() if s.strip()]


def _tree_hashes(ws: Path) -> dict[str, str]:
    """sha256 over every file under ws, excluding the git metadata and the
    sanctioned upgrade telemetry (snapshot json + event logs)."""
    out: dict[str, str] = {}
    for p in sorted(ws.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(ws).as_posix()
        if rel == ".git" or rel.startswith(".git/") \
                or rel == ".gitignore" \
                or rel.startswith("runs/logs/") \
                or rel.startswith("runs/claudemd-pending-merge.") \
                or (rel.startswith("runs/upgrade-snapshot.")
                    and rel.endswith(".json")):
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def synth_ws(tmp: Path, *, stamp: str = OLDER, tag: str = "ws") -> Path:
    """A 0.1.4/0.1.5-shaped workspace with deployed framework copies,
    a stale deployed copy, an orphan deployed file, ledger + report
    version stamps, user data across the iron-rule dirs, and the required
    intake answers. CLAUDE.md is the CURRENT rendered frame carrying the
    old stamp — the mergeable shape (a hand-written body would hit the
    #758 frame gate and honestly keep its old stamp, which is the OTHER
    sanctioned face, pinned by #726)."""
    import hook_activation as ha
    import claudemd_frame
    u = _load_upgrade()
    ws = tmp / tag
    ws.mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        _stamp_line(stamp) + "\n# facts\nF001 | PROVEN | C-1 | keep me\n",
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        _stamp_line(stamp) + "\nclaims: []\n# [initialized] 2026-08-01\n",
        encoding="utf-8")
    frame = claudemd_frame.wrap_frame(
        u._build_current_frame(ws, "# old\n", None))
    (ws / "CLAUDE.md").write_text(
        _stamp_line(stamp) + "\n" + frame, encoding="utf-8")
    for d, f, body in [
        ("claims", "C-001.md", "claim body"), ("facts", "F001.md", "fact body"),
        ("runs", "worker-status-C001.txt", "status line"),
        ("hypotheses", "H-001.md", "hyp body"), ("notes", "N-1.md", "note"),
        ("evidence", "e.txt", "ev"), ("oracle", "o.txt", "or"),
    ]:
        p = ws / d
        p.mkdir(exist_ok=True)
        (p / f).write_text(body, encoding="utf-8")
    # deployed framework copies (phase-2 semantics) + a STALE copy + orphan
    ha.deploy_workspace_copy(ws)
    stale = ws / ".claude" / "templates" / "state" / "blocker.md"
    if stale.is_file():
        stale.write_text(stale.read_text(encoding="utf-8")
                         + "\n<!-- stale 0.1.4 copy -->\n", encoding="utf-8")
    orphan = ws / ".claude" / "templates" / "state" / "superseded-v04.md"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("# superseded scaffolding\n", encoding="utf-8")
    # ledger + report version stamps behind
    (ws / "env-manifest.yaml").write_text(
        "generated: 2026-09-01T00:00:00Z\n"
        f"project_type: windows\nkunglao_version: {stamp}\n"
        "components: []\n", encoding="utf-8")
    (ws / "runs" / ".init-report.json").write_text(
        json.dumps({"skill_version": stamp}), encoding="utf-8")
    settings = {"hooks": {"PreToolUse": [
        {"type": "command",
         "command": f"python {SCRIPTS.name}/{h}"} for h in (
             "env_check_gate.py", "worker_budget.py")]}}
    (ws / ".claude").mkdir(exist_ok=True)
    (ws / ".claude" / "settings.json").write_text(
        json.dumps(settings), encoding="utf-8")
    # pre-register the statusline (the upgrade's first-line verify must be
    # ok so the transaction tests compare a stable tree)
    ha.register_statusline(ws)
    write_hook_state(ws, active_hooks=["active_intervention"],
                     phase="IDLE", user_override={},
                     extra={"state": "active"})
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: legacy goal\n"
        "success_criterion: legacy criterion\n"
        "verification_method: manual\n", encoding="utf-8")
    return ws


# --------------------------------------------------------------------------
# 1. registry + migrate_to_0_1_6
# --------------------------------------------------------------------------

def test_registry_has_016_entry_after_014(up):
    names = [v for v, _fn in up.MIGRATIONS]
    assert "0.1.6" in names
    assert names.index("0.1.6") > names.index("0.1.4")
    entry = dict(up.MIGRATIONS)["0.1.6"]
    assert entry is up.migrate_to_0_1_6


def test_014_and_015_origins_plan_the_016_entry(up):
    plan_v = [v for v, _fn in up._plan_migrations(up._vkey(OLDER), CUR)]
    assert "0.1.6" in plan_v
    plan_p = [v for v, _fn in up._plan_migrations(up._vkey("0.1.5"), CUR)]
    assert "0.1.6" in plan_p
    # 0.1.6 origins plan nothing version-specific (only the carry tail)
    plan_c = [v for v, _fn in up._plan_migrations(up._vkey(CUR), CUR)]
    assert "0.1.6" not in plan_c


def test_016_migration_items_are_the_refresh_family(up, tmp_path):
    ws = synth_ws(tmp_path)
    labels = up.migrate_to_0_1_6(ws, dry=True)
    blob = "\n".join(labels)
    for face in ("agents_refresh", "deployed_refresh", "env_ledger_refresh",
                 "toolchain_manifest_check", "uv_sync", "skill_staleness"):
        assert face in blob, face


def test_014_origin_upgrade_ends_fully_016(up, tmp_path):
    ws = synth_ws(tmp_path)
    assert up.main([str(ws)]) == 0
    # stamp advanced on all three carriers
    for rel in ("CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"):
        text = (ws / rel).read_text(encoding="utf-8")
        assert f"{tv.STAMP_KEY}: {CUR}" in text, rel
        assert f"{tv.STAMP_KEY}: {OLDER}" not in text, rel
    # stale deployed copy refreshed to install bytes
    stale = ws / ".claude" / "templates" / "state" / "blocker.md"
    src = REPO / ".claude" / "templates" / "state" / "blocker.md"
    if src.is_file() and stale.is_file():
        assert stale.read_bytes() == src.read_bytes(), \
            "deployed copy must be refreshed to the install source"
    # superseded deployed file pruned (backed up, then removed)
    assert not (ws / ".claude" / "templates" / "state"
                / "superseded-v04.md").exists()
    assert any((ws / "runs" / "deploy-backup-orphan").glob("*")) \
        if (ws / "runs" / "deploy-backup-orphan").is_dir() else True
    # ledger + report stamps advanced
    import yaml
    led = yaml.safe_load((ws / "env-manifest.yaml").read_text(encoding="utf-8"))
    assert led["kunglao_version"] == CUR
    report = json.loads((ws / "runs" / ".init-report.json")
                        .read_text(encoding="utf-8"))
    assert report["skill_version"] == CUR
    # user data never moved
    assert (ws / "facts" / "F001.md").read_text(encoding="utf-8") == "fact body"


# --------------------------------------------------------------------------
# 2. transactional migration
# --------------------------------------------------------------------------

def test_success_lands_two_contract_commits(up, tmp_path):
    ws = synth_ws(tmp_path)
    assert not (ws / ".git").exists()
    assert up.main([str(ws)]) == 0
    subs = _subjects(ws)
    assert len(subs) == 2, subs
    assert subs[0] == f"kunglao upgrade: {OLDER} -> {CUR}", subs
    assert subs[-1] == f"kunglao upgrade snapshot: pre {CUR} (from {OLDER})", \
        subs


def test_dirty_repo_snapshot_committed_not_refused(up, tmp_path):
    ws = synth_ws(tmp_path)
    for args in (("init",), ("add", "-A"),
                 ("commit", "--no-gpg-sign", "-m", "base")):
        assert _git(ws, *args).returncode == 0
    (ws / "notes" / "N-uncommitted.md").write_text(
        "uncommitted work", encoding="utf-8")
    rc = up.main([str(ws)])
    assert rc == 0, "dirty state must be snapshot-committed, never refused"
    subs = _subjects(ws)
    assert subs[0] == f"kunglao upgrade: {OLDER} -> {CUR}", subs
    assert subs[1] == f"kunglao upgrade snapshot: pre {CUR} (from {OLDER})", \
        subs
    assert subs[-1] == "base", subs
    # the uncommitted work rides INSIDE the snapshot commit, not lost
    snap_msg = f"kunglao upgrade snapshot: pre {CUR} (from {OLDER})"
    sha = _git(ws, "log", "--format=%H", "--grep", snap_msg,
               "--fixed-strings", "-1").stdout.strip()
    assert sha, "snapshot commit must be findable by subject"
    show = _git(ws, "show", "--name-only", "--format=", sha)
    assert "notes/N-uncommitted.md" in show.stdout


def test_clean_repo_gets_only_the_success_commit(up, tmp_path):
    ws = synth_ws(tmp_path)
    for args in (("init",), ("add", "-A"),
                 ("commit", "--no-gpg-sign", "-m", "base")):
        assert _git(ws, *args).returncode == 0
    assert up.main([str(ws)]) == 0
    subs = _subjects(ws)
    assert subs == [f"kunglao upgrade: {OLDER} -> {CUR}", "base"], subs


def test_failed_item_rolls_back_byte_identical(up, tmp_path):
    ws = synth_ws(tmp_path)
    pre = _tree_hashes(ws)

    def evil(ws: Path, dry: bool):
        if not dry:
            (ws / "facts" / "F001.md").write_text("tampered",
                                                  encoding="utf-8")
            (ws / "notes" / "N-migration-junk.md").write_text(
                "junk", encoding="utf-8")
        return ["evil_touch"]

    up.MIGRATIONS = [("9.9.9", evil)]
    rc = up.main([str(ws)])
    assert rc == 4, "user-data mutation must fail the run"
    assert _tree_hashes(ws) == pre, \
        "rollback must restore the tree byte-identical to the snapshot"


def test_midway_raise_triggers_rollback(up, tmp_path):
    ws = synth_ws(tmp_path)
    pre = _tree_hashes(ws)

    def exploding(ws: Path, dry: bool):
        raise RuntimeError("simulated kill mid-migration")

    up.MIGRATIONS = [("9.9.9", exploding)]
    rc = up.main([str(ws)])
    assert rc == 7
    assert _tree_hashes(ws) == pre
    subs = _subjects(ws)
    assert subs and "kunglao upgrade snapshot: pre" in subs[-1], subs
    assert len(subs) == 1, "no success commit may follow a rolled-back run"


def test_iron_rule_violation_restores_user_data(up, tmp_path):
    ws = synth_ws(tmp_path)

    def evil(ws: Path, dry: bool):
        if not dry:
            (ws / "facts" / "F001.md").write_text("tampered",
                                                  encoding="utf-8")
        return ["evil_touch"]

    up.MIGRATIONS = [("9.9.9", evil)]
    rc = up.main([str(ws)])
    assert rc == 4
    assert (ws / "facts" / "F001.md").read_text(encoding="utf-8") \
        == "fact body", "rollback must restore the iron-rule violation"
    assert list((ws / "runs").glob("upgrade-snapshot.*.json")), \
        "framework snapshot must survive for forensics"


def test_rollback_survives_missing_git_binary(up, tmp_path, capsys):
    """A rollback whose git is gone degrades to a loud WARN, never a crash."""
    ws = synth_ws(tmp_path)

    def exploding(ws: Path, dry: bool):
        raise RuntimeError("boom")

    up.MIGRATIONS = [("9.9.9", exploding)]

    real_run = up._run_git

    def git_then_vanish(ws, *args):
        if args and args[0] == "reset":
            raise FileNotFoundError("git binary not found")
        return real_run(ws, *args)

    up._run_git = git_then_vanish
    rc = up.main([str(ws)])
    assert rc == 7
    assert "WARN" in capsys.readouterr().err


# --------------------------------------------------------------------------
# 3. version-consistency gate
# --------------------------------------------------------------------------

def _run_cli(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script), *args], cwd=str(REPO),
        capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=180)


def _decision_ws(tmp: Path, stamp: str | None, tag: str = "dec") -> Path:
    """Minimal workspace for the decide face: markers + one open claim."""
    ws = tmp / tag
    ws.mkdir(parents=True)
    stamp_line = f"{_stamp_line(stamp)}\n" if stamp else ""
    (ws / "CLAUDE.md").write_text(stamp_line + "# ws\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        stamp_line + "claims:\n- id: C-001\n  status: OPEN\n"
        "# [initialized] 2026-08-01\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: g\nsuccess_criterion: c\n"
        "verification_method: manual\nprimary_questions:\n"
        "  - \"q1\"\n", encoding="utf-8")
    return ws


def test_convergence_refuses_older_stamp(tmp_path):
    ws = _decision_ws(tmp_path, OLDER)
    proc = _run_cli(SCRIPTS / "convergence_check.py", str(ws))
    assert proc.returncode == 67, f"{proc.stdout}{proc.stderr}"
    assert "upgrade" in (proc.stdout + proc.stderr).lower()


def test_convergence_refuses_missing_stamp(tmp_path):
    ws = _decision_ws(tmp_path, None)
    proc = _run_cli(SCRIPTS / "convergence_check.py", str(ws))
    assert proc.returncode == 67, f"{proc.stdout}{proc.stderr}"


def test_convergence_proceeds_on_exact_match(tmp_path):
    ws = _decision_ws(tmp_path, CUR)
    proc = _run_cli(SCRIPTS / "convergence_check.py", str(ws))
    assert proc.returncode in (0, 1, 2, 3, 4, 5), \
        f"{proc.stdout}{proc.stderr}"
    assert "kunglao_upgrade" not in (proc.stdout + proc.stderr)


def test_convergence_refuses_newer_stamp(tmp_path):
    ws = _decision_ws(tmp_path, "9.9.9")
    proc = _run_cli(SCRIPTS / "convergence_check.py", str(ws))
    assert proc.returncode == 67, f"{proc.stdout}{proc.stderr}"


def test_exit_version_mismatch_registered_distinct():
    sys.path.insert(0, str(SCRIPTS))
    import contracts
    assert contracts.EXIT_VERSION_MISMATCH == 67
    taken = {contracts.EXIT_CONVERGED, contracts.EXIT_DISPATCH,
             contracts.EXIT_VERIFY, contracts.EXIT_SATURATED,
             contracts.EXIT_BLOCKED, contracts.EXIT_PARK,
             contracts.EXIT_MISSING_WORKSPACE, contracts.EXIT_CRASHED,
             contracts.EXIT_EMPTY_WORKSPACE}
    assert contracts.EXIT_VERSION_MISMATCH not in taken


def test_init_resume_refuses_mismatched_stamp(tmp_path):
    ws = synth_ws(tmp_path, stamp=OLDER, tag="initws")
    proc = _run_cli(SCRIPTS / "kunglao-init.py", str(ws))
    assert proc.returncode == 9, f"{proc.stdout}{proc.stderr}"
    assert "upgrade" in (proc.stdout + proc.stderr).lower()


def test_init_resume_proceeds_on_exact_match(tmp_path):
    ws = synth_ws(tmp_path, stamp=CUR, tag="initcur")
    proc = _run_cli(SCRIPTS / "kunglao-init.py", str(ws))
    assert proc.returncode != 9, f"{proc.stdout}{proc.stderr}"


def test_loop_prompt_refuses_mismatched_stamp(tmp_path):
    ws = _decision_ws(tmp_path, OLDER, tag="loopws")
    proc = _run_cli(SCRIPTS / "heartbeat_loop_prompt.py", str(ws))
    assert proc.returncode == 9, f"{proc.stdout}{proc.stderr}"
    assert "upgrade" in (proc.stdout + proc.stderr).lower()
    cur_ws = _decision_ws(tmp_path, CUR, tag="loopcur")
    ok = _run_cli(SCRIPTS / "heartbeat_loop_prompt.py", str(cur_ws))
    assert ok.returncode == 0, f"{ok.stdout}{ok.stderr}"


def test_check_stale_refuses_newer_stamp(tmp_path):
    """A workspace stamped NEWER than the skill must refuse too — the
    version gate is exact-match, not a one-directional staleness warn."""
    from kunglao_log import emit  # noqa: F401  (import sanity only)
    ws = _decision_ws(tmp_path, "9.9.9", tag="newer")
    proc = _run_cli(SCRIPTS / "kunglao.py", "check-stale", str(ws))
    assert proc.returncode == 5, f"{proc.stdout}{proc.stderr}"
    env = json.loads(proc.stdout.strip().splitlines()[-1])
    assert env["status"] == "stale"
    assert "upgrade" in (env["advice"] or "").lower()


# --------------------------------------------------------------------------
# 4. owner defects from the 51job live run
# --------------------------------------------------------------------------

def test_snapshot_skip_refuses_before_any_mutation(up, tmp_path):
    """Reviewer blocking finding: when the pre-migration snapshot CANNOT
    be taken, the migration must refuse BEFORE any mutation — rolling
    back without a snapshot would destroy uncommitted work."""
    ws = synth_ws(tmp_path)
    pre = _tree_hashes(ws)
    up._snapshot_pre_migration = lambda *a, **k: {"status": "skipped",
                                                  "sha": None}
    rc = up.main([str(ws)])
    assert rc == 6, "no rollback anchor -> refuse the migration"
    assert _tree_hashes(ws) == pre, "refusal must precede every write"


def test_ida_known_dir_probe_finds_fixture_and_records_bad_pattern(
        tmp_path, capsys):
    """Static-audit finding: the known-dir rung referenced `glob` without
    importing it — NameError swallowed into a silent no-op. With the
    import fixed it returns REAL hits, and a failing pattern is recorded
    as a stderr WARN instead of being silently eaten."""
    import toolchain as tc
    import os as _os
    hit_dir = tmp_path / "ida" / "bin"
    hit_dir.mkdir(parents=True)
    hit = hit_dir / "idat64"
    hit.write_text("#!/bin/sh\n", encoding="utf-8")
    _os.chmod(hit, 0o755)
    got = tc._probe_ida_via_known_dirs(
        patterns=(str(hit_dir / "idat64"),))
    assert got == hit, "the probe must return a real hit now"
    # a pattern that makes glob itself raise must WARN, never raise
    import glob as _glob

    real_glob = _glob.glob

    def _boom(pattern, *a, **k):
        if "[unclosed" in str(pattern):
            raise OSError("glob exploded")
        return real_glob(pattern, *a, **k)

    tc.glob.glob = _boom
    try:
        got_bad = tc._probe_ida_via_known_dirs(
            patterns=(str(tmp_path / "[unclosed"),))
    finally:
        tc.glob.glob = real_glob
    assert got_bad is None
    assert "WARN" in capsys.readouterr().err


def test_prescan_obligation_is_lane_aware(tmp_path):
    """51job live-run defect: the prescan obligation wrote native
    binary-identification artifacts (die.json/apkid.json) for EVERY lane,
    locking web-lane deep-analysis claims forever. Web -> no required
    artifacts + an explicit on-disk note; native lane keeps the
    obligation."""
    import intake_promise as ip
    ws = tmp_path / "ws"
    ws.mkdir()
    report = type("R", (), {"items": []})()
    web_spec = {"lane": "web"}
    got = ip.build(report, web_spec, ws)["prescan_obligation"]
    assert got["required"] == [], "web lane must not require die/apkid"
    assert got["lane"] == "web"
    assert "lane=web" in got["note"] and "NOT" in got["note"], \
        "the explicit no-op note must be on disk either way"
    # native lane keeps the current obligation
    native = ip.build(report, {"lane": "malware"}, ws)["prescan_obligation"]
    assert native["required"] == list(ip.OBLIGATION)
    # undeclared lane keeps the pre-lane malware default
    undeclared = ip.build(report, {}, ws)["prescan_obligation"]
    assert undeclared["required"] == list(ip.OBLIGATION)


def test_user_visible_output_free_of_dev_era_versions(tmp_path):
    """51job live-run defect: internal dev-era labels (v1.9.x) leaked into
    user-visible init/loop output. Docstrings/comments may keep them;
    print faces and the loop prompt body must not."""
    import heartbeat_loop_prompt as hlp
    ws = tmp_path / "ws"
    ws.mkdir()
    body = hlp.build_prompt(str(ws), "5m")
    assert "v1.9." not in body, "loop prompt body leaked a dev-era label"
    init_src = (SCRIPTS / "kunglao-init.py").read_text(encoding="utf-8")
    offenders = [ln for ln in init_src.splitlines()
                 if "print(" in ln and "v1.9." in ln
                 and not ln.strip().startswith("#")]
    assert not offenders, f"init print faces leak dev-era labels: {offenders}"


def test_tick_module_wired_row_lands_with_resolved_ws(tmp_path):
    """#413: the #534 "module wired" emit moved from import time (where `ws`
    was undefined — degraded.module_emit poisoned every tick report) into
    main() after ws resolution. Pin: a healthy tick carries NO
    module_emit degradation and the ledger DOES carry the module-wired
    row with the resolved workspace."""
    import heartbeat_tick as hbt
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    stamp_current(ws)
    (ws / "claim-register.yaml").write_text("claims: []\n",
                                            encoding="utf-8")
    (ws / "task_spec.yaml").write_text("primary_questions: []\n",
                                       encoding="utf-8")
    rc = hbt.main([str(ws)])
    assert rc in (0, 1)
    report = json.loads((ws / "runs" / ".heartbeat-tick.json")
                        .read_text(encoding="utf-8"))
    degraded = report.get("degraded") or {}
    assert "module_emit" not in degraded, degraded
    rows = []
    for log in (ws / "runs" / "logs").glob("kunglao-*.jsonl"):
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    wired = [r for r in rows
             if r.get("actor") == "heartbeat_tick"
             and r.get("detail") == "module wired"]
    assert wired, "the module-wired row must land with the resolved ws"


# --------------------------------------------------------------------------
# 5. #415 tick-continuity + #6 hook env + #413 already above
# --------------------------------------------------------------------------

def test_continuity_counts_real_ticks_not_hook_pulses(tmp_path):
    """#415: the durable sidecar is a shared substrate — hook-event rows
    (actor="hook") and registration markers (actor="register") are NOT
    ticks. Deploy-day quiet gaps must not read as dead crons; real tick
    rows (actor="tick") DO count."""
    import heartbeat
    ws = tmp_path / "ws"
    ws.mkdir()
    log = ws / "runs" / ".heartbeat.log"
    log.parent.mkdir(parents=True)
    import json as _json
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    rows = []
    # deployment day: a register marker, then only hook pulses for 40 min
    rows.append({"ts": (now - timedelta(minutes=40)).isoformat()
                 .replace("+00:00", "Z"), "actor": "register"})
    for m in (38, 32, 25, 18, 12, 6, 1):
        rows.append({"ts": (now - timedelta(minutes=m)).isoformat()
                     .replace("+00:00", "Z"), "actor": "hook"})
    log.write_text("".join(_json.dumps(r) + "\n" for r in rows),
                   encoding="utf-8")
    state = {"interval_min": 5, "tick_history": []}
    alive, detail = heartbeat.evaluate_tick_continuity(
        state, stale_minutes=35, log_path=log)
    assert alive is False, "hook pulses are not ticks: <2 real ticks rejects"
    assert "single tick only" in detail or "no tick_history" in detail \
        or "tick" in detail, detail
    # REAL tick rows count: two ticks 5 min apart => alive cadence
    rows2 = [{"ts": (now - timedelta(minutes=10)).isoformat()
              .replace("+00:00", "Z"), "actor": "tick"},
             {"ts": (now - timedelta(minutes=5)).isoformat()
              .replace("+00:00", "Z"), "actor": "tick"},
             {"ts": (now - timedelta(minutes=40)).isoformat()
              .replace("+00:00", "Z"), "actor": "hook"}]
    log.write_text("".join(_json.dumps(r) + "\n" for r in rows2),
                   encoding="utf-8")
    alive2, detail2 = heartbeat.evaluate_tick_continuity(
        state, stale_minutes=35, log_path=log)
    assert alive2 is True, detail2
    # a real cadence GAP between tick rows still rejects (hook rows cannot
    # paper over a dead cron)
    rows3 = [{"ts": (now - timedelta(minutes=60)).isoformat()
              .replace("+00:00", "Z"), "actor": "tick"},
             {"ts": (now - timedelta(minutes=1)).isoformat()
              .replace("+00:00", "Z"), "actor": "tick"},
             {"ts": (now - timedelta(minutes=30)).isoformat()
              .replace("+00:00", "Z"), "actor": "hook"}]
    log.write_text("".join(_json.dumps(r) + "\n" for r in rows3),
                   encoding="utf-8")
    alive3, _ = heartbeat.evaluate_tick_continuity(
        state, stale_minutes=90, log_path=log)
    assert alive3 is False, "a 59-min gap between real ticks is a stall"


def test_continuity_baseline_reset_gating(tmp_path):
    """#415.3: the fresh-deploy reset is fail-closed — refused when real
    tick rows exist (a real stall needs the re-arm chain, not a reset)
    or the state is old; a fresh hook-only sidecar resets and rebuilds."""
    import heartbeat
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    log = ws / "runs" / ".heartbeat.log"
    log.write_text(json.dumps(
        {"ts": "2026-09-27T00:00:00Z", "actor": "hook"}) + "\n",
        encoding="utf-8")
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps(
        {"interval_min": 5, "tick_history": []}), encoding="utf-8")
    got = heartbeat.reset_continuity_baseline(ws)
    assert got["status"] == "reset", got
    assert (ws / "runs" / ".heartbeat.json").read_text().count("tick_history")
    # now with a REAL tick row: refused (fail-closed)
    ws2 = tmp_path / "ws2"
    (ws2 / "runs").mkdir(parents=True)
    (ws2 / "runs" / ".heartbeat.log").write_text(json.dumps(
        {"ts": "2026-09-27T00:00:00Z", "actor": "tick"}) + "\n",
        encoding="utf-8")
    (ws2 / "runs" / ".heartbeat.json").write_text(json.dumps(
        {"interval_min": 5, "tick_history": []}), encoding="utf-8")
    got2 = heartbeat.reset_continuity_baseline(ws2)
    assert got2["status"] == "refused", got2
    assert "real tick" in got2["reason"]


def test_mid_session_cron_warning_present(tmp_path):
    """#415.2: deploy-day reality — a durable cron registered mid-session
    only fires after the next session start; both output faces must say
    so (the quiet gap is deploy-day shape, not a dead cron)."""
    import heartbeat_loop_prompt as hlp
    body = hlp.build_prompt(str(tmp_path), "5m")
    assert "#415" in body and "MID-SESSION" in body.upper()
    init_src = (SCRIPTS / "kunglao-init.py").read_text(encoding="utf-8")
    assert "durable cron takes effect from the" in init_src
    assert "--reset-continuity" in init_src


def test_hook_wiring_runs_in_framework_env(up, tmp_path):
    """#6 (51job live run): hooks wired as `uv run --project <workspace>`
    built an ephemeral empty env — write_guard's lazy `import yaml`
    ModuleNotFoundError'd into a fail-closed BLOCK on legitimate writes.
    The wired command's env project must be the FRAMEWORK root (pyproject
    present), the script path stays the workspace deployed copy, and that
    env must actually resolve `import yaml`."""
    import hook_activation as ha
    ws = tmp_path / "ws"
    (ws / ".claude" / "hooks").mkdir(parents=True)
    entry = ha.build_hook_entry(ws / ".claude" / "hooks",
                                "env_check_gate.py", project=ws)
    cmd = entry["hooks"][0]["command"]
    assert "uv run --project " in cmd and " python " in cmd
    # the --project path owns pyproject.toml (the framework project)…
    proj = cmd.split("--project ", 1)[1].split(" ", 1)[0]
    assert (Path(proj) / "pyproject.toml").is_file(), proj
    # …the script path stays in the workspace…
    assert str(ws) in cmd and ".claude/hooks/env_check_gate.py" in cmd
    # …and that env really resolves the framework imports.
    proj_esc = proj.replace("'", "'\\''")
    probe = subprocess.run(
        ["uv", "run", "--project", proj, "python", "-c", "import yaml"],
        capture_output=True, text=True, timeout=120)
    assert probe.returncode == 0, probe.stderr


def test_camoufox_required_on_web_lane(tmp_path, monkeypatch):
    """Owner ruling (51job live run): camoufox-reverse is REQUIRED on the
    web lane (HARD). #408/#423 merge semantics: the remediation is plugin
    CARRIAGE (.claude-plugin/plugin.json mcpServers), never a user-level
    `claude mcp add` — the FAIL face only exists when carriage AND
    workspace registration are BOTH absent."""
    import mcp_probe
    ws = tmp_path / "ws"
    ws.mkdir()
    # default face: the repo's own plugin carriage satisfies supply
    checks = {c.name: c for c in mcp_probe.check_mcp(ws, "web")}
    cam = checks["camoufox-reverse"]
    assert cam.status == "PASS" and cam.tier == "HARD"
    assert "plugin-carried" in cam.detail, cam.detail
    # carriage removed (plugin disabled / manifest drift) -> HARD FAIL
    monkeypatch.setattr(mcp_probe, "plugin_declared_servers",
                        lambda root=None: {})
    checks1 = {c.name: c for c in mcp_probe.check_mcp(ws, "web")}
    cam1 = checks1["camoufox-reverse"]
    assert cam1.status == "FAIL" and cam1.tier == "HARD"
    assert cam1.fix == ("ships with the kunglao-agent plugin "
                        "(.claude-plugin/plugin.json mcpServers) — enable "
                        "the plugin; install dep: pip install "
                        "camoufox-reverse-mcp")
    assert "claude mcp add" not in cam1.fix  # user-scope surface deleted
    # workspace .mcp.json alone also satisfies (project-scope path)
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"camoufox-reverse": {"command": "python",
         "args": ["-m", "camoufox_reverse_mcp"]}}}), encoding="utf-8")
    checks2 = {c.name: c for c in mcp_probe.check_mcp(ws, "web")}
    assert checks2["camoufox-reverse"].status == "PASS"


def test_init_refuses_web_without_camoufox(tmp_path, capsys, monkeypatch):
    """Web-lane init refuses (rc 4) when camoufox-reverse supply is absent
    on BOTH #408 surfaces (workspace .mcp.json AND plugin carriage — with
    the repo's own plugin.json carrying mcpServers the in-repo supply is
    satisfied by construction, so the refusal face needs the carriage
    removed). The remediation names the plugin carriage + pip dep, never
    a user-level `claude mcp add`. Unit face over refuse_missing_required_mcp
    (the full-run face needs the whole intake completed first — that is
    the 51job live-run shape), plus a source pin that run() wires the gate
    into the supply preflight."""
    ws = _decision_ws(tmp_path, CUR, tag="webws")
    (ws / "analysis_state.txt").write_text("project_type=web\n",
                                           encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_sweep", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # remove BOTH supply surfaces (deploy without plugin carriage)
    monkeypatch.setattr(mod.mcp_probe, "plugin_declared_servers",
                        lambda root=None: {})
    rc = mod.refuse_missing_required_mcp(ws, "web")
    err = capsys.readouterr().err
    assert rc == 4, err
    assert "ships with the kunglao-agent plugin" in err, err[-600:]
    assert "pip install camoufox-reverse-mcp" in err, err[-600:]
    assert "claude mcp add" not in err  # user-scope surface deleted (#408)
    assert "AGENT-DO" in err
    # registered in the workspace .mcp.json -> satisfied
    (ws / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"camoufox-reverse": {"command": "python",
         "args": ["-m", "camoufox_reverse_mcp"]}}}), encoding="utf-8")
    capsys.readouterr()
    assert mod.refuse_missing_required_mcp(ws, "web") is None
    # desktop (windows) project type: camoufox is not applicable at all
    ws_native = _decision_ws(tmp_path, CUR, tag="nat")
    (ws_native / "analysis_state.txt").write_text("project_type=windows\n",
                                                  encoding="utf-8")
    assert mod.refuse_missing_required_mcp(ws_native, "windows") is None

    # wiring pin: run() invokes the gate inside the toolchain preflight
    init_src = (SCRIPTS / "kunglao-init.py").read_text(encoding="utf-8")
    assert "refuse_missing_required_mcp(ws, project_type)" in init_src
    assert init_src.index("refuse_missing_required_mcp(ws, project_type)") \
        > init_src.index("toolchain.check BEFORE scaffold")
    # the gate is inside the skip_toolchain-guarded preflight block
    preflight = init_src[init_src.index("if not skip_toolchain:"):]
    assert "refuse_missing_required_mcp(ws, project_type)" in \
        preflight[:preflight.index("# uv env deployment")]
