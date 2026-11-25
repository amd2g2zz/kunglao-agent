# -*- coding: utf-8 -*-
"""tests/test_gc_harness_735.py — devkit/gc code_gc leg (report-only rot sweep).

Subprocess-fixture suite (the test_gc_harness_720 pattern): a tmp git repo
is planted with the detection targets and the module runs against it via
`sys.executable devkit/gc/code_gc.py scan`. Pins: dead-local CONFIRMED
tier, the liveness witness SET (dispatch witnesses keep a subject alive,
deployment / registration / coverage witnesses do not), liveness at
SYMBOL granularity (a witnessed file no longer keeps all of its symbols
alive), the --json report shape, and report-only safety (no mutation, no
apply flag).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "devkit" / "gc"

# --- witnesses ---------------------------------------------------------------

#: dispatch face: a hit here means something at runtime reaches the module.
SKILL = """# re skill (fixture)

Run `scripts/dispatched_cli.py` — the entry face is `wired_entry`.
"""

MECHANISMS = """mechanisms:
  - id: caller
    entry: scripts/caller.py
    face: run
    trigger: on-event
"""

#: deployment witness — says a file is packaged, never that it is called.
DEPLOY_MANIFEST = """schema_version: '1'
files:
  - src: scripts/shipped_mod.py
    dest: .claude/scripts/shipped_mod.py
    kind: script
  - src: scripts/dispatched_cli.py
    dest: .claude/scripts/dispatched_cli.py
    kind: script
"""

#: registration witnesses — inventory row + capability catalog + teaching doc.
SCRIPTS_README = """# scripts inventory (fixture)

| `catalogued_mod.py` | a face nobody dispatches | tests |
| `shipped_mod.py` | shipped | tests |
"""

EXT_INDEX = """entries:
  - name: "catalogued_mod"
    source: "scripts/catalogued_mod.py"
"""

#: coverage witness — a test-only reference is the dead-production-face shape.
TEST_REFS = """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import test_only_mod  # noqa: E402


def test_test_only_face():
    assert test_only_mod.test_only_face() == 5
"""

# --- subjects ----------------------------------------------------------------

CALC_KIT = "def compute(total):\n    leftover = total * 2\n    return total\n"

ORPHAN_MOD = "RATE = 2\n"

SHIPPED_MOD = "def manifest_only_face():\n    return 1\n"

CATALOGUED_MOD = "def catalogued_face():\n    return 2\n"

TEST_ONLY_MOD = """import orphan_dep


def test_only_face():
    return orphan_dep.helper_of_the_dead()
"""

#: consumed only by an unwired module — liveness is transitive from a LIVE root
ORPHAN_DEP = "def helper_of_the_dead():\n    return 5\n"

DISPATCHED_CLI = """def wired_entry(ws):
    return internal_face(ws)


def internal_face(ws):
    return ws


def never_reached(ws):
    return ws
"""

LIVE_MOD = "def helper_used_elsewhere():\n    return 7\n"

CALLER = """import live_mod


def run():
    return live_mod.helper_used_elsewhere()
"""


def _clean_git_env() -> dict:
    env = dict(os.environ)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=_clean_git_env(), check=check,
    )


def _harness(tmp_repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Run devkit/gc/code_gc.py with cwd inside tmp_repo."""
    return subprocess.run(
        [sys.executable, str(HARNESS / "code_gc.py"), *args],
        cwd=str(tmp_repo), capture_output=True, text=True,
        env=_clean_git_env(), timeout=180,
    )


def _make_repo(tmp_path: Path) -> Path:
    """Tmp repo: dispatch-witnessed, deployment-witnessed, registration- and
    coverage-witnessed, and wholly undeclared detection subjects."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / "calc_kit.py").write_text(CALC_KIT, encoding="utf-8")
    (scripts / "orphan_mod.py").write_text(ORPHAN_MOD, encoding="utf-8")
    (scripts / "shipped_mod.py").write_text(SHIPPED_MOD, encoding="utf-8")
    (scripts / "catalogued_mod.py").write_text(CATALOGUED_MOD, encoding="utf-8")
    (scripts / "test_only_mod.py").write_text(TEST_ONLY_MOD, encoding="utf-8")
    (scripts / "orphan_dep.py").write_text(ORPHAN_DEP, encoding="utf-8")
    (scripts / "dispatched_cli.py").write_text(DISPATCHED_CLI, encoding="utf-8")
    (scripts / "live_mod.py").write_text(LIVE_MOD, encoding="utf-8")
    (scripts / "caller.py").write_text(CALLER, encoding="utf-8")
    (scripts / "README.md").write_text(SCRIPTS_README, encoding="utf-8")
    (repo / "deploy-manifest.yaml").write_text(DEPLOY_MANIFEST, encoding="utf-8")
    tools = repo / "tools"
    tools.mkdir()
    (tools / "_INDEX.ext.yaml").write_text(EXT_INDEX, encoding="utf-8")
    (repo / "skills" / "re").mkdir(parents=True)
    (repo / "skills" / "re" / "SKILL.md").write_text(SKILL, encoding="utf-8")
    (repo / "scripts" / "mechanisms.yaml").write_text(MECHANISMS, encoding="utf-8")
    tests = repo / "tests"
    tests.mkdir()
    (tests / "test_inert.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (tests / "test_refs.py").write_text(TEST_REFS, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _snapshot(repo: Path) -> dict:
    """relpath -> sha256 for every file in the repo (workspace files only)."""
    out = {}
    for p in sorted(repo.rglob("*")):
        if ".git" in p.parts or not p.is_file():
            continue
        out[p.relative_to(repo).as_posix()] = hashlib.sha256(
            p.read_bytes()).hexdigest()
    return out


def _suspects(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith("SUSPECT")]


def _ok_lines(stdout: str) -> list[str]:
    return [ln for ln in stdout.splitlines() if ln.startswith("ok:")]


# ---------- class B: dead_local (CONFIRMED) ----------

def test_dead_local_planted_reproduces_confirmed(tmp_path: Path) -> None:
    """An unused local is a CONFIRMED candidate with file:line and symbol."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    assert r.returncode == 0, r.stderr
    assert "CONFIRMED: scripts/calc_kit.py:2 leftover (F841)" in r.stdout


# ---------- class C: module liveness (SUSPECT) ----------

def test_undeclared_module_is_suspect(tmp_path: Path) -> None:
    """Referenced by nothing at all -> unwired module, declared nowhere."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    line = next(ln for ln in _suspects(r.stdout) if "orphan_mod.py" in ln)
    assert "no dispatch witness" in line and "declared: nowhere" in line


def test_dispatch_witness_and_import_edge_keep_module_alive(tmp_path: Path) -> None:
    """A SKILL mention or a real importer clears liveness; no SUSPECT for them."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    suspects = _suspects(r.stdout)
    assert not [s for s in suspects if "dispatched_cli.py:" not in s
                and "dispatched_cli.py" in s], suspects
    assert not [s for s in suspects if "live_mod.py" in s], suspects
    assert not [s for s in suspects if "caller.py" in s], suspects
    ok = _ok_lines(r.stdout)
    assert any("dispatched_cli.py" in ln and "dispatch" in ln for ln in ok), ok
    assert any("live_mod.py" in ln and "import" in ln for ln in ok), ok


# ---------- the wrong witnesses no longer clear liveness -----------------

def test_deploy_manifest_does_not_clear_liveness(tmp_path: Path) -> None:
    """A manifest entry says a file ships, never that a symbol is called."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    line = next(ln for ln in _suspects(r.stdout) if "shipped_mod.py" in ln)
    assert "unwired module" in line
    assert "declared: deploy-manifest.yaml" in line
    assert not [ln for ln in _ok_lines(r.stdout) if "shipped_mod.py" in ln]


def test_registration_faces_do_not_clear_liveness(tmp_path: Path) -> None:
    """scripts/README.md + the ext capability catalog are registration only:
    a catalogued face nobody dispatches is SUSPECT (relib_audit's own
    seed/diagnostic split — registration alone is not liveness)."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    line = next(ln for ln in _suspects(r.stdout) if "catalogued_mod.py" in ln)
    assert "unwired module" in line
    assert not [ln for ln in _ok_lines(r.stdout) if "catalogued_mod.py" in ln]


def test_test_only_reference_does_not_clear_liveness(tmp_path: Path) -> None:
    """A symbol referenced ONLY by tests is a dead production face — the
    phi_tree.settle_resolution shape; tests/ must not wash it."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    line = next(ln for ln in _suspects(r.stdout) if "test_only_mod.py" in ln)
    assert "unwired module" in line
    assert "tests/test_refs.py" in line
    assert not [ln for ln in _ok_lines(r.stdout) if "test_only_mod.py" in ln]


def test_liveness_is_transitive_from_a_live_root(tmp_path: Path) -> None:
    """An import edge only propagates from a module that is itself live:
    orphan_dep is consumed by the unwired test_only_mod, so it stays unwired
    (the scheduling_selection / intelligent_scheduling shape)."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    line = next(ln for ln in _suspects(r.stdout) if "orphan_dep.py" in ln)
    assert "no live importer" in line, line


# ---------- keep-alive granularity is per symbol ----------------------

def test_keep_alive_is_symbol_level_inside_a_witnessed_file(tmp_path: Path) -> None:
    """A dispatch witness for the file must NOT keep every symbol in it
    alive: the untouched face of a witnessed module is still SUSPECT, while
    its internally-used face stays alive."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    assert ("SUSPECT: scripts/dispatched_cli.py:9 never_reached (dead_symbol)"
            in r.stdout), r.stdout
    suspects = _suspects(r.stdout)
    assert not [s for s in suspects if "internal_face" in s], suspects
    assert not [s for s in suspects if "wired_entry" in s], suspects
    ok = next(ln for ln in _ok_lines(r.stdout) if "dispatched_cli.py" in ln)
    assert "2/3 symbols alive" in ok, ok  # wired_entry + internal_face, not never_reached


def test_unwired_module_is_reported_once_not_per_symbol(tmp_path: Path) -> None:
    """Module-level reporting is the whole-module signal; its faces are not
    enumerated on top of it (the report stays readable)."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan")
    faces = [s for s in _suspects(r.stdout) if "manifest_only_face" in s
             or "test_only_face" in s or "catalogued_face" in s]
    assert faces == [], faces


# ---------- report shape ----------

def test_json_report_shape(tmp_path: Path) -> None:
    """--json carries leg/generated/head/scopes/candidates/counts/keepalive."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan", "--json")
    payload = json.loads(r.stdout)
    assert set(payload) == {
        "leg", "generated", "head", "scopes", "candidates", "counts",
        "keepalive"}
    assert payload["leg"] == "code_gc"
    assert payload["generated"]
    assert len(payload["head"]) == 40
    assert payload["scopes"] == ["scripts", "tools", "hooks", "devkit/gc"]
    assert set(payload["counts"]) == {"confirmed", "suspect", "total"}
    counts = payload["counts"]
    assert counts["confirmed"] + counts["suspect"] == counts["total"]
    assert counts["total"] == len(payload["candidates"])
    assert counts["confirmed"] >= 1
    for c in payload["candidates"]:
        assert set(c) == {"class", "tier", "path", "line", "symbol", "evidence"}
        assert c["tier"] in ("CONFIRMED", "SUSPECT")
        assert c["evidence"]
    planted = [c for c in payload["candidates"]
               if c["path"] == "scripts/calc_kit.py" and c["symbol"] == "leftover"]
    assert planted and planted[0]["class"] == "dead_local"
    assert planted[0]["tier"] == "CONFIRMED"


def test_keepalive_attribution_excludes_the_wrong_witnesses(tmp_path: Path) -> None:
    """The attribution block is how the 84%-from-manifest claim stays dead:
    no alive verdict may be attributed to a deployment / coverage witness,
    and those faces are listed as never-clearing."""
    repo = _make_repo(tmp_path)
    r = _harness(repo, "scan", "--json")
    payload = json.loads(r.stdout)
    ka = payload["keepalive"]
    assert set(ka) == {"modules", "faces", "never_clears"}
    assert set(ka["modules"]["by_witness"]) <= {
        "dispatch_surface", "import_edge", "gitnexus"}
    assert set(ka["faces"]["by_witness"]) <= {
        "dispatch_surface", "external_caller", "internal_use", "gitnexus"}
    for face in ("deploy-manifest.yaml", "tests/**", "scripts/README.md",
                 "tools/_INDEX.ext.yaml"):
        assert face in ka["never_clears"], ka["never_clears"]
    assert ka["modules"]["total"] == 9  # planted inventory subjects
    assert ka["modules"]["unwired"] == 6
    assert ka["faces"]["total"] == 10
    assert ka["faces"]["suspect"] == 1  # never_reached, inside a witnessed file


# ---------- report-only safety ----------

def test_report_only_no_apply_no_mutation(tmp_path: Path) -> None:
    """scan never writes, never deletes; there is no --apply flag at all."""
    repo = _make_repo(tmp_path)
    before = _snapshot(repo)
    r = _harness(repo, "scan")
    assert r.returncode == 0, r.stderr
    assert _snapshot(repo) == before
    rj = _harness(repo, "scan", "--json")
    assert rj.returncode == 0
    assert _snapshot(repo) == before
    ra = _harness(repo, "scan", "--apply")
    assert ra.returncode != 0
    assert _snapshot(repo) == before
    help_text = _harness(repo, "scan", "--help")
    assert "--apply" not in help_text.stdout + help_text.stderr
