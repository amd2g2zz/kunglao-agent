# -*- coding: utf-8 -*-
"""tests/test_deploy_surface_755.py — issue #755 upgrade deployment surface.

Wave-2 items complete what Wave-1's migration registry could not touch:

  A2 (T1) `_item_agents_refresh` — L2 subagents re-copy: the executing
          install's agents/ are truth (#478 deploy semantics mirrored);
          ws `.claude/agents/*.md` drift is repaired byte-exactly.
  A4/A5/A6 (T3) config trio refresh — .mcp.json scaffold backfill,
          env-manifest.yaml ledger backfill / version-field refresh,
          toolchain-manifest existence check (code-reality ruling).
  A7 (T4) `_item_uv_sync` — install-root `uv sync --locked`, WARN-only.
  A1 (T5) `_item_skill_staleness_check` — detect+report install git lag.

All items are idempotent and WARN-only (never flip the upgrade exit code).
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
AGENTS_SRC = REPO / "agents"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import template_version as tv  # noqa: E402
from event_taxonomy import EMIT_ACTIONS  # noqa: E402
from _factories import seed_bins


def _load_upgrade():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CUR_VERSION = tv.read_skill_version()
STAMP = tv.stamp_line(CUR_VERSION)

CORE_AGENTS = ("kunglao-worker.md", "kunglao-redteam.md",
               "kunglao-init-worker.md")


def _fixture_ws(tmp_path: Path) -> Path:
    """Minimal CURRENT-stamped workspace (deploy items apply around a
    current frame so no cross-talk with the G4 stamp gate)."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "CLAUDE.md").write_text(STAMP + "\n\n# frame body placeholder\n",
                                  encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        f"state_hash=abc\nproject_type=windows\n", encoding="utf-8")
    (ws / ".claude").mkdir()
    (ws / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
    (ws / "runs").mkdir()
    return ws


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def _log_actions(ws: Path) -> list[str]:
    out: list[str] = []
    for log in (ws / "runs" / "logs").glob("kunglao-*.jsonl"):
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line).get("action"))
    return out


# ================================================================ T1 / A2

class TestA2AgentsRefresh:
    def test_vocab_registered(self):
        assert "agents_refresh" in EMIT_ACTIONS
        assert EMIT_ACTIONS == sorted(set(EMIT_ACTIONS))

    def test_stale_and_missing_agents_are_repairoled(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        adir = ws / ".claude" / "agents"
        adir.mkdir()
        stale = (adir / "kunglao-worker.md")
        stale.write_text("# stale worker agent body\n", encoding="utf-8")

        up = _load_upgrade()
        label = up._item_agents_refresh(ws, False)

        src_worker = AGENTS_SRC / "kunglao-worker.md"
        assert stale.read_bytes() == src_worker.read_bytes(), (
            "stale agent must be re-copied byte-exact from the executing "
            "install source")
        for name in CORE_AGENTS[1:]:
            got = adir / name
            assert got.is_file(), name
            assert got.read_bytes() == (AGENTS_SRC / name).read_bytes(), name
        assert _md5(stale) == _md5(src_worker)
        assert "agents_refresh" in label

    def test_matching_agents_untouched_idempotent(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        adir = ws / ".claude" / "agents"
        adir.mkdir()
        for name in CORE_AGENTS:
            (adir / name).write_bytes((AGENTS_SRC / name).read_bytes())
        pre = {n: _md5(adir / n) for n in CORE_AGENTS}

        up = _load_upgrade()
        first = up._item_agents_refresh(ws, False)
        assert "unchanged" in first or "noop" in first
        assert {n: _md5(adir / n) for n in CORE_AGENTS} == pre
        # second run agrees (idempotent fixed point)
        second = up._item_agents_refresh(ws, False)
        assert second == first or "unchanged" in second

    def test_event_emitted(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        (ws / ".claude" / "agents").mkdir()
        (ws / ".claude" / "agents" / "kunglao-worker.md").write_text(
            "old\n", encoding="utf-8")
        up = _load_upgrade()
        up._item_agents_refresh(ws, False)
        assert "agents_refresh" in _log_actions(ws)

    def test_dry_run_writes_nothing(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        adir = ws / ".claude" / "agents"
        adir.mkdir()
        (adir / "kunglao-worker.md").write_text("stale\n", encoding="utf-8")
        before = {p: p.read_bytes() for p in adir.rglob("*") if p.is_file()}
        up = _load_upgrade()
        up._item_agents_refresh(ws, True)
        after = {p: p.read_bytes() for p in adir.rglob("*") if p.is_file()}
        assert before == after

    def test_source_defect_fails_warn_only(self, tmp_path):
        """A repo-layout defect (agent source missing) must degrade to a
        WARN-face label + stderr line, never raise through the migration."""
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()

        class FakeNs:
            AGENTS_SRC = tmp_path / "not-a-repo-agents"

            @staticmethod
            def _unused():  # pragma: no cover
                pass

        up._init_mod = lambda: FakeNs
        label = up._item_agents_refresh(ws, False)
        assert "warn" in label.lower() or "skip" in label.lower()


# ============================================================ T3 / A4+A5+A6

import yaml  # noqa: E402


class TestA4McpRefresh:
    def test_missing_scaffold_is_rebuilt(self, tmp_path):
        import mcp_probe
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        label = up._item_mcp_refresh(ws, False)
        p = ws / ".mcp.json"
        assert p.is_file() and "create" in label
        got = json.loads(p.read_text(encoding="utf-8"))
        want = mcp_probe.build_scaffold_json()
        assert got == want, "backfill must be the init-parity scaffold"
        assert got["mcpServers"] == {}, \
            "scaffold never fabricates registrations (#316)"

    def test_existing_file_never_touched(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        p = ws / ".mcp.json"
        original = '{"mcpServers": {"custom": {"command": "user-server"}}}'
        p.write_text(original, encoding="utf-8")
        up = _load_upgrade()
        label = up._item_mcp_refresh(ws, False)
        assert p.read_text(encoding="utf-8") == original
        assert "noop" in label or "present" in label

    def test_dry_run_writes_nothing(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        up._item_mcp_refresh(ws, True)
        assert not (ws / ".mcp.json").exists()


def _ledger(tmp_path: Path, data: dict) -> Path:
    ws = _fixture_ws(tmp_path)
    (ws / ".kunglao-init.json").write_text(
        json.dumps({"project_type": "android", "state_hash": "x",
                    "seed_count": 8, "ts": "t"}), encoding="utf-8")
    (ws / "env-manifest.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return ws


FULL_LEDGER = {
    "generated": "2026-08-01T00:00:00Z",
    "project_type": "android",
    "components": [{"name": "hooks", "status": "deployed"}],
}


class TestA5EnvLedgerRefresh:
    def test_vocab_registered(self):
        assert "env_ledger_refresh" in EMIT_ACTIONS

    def test_missing_backfilled_with_channel_row(self, tmp_path, monkeypatch):
        import init_channel_default as icd
        ws = _fixture_ws(tmp_path)
        (ws / ".kunglao-init.json").write_text(json.dumps(
            {"project_type": "linux", "state_hash": "x",
             "seed_count": 8, "ts": "t"}), encoding="utf-8")
        monkeypatch.setattr(icd, "resolve_init_channel", lambda _ws: icd
                            .ChannelDecision(selected="local",
                                             defaulted_to_local=True,
                                             probes={}, warn_reason="probe x"))
        up = _load_upgrade()
        label = up._item_env_manifest_refresh(ws, False)
        p = ws / "env-manifest.yaml"
        assert p.is_file() and "create" in label
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        for key in ("generated", "project_type", "components"):
            assert key in data, key
        assert "version" not in data, (
            "a version key would flip the env-facts loader discriminator "
            "(#450 governance)")
        assert data["project_type"] == "linux"
        row = next(c for c in data["components"] if c["name"] == "channel")
        assert row["status"] == "defaulted-local" or "local" in str(row)

    def test_defaulted_local_warns(self, tmp_path, capsys, monkeypatch):
        import init_channel_default as icd
        ws = _fixture_ws(tmp_path)
        monkeypatch.setattr(icd, "resolve_init_channel", lambda _ws: icd
                            .ChannelDecision(selected="local",
                                             defaulted_to_local=True,
                                             probes={},
                                             warn_reason="no remote lane"))
        up = _load_upgrade()
        up._item_env_manifest_refresh(ws, False)
        err = capsys.readouterr().err
        assert "WARN" in err
        assert "env_ledger_refresh" in _log_actions(ws)

    def test_existing_gets_version_field_only(self, tmp_path):
        cur = tv.read_skill_version()
        stale = dict(FULL_LEDGER, kunglao_version="0.0.9")
        ws = _ledger(tmp_path, stale)
        p = ws / "env-manifest.yaml"
        up = _load_upgrade()
        label = up._item_env_manifest_refresh(ws, False)
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        assert data["kunglao_version"] == cur
        assert data["components"] == FULL_LEDGER["components"], \
            "component history must survive a metadata refresh"
        assert data["generated"] == FULL_LEDGER["generated"]
        assert "refresh" in label

    def test_unparseable_existing_stays_warn_only(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        (ws / "env-manifest.yaml").write_text(":::: not yaml ::::",
                                              encoding="utf-8")
        up = _load_upgrade()
        label = up._item_env_manifest_refresh(ws, False)
        assert "warn" in label.lower()


class TestA6ToolchainManifest:
    def test_init_report_skill_version_refreshed(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        report = ws / "runs" / ".init-report.json"
        report.write_text(json.dumps({
            "ts": "t", "skill_version": "0.1.1", "phases": [],
            "overall": "ok", "exit": 0}), encoding="utf-8")
        up = _load_upgrade()
        label = up._item_toolchain_manifest(ws, False)
        data = json.loads(report.read_text(encoding="utf-8"))
        assert data["skill_version"] == tv.read_skill_version()
        assert "refresh" in label or "current" in label

    def test_absence_reports_without_fabrication(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        label = up._item_toolchain_manifest(ws, False)
        assert "missing" in label or "absent" in label
        assert not (ws / ".kunglao-init.json").exists(), \
            "upgrade must never fabricate init-completeness state (#625)"
        assert not (ws / "runs" / ".toolchain-lock.yaml").exists()

    def test_dry_run_writes_nothing(self, tmp_path):
        ws = _fixture_ws(tmp_path)
        report = ws / "runs" / ".init-report.json"
        report.write_text('{"skill_version":"0.1.1"}', encoding="utf-8")
        before = report.read_bytes()
        up = _load_upgrade()
        up._item_toolchain_manifest(ws, True)
        assert report.read_bytes() == before


# ================================================================ T4 / A7

class TestA7UvSync:
    ERR = "[event] name=uv_sync"

    @staticmethod
    def _patch_which(monkeypatch, up, path):
        import shutil as _shutil
        monkeypatch.setattr(_shutil, "which",
                            lambda name, *a, **k: path)

    def test_vocab_registered(self):
        assert "uv_sync" in EMIT_ACTIONS

    def test_success_event_ok(self, tmp_path, monkeypatch, capsys):
        import subprocess
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        self._patch_which(monkeypatch, up, "/fake/uv")

        seen: dict = {}

        def fake_run(argv, **kw):
            seen["argv"] = argv
            seen["timeout"] = kw.get("timeout")
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr(up.subprocess, "run", fake_run)
        label = up._item_uv_sync(ws, False)
        assert "ok" in label
        assert "--locked" in seen["argv"]
        assert "--project" in seen["argv"]
        assert seen["timeout"], "sync must be timeout-bounded"
        assert self.ERR in capsys.readouterr().err

    def test_failure_is_warn_not_fatal(self, tmp_path, monkeypatch, capsys):
        import subprocess
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        self._patch_which(monkeypatch, up, "/fake/uv")
        monkeypatch.setattr(
            up.subprocess, "run",
            lambda a, **k: subprocess.CompletedProcess(a, 3, "", "boom"))
        label = up._item_uv_sync(ws, False)
        assert "warn" in label.lower()
        err = capsys.readouterr().err
        assert "WARN" in err and "uv_sync" in err  # git-binary precedent

    def test_timeout_is_warn(self, tmp_path, monkeypatch, capsys):
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        self._patch_which(monkeypatch, up, "/fake/uv")

        def slow(a, **k):
            raise up.subprocess.TimeoutExpired(cmd=a, timeout=k["timeout"])

        monkeypatch.setattr(up.subprocess, "run", slow)
        label = up._item_uv_sync(ws, False)
        assert "warn" in label.lower()
        assert "timeout" in capsys.readouterr().err.lower()

    def test_missing_binary_skips_without_run(self, tmp_path,
                                              monkeypatch, capsys):
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        self._patch_which(monkeypatch, up, None)

        def must_not_run(*a, **k):  # pragma: no cover
            raise AssertionError("subprocess must not run without uv")

        monkeypatch.setattr(up.subprocess, "run", must_not_run)
        label = up._item_uv_sync(ws, False)
        assert "warn" in label.lower()
        assert "uv" in capsys.readouterr().err.lower()

    def test_dry_run_invokes_nothing(self, tmp_path, monkeypatch):
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        self._patch_which(monkeypatch, up, "/fake/uv")

        def must_not_run(*a, **k):  # pragma: no cover
            raise AssertionError("dry-run must stay side-effect free")

        monkeypatch.setattr(up.subprocess, "run", must_not_run)
        assert "dry" in up._item_uv_sync(ws, True)

    def test_targets_install_root_not_workspace(self, tmp_path,
                                                monkeypatch):
        import subprocess
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        self._patch_which(monkeypatch, up, "/fake/uv")
        seen: dict = {}

        def fake_run(argv, **kw):
            seen["argv"] = list(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        monkeypatch.setattr(up.subprocess, "run", fake_run)
        up._item_uv_sync(ws, False)
        proj = seen["argv"][seen["argv"].index("--project") + 1]
        assert Path(proj).resolve() != ws.resolve(), (
            "the analysis venv lives under the INSTALL root (#752 seam), "
            "never inside the user workspace")


# ================================================================ T5 / A1

class TestA1SkillStaleness:
    """Detect+report ONLY — self-update stays with the user's git pull."""

    @staticmethod
    def _fake_git(up, monkeypatch, mapping):
        def fake_run_git(root, *args):
            key = " ".join(args)
            row = mapping.get(key)
            if row is None:
                return type("P", (), {"returncode": 128, "stdout": "",
                                      "stderr": "unexpected"})()
            rc, out = row
            return type("P", (), {"returncode": rc, "stdout": out,
                                  "stderr": ""})()

        monkeypatch.setattr(up, "_git_at", fake_run_git)
        return up

    def test_vocab_registered(self):
        assert "skill_install_staleness" in EMIT_ACTIONS

    def _cloneish(self, tmp_path: Path) -> Path:
        root = tmp_path / "install-root"
        (root / ".git").mkdir(parents=True)
        return root

    def test_behind_n_reports(self, tmp_path, monkeypatch, capsys):
        ws = _fixture_ws(tmp_path)
        up = self._fake_git(_load_upgrade(), monkeypatch, {
            "rev-parse --abbrev-ref HEAD": (0, "main\n"),
            "rev-parse --symbolic-full-name @{u}": (128, "",),
            "rev-list --count HEAD..origin/main": (0, "4\n"),
        })
        monkeypatch.setattr(up, "_exec_install_root",
                            lambda: self._cloneish(tmp_path))
        label = up._item_skill_staleness_check(ws, False)
        assert "behind=4" in label or "behind 4" in label
        assert ("name=skill_install_staleness status=warn"
                in capsys.readouterr().err)

    def test_parity_is_ok_event(self, tmp_path, monkeypatch, capsys):
        ws = _fixture_ws(tmp_path)
        up = self._fake_git(_load_upgrade(), monkeypatch, {
            "rev-parse --abbrev-ref HEAD": (0, "dev\n"),
            "rev-parse --symbolic-full-name @{u}": (128, ""),
            "rev-list --count HEAD..origin/dev": (0, "0\n"),
        })
        monkeypatch.setattr(up, "_exec_install_root",
                            lambda: self._cloneish(tmp_path))
        up._item_skill_staleness_check(ws, False)
        err = capsys.readouterr().err
        assert ("name=skill_install_staleness status=ok" in err)

    def test_upstream_ref_preferred_when_set(self, tmp_path,
                                             monkeypatch, capsys):
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        seen: list[str] = []

        def fake_run_git(root, *args):
            key = " ".join(args)
            seen.append(key)
            table = {
                "rev-parse --abbrev-ref HEAD": (0, "dev\n"),
                "rev-parse --symbolic-full-name @{u}":
                    (0, "origin/dev2\n"),
                "rev-list --count HEAD..origin/dev2": (0, "0\n"),
            }
            row = table.get(key)
            if row is None:
                raise AssertionError(f"unexpected git probe: {key}")
            rc, out = row
            return type("P", (), {"returncode": rc, "stdout": out,
                                  "stderr": ""})()

        monkeypatch.setattr(up, "_git_at", fake_run_git)
        monkeypatch.setattr(up, "_exec_install_root",
                            lambda: self._cloneish(tmp_path))
        up._item_skill_staleness_check(ws, False)
        assert any("HEAD..origin/dev2" in k for k in seen), \
            "an upstream ref must be preferred over origin/<branch>"

    def test_not_a_clone_skips_quietly(self, tmp_path, monkeypatch, capsys):
        ws = _fixture_ws(tmp_path)
        up = _load_upgrade()
        monkeypatch.setattr(up, "_exec_install_root",
                            lambda: tmp_path / "plain-dir-no-git")
        called = {"n": 0}

        def must_not(*a, **k):
            called["n"] += 1
            return None

        monkeypatch.setattr(up, "_git_at", must_not)
        label = up._item_skill_staleness_check(ws, False)
        assert "skip" in label.lower()
        assert called["n"] == 0
        assert "skill_install_staleness" not in capsys.readouterr().err

    def test_git_failure_is_warn_face(self, tmp_path, monkeypatch, capsys):
        ws = _fixture_ws(tmp_path)
        up = self._fake_git(_load_upgrade(), monkeypatch, {
            "rev-parse --abbrev-ref HEAD": (128, "",),
        })
        monkeypatch.setattr(up, "_exec_install_root",
                            lambda: self._cloneish(tmp_path))
        label = up._item_skill_staleness_check(ws, False)
        assert "warn" in label.lower()
        assert "WARN" in capsys.readouterr().err


# ================================================================ T6 registry

def _render_legacy_body(tmp_path: Path, project_type: str = "windows"):
    """An UNMARKED render of today's template — stands in for a real
    v0.1.x artifact (same skeleton, no G2 pair yet)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        f"init_legacy_{project_type}", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SKILL_DIR = Path("/kunglao/install-under-test")
    sys.version_info_backup = None
    ws = tmp_path / f"legacy-render-{project_type}"
    seed_bins(ws, payload=b"MZ\x90\x00" + b"\x00" * 64)
    target = mod.write_claudemd(ws, "sample.exe",
                                hashlib.sha256(b"MZ\x90\x00"
                                               + b"\x00" * 64).hexdigest(),
                                project_type=project_type)
    text = target.read_text(encoding="utf-8")
    stripped = "\n".join(
        l for l in text.splitlines()
        if not l.startswith("<!-- kunglao:frame:")
        and l.strip() != "<!-- /kunglao:frame -->")
    return stripped + "\n"


class TestT6Registry:
    def test_entry_0_1_4_registered_with_stamp_carry(self, tmp_path):
        up = _load_upgrade()
        versions = [v for v, _fn in up.MIGRATIONS]
        assert "0.1.4" in versions, (
            "T6 ruling (design D1): tri-segment entry '0.1.4' so a "
            "0.1.3-stamped workspace re-plans instead of short-circuiting")
        assert versions.index("0.1.3") < versions.index("0.1.4"), \
            "registry stays linear"
        last_fn = up.MIGRATIONS[-1][1]
        items = last_fn(_fixture_ws(tmp_path), True)
        assert any(i.startswith("template_stamp_refresh") for i in items), \
            "the stamp refresh must ride the LAST migration"
        assert any("uv_sync" in i for i in items)

    @pytest.fixture(autouse=True)
    def _offline_uv(self, monkeypatch):
        """Migration-heavy flows must never invoke a real `uv sync`
        (network/time non-determinism); item keeps an operational opt-out."""
        monkeypatch.setenv("KUNGLAO_UPGRADE_NO_UV_SYNC", "1")

    def _stamped_ws(self, tmp_path: Path, version: str) -> Path:
        """Renderer-real workspace at an ARBITRARY stamp carrying legacy
        agents/config absences — the live-run-shaped closure case."""
        import collections
        VI = collections.namedtuple("VI", "major minor micro release serial")
        real_vi = sys.version_info
        sys.version_info = VI(3, 11, 0, "final", 0)
        try:
            body = _render_legacy_body(tmp_path)
        finally:
            sys.version_info = real_vi

        ws = tmp_path / "live-run-ws"
        ws.mkdir()
        (ws / "CLAUDE.md").write_text(
            tv.stamp_line(version) + "\n\n" + body, encoding="utf-8")
        facts = ws / "facts"
        facts.mkdir()
        (facts / "_INDEX.md").write_text(tv.stamp_line(version),
                                         encoding="utf-8")
        (ws / "claim-register.yaml").write_text(tv.stamp_line(version),
                                                encoding="utf-8")
        (ws / ".kunglao-init.json").write_text(json.dumps({
            "project_type": "windows", "state_hash": "abc",
            "seed_count": 12, "ts": "t"}), encoding="utf-8")
        (ws / "analysis_state.txt").write_text(
            "state_hash=abc\nproject_type=windows\n", encoding="utf-8")
        adir = ws / ".claude" / "agents"
        adir.mkdir(parents=True)
        (adir / "kunglao-worker.md").write_text("# stale\n",
                                                encoding="utf-8")
        (ws / "runs").mkdir()
        # user data that MUST survive untouched
        (ws / "notes" ).mkdir()
        (ws / "notes" / "keep.md").write_text("precious bytes",
                                              encoding="utf-8")
        return ws

    @staticmethod
    def _snap(ws: Path) -> dict[str, str]:
        return {str(p.relative_to(ws)): hashlib.sha256(p.read_bytes())
                .hexdigest() for p in ws.rglob("*") if p.is_file()}

    def test_already_at_target_still_plans_deploy_items(self, tmp_path,
                                                        pinned=False):
        """The live-run problem (real-world shape): a 0.1.3-stamped workspace
        (stamped before this release) whose deploy surface is incomplete —
        the 0.1.4 registry entry must make plan non-empty so the fast
        path cannot skip the repair."""
        maj, mi, pa = (int(x) for x in tv.read_skill_version().split("."))
        prev = ".".join(str(x) for x in (maj, mi, max(pa - 1, 0)))
        up = _load_upgrade()
        ws = self._stamped_ws(tmp_path, prev)
        pre_notes = self._snap(ws)["notes/keep.md"]
        rc = up.main([str(ws)])
        assert rc == 0
        post_notes = self._snap(ws)["notes/keep.md"]
        assert post_notes == pre_notes
        for rel in (".mcp.json", "env-manifest.yaml"):
            assert (ws / rel).is_file(), rel
        assert (ws / ".claude" / "agents" / "kunglao-init-worker.md") \
            .is_file()

    def test_full_v012_acceptance_fixture(self, tmp_path):
        """SOP acceptance: v0.1.2 fixture (old agents, marker-less rendered
        CLAUDE.md, missing .mcp.json/env-manifest) upgrades to: agents
        md5-aligned, frame == fresh render WITH markers, requirement+custom
        sections intact, config present, stamps honest-fresh."""
        cur = tv.read_skill_version()
        ws = self._stamped_ws(tmp_path, "0.1.2")

        # inject a user section OUTSIDE the legacy frame + a task-spec req
        spec_lines = ["## Task constraints (task_spec)", "",
                      "- depth: exhaustive-zz-custom", "",
                      ""]
        p = ws / "CLAUDE.md"
        original = p.read_text(encoding="utf-8")
        marked_up = original.rstrip("\n") + "\n" + "\n".join(spec_lines) \
            + "\n## Operator notes\n\noperator custom zz 42\n"
        p.write_text(marked_up, encoding="utf-8")

        up = _load_upgrade()
        rc = up.main([str(ws)])
        assert rc == 0

        out = p.read_text(encoding="utf-8")
        lines_out = out.splitlines()
        assert lines_out[0] == tv.stamp_line(cur), \
            "stamp rides the top carrier line (#536 comment form)"
        assert lines_out[1] == f"<!-- kunglao:frame:v{cur} -->"
        assert "/* /kunglao:frame */" not in out
        assert "<!-- /kunglao:frame -->" in out, "frame close present"
        assert tv.frame_section_current(ws) is True
        assert "- depth: exhaustive-zz-custom" in out, "needful survives"
        assert "operator custom zz 42" in out, "custom survives"

        src = {name: (REPO / "agents" / name).read_bytes()
               for name in CORE_AGENTS}
        dst = {name: (ws / ".claude" / "agents" / name).read_bytes()
               for name in CORE_AGENTS}
        assert src == dst, "agents md5 must equal install sources"

        for rel in ("CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"):
            assert f"{tv.STAMP_KEY}: {cur}" in (ws / rel).read_text(
                encoding="utf-8"), rel

        ledger = yaml.safe_load((ws / "env-manifest.yaml")
                                .read_text(encoding="utf-8"))
        assert ledger["project_type"] == "windows"
        assert ledger.get("kunglao_version") == cur

    def test_stale_frame_refusal_keeps_stamp_guard(self, tmp_path):
        """Even inside the integrated plan, a hand-written junk body keeps
        the whole chain WARN-only AND refuses to stamp (#758 honesty)."""
        ws = self._stamped_ws(tmp_path, "0.1.2")
        (ws / "CLAUDE.md").write_text(
            tv.stamp_line("0.1.2") + "\n\n# old workspace\nhand made\n",
            encoding="utf-8")
        cur = tv.read_skill_version()
        up = _load_upgrade()
        rc = up.main([str(ws)])
        assert rc == 0
        text = (ws / "CLAUDE.md").read_text(encoding="utf-8")
        assert f"{tv.STAMP_KEY}: {cur}" not in text
        assert "# old workspace" in text
