"""#739: init last-step workspace git snapshot (snapshot layer) tests.

Pins the three faces of the contract:
  1. fresh init -> workspace becomes a git repo with exactly one initial
     commit and a .gitignore that keeps immutable input (bins/) and
     runtime telemetry noise (runs/) out of snapshots;
  2. re-init idempotency -> an existing ws/.git is never re-initialized;
  3. git binary missing -> WARN + git_snapshot_skipped log event, never a
     raise; the overall init still exits 0 (WARN tier, not HARD).

Teaching surface: the stdout banner uses `git -C <workspace>` forms
(nested-repo discipline) and the rendered CLAUDE.md carries the
"Workspace git snapshots" section.

#690: no absolute-path assertions - every path derives from tmp_path.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from _factories import seed_bins

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"

PAYLOAD = b"MZ\x90\x00" + b"\x00" * 64
SAMPLE_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _load_init():
    """Load kunglao-init.py as a module (hyphen filename, no package)."""
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_git_739", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def init_mod():
    return _load_init()


def _git(ws: Path, *args: str) -> str:
    argv = ["git", "-C", str(ws), *args]
    cp = subprocess.run(argv, capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    assert cp.returncode == 0, "git failed: " + cp.stderr
    return cp.stdout.strip()


def _make_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    seed_bins(ws, payload=PAYLOAD)
    return ws


def _run_init(mod, ws: Path, monkeypatch, project_type: str = "windows") -> int:
    monkeypatch.setenv(FLAG_NAME, "0")
    return mod.run(ws, skip_toolchain=True, project_type=project_type,
                   profile_root=ws.parent / "profile-root")


# ---------- 1. unit: fresh workspace -> repo + gitignore + banner ----------

def test_unit_creates_repo_and_gitignore(tmp_path: Path, capsys, init_mod):
    """One call on a file-bearing ws: .git created, exactly 1 commit,
    .gitignore keeps bins/ + runs/ out, banner teaches git -C forms."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.txt").write_text("state", encoding="utf-8")

    result = init_mod.init_workspace_git(ws)

    assert result["status"] == "created", result
    assert (ws / ".git").is_dir(), "workspace did not become a git repo"
    assert _git(ws, "rev-list", "--count", "HEAD") == "1", \
        "expected exactly one initial commit"
    gitignore = (ws / ".gitignore").read_text(encoding="utf-8")
    assert "bins/" in gitignore, "sample input must be gitignored"
    assert "runs/" in gitignore, "runtime telemetry must be gitignored"
    out = capsys.readouterr().out
    assert "[git-snapshot]" in out
    assert "git -C <workspace>" in out, \
        "banner must teach the -C form (nested-repo discipline)"


# ---------- 2. unit: existing repo -> idempotent, no second init ----------

def test_unit_existing_repo_is_idempotent(tmp_path: Path, capsys, init_mod):
    """A second call on an already-repo ws returns existing and adds no
    commit (snapshot history is never rewritten by re-init)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.txt").write_text("state", encoding="utf-8")
    first = init_mod.init_workspace_git(ws)
    assert first["status"] == "created"

    second = init_mod.init_workspace_git(ws)

    assert second == {"status": "existing"}, second
    assert _git(ws, "rev-list", "--count", "HEAD") == "1"


# ---------- 3. unit: git binary missing -> WARN, never a raise ----------

def _read_log_events(ws: Path) -> list[dict]:
    log_files = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    assert log_files, "kunglao_log event file missing"
    lines = log_files[-1].read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines]


def test_unit_git_missing_warns_and_emits(tmp_path: Path, capsys,
                                          monkeypatch, init_mod):
    """FileNotFoundError from subprocess -> WARN on stderr + a
    git_snapshot_skipped kunglao_log event; the function returns a skip
    dict instead of raising (WARN tier, not HARD)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "note.txt").write_text("state", encoding="utf-8")

    def _no_git(*_a, **_k):
        raise FileNotFoundError("git binary not found")

    monkeypatch.setattr(init_mod.subprocess, "run", _no_git)
    result = init_mod.init_workspace_git(ws)

    assert result["status"] == "skipped", result
    assert not (ws / ".git").exists(), "no repo may be created"
    err = capsys.readouterr().err
    assert "WARNING" in err and "git" in err.lower()
    events = _read_log_events(ws)
    assert any(e["action"] == "git_snapshot_skipped" for e in events), \
        "git_snapshot_skipped event not emitted"


# ---------- 4. e2e: full init wires the snapshot as the last step ----------

def test_e2e_init_snapshots_and_banners(tmp_path: Path, capsys, monkeypatch,
                                        init_mod):
    """Full run(): rc 0, .git present, 1 commit, .gitignore present, and
    the multi-line [git-snapshot] banner lands on stdout."""
    ws = _make_ws(tmp_path)
    rc = _run_init(init_mod, ws, monkeypatch)
    assert rc == 0

    assert (ws / ".git").is_dir()
    assert _git(ws, "rev-list", "--count", "HEAD") == "1"
    gitignore = (ws / ".gitignore").read_text(encoding="utf-8")
    assert "bins/" in gitignore and "runs/" in gitignore
    out = capsys.readouterr().out
    assert "[git-snapshot]" in out
    assert "git -C <workspace>" in out


def test_e2e_reinit_keeps_single_commit(tmp_path: Path, monkeypatch, init_mod):
    """Re-running init over an initialized workspace does not duplicate the
    repository or manufacture a second commit."""
    ws = _make_ws(tmp_path)
    assert _run_init(init_mod, ws, monkeypatch) == 0
    assert _run_init(init_mod, ws, monkeypatch) == 0

    assert (ws / ".git").is_dir()
    assert _git(ws, "rev-list", "--count", "HEAD") == "1", \
        "re-init must not add commits"


def test_e2e_git_missing_still_exits_zero(tmp_path: Path, monkeypatch,
                                          init_mod):
    """WARN-not-HARD at the run() level: with git unavailable the full init
    still exits 0 and leaves no .git behind."""
    ws = _make_ws(tmp_path)

    def _no_git(*_a, **_k):
        raise FileNotFoundError("git binary not found")

    monkeypatch.setenv(FLAG_NAME, "0")
    monkeypatch.setattr(init_mod.subprocess, "run", _no_git)
    rc = init_mod.run(ws, skip_toolchain=True, project_type="windows",
                      profile_root=ws.parent / "profile-root")

    assert rc == 0, "git-missing must degrade to WARN, not fail init"
    assert not (ws / ".git").exists()
    events = _read_log_events(ws)
    assert any(e["action"] == "git_snapshot_skipped" for e in events)


# ---------- 5. teaching surface: rendered CLAUDE.md ----------

def test_e2e_claudemd_teaches_git_snapshot_section(tmp_path: Path,
                                                   monkeypatch, init_mod):
    """The rendered CLAUDE.md carries the Workspace-git-snapshots teaching
    section with -C <workspace> command forms (teach, not enforce)."""
    ws = _make_ws(tmp_path)
    assert _run_init(init_mod, ws, monkeypatch) == 0

    claude = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "## Workspace git snapshots" in claude
    assert "git -C <workspace>" in claude
    assert "SNAPSHOT layer" in claude, \
        "snapshot-vs-state-authority framing missing"


# ---------- 6. emit vocabulary stays CI-anchored ----------

def test_git_snapshot_skip_word_is_registered():
    """git_snapshot_skipped must live in event_taxonomy.EMIT_ACTIONS
    (sorted + unique) or the #459 CI anchor turns the suite red."""
    sys.path.insert(0, str(SCRIPTS))
    import event_taxonomy  # noqa: E402

    assert "git_snapshot_skipped" in event_taxonomy.EMIT_ACTIONS
    words = event_taxonomy.EMIT_ACTIONS
    assert words == sorted(set(words)), "EMIT_ACTIONS must stay sorted+unique"
