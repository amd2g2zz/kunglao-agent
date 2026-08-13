# -*- coding: utf-8 -*-
"""Tests for scripts/review_gate.py — 3-reviewer all-PASS commit gate (#145).

Covers the anti-cheat contract: mint requires >=3 distinct registered ids,
each with a PASS verdict and diff_sha256 matching the staged diff; the minted
JSON is HMAC-signed and check refuses forged/missing/stale evidence.
"""
import hashlib
import json
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "review_gate.py"))
IDS = ["r1-gate", "r2-gate", "r3-gate"]


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "-C", str(r), "init", "-q", "-b", "feat/test"], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.email", "t@t.t"], check=True)
    subprocess.run(["git", "-C", str(r), "config", "user.name", "t"], check=True)
    (r / "base.txt").write_text("base\n")
    subprocess.run(["git", "-C", str(r), "add", "base.txt"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    (r / "a.txt").write_text("a\n")
    subprocess.run(["git", "-C", str(r), "add", "a.txt"], check=True)
    return r


@pytest.fixture()
def key(tmp_path):
    k = tmp_path / "review.key"
    run("key-init", str(k))
    return k


def staged_sha(repo):
    out = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--binary"], capture_output=True, check=True,
    ).stdout
    return hashlib.sha256(out).hexdigest()


def write_evidence(repo, name, rid, verdict, sha):
    runs = repo / "runs"
    runs.mkdir(exist_ok=True)
    (runs / f"review-{name}.md").write_text(
        f"---\nreviewer_id: {rid}\nverdict: {verdict}\ndiff_sha256: {sha}\n---\nindependent review\n"
    )


def mint(repo, key, branch="feat/test"):
    return run("mint", str(repo), str(key), branch, f"{repo}/runs/review-*.md", *IDS)


def gate_json(repo):
    return repo / ".review-gate" / "feat-test.json"


def test_key_init_writes_hex_key(tmp_path):
    k = tmp_path / "k"
    r = run("key-init", str(k))
    assert r.returncode == 0
    assert len(k.read_text().strip()) == 64


def test_mint_ok_with_three_distinct_pass(repo, key):
    sha = staged_sha(repo)
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", sha)
    r = mint(repo, key)
    assert r.returncode == 0, r.stdout
    assert "mint OK" in r.stdout
    ev = json.loads(gate_json(repo).read_text())
    assert ev["reviewers"] == sorted(IDS)
    assert "hmac" in ev


def test_mint_fail_wrong_sha(repo, key):
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", "0" * 64)
    r = mint(repo, key)
    assert r.returncode == 2
    assert "bad" in r.stdout


def test_mint_fail_fail_verdict(repo, key):
    sha = staged_sha(repo)
    write_evidence(repo, "r1", "r1-gate", "PASS", sha)
    write_evidence(repo, "r2", "r2-gate", "FAIL", sha)
    write_evidence(repo, "r3", "r3-gate", "PASS", sha)
    r = mint(repo, key)
    assert r.returncode == 2


def test_mint_rejects_duplicate_registered_id(repo, key):
    sha = staged_sha(repo)
    write_evidence(repo, "a", "r1-gate", "PASS", sha)
    write_evidence(repo, "b", "r1-gate", "PASS", sha)
    write_evidence(repo, "c", "r2-gate", "PASS", sha)
    write_evidence(repo, "d", "r3-gate", "PASS", sha)
    r = mint(repo, key)
    assert r.returncode == 2


def test_mint_rejects_unregistered_alias_ids(repo, key):
    # anti-cheat: suffix aliasing (r1-gate-a) must NOT mint
    sha = staged_sha(repo)
    for name, rid in [("a", "r1-gate-a"), ("b", "r2-gate-b"), ("c", "r3-gate-c")]:
        write_evidence(repo, name, rid, "PASS", sha)
    r = mint(repo, key)
    assert r.returncode == 2
    assert "unregistered" in r.stdout


def test_mint_requires_min_three_ids(repo, key):
    sha = staged_sha(repo)
    write_evidence(repo, "a", "r1-gate", "PASS", sha)
    r = run("mint", str(repo), str(key), "feat/test", f"{repo}/runs/review-*.md", "r1-gate", "r2-gate")
    assert r.returncode == 2


def test_check_ok_after_mint(repo, key):
    sha = staged_sha(repo)
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", sha)
    r = mint(repo, key)
    assert r.returncode == 0
    r = run("check", str(repo), str(gate_json(repo)), "feat/test", str(key))
    assert r.returncode == 0, r.stdout


def test_check_rejects_forged_hmac(repo, key):
    sha = staged_sha(repo)
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", sha)
    assert mint(repo, key).returncode == 0
    ev = json.loads(gate_json(repo).read_text())
    ev["hmac"] = "deadbeef" * 16
    gate_json(repo).write_text(json.dumps(ev))
    r = run("check", str(repo), str(gate_json(repo)), "feat/test", str(key))
    assert r.returncode == 1
    assert "HMAC" in r.stdout


def test_check_rejects_forged_without_key(repo, key):
    # forged JSON with fake ids and no valid signature: must fail
    sha = staged_sha(repo)
    ev = {"branch": "feat/test", "diff_sha256": sha, "reviewers": IDS,
          "minted_ts": 0, "hmac": "0" * 64}
    (repo / ".review-gate").mkdir()
    gate_json(repo).write_text(json.dumps(ev))
    r = run("check", str(repo), str(gate_json(repo)), "feat/test", str(key))
    assert r.returncode == 1


def test_check_stale_diff_rc2(repo, key):
    sha = staged_sha(repo)
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", sha)
    assert mint(repo, key).returncode == 0
    with open(repo / "a.txt", "a") as f:
        f.write("tamper\n")
    subprocess.run(["git", "-C", str(repo), "add", "a.txt"], check=True)
    r = run("check", str(repo), str(gate_json(repo)), "feat/test", str(key))
    assert r.returncode == 2
    assert "stale" in r.stdout


def test_check_branch_mismatch(repo, key):
    sha = staged_sha(repo)
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", sha)
    assert mint(repo, key).returncode == 0
    r = run("check", str(repo), str(gate_json(repo)), "other-branch", str(key))
    assert r.returncode == 1


def test_check_missing_evidence(repo, key):
    r = run("check", str(repo), str(gate_json(repo)), "feat/test", str(key))
    assert r.returncode == 1


def test_default_keyfile_ignores_env(monkeypatch, tmp_path):
    # anti-cheat: attacker-controllable KUNGLAO_REVIEW_KEY must not select the
    # key used by check — the path is pinned (r2-gate FAIL finding, rev-2).
    import importlib.util

    spec = importlib.util.spec_from_file_location("review_gate_mod", SCRIPT)
    rg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rg)
    monkeypatch.setenv("KUNGLAO_REVIEW_KEY", str(tmp_path / "attacker.key"))
    assert rg.default_keyfile() == os.path.expanduser("~/.claude/kunglao-review.key")


def test_check_explicit_key_arg_ignores_userprofile(repo, key, monkeypatch):
    # anti-cheat: when the hook passes an explicit keyfile (production path),
    # USERPROFILE redirection must NOT change the key used by check.
    sha = staged_sha(repo)
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", sha)
    assert mint(repo, key).returncode == 0
    fake_home = repo.parent / "fakehome"
    fake_home.mkdir()
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
    r = run("check", str(repo), str(gate_json(repo)), "feat/test", str(key))
    assert r.returncode == 0  # explicit key wins


def test_check_rejects_duplicate_reviewers_in_json(repo, key):
    sha = staged_sha(repo)
    for rid in IDS:
        write_evidence(repo, rid, rid, "PASS", sha)
    assert mint(repo, key).returncode == 0
    ev = json.loads(gate_json(repo).read_text())
    ev["hmac"] = "deadbeef" * 16
    ev["reviewers"] = ["r1-gate", "r1-gate", "r2-gate"]
    gate_json(repo).write_text(json.dumps(ev))
    r = run("check", str(repo), str(gate_json(repo)), "feat/test", str(key))
    assert r.returncode == 1
