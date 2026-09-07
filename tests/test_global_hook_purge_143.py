#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_global_hook_purge_143.py — upgrade purges legacy global kunglao
hooks (#143).

Contract (issue #143, owner ruling 2026-09-07: ships in v0.1.5): hook
deployment has been PROJECT-scoped since #258, but machines that ran
pre-#258 versions still carry kunglao hooks in the user-global
~/.claude/settings.json. The upgrade item _item_global_hook_purge:

  - removes ONLY hook entries whose command references a WIRE_UP_HOOK_FILES
    registry basename (#372 single source); non-kunglao entries and every
    non-hooks top-level key (env/statusLine/enabledPlugins/...) survive;
  - backs up the ORIGINAL file bytes to
    <ws>/runs/global-settings-backup-<utc-ts>.json before the first write
    (iron-rule-exempt, D4 class);
  - skips with a WARN on a corrupted file, leaving it byte-untouched (never
    repair a corrupted global file by truncation);
  - is idempotent: no kunglao entries -> noop, no backup, no write;
  - is registered AFTER _item_hooks_rewire so project-level registration is
    confirmed earlier in the SAME upgrade run (#258: no window where neither
    layer is active); a project layer that still reads hook-less draws a
    WARN but the purge proceeds.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

UGRADE_PATH = SCRIPTS / "kunglao_upgrade.py"

KUNGLAO_CMD_1 = "python /legacy/install/kunglao-agent/hooks/heartbeat_touch.py"
KUNGLAO_CMD_2 = ("PYTHONUTF8=1 uv run --project /legacy/kunglao-agent "
                 "/legacy/kunglao-agent/hooks/worker_budget.py")
FOREIGN_CMD = "/usr/local/bin/prettier --stdin-filepath x.ts"


def _load_upgrade():
    spec = importlib.util.spec_from_file_location("kunglao_upgrade_143",
                                                  UGRADE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _global_settings() -> dict:
    """Mixed global settings: 2 kunglao hook entries + 1 foreign hook +
    env + statusLine. The kunglao commands reference registry basenames via
    paths from a DEAD pre-#258 install (the exact legacy shape #143 purges)."""
    return {
        "env": {"KUNGLAO_VALUE_ALGO": "keep-me"},
        "hooks": {
            "PreToolUse": [
                {"matcher": "Agent", "hooks": [
                    {"type": "command", "command": KUNGLAO_CMD_1},
                    {"type": "command", "command": FOREIGN_CMD},
                ]},
            ],
            "Stop": [
                {"hooks": [{"type": "command", "command": KUNGLAO_CMD_2}]},
            ],
        },
        "statusLine": {"type": "command", "command": "starship prompt"},
    }


def _write_global(gp: Path, payload: dict) -> bytes:
    gp.parent.mkdir(parents=True, exist_ok=True)
    gp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return gp.read_bytes()


@pytest.fixture
def purge_env(tmp_path, monkeypatch):
    """Fixture home (the established Path.home monkeypatch seam —
    hook_activation.canonical_install_root precedent) + a workspace whose
    project-level settings carry live hooks (the post-rewire state)."""
    home = tmp_path / "home"
    gp = home / ".claude" / "settings.json"
    original = _write_global(gp, _global_settings())
    monkeypatch.setattr(Path, "home", lambda: home)
    ws = tmp_path / "ws"
    _write_global(ws / ".claude" / "settings.json", {
        "hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "uv run completion_gate.py"}]}]},
    })
    return home, gp, ws, original


# ------------------------------------------------------------- purge core

def test_purge_removes_exactly_the_kunglao_entries(purge_env):
    home, gp, ws, original = purge_env
    up = _load_upgrade()
    line = up._item_global_hook_purge(ws, False)
    assert "removed=2" in line, line
    post = json.loads(gp.read_text(encoding="utf-8"))
    pre = json.loads(original)
    # non-hooks top-level keys untouched (parsed equality of whole subtrees)
    assert post["env"] == pre["env"]
    assert post["statusLine"] == pre["statusLine"]
    # the foreign hook entry survives IN PLACE; Stop emptied -> key dropped
    assert [h["command"] for h in post["hooks"]["PreToolUse"][0]["hooks"]] \
        == [FOREIGN_CMD]
    assert "Stop" not in post["hooks"]
    blob = gp.read_text(encoding="utf-8")
    assert KUNGLAO_CMD_1 not in blob and KUNGLAO_CMD_2 not in blob
    assert FOREIGN_CMD in blob


def test_purge_keeps_foreign_entries_in_original_shape(purge_env):
    """A matcher entry that also carried foreign hooks is KEPT (with the
    kunglao rows removed), not dropped wholesale."""
    home, gp, ws, original = purge_env
    up = _load_upgrade()
    up._item_global_hook_purge(ws, False)
    post = json.loads(gp.read_text(encoding="utf-8"))
    entry = post["hooks"]["PreToolUse"][0]
    assert entry["matcher"] == "Agent"
    assert len(entry["hooks"]) == 1


def test_backup_written_before_first_write(purge_env):
    home, gp, ws, original = purge_env
    up = _load_upgrade()
    up._item_global_hook_purge(ws, False)
    backups = list((ws / "runs").glob("global-settings-backup-*.json"))
    assert len(backups) == 1, backups
    assert backups[0].read_bytes() == original, \
        "backup must carry the ORIGINAL bytes"


def test_second_run_is_idempotent_noop(purge_env):
    home, gp, ws, original = purge_env
    up = _load_upgrade()
    up._item_global_hook_purge(ws, False)
    after_first = gp.read_bytes()
    line2 = up._item_global_hook_purge(ws, False)
    assert "noop" in line2, line2
    assert gp.read_bytes() == after_first, "second run must not rewrite"
    assert len(list((ws / "runs").glob("global-settings-backup-*.json"))) == 1


def test_atomic_write_preserves_file_mode(purge_env):
    home, gp, ws, original = purge_env
    gp.chmod(0o600)
    up = _load_upgrade()
    up._item_global_hook_purge(ws, False)
    assert gp.stat().st_mode & 0o777 == 0o600
    assert not gp.with_name(gp.name + ".tmp143").exists(), \
        "temp file must not survive the rename"


def test_missing_global_file_is_noop(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    up = _load_upgrade()
    line = up._item_global_hook_purge(tmp_path / "ws", False)
    assert "noop" in line, line


def test_no_hooks_segment_is_noop(tmp_path, monkeypatch):
    home = tmp_path / "home"
    gp = home / ".claude" / "settings.json"
    original = _write_global(gp, {"env": {"A": "1"},
                                  "statusLine": {"type": "command"}})
    monkeypatch.setattr(Path, "home", lambda: home)
    up = _load_upgrade()
    line = up._item_global_hook_purge(tmp_path / "ws", False)
    assert "noop" in line, line
    assert gp.read_bytes() == original


# ------------------------------------------------------------- safety rails

def test_corrupted_global_file_skips_with_warn_untouched(purge_env, capsys):
    home, gp, ws, original = purge_env
    corrupted = b'{"hooks": {"PreToolUse": [TRUNCATED'
    gp.write_bytes(corrupted)
    up = _load_upgrade()
    line = up._item_global_hook_purge(ws, False)
    assert "warn" in line.lower(), line
    assert gp.read_bytes() == corrupted, "corrupted file must stay untouched"
    err = capsys.readouterr().err
    assert "WARN" in err and "global" in err.lower()
    assert not list((ws / "runs").glob("global-settings-backup-*.json")), \
        "a skipped purge must not write a backup"


def test_dry_run_reports_removal_writes_nothing(purge_env):
    home, gp, ws, original = purge_env
    up = _load_upgrade()
    line = up._item_global_hook_purge(ws, True)
    assert "dry" in line and "2" in line, line
    assert gp.read_bytes() == original, "dry run must not write"
    assert not list((ws / "runs").glob("global-settings-backup-*.json")), \
        "dry run must not write a backup"


def test_project_layer_missing_still_purges_but_warns(tmp_path, monkeypatch,
                                                       capsys):
    """Order contract: project rewire runs EARLIER in the same upgrade run.
    If the project layer still reads hook-less, the purge proceeds (stale
    global hooks are live pollution either way) but logs the WARN."""
    home = tmp_path / "home"
    gp = home / ".claude" / "settings.json"
    _write_global(gp, _global_settings())
    monkeypatch.setattr(Path, "home", lambda: home)
    ws = tmp_path / "ws"
    ws.mkdir()  # no ws/.claude/settings.json at all
    up = _load_upgrade()
    line = up._item_global_hook_purge(ws, False)
    assert "removed=2" in line, line
    err = capsys.readouterr().err
    assert "WARN" in err and "project" in err.lower()


def test_project_layer_present_no_warn(purge_env, capsys):
    home, gp, ws, original = purge_env
    up = _load_upgrade()
    up._item_global_hook_purge(ws, False)
    assert "WARN" not in capsys.readouterr().err


# ------------------------------------------------------------- registration

def test_registered_after_hooks_rewire_in_the_items_list(tmp_path):
    """The purge item must ride the 0.1.3 migration plan AFTER
    _item_hooks_rewire (#258: project registration confirmed before global
    removal — no window where neither layer is active)."""
    up = _load_upgrade()
    ws = tmp_path / "ws"
    ws.mkdir()
    plan = up.migrate_to_0_1_3(ws, dry=True)
    assert "hooks_rewire" in plan
    purge_rows = [i for i in plan if i.startswith("global_hook_purge")]
    assert len(purge_rows) == 1, plan
    assert plan.index("hooks_rewire") < plan.index(purge_rows[0])


def test_purge_event_word_registered():
    """The ledger emit face is a controlled-vocabulary word (#459)."""
    sys.path.insert(0, str(SCRIPTS))
    import event_taxonomy
    assert "global_hook_purge" in event_taxonomy.EMIT_ACTIONS


# ------------------------------------------------------------- iron rule

def test_purge_backup_is_iron_rule_exempt(tmp_path):
    """<ws>/runs/global-settings-backup-*.json is framework-owned telemetry
    of the upgrade's own item — same D4 exemption class as deploy-backup;
    the file mirrors the USER-GLOBAL settings the iron rule never hashed."""
    up = _load_upgrade()
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "F001.md").write_text("body", encoding="utf-8")
    pre = up.user_data_digest(ws)
    backup = ws / "runs" / "global-settings-backup-20260907T000000Z.json"
    backup.parent.mkdir(parents=True)
    backup.write_text("{}", encoding="utf-8")
    assert up.user_data_digest(ws) == pre, \
        "the purge backup must not trip the iron rule"
