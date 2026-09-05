# -*- coding: utf-8 -*-
"""tests/test_claudemd_pending_merge_5.py — issue #5: sanctioned recovery
path for a workspace CLAUDE.md left permanently stale after a refused
upgrade merge.

The three-component deadlock (each correct in isolation):
  1. kunglao_upgrade._item_claudemd_merge REFUSES a user-edited body
     (宁可旧也不要错删, #758 posture) — skip + WARN, body untouched.
  2. the G4 stamp gate (_guarded_stamp_refresh) then honestly keeps the old
     stamp: a fresh stamp may only ride a CURRENT frame.
  3. check-stale sees stamp < skill and advises "run /kunglao-agent:upgrade
     first" — which can now never succeed → stale forever, no sanctioned
     escape; the operator must hand-edit files with no diff to work from.

The fix turns the refusal into an explicit pending-merge state:
  - upgrade writes runs/claudemd-pending-merge.yaml (machine-readable
    marker; presence IS the state machine) plus
    runs/claudemd-pending-merge.diff.patch (incoming frame vs current body)
    instead of leaving nothing behind;
  - check-stale reports status=manual-merge-pending (rc 5, honest — the
    frame IS still stale) with the full recovery instruction: review the
    diff, merge manually, clear the marker with `check-stale --resolve`;
  - the marker is cleared by an explicit --resolve or by any later
    SUCCESSFUL merge (applied or fixed-point noop); absence restores the
    normal check-stale semantics.
"""
from __future__ import annotations

import collections
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
KUNGLAO_PY = SCRIPTS / "kunglao.py"

import template_version as tv  # noqa: E402
from _factories import seed_bins  # noqa: E402

CUR_VERSION = tv.read_skill_version()
STAMP_KEY = tv.STAMP_KEY

MARKER_REL = "runs/claudemd-pending-merge.yaml"
DIFF_REL = "runs/claudemd-pending-merge.diff.patch"

SKILL_SENTINEL = Path("/kunglao/skill-sentinel")
PAYLOAD = b"MZ\x90\x00" + b"\x00" * 64
SAMPLE_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _load_upgrade():
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_init():
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_pending5", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SKILL_DIR = SKILL_SENTINEL
    return mod


@pytest.fixture
def pinned_vi(monkeypatch):
    """Pin the interpreter series the renders echo (see g2g3 fixture)."""
    VI = collections.namedtuple("VI", "major minor micro release serial")
    real = sys.version_info
    monkeypatch.setattr(sys, "version_info", VI(3, 11, 0, "final", 0))
    yield
    monkeypatch.setattr(sys, "version_info", real)


def _stamp_line(v: str) -> str:
    return f"# {STAMP_KEY}: {v}"


def _refusing_ws(tmp: Path) -> Path:
    """A workspace whose hand-written CLAUDE.md can never place the current
    frame (the #5 user journey: real user edits in a legacy body)."""
    ws = tmp / "ws"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text(
        _stamp_line("0.1.2") + "\n\n# my own workspace notes\nkeep hands off\n",
        encoding="utf-8")
    # one real user-data file under runs/ so the iron-rule digest has
    # non-exempt company for the marker the upgrade is about to write
    (ws / "runs").mkdir()
    (ws / "runs" / "worker-status-C001.txt").write_text("status line",
                                                        encoding="utf-8")
    return ws


def _rendered_ws(tmp: Path) -> tuple[Path, str]:
    """ws carrying a fresh init-style render (the mergeable body class)."""
    init = _load_init()
    ws = tmp / "ws"
    seed_bins(ws, payload=PAYLOAD)
    target = init.write_claudemd(ws, "sample.exe", SAMPLE_SHA,
                                 project_type="windows")
    return ws, target.read_text(encoding="utf-8")


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(KUNGLAO_PY), *args],
        capture_output=True, text=True, timeout=120,
        encoding="utf-8", errors="replace",
    )


def _envelope(proc: subprocess.CompletedProcess) -> dict:
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ------------------------------------------------------------- upgrade face

class TestRefusalLeavesPendingState:
    def test_refusal_writes_marker_and_diff(self, tmp_path):
        ws = _refusing_ws(tmp_path)
        claudemd = ws / "CLAUDE.md"
        before = claudemd.read_bytes()

        up = _load_upgrade()
        label = up._item_claudemd_merge(ws, False)

        assert "skip" in label.lower(), label
        marker = ws / MARKER_REL
        diff = ws / DIFF_REL
        assert marker.is_file(), \
            "a refused merge must leave the pending-merge marker"
        assert diff.is_file() and diff.read_text(encoding="utf-8").strip(), \
            "a refused merge must leave a reviewable diff report"
        rec = yaml.safe_load(marker.read_text(encoding="utf-8"))
        assert str(rec["schema"]).startswith("kunglao.claudemd-pending-merge/")
        assert rec["skill_version"] == CUR_VERSION
        assert rec["workspace_stamp"] == "0.1.2"
        assert rec["reason"], "the refusal reason must be recorded"
        assert rec["diff_report"] == DIFF_REL
        assert "--resolve" in rec["resolve_command"]
        dtext = diff.read_text(encoding="utf-8")
        assert "incoming" in dtext
        assert "---" in dtext and "+++" in dtext, "unified diff shape"
        # 宁可旧也不要错删 still holds: the body itself is untouched
        assert claudemd.read_bytes() == before

    def test_refusal_label_names_the_marker(self, tmp_path):
        ws = _refusing_ws(tmp_path)
        up = _load_upgrade()
        label = up._item_claudemd_merge(ws, False)
        assert "claudemd_merge(skipped" in label, \
            "existing runtime-version pin must survive"
        assert MARKER_REL in label, \
            "the skip label must point at the pending marker"

    def test_dry_run_refusal_writes_nothing(self, tmp_path):
        ws = _refusing_ws(tmp_path)
        up = _load_upgrade()
        up._item_claudemd_merge(ws, True)
        assert not (ws / MARKER_REL).exists()
        assert not (ws / DIFF_REL).exists()

    def test_full_upgrade_keeps_iron_rule_and_honest_stamp(self, tmp_path):
        """The end-to-end #5 run: rc 0, marker written, stamp honestly NOT
        refreshed, and the marker/diff under runs/ never trip the iron
        rule (they are upgrade telemetry, D4-exempt)."""
        ws = _refusing_ws(tmp_path)
        up = _load_upgrade()
        pre = up.user_data_digest(ws)
        rc = up.main([str(ws)])
        assert rc == 0
        assert (ws / MARKER_REL).is_file()
        assert (ws / DIFF_REL).is_file()
        text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
        assert _stamp_line("0.1.2") in text, "old stamp stays honest"
        assert _stamp_line(CUR_VERSION) not in text
        assert up.user_data_digest(ws) == pre, \
            "marker + diff are exempt upgrade telemetry, not user data"


class TestCleanMergeRegression:
    def test_automerge_of_mergeable_body_writes_no_marker(self, tmp_path,
                                                          pinned_vi):
        """Regression guard: the normal collect-and-merge path must not
        grow a pending state."""
        ws, original = _rendered_ws(tmp_path)
        (ws / "CLAUDE.md").write_text(
            _stamp_line("0.1.2") + "\n\n" + original, encoding="utf-8")
        up = _load_upgrade()
        label = up._item_claudemd_merge(ws, False)
        assert "applied" in label or "noop" in label, label
        assert not (ws / MARKER_REL).exists()
        assert not (ws / DIFF_REL).exists()

    def test_successful_merge_clears_a_stale_marker(self, tmp_path,
                                                    pinned_vi):
        """The operator merged by hand (or a later upgrade can place the
        frame): any successful merge (applied or fixed-point noop) must
        clear the pending marker."""
        ws = _refusing_ws(tmp_path)
        up = _load_upgrade()
        up._item_claudemd_merge(ws, False)
        assert (ws / MARKER_REL).is_file()
        # operator's manual merge lands a body the frame walker CAN place
        # (render into a sibling dir: init never clobbers an existing
        # CLAUDE.md, so the same dir would return None)
        _, merged = _rendered_ws(tmp_path / "merged-src")
        (ws / "CLAUDE.md").write_text(merged, encoding="utf-8")
        label = up._item_claudemd_merge(ws, False)
        assert "applied" in label or "noop" in label, label
        assert not (ws / MARKER_REL).exists(), \
            "a successful merge resolves the pending state"


# --------------------------------------------------------- check-stale face

class TestCheckStalePendingMerge:
    def _ws_with_marker(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "CLAUDE.md").write_text(
            _stamp_line("0.1.2") + "\n# my own workspace notes\n",
            encoding="utf-8")
        up = _load_upgrade()
        up._write_pending_merge(ws, "# my own workspace notes\n",
                                "current frame does not place in order")
        return ws

    def test_pending_marker_reports_manual_merge_pending(self, tmp_path):
        ws = self._ws_with_marker(tmp_path)
        proc = _cli("check-stale", str(ws))
        assert proc.returncode == 5, proc.stdout + proc.stderr
        env = _envelope(proc)
        assert env["status"] == "manual-merge-pending", env
        assert env["rc"] == 5
        assert env["workspace_stamp"] == "0.1.2"
        assert env["skill_version"] == CUR_VERSION
        assert env["pending_reason"] == \
            "current frame does not place in order"
        assert env["diff_report"] == str(ws / DIFF_REL)
        advice = env["advice"] or ""
        assert str(ws / DIFF_REL) in advice, \
            "the recovery instruction must point at the diff report"
        assert "--resolve" in advice, \
            "the recovery instruction must name the marker-clearing command"
        assert "upgrade" in advice, \
            "the recovery path ends with re-running the upgrade"

    def test_resolve_clears_marker_and_restores_normal_semantics(
            self, tmp_path):
        ws = self._ws_with_marker(tmp_path)
        proc = _cli("check-stale", str(ws), "--resolve")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert not (ws / MARKER_REL).exists(), \
            "--resolve must remove the marker"
        # idempotent: resolving with no marker is a clean rc 0
        proc_again = _cli("check-stale", str(ws), "--resolve")
        assert proc_again.returncode == 0
        # normal semantics restored: honest generic stale, no pending fields
        proc_after = _cli("check-stale", str(ws))
        assert proc_after.returncode == 5
        env = _envelope(proc_after)
        assert env["status"] == "stale", env
        assert "manual-merge" not in json.dumps(env)
        assert "/kunglao-agent:upgrade" in (env["advice"] or "")

    def test_current_stamp_with_leftover_marker_stays_current(self,
                                                              tmp_path):
        """A leftover marker must never poison an already-current
        workspace: the pending branch only lives on the stale path."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "CLAUDE.md").write_text(
            _stamp_line(CUR_VERSION) + "\n# body\n", encoding="utf-8")
        up = _load_upgrade()
        up._write_pending_merge(ws, "whatever\n", "reason-x")
        proc = _cli("check-stale", str(ws))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        env = _envelope(proc)
        assert env["status"] == "current", env
