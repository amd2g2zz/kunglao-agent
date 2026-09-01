# -*- coding: utf-8 -*-
"""tests/test_deploy_lifecycle_783.py — #783 T5 digest gate + T6 lifecycle e2e.

Closes the #783 takeover-comment remainder (2026-08-28):

  T5  deployed-manifest carrier `<ws>/.claude/deployed-manifest.json`
      written by BOTH deployment faces (deploy_workspace_copy /
      deployed_refresh.refresh); `kunglao check-stale` grows the third
      criterion (deploy-drift, rc=5) behind no-stamp > stale(version);
  T5 chain-hole — upgrade's already-at-version early-exit path refreshes
      deployed copies behind the SAME #753 B1 dirty gate;
  default-flip — real init materializes the deployment manifest and the
      registration inverts to workspace-local `uv run --project <ws>`;
  T6  full lifecycle: init -> tamper -> check-stale deploy-drift ->
      upgrade (same version) restores -> check-stale current + zero
      skill-install absolute paths in settings.json + init idempotency.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import template_version as tv  # noqa: E402

# #794 lesson: behavioral env vars must never leak into CLI children.
_BEHAVIORAL_ENV_VARS = ("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",)

GIT_IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@localhost")


def _run_cli(args: list[str], *, env: dict | None = None,
             timeout: int = 120) -> subprocess.CompletedProcess:
    """#794-shaped child env: inherit-minus-behavioral + forced UTF-8."""
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    for var in _BEHAVIORAL_ENV_VARS:
        full_env.pop(var, None)
    full_env.setdefault("PYTHONUTF8", "1")
    full_env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run([sys.executable, *args], cwd=str(ROOT),
                          env=full_env, capture_output=True,
                          encoding="utf-8", errors="replace", timeout=timeout)


def _check_stale(ws: Path) -> tuple[dict, subprocess.CompletedProcess]:
    proc = _run_cli([str(SCRIPTS / "kunglao.py"), "check-stale", str(ws)])
    envelope = json.loads(proc.stdout.strip().splitlines()[-1])
    return envelope, proc


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = m = mod
    spec.loader.exec_module(m)
    return m


def _dm():
    return _load("deploy_manifest_lc", "scripts/deploy_manifest.py")


def _upgrade():
    return _load("kunglao_upgrade_lc", "scripts/kunglao_upgrade.py")


def _deployed_ws(tmp_path: Path, *, stamp: str | None = None,
                 tag: str = "ws") -> Path:
    """A workspace with the deployment manifest materialized (phase-2
    'copies present' semantics) and a version stamp."""
    import hook_activation as ha
    ws = tmp_path / tag
    ws.mkdir(parents=True)
    ha.deploy_workspace_copy(ws)
    (ws / "CLAUDE.md").write_text(
        tv.stamp_line(stamp or tv.read_skill_version()) + "\n",
        encoding="utf-8")
    return ws


def _carrier(ws: Path) -> dict:
    return json.loads((ws / ".claude" / "deployed-manifest.json")
                      .read_text(encoding="utf-8"))


def _commands(ws: Path) -> list[str]:
    settings = json.loads((ws / ".claude" / "settings.json")
                          .read_text(encoding="utf-8"))
    return [h["command"]
            for face in settings.get("hooks", {}).values()
            for e in face for h in e.get("hooks", [])]


def _git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ws), *GIT_IDENTITY, *args],
                          capture_output=True, text=True)


def _hook_shas(ws: Path) -> dict[str, str]:
    hooks = ws / ".claude" / "hooks"
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(hooks.glob("*.py"))}


# ---------------------------------------------------------------------------
# T5 unit pins — manifest_digest single source
# ---------------------------------------------------------------------------

def test_manifest_digest_matches_yaml_contract_and_is_order_stable():
    """The digest algorithm is dest+sha256 concatenation, dest-sorted, and
    the recomputed closure agrees with the committed deploy-manifest.yaml
    (the CI --verify invariant this equivalence rests on)."""
    dm = _dm()
    entries = dm.build_entries()
    yaml_entries = dm.load_manifest_entries()
    assert entries and len(entries) == len(yaml_entries)

    d1 = dm.manifest_digest(entries)
    d2 = dm.manifest_digest(list(reversed(entries)))
    d3 = dm.manifest_digest(yaml_entries)
    assert d1 == d2, "digest must be order-independent (dest-sorted)"
    assert d1 == d3, "build_entries and the committed yaml must agree"


def test_deploy_workspace_copy_writes_carrier(tmp_path: Path):
    """T5 carrier: BOTH-face contract — deploy_workspace_copy leaves
    <ws>/.claude/deployed-manifest.json whose digest is the manifest
    digest, and reports it."""
    import hook_activation as ha
    dm = _dm()
    ws = tmp_path / "ws"
    ws.mkdir()

    report = ha.deploy_workspace_copy(ws)

    carrier = _carrier(ws)
    expected = dm.manifest_digest(dm.build_entries())
    assert carrier["schema_version"] == 2  # #810: dests list added
    assert carrier["deployed_digest"] == expected
    assert carrier["entries"] == len(dm.build_entries())
    assert carrier["deployed_at"]  # UTC iso stamp present
    assert report["digest"] == expected


def test_refresh_writes_and_rewrites_carrier(tmp_path: Path):
    """deployed_refresh (the upgrade face) stamps/refreshes the carrier."""
    import hook_activation as ha
    from deployed_refresh import refresh
    dm = _dm()
    ws = _deployed_ws(tmp_path)
    expected = dm.manifest_digest(dm.build_entries())
    assert _carrier(ws)["deployed_digest"] == expected  # deploy face wrote it

    target = ws / ".claude" / "hooks" / "write_guard.py"
    target.write_bytes(target.read_bytes() + b"\n# drifted\n")
    detail = refresh(ws)

    assert _carrier(ws)["deployed_digest"] == expected, (
        "refresh must re-stamp the carrier after restoring bytes")
    assert "carrier=" in detail, "refresh detail must surface the carrier"


# ---------------------------------------------------------------------------
# T5 unit pins — check-stale third criterion
# ---------------------------------------------------------------------------

def test_check_stale_deploy_drift_on_tampered_copy(tmp_path: Path):
    """Copies present + one hand-tampered byte -> status=deploy-drift rc=5,
    advice directs at upgrade. Untampered baseline stays current (no false
    positive from the criterion itself)."""
    ws = _deployed_ws(tmp_path)
    envelope, proc = _check_stale(ws)
    assert (envelope["status"], envelope["rc"]) == ("current", 0), envelope

    victim = ws / ".claude" / "hooks" / "write_guard.py"
    victim.write_bytes(victim.read_bytes() + b"\n# hand edit\n")

    envelope, proc = _check_stale(ws)
    assert proc.returncode == 5, envelope
    assert envelope["status"] == "deploy-drift", envelope
    assert "/kunglao-agent:upgrade" in envelope["advice"]
    assert "drift" in envelope["advice"]


def test_check_stale_deploy_drift_when_carrier_missing(tmp_path: Path):
    """Copies present but the carrier never written (pre-T5 deploy or hand
    deletion) -> deploy-drift; upgrade's refresh rewrites it."""
    import hook_activation as ha
    ws = _deployed_ws(tmp_path)
    (ws / ".claude" / "deployed-manifest.json").unlink()
    envelope, proc = _check_stale(ws)
    assert proc.returncode == 5
    assert envelope["status"] == "deploy-drift"


def test_check_stale_deploy_drift_when_stale_carrier_digest(tmp_path: Path):
    """A carrier stamped by an OLDER skill content (deployed_digest trails
    the current manifest) is drift even with untouched workspace bytes —
    the same-version skill-move case the semver leg cannot see."""
    ws = _deployed_ws(tmp_path)
    carrier = _carrier(ws)
    carrier["deployed_digest"] = "0" * 64
    (ws / ".claude" / "deployed-manifest.json").write_text(
        json.dumps(carrier), encoding="utf-8")
    envelope, proc = _check_stale(ws)
    assert proc.returncode == 5
    assert envelope["status"] == "deploy-drift"


def test_check_stale_version_stale_beats_deploy_drift(tmp_path: Path):
    """Priority pin: no-stamp > stale(version) > deploy-drift > current.
    A version-stale workspace reports stale even with drifted copies —
    the upgrade that fixes the version overwrites the copies anyway."""
    import hook_activation as ha
    ws = _deployed_ws(tmp_path, stamp="0.1.0")
    victim = ws / ".claude" / "hooks" / "write_guard.py"
    victim.write_bytes(victim.read_bytes() + b"\n# hand edit\n")
    envelope, proc = _check_stale(ws)
    assert proc.returncode == 5
    assert envelope["status"] == "stale", envelope


def test_check_stale_untouched_without_deployed_copies(tmp_path: Path):
    """Legacy workspace (no .claude/hooks) never enters the third
    criterion: current stamp -> current, regardless of any carrier."""
    ws = tmp_path / "legacy"
    ws.mkdir()
    (ws / "CLAUDE.md").write_text(
        tv.stamp_line(tv.read_skill_version()) + "\n", encoding="utf-8")
    envelope, proc = _check_stale(ws)
    assert (envelope["status"], envelope["rc"]) == ("current", 0)


# ---------------------------------------------------------------------------
# T5 chain-hole — upgrade early-exit refresh
# ---------------------------------------------------------------------------

def _early_exit_ws(tmp_path: Path, tag: str) -> Path:
    """Deployed workspace stamped ABOVE the skill target so upgrade()
    takes the already-at-version early-exit path (plan empty)."""
    return _deployed_ws(tmp_path, stamp="0.1.4", tag=tag)


def test_upgrade_early_exit_refreshes_copies_and_carrier(tmp_path: Path):
    """The chain-hole: already-at-version + drifted copies -> upgrade still
    restores the bytes and re-stamps the carrier (advice must not spin)."""
    up = _upgrade()
    ws = _early_exit_ws(tmp_path, "early")
    for args in (("init",), ("add", "-A"), ("commit", "--no-gpg-sign",
                                             "-m", "base")):
        assert _git(ws, *args).returncode == 0
    victim = ws / ".claude" / "hooks" / "write_guard.py"
    original = victim.read_bytes()
    victim.write_bytes(original + b"\n# drifted\n")
    (ws / "CLAUDE.md").write_text(
        (ws / "CLAUDE.md").read_text(encoding="utf-8") + "local edit\n",
        encoding="utf-8")
    assert _git(ws, "add", "-A").returncode == 0
    assert _git(ws, "commit", "--no-gpg-sign", "-m", "drift").returncode == 0

    items: list = []
    rc = up.upgrade(ws, dry_run=False, items_out=items)

    assert rc == 0
    assert victim.read_bytes() == original, "early exit must refresh copies"
    dm = _dm()
    assert _carrier(ws)["deployed_digest"] == \
        dm.manifest_digest(dm.build_entries())
    assert any("deployed_refresh" in str(i.get("name")) for i in items), items


def test_upgrade_early_exit_refuses_dirty_workspace(tmp_path: Path):
    """#753 B1 parity: the early-exit refresh writes the tree, so a dirty
    owned repo is refused RC=6 BEFORE any copy is touched."""
    up = _upgrade()
    ws = _early_exit_ws(tmp_path, "dirty")
    for args in (("init",), ("add", "-A"), ("commit", "--no-gpg-sign",
                                             "-m", "base")):
        assert _git(ws, *args).returncode == 0
    victim = ws / ".claude" / "hooks" / "write_guard.py"
    original = victim.read_bytes()
    victim.write_bytes(original + b"\n# uncommitted drift\n")

    rc = up.main([str(ws)])

    assert rc == 6, "dirty workspace must be refused on the fast path too"
    assert b"# uncommitted drift" in victim.read_bytes(), (
        "refusal must precede every copy write")


def test_upgrade_early_exit_dry_run_lists_refresh_item(tmp_path: Path):
    """The dry-run plan on an already-current workspace must surface the
    deployed-refresh item (noop) when copies actually drifted, without
    touching a single byte."""
    up = _upgrade()
    ws = _early_exit_ws(tmp_path, "dryws")
    victim = ws / ".claude" / "hooks" / "write_guard.py"
    victim.write_bytes(victim.read_bytes() + b"\n# drift\n")
    before = victim.read_bytes()

    items: list = []
    rc = up.upgrade(ws, dry_run=True, items_out=items)

    assert rc == 0
    assert any("deployed_refresh(dry)" in str(i.get("name")) for i in items), \
        items
    assert victim.read_bytes() == before


def test_upgrade_early_exit_no_drift_stays_true_noop(tmp_path: Path):
    """#726 already-current contract preserved: current copies + no drift ->
    the fast path stays a noop (rc 0, no item, no #753 gate) even when the
    tree is dirty — the gate only fires when a write is actually required."""
    up = _upgrade()
    ws = _early_exit_ws(tmp_path, "noopws")
    for args in (("init",), ("add", "-A"), ("commit", "--no-gpg-sign",
                                             "-m", "base")):
        assert _git(ws, *args).returncode == 0
    (ws / "CLAUDE.md").write_text(
        (ws / "CLAUDE.md").read_text(encoding="utf-8") + "user edit\n",
        encoding="utf-8")  # dirty tree, but copies are current

    items: list = []
    rc = up.upgrade(ws, dry_run=False, items_out=items)

    assert rc == 0, "no-drift fast path must stay a noop"
    assert not any("deployed_refresh" in str(i.get("name")) for i in items)


# ---------------------------------------------------------------------------
# T6 — full lifecycle e2e (real init subprocess)
# ---------------------------------------------------------------------------

def _init_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "e2e"
    ws.mkdir()
    (ws / "bins").mkdir()
    (ws / "bins" / "sample.exe").write_bytes(b"\x00\x01\x02")
    proc = _run_cli([
        str(SCRIPTS / "kunglao-init.py"), str(ws),
        "--type", "linux", "--skip-toolchain", "--assume-yes",
    ])
    assert proc.returncode == 0, (
        f"init failed:\nstdout={proc.stdout[-2000:]!r}\n"
        f"stderr={proc.stderr[-2000:]!r}")
    return ws


def test_lifecycle_init_drift_upgrade_current(tmp_path: Path):
    """T6 chain: real init deploys copies + carrier + inverted settings ->
    tamper -> check-stale deploy-drift -> same-version upgrade restores ->
    check-stale current + zero skill-install paths -> init idempotent."""
    ws = _init_ws(tmp_path)

    # 1. init materialized the deployment + carrier + inverted registration
    hooks_dir = ws / ".claude" / "hooks"
    assert (hooks_dir / "dispatch_gate.py").is_file(), "hooks deployed"
    assert (ws / ".claude" / "agents" / "kunglao-worker.md").is_file()
    dm = _dm()
    carrier = _carrier(ws)
    assert carrier["deployed_digest"] == dm.manifest_digest(
        dm.build_entries()), "init must stamp the deployment carrier"
    cmds = _commands(ws)
    assert cmds, "settings.json must carry the hook registry"
    for c in cmds:
        assert f"uv run --project {ws.as_posix()}" in c, c
        assert "/.claude/hooks/" in c.replace("\\", "/"), c

    # 2. hand-tamper one deployed copy -> gate flips to deploy-drift
    victim = hooks_dir / "write_guard.py"
    original = victim.read_bytes()
    victim.write_bytes(original + b"\n# local tinkering\n")
    envelope, proc = _check_stale(ws)
    assert proc.returncode == 5, envelope
    assert envelope["status"] == "deploy-drift", envelope

    # 3. same-version upgrade (git-clean per init's #739 commit) restores
    assert _git(ws, "add", "-A").returncode == 0
    assert _git(ws, "commit", "--no-gpg-sign", "-m",
                "local drift").returncode == 0
    up_proc = _run_cli([str(SCRIPTS / "kunglao_upgrade.py"), str(ws)],
                       env={"KUNGLAO_UPGRADE_NO_UV_SYNC": "1"})
    assert up_proc.returncode == 0, up_proc.stderr[-2000:]
    assert victim.read_bytes() == original, "upgrade must restore bytes"
    assert _carrier(ws)["deployed_digest"] == dm.manifest_digest(
        dm.build_entries()), "upgrade must re-stamp the carrier"

    # 4. gate back to current; zero skill-install absolute paths remain
    envelope, proc = _check_stale(ws)
    assert (envelope["status"], envelope["rc"]) == ("current", 0), envelope
    settings_text = (ws / ".claude" / "settings.json").read_text(
        encoding="utf-8")
    assert "/.claude/skills/" not in settings_text, (
        "settings.json must not reference the skill install")

    # 5. init idempotent re-run: deployed copies byte-identical
    before = _hook_shas(ws)
    proc2 = _run_cli([
        str(SCRIPTS / "kunglao-init.py"), str(ws),
        "--type", "linux", "--skip-toolchain", "--assume-yes",
    ])
    assert proc2.returncode == 0, proc2.stderr[-2000:]
    assert _hook_shas(ws) == before, "init re-run must not mutate copies"


def test_deploy_backup_dirs_are_iron_rule_exempt():
    """T6-found defect pin: #791's refresh backs modified copies up under
    runs/deploy-backup-*/ — framework-owned forensics, exempt from the
    #726 iron-rule digest exactly like runs/upgrade-snapshot.* (D4 class).
    Without this, every real drift-repair upgrade dies with RC=4."""
    up = _upgrade()
    assert up._is_exempt("runs/deploy-backup-20260827T164645Z/hooks/"
                         "write_guard.py")
    assert up._is_exempt("runs/deploy-backup-orphan/intruder.py")
    assert not up._is_exempt("runs/worker-status-C001.txt"), (
        "real user data stays protected")
