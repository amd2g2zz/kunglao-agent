# -*- coding: utf-8 -*-
"""tests/test_upgrade_identity_655.py — upgrade identity = source head hash.

issue 655: `kunglao upgrade` keyed currency on the VERSION STRING ("already at
version 0.1.6-rc1"), so a re-cut release batch carrying different content
under the SAME version number was indistinguishable to the upgrade face.
The update identity is now the SOURCE TREE's git head hash (the deployed-
manifest carrier records it; the manifest digest is the fallback when the
executing tree is not a git checkout), and the version number stays
human-facing metadata. Pinned here:

  1. same version + different head hash -> refresh happens AND the hash
     change is reported explicitly;
  2. same head hash -> report current, no refresh;
  3. version-only differences neither block a refresh nor fake currency;
  4. the carrier records the head hash (+ version metadata).

The RECORDED side is driven by rewriting the workspace carrier (the
identity witness); the CURRENT side is this repo's real git head, so the
head-vs-head legs need no production seam monkeypatched.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import deploy_manifest as dm  # noqa: E402
import template_version as tv  # noqa: E402

GIT_IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@localhost")


@pytest.fixture(autouse=True)
def _isolated_upgrade_home(tmp_path, monkeypatch):
    """Path.home isolation (upgrade tests' standing protection class): the
    statusline verify/heal faces must never read the operator's real
    ~/.claude."""
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _upgrade():
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade_id655", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["kunglao_upgrade_id655"] = mod
    spec.loader.exec_module(mod)
    return mod


def _git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *GIT_IDENTITY, *args],
                          capture_output=True, text=True)


def _carrier(ws: Path) -> dict:
    return json.loads((ws / ".claude" / "deployed-manifest.json")
                      .read_text(encoding="utf-8"))


def _write_carrier(ws: Path, doc: dict) -> None:
    (ws / ".claude" / "deployed-manifest.json").write_text(
        json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _deployed_ws(tmp_path: Path, tag: str, *, stamp: str | None = None) -> Path:
    """A deployed-copies workspace at the given stamp (default: current
    skill version -> the upgrade fast path), with the carrier written by the
    REAL deploy face (so it records this repo's real head), the required
    intake answers present, and a clean git repo (the refresh face writes,
    so the rollback-anchor hygiene of issue 753 applies)."""
    import hook_activation as ha
    ws = tmp_path / tag
    ws.mkdir(parents=True)
    ha.deploy_workspace_copy(ws)  # carrier write rides this face
    (ws / "CLAUDE.md").write_text(
        tv.stamp_line(stamp or tv.read_skill_version()) + "\n",
        encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: identity goal\n"
        "success_criterion: identity criterion\n"
        "verification_method: manual\n", encoding="utf-8")
    assert _git(ws, "init").returncode == 0
    assert _git(ws, "add", "-A").returncode == 0
    assert _git(ws, "commit", "--no-gpg-sign", "-m", "base").returncode == 0
    return ws


def _refresh_items(items: list) -> list:
    return [i for i in items if "deployed_refresh" in str(i.get("name"))]


# ---------------------------------------------------------------------------
# 4. the carrier records the head hash (+ version metadata)
# ---------------------------------------------------------------------------

def test_carrier_records_head_hash_and_version_metadata(tmp_path: Path):
    ws = _deployed_ws(tmp_path, "carrier")
    head = dm.source_head()
    assert head, "test requires a git-backed source tree"
    doc = _carrier(ws)
    assert doc["source_head"] == head, "carrier must record the head hash"
    assert doc["source_version"] == tv.read_skill_version(), \
        "version stays human-facing metadata on the carrier"
    # the digest face of issue 783 is untouched (check-stale reads it)
    # — and the identity decision itself is never inferred from the version.
    assert doc["deployed_digest"] == dm.manifest_digest(dm.build_entries())


def test_source_head_none_when_tree_is_not_its_own_repo_top(tmp_path: Path):
    """A plugin copy nested inside an unrelated host repo must NOT inherit
    the host's head — identity would move on unrelated commits. Not-own-top
    (and not-a-repo) answer None -> the digest fallback carries identity."""
    nested = tmp_path / "nested"
    nested.mkdir()
    assert dm.source_head(nested) is None


# ---------------------------------------------------------------------------
# 2. same head hash -> report current, no refresh
# ---------------------------------------------------------------------------

def test_same_head_reports_current_without_refresh(tmp_path: Path, capsys):
    up = _upgrade()
    ws = _deployed_ws(tmp_path, "same")
    head = dm.source_head()
    assert _carrier(ws)["source_head"] == head
    sentinel = ws / ".claude" / "hooks" / "write_guard.py"
    before = sentinel.read_bytes()
    carrier_before = _carrier(ws)
    items: list = []

    rc = up.upgrade(ws, dry_run=False, items_out=items)

    assert rc == 0
    out = capsys.readouterr().out
    assert "already at version" in out
    assert "current" in out.lower()
    assert head[:12] in out, "the identity (not just the version) is spoken"
    assert not _refresh_items(items), f"same head must not refresh: {items}"
    assert sentinel.read_bytes() == before
    assert _carrier(ws) == carrier_before, "no refresh -> carrier untouched"


# ---------------------------------------------------------------------------
# 1. same version + different head hash -> refresh + explicit hash report
# ---------------------------------------------------------------------------

def test_same_version_different_head_refreshes_and_reports(tmp_path: Path,
                                                           capsys):
    """The re-cut batch case: version 0.1.6-rc1 deployed from an older head
    is NOT current even though the version string matches. Bytes and digest
    are current (drift is silent) — ONLY the head difference drives this
    run, so the refresh proves the identity gate fires on its own."""
    up = _upgrade()
    ws = _deployed_ws(tmp_path, "moved")
    head = dm.source_head()
    assert head
    stale = "0" * 40
    doc = _carrier(ws)
    doc["source_head"] = stale  # deployed from an older batch, same version
    _write_carrier(ws, doc)
    assert _git(ws, "add", "-A").returncode == 0
    assert _git(ws, "commit", "--no-gpg-sign",
                "-m", "older batch carrier").returncode == 0
    assert dm.deploy_drift(ws)["drift"] is False, \
        "bytes+digest current: only the head moved"
    items: list = []

    rc = up.upgrade(ws, dry_run=False, items_out=items)

    assert rc == 0
    out = capsys.readouterr().out
    assert stale in out and head in out, \
        "hash change (old -> new) must be reported explicitly"
    assert "already at version" not in out, \
        "version-only currency must not be faked when the head differs"
    assert _refresh_items(items), f"head change must trigger the refresh: {items}"
    assert _carrier(ws)["source_head"] == head, \
        "the refresh re-records the current head"

    # ... and the next run is a true no-op: identity now current.
    items2: list = []
    rc = up.upgrade(ws, dry_run=False, items_out=items2)
    assert rc == 0
    assert not _refresh_items(items2), items2
    assert "already at version" in capsys.readouterr().out


def test_head_change_dry_run_plans_without_writing(tmp_path: Path, capsys):
    up = _upgrade()
    ws = _deployed_ws(tmp_path, "dry")
    head = dm.source_head()
    doc = _carrier(ws)
    doc["source_head"] = "0" * 40
    _write_carrier(ws, doc)
    carrier_bytes = (ws / ".claude" / "deployed-manifest.json").read_bytes()
    items: list = []

    rc = up.upgrade(ws, dry_run=True, items_out=items)

    assert rc == 0
    out = capsys.readouterr().out
    assert head in out, "dry-run reports the identity change too"
    assert _refresh_items(items), items
    assert (ws / ".claude" / "deployed-manifest.json").read_bytes() == \
        carrier_bytes, "dry-run writes nothing"


# ---------------------------------------------------------------------------
# 3. version-only differences never block a refresh nor fake currency
# ---------------------------------------------------------------------------

def test_version_only_difference_is_metadata_not_currency(tmp_path: Path,
                                                          capsys):
    """Same head, stamp ABOVE the target: the version string alone neither
    blocks currency nor fakes staleness — the head hash decides. (The
    reverse direction — same version, moved head still refreshes — is
    pinned by test_same_version_different_head_refreshes_and_reports.)"""
    up = _upgrade()
    ws = _deployed_ws(tmp_path, "veronly", stamp="9.9.9")
    head = dm.source_head()
    items: list = []

    rc = up.upgrade(ws, dry_run=False, items_out=items)

    assert rc == 0
    out = capsys.readouterr().out
    assert "already at version 9.9.9" in out
    assert head[:12] in out
    assert not _refresh_items(items), items


# ---------------------------------------------------------------------------
# digest fallback — non-git installs
# ---------------------------------------------------------------------------

def test_digest_fallback_when_head_unavailable(tmp_path: Path, capsys,
                                               monkeypatch):
    """Plugin/zip installs (no git top): identity falls back to the manifest
    digest the carrier already records. A matching digest still reports
    current (no false refresh) and the report names the digest basis."""
    monkeypatch.setattr(dm, "source_head", lambda root=None: None)
    up = _upgrade()
    ws = _deployed_ws(tmp_path, "nogit")
    doc = _carrier(ws)
    assert not doc.get("source_head")
    assert doc["deployed_digest"] == dm.manifest_digest(dm.build_entries())
    items: list = []

    rc = up.upgrade(ws, dry_run=False, items_out=items)

    assert rc == 0
    out = capsys.readouterr().out
    assert "current" in out.lower()
    assert "source manifest digest" in out
    assert not _refresh_items(items), items
