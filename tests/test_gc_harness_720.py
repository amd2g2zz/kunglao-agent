# -*- coding: utf-8 -*-
"""tests/test_gc_harness_720.py — Agent asset lifecycle controller v1 (#720).

RED suite: gc-harness/ modules do not exist yet at authoring time — every
case below must fail against the bare tree (import/CLI errors) and pass
once the minimal v1 lands. Determinism rules: no clock injection needed
(ages come from registry dates / committer dates / explicit utime), and
every tmp git fixture strips GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE so
child gits never leak into the host repo (test_review_gate precedent).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
HARNESS = REPO / "gc-harness"

_OLD = "2026-01-01"          # fixed past date for age windows
_RECENT = "2026-08-20"       # fixed fresh date


def _clean_git_env() -> dict:
    env = dict(os.environ)
    for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(k, None)
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, env=_clean_git_env(),
        check=check,
    )


def _harness(tmp_repo: Path, module: str, *args: str) -> subprocess.CompletedProcess:
    """Run gc-harness/<module>.py inside tmp_repo."""
    return subprocess.run(
        [sys.executable, str(HARNESS / f"{module}.py"), *args],
        cwd=str(tmp_repo), capture_output=True, text=True,
        env=_clean_git_env(), timeout=60,
    )


def _make_repo(tmp_path: Path) -> Path:
    """Tmp repo: committed dev branch with openspec/tests/scaffold + .agent registry."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "dev")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "openspec" / "changes" / "spec-alpha").mkdir(parents=True)
    (repo / "openspec" / "changes" / "spec-alpha" / "proposal.md").write_text(
        "alpha", encoding="utf-8")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_alpha.py").write_text(
        "def test_alpha_one():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _registry(repo: Path, name: str, text: str) -> None:
    d = repo / ".agent"
    d.mkdir(exist_ok=True)
    (d / f"{name}.yaml").write_text(text, encoding="utf-8")


# ---------- spec_gc ----------

def test_spec_orphan_older_than_90d_archives_on_apply(tmp_path: Path) -> None:
    """Rule 1: zero code refs + last_modified older than orphan_days → ARCHIVED (apply only)."""
    repo = _make_repo(tmp_path)
    _registry(repo, "specs", (
        f"specs:\n- id: SPEC-ALPHA\n  path: openspec/changes/spec-alpha/proposal.md\n"
        f"  status: active\n  created: {_OLD}\n  last_modified: {_OLD}\n"
        f"  linked_tests: []\n"))
    dry = _harness(repo, "spec_gc", "scan")
    assert "SPEC-ALPHA" in dry.stdout and "ARCHIVED" in dry.stdout
    assert "archived (applied)" not in dry.stdout          # dry-run reports only
    _harness(repo, "spec_gc", "scan", "--apply")
    applied = (repo / ".agent" / "specs.yaml").read_text(encoding="utf-8")
    assert "status: archived" in applied


def test_spec_with_code_refs_zero_tests_flagged_suspect(tmp_path: Path) -> None:
    """Rule 2: code refs present, test refs zero → SUSPECT (report only, never archived)."""
    repo = _make_repo(tmp_path)
    (repo / "scripts").mkdir()
    (repo / "scripts" / "alpha_user.py").write_text(
        "SPEC-ALPHA anchor\n", encoding="utf-8")            # code reference exists
    _registry(repo, "specs", (
        f"specs:\n- id: SPEC-ALPHA\n  path: openspec/changes/spec-alpha/proposal.md\n"
        f"  status: active\n  created: {_OLD}\n  last_modified: {_RECENT}\n"
        f"  linked_tests: []\n"))
    r = _harness(repo, "spec_gc", "scan", "--apply")
    assert "SUSPECT" in r.stdout
    assert "status: archived" not in (repo / ".agent" / "specs.yaml").read_text(encoding="utf-8")


def test_spec_search_returns_existing_and_decision(tmp_path: Path) -> None:
    """Creation gate: `spec search alpha` prints Existing + modify|create Decision."""
    repo = _make_repo(tmp_path)
    _registry(repo, "specs", (
        f"specs:\n- id: SPEC-ALPHA\n  path: openspec/changes/spec-alpha/proposal.md\n"
        f"  status: active\n  created: {_OLD}\n  last_modified: {_RECENT}\n"
        f"  linked_tests: []\n"))
    r = _harness(repo, "spec_gc", "search", "alpha")
    assert "SPEC-ALPHA" in r.stdout
    assert "modify" in r.stdout and "create" in r.stdout


def test_spec_duplicate_reported_not_merged(tmp_path: Path) -> None:
    """Rule 3: duplicate path-stems → report only; registry untouched."""
    repo = _make_repo(tmp_path)
    for d in ("spec-alpha", "spec-alpha-v2"):
        (repo / "openspec" / "changes" / d).mkdir(parents=True, exist_ok=True)
        (repo / "openspec" / "changes" / d / "proposal.md").write_text(
            d, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "dupes")
    _registry(repo, "specs", (
        f"specs:\n- id: SPEC-ALPHA\n  path: openspec/changes/spec-alpha/proposal.md\n"
        f"  status: active\n  created: {_OLD}\n  last_modified: {_RECENT}\n"
        f"  linked_tests: []\n"
        f"- id: SPEC-ALPHA-V2\n  path: openspec/changes/spec-alpha-v2/proposal.md\n"
        f"  status: active\n  created: {_OLD}\n  last_modified: {_RECENT}\n"
        f"  linked_tests: []\n"))
    r = _harness(repo, "spec_gc", "scan", "--apply")
    assert "duplicate" in r.stdout.lower()
    after = (repo / ".agent" / "specs.yaml").read_text(encoding="utf-8")
    assert after.count("status: active") == 2               # nothing merged/changed


def test_spec_init_registers_active_without_adjudication(tmp_path: Path) -> None:
    """init: every openspec/changes dir with proposal.md → ACTIVE; registration only."""
    repo = _make_repo(tmp_path)
    _harness(repo, "spec_gc", "init")
    reg = (repo / ".agent" / "specs.yaml").read_text(encoding="utf-8")
    assert "SPEC-ALPHA" in reg and "status: active" in reg


# ---------- test_gc ----------

def test_stale_last_failure_is_delete_candidate(tmp_path: Path) -> None:
    """Candidate condition ①: registered last_failure older than 180d."""
    repo = _make_repo(tmp_path)
    _registry(repo, "tests", (
        f"tests:\n- id: test_alpha\n  path: tests/test_alpha.py\n  status: active\n"
        f"  created: {_OLD}\n  last_modified: {_OLD}\n  last_failure: {_OLD}\n"))
    r = _harness(repo, "test_gc", "scan")
    assert "test_alpha" in r.stdout and "CANDIDATE" in r.stdout


def test_no_last_failure_record_never_candidate(tmp_path: Path) -> None:
    """Fail-safe: absent last_failure ⇒ not a candidate by condition ①."""
    repo = _make_repo(tmp_path)
    _registry(repo, "tests", (
        f"tests:\n- id: test_alpha\n  path: tests/test_alpha.py\n  status: active\n"
        f"  created: {_OLD}\n  last_modified: {_OLD}\n  last_failure: null\n"))
    r = _harness(repo, "test_gc", "scan")
    assert "CANDIDATE" not in r.stdout


def test_quarantine_moves_and_restore_reverts(tmp_path: Path) -> None:
    """quarantine → git mv into tests/quarantine/ + record; restore moves back."""
    repo = _make_repo(tmp_path)
    _harness(repo, "test_gc", "init")
    q = _harness(repo, "test_gc", "quarantine", "tests/test_alpha.py")
    assert q.returncode == 0, q.stderr
    assert (repo / "tests" / "quarantine" / "test_alpha.py").is_file()
    reg = (repo / ".agent" / "tests.yaml").read_text(encoding="utf-8")
    assert "quarantined_at" in reg and "original_path" in reg
    _harness(repo, "test_gc", "restore", "test_alpha")
    assert (repo / "tests" / "test_alpha.py").is_file()
    assert not (repo / "tests" / "quarantine" / "test_alpha.py").exists()


def test_quarantine_expiry_deletes_only_on_apply(tmp_path: Path) -> None:
    """expire: older than quarantine_days → DELETE candidate; --apply removes file + REMOVED."""
    import datetime as _dt
    old = (_dt.date.today() - _dt.timedelta(days=40)).isoformat()
    repo = _make_repo(tmp_path)
    _harness(repo, "test_gc", "init")
    _harness(repo, "test_gc", "quarantine", "tests/test_alpha.py")
    # force the recorded date old (registry is data, not code — deterministic edit)
    reg_path = repo / ".agent" / "tests.yaml"
    reg_path.write_text(
        reg_path.read_text(encoding="utf-8").replace(
            "quarantined_at:", f"quarantined_at: {old}  #forced:", 1),
        encoding="utf-8")
    reg_path.write_text(
        f"tests:\n- id: test_alpha\n  path: tests/quarantine/test_alpha.py\n"
        f"  status: quarantined\n  created: {_OLD}\n  last_modified: {_OLD}\n"
        f"  last_failure: null\n  quarantined_at: {old}\n"
        f"  original_path: tests/test_alpha.py\n", encoding="utf-8")
    dry = _harness(repo, "test_gc", "expire")
    assert "test_alpha" in dry.stdout and "DELETE" in dry.stdout
    assert (repo / "tests" / "quarantine" / "test_alpha.py").is_file()
    _harness(repo, "test_gc", "expire", "--apply")
    assert not (repo / "tests" / "quarantine" / "test_alpha.py").exists()
    assert "status: removed" in (repo / ".agent" / "tests.yaml").read_text(encoding="utf-8")


def test_identical_test_name_in_two_files_is_duplicate_candidate(tmp_path: Path) -> None:
    """Candidate condition ②: identical test function name in 2+ files (no content analysis)."""
    repo = _make_repo(tmp_path)
    (repo / "tests" / "test_beta.py").write_text(
        "def test_alpha_one():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "dupe test")
    r = _harness(repo, "test_gc", "scan")
    assert "test_alpha_one" in r.stdout and "CANDIDATE" in r.stdout


# ---------- worktree_gc ----------

def _merged_stale_worktree(tmp_path: Path) -> Path:
    repo = _make_repo(tmp_path)
    old_env_date = "2026-05-01T00:00:00"
    env = _clean_git_env()
    env["GIT_COMMITTER_DATE"] = old_env_date
    env["GIT_AUTHOR_DATE"] = old_env_date
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "-b", "wt-merged"],
                   capture_output=True, env=env, check=True)
    (repo / "marker.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True, env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "merged work",
                    "--date", old_env_date],
                   capture_output=True, env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "checkout", "-q", "dev"],
                   capture_output=True, env=env, check=True)
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "--no-ff", "-m", "merge", "wt-merged"],
                   capture_output=True, env=env, check=True)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q",
         str(tmp_path / "wt-merged"), "wt-merged"],
        capture_output=True, env=env, check=True)
    return repo


def test_merged_worktree_past_7d_is_candidate(tmp_path: Path) -> None:
    """merged + older than merged_days → delete candidate (dry-run default)."""
    repo = _merged_stale_worktree(tmp_path)
    r = _harness(repo, "worktree_gc", "scan")
    assert "wt-merged" in r.stdout and "candidate" in r.stdout.lower()
    assert (tmp_path / "wt-merged").is_dir()               # dry-run: still there


def test_abandoned_worktree_past_14d_is_candidate(tmp_path: Path) -> None:
    """abandoned (zero own commits) + dir older than abandoned_days → candidate."""
    repo = _make_repo(tmp_path)
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-q",
         str(tmp_path / "wt-abandoned"), "-b", "wt-abandoned"],
        capture_output=True, env=_clean_git_env(), check=True)
    stale = tmp_path / "wt-abandoned"
    old_ts = 1_700_000_000                                    # fixed epoch, 2023-11
    os.utime(stale / ".git", (old_ts, old_ts))
    r = _harness(repo, "worktree_gc", "scan")
    assert "wt-abandoned" in r.stdout and "candidate" in r.stdout.lower()


def test_main_worktree_never_candidate(tmp_path: Path) -> None:
    repo = _merged_stale_worktree(tmp_path)
    r = _harness(repo, "worktree_gc", "scan")
    assert str(repo) not in r.stdout


# ---------- Artifact Budget observation (devkit/quality_gates.py) ----------

def _budget_observation(repo: Path) -> str:
    sys.path.insert(0, str(REPO / "devkit"))
    try:
        import quality_gates  # noqa: E402
        out: list[str] = []
        quality_gates._observation_artifact_budget(
            verbose=True, repo_root=repo, sink=out.append)
        return "\n".join(out)
    finally:
        sys.path.remove(str(REPO / "devkit"))


def _budget_repo(tmp_path: Path, n_new_tests: int, justification: str | None) -> Path:
    repo = _make_repo(tmp_path)
    # honest base: bare origin holding the pre-addition state, so the
    # observation's origin/dev diff counts exactly the task's additions
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)],
                   capture_output=True, check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "dev")
    for i in range(n_new_tests):
        (repo / "tests" / f"test_new_{i}.py").write_text(
            f"def test_n{i}():\n    assert True\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "additions")
    if justification is not None:
        d = repo / ".agent"
        d.mkdir(exist_ok=True)
        (d / "budget_justification.md").write_text(justification, encoding="utf-8")
    return repo


def test_budget_over_limit_without_justification_warns(tmp_path: Path) -> None:
    repo = _budget_repo(tmp_path, n_new_tests=6, justification=None)
    out = _budget_observation(repo)
    assert "[warn]" in out and "max_new_test" in out
    assert "justification" in out.lower()


def test_budget_over_limit_with_justification_observes(tmp_path: Path) -> None:
    repo = _budget_repo(
        tmp_path, n_new_tests=6,
        justification=("Existing artifact cannot satisfy because: none cover GC\n"
                       "New artifact justification: lifecycle controller v1"))
    out = _budget_observation(repo)
    assert "[observe]" in out
    assert "[warn]" not in out
