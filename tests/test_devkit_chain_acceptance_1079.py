#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_devkit_chain_acceptance_1079.py — devkit/chain_acceptance.py contract.

Regression fixtures for issue 1079 (closeout completion as a reconciled
fact):

| direction | real instance | fixture shape | rule |
|---|---|---|---|
| 超前 (record ahead of fact) | S2 (issue 1042): 两段 accepted 而 PR OPEN、无 merge_sha | closeout accepted 无 merge_sha；或 merge_sha 非 origin/dev 祖先 | closeout evidence |
| 辅助字段 (authority bypassed) | N0: 结果写进 closeout_step=DONE 而权威 status 停在 working | closeout 行 working、updated_at 超过声明阈值 | stagnation report |
| 落后 (record behind fact) | S13 (issue 1005): 收口段已工作约两小时而自己那行仍 pending | 行已部分推进(owner 已填)但 status 仍 pending | owner↔status 一致 |

History no-false-positive: the five pre-mechanization records (N0/S1/S2/S13/S17)
live OUTSIDE the repo (~/.claude/kunglao-chains/) and read clean under the
dev-chain/1 legacy tolerance — verified locally by
test_real_history_records_read_clean (skips when the chain home is absent,
e.g. CI hosts).

The tool is invoked as a subprocess: the CLI is the public API, asserted via
observable exit codes + output (unit_test_spec §5 — no internals).

Exit codes: 0 = clean / 1 = REFUSE (invalid record) / 2 = unverifiable
(tool/env: missing file, non-JSON, origin/dev unresolvable) /
3 = STAGNANT (consistent record with working rows past the threshold).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHAIN_TOOL = REPO_ROOT / "devkit" / "chain_acceptance.py"

RC_PASS = 0
RC_REFUSE = 1
RC_UNVERIFIABLE = 2
RC_STAGNANT = 3

HISTORY_NAMES = ("N0", "S1", "S2", "S13", "S17")

SAMPLE_SHA = "0" * 40


def _chain_home() -> Path:
    """Real chain-record home. The root conftest redirects HOME per test,
    so local runs must point here explicitly (KUNGLAO_CHAINS_HOME); CI hosts
    have neither, and the test skips."""
    override = os.environ.get("KUNGLAO_CHAINS_HOME")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "kunglao-chains"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_tool(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHAIN_TOOL), *argv],
        capture_output=True, text=True, timeout=120, cwd=REPO_ROOT,
        errors="replace")


def _write_record(record: dict, tmp: Path, name: str = "chain.json") -> Path:
    path = tmp / name
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def _settled_record(chain: str = "S-TEST", schema: str = "dev-chain/2",
                    merge_sha: str | None = SAMPLE_SHA) -> dict:
    """A fully settled record. merge_sha=None omits the field entirely."""
    end = {"id": "end", "kind": "closeout", "owner": "end-agent",
           "status": "accepted", "updated_at": "2026-11-25T09:00:00Z"}
    if merge_sha is not None:
        end["merge_sha"] = merge_sha
    return {
        "schema": schema,
        "chain": chain,
        "branch": f"fix/{chain}",
        "segments": [
            {"id": "s1", "kind": "develop", "owner": "s1-agent",
             "status": "accepted", "updated_at": "2026-11-25T08:00:00Z"},
            end,
        ],
    }


def _mk_repo_with_dev(tmp: Path) -> tuple[Path, str]:
    """Minimal git repo whose refs/remotes/origin/dev resolves (no network)."""
    repo = tmp / "origin-repo"
    repo.mkdir()
    git = ["git", "-C", str(repo)]
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"]):
        subprocess.run([*git, *cmd], check=True, capture_output=True, text=True)
    (repo / "f.txt").write_text("dev", encoding="utf-8")
    subprocess.run([*git, "add", "f.txt"], check=True)
    subprocess.run([*git, "commit", "-qm", "initial"], check=True)
    tip = subprocess.run(
        [*git, "rev-parse", "HEAD"], capture_output=True, text=True,
        check=True).stdout.strip()
    subprocess.run([*git, "update-ref", "refs/remotes/origin/dev", tip],
                   check=True)
    return repo, tip


def _side_commit(tmp: Path, repo: Path) -> str:
    """A commit NOT reachable from the dev tip (merge-base --is-ancestor = no)."""
    git = ["git", "-C", str(repo)]
    subprocess.run([*git, "checkout", "-qb", "side", "HEAD"], check=True,
                   capture_output=True, text=True)
    (repo / "side.txt").write_text("side", encoding="utf-8")
    subprocess.run([*git, "add", "side.txt"], check=True)
    subprocess.run([*git, "commit", "-qm", "side"], check=True)
    return subprocess.run(
        [*git, "rev-parse", "HEAD"], capture_output=True, text=True,
        check=True).stdout.strip()


# ---------- 超前 form — S2 (issue 1042): both segments accepted, PR OPEN ----------

def test_ahead_form_closeout_accepted_without_merge_sha_refuses_and_names_chain(tmp_path):
    # Arrange — red op "去掉 merge_sha": the settled record minus the field.
    path = _write_record(_settled_record(merge_sha=None), tmp_path)

    # Act
    r = _run_tool("check", str(path))

    # Assert
    assert r.returncode == RC_REFUSE
    assert "S-TEST" in r.stdout
    assert "merge_sha" in r.stdout


def test_ahead_form_merge_sha_not_dev_ancestor_refuses(tmp_path):
    # Arrange — red op "给一个不在 dev 上的 sha": a real commit, but not on
    # origin/dev's history.
    repo, _dev_tip = _mk_repo_with_dev(tmp_path)
    side = _side_commit(tmp_path, repo)
    path = _write_record(_settled_record(merge_sha=side), tmp_path)

    # Act
    r = _run_tool("check", str(path), "--repo", str(repo))

    # Assert
    assert r.returncode == RC_REFUSE
    assert "not an ancestor" in r.stdout
    assert side in r.stdout


def test_closeout_accepted_merge_sha_ancestor_of_dev_passes(tmp_path):
    # Arrange — the reconciled fact: merge_sha IS the dev tip (S13/S17 form).
    repo, dev_tip = _mk_repo_with_dev(tmp_path)
    path = _write_record(_settled_record(merge_sha=dev_tip), tmp_path)

    # Act
    r = _run_tool("check", str(path), "--repo", str(repo))

    # Assert
    assert r.returncode == RC_PASS


def test_closeout_accepted_with_abandoned_reason_passes(tmp_path):
    # Arrange — explicit give-up (spec §6: PR 已合并，或明确放弃).
    record = _settled_record(merge_sha=None)
    record["segments"][-1]["abandoned"] = "owner ruled the chain obsolete"

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_PASS


def test_closeout_accepted_with_merge_sha_and_abandoned_refuses(tmp_path):
    # Arrange — contradictory evidence: both merge_sha and abandoned present.
    record = _settled_record(merge_sha=SAMPLE_SHA)
    record["segments"][-1]["abandoned"] = "but also merged"

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE


# ---------- 落后 form — S13 (issue 1005): row partial-advanced, status still pending ----------

def test_behind_form_pending_row_with_owner_refuses(tmp_path):
    # Arrange — the S13 (issue 1005) shape: closeout row carries an owner (the
    # segment DID work, "working 期间就更新 owner") while status stayed
    # pending: the record lags the fact. Chain id "S13" is whitelisted for
    # dev-chain/1, so this fixture is read under the same legacy lens as
    # the real record — a re-enactment of its pre-fix standing. The
    # owner↔status rule is schema-independent. The incident-literal
    # null-owner form is shape-legal by design (issue admits stalled vs
    # unclaimed is indistinguishable); this is the partial-advance
    # projection the reader can refuse.
    record = _settled_record(chain="S13", schema="dev-chain/1", merge_sha=None)
    record["segments"][-1].update(
        {"owner": "s13-end", "status": "pending", "updated_at": None})

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE
    assert "pending" in r.stdout and "owner" in r.stdout


def test_working_row_without_updated_at_refuses(tmp_path):
    # Arrange — working must carry a timestamp (else age is inscrutable).
    record = _settled_record(merge_sha=None)
    record["segments"][-1].update({"status": "working", "updated_at": None})

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE


def test_working_row_without_owner_refuses(tmp_path):
    # Arrange — working-but-unnamed: who is working?
    record = _settled_record(merge_sha=None)
    record["segments"][-1].update(
        {"status": "working", "owner": None, "updated_at": _now_iso()})

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE


# ---------- 辅助字段 form — N0: closeout_step=DONE, status stuck working ----------

def test_aux_form_working_row_stale_updated_at_reports_stagnant(tmp_path):
    # Arrange — the N0 shape: the result lives in an auxiliary field
    # (closeout_step=DONE); the authoritative status stayed working with
    # an aged timestamp. Chain id "N0" is whitelisted for dev-chain/1, so
    # this fixture is read under the same legacy lens as the real record —
    # a re-enactment of its pre-fix standing. The reader cannot know the
    # auxiliary field's semantics — it reports the failure mode the
    # carrier exists for: a working row past the stated threshold.
    stale = (datetime.now(timezone.utc) - timedelta(hours=3)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    record = _settled_record(chain="N0", schema="dev-chain/1", merge_sha=None)
    record["segments"][-1].update(
        {"status": "working", "updated_at": stale, "closeout_step": "DONE"})

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)),
                  "--stale-hours", "1")

    # Assert
    assert r.returncode == RC_STAGNANT
    assert "STAGNANT" in r.stdout
    assert "end" in r.stdout


def test_working_row_fresh_updated_at_reads_clean(tmp_path):
    # Arrange — a genuinely in-flight chain (S16's own shape while working).
    record = _settled_record(schema="dev-chain/2", merge_sha=None)
    record["segments"][-1].update(
        {"status": "working", "updated_at": _now_iso(), "owner": "s16-s1"})

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)),
                  "--stale-hours", "12")

    # Assert
    assert r.returncode == RC_PASS


# ---------- history tolerance: pre-mechanization records must read clean ----------

def test_legacy_accepted_closeout_without_merge_sha_reads_clean(tmp_path):
    # Arrange — the S1/N0/S2 shape: closeout accepted with no merge
    # evidence. The rule did not exist when these chains were written, so
    # the reader bounds dev-chain/1 to the whitelisted pre-mechanization
    # chains (chain id "S1" is a member) and lets this exact shape pass —
    # flagging real history would be the false positive this tool must
    # never produce.
    path = _write_record(
        _settled_record(chain="S1", schema="dev-chain/1", merge_sha=None),
        tmp_path)

    # Act
    r = _run_tool("check", str(path), "--stale-hours", "12")

    # Assert
    assert r.returncode == RC_PASS


def test_new_chain_claiming_legacy_schema_refuses(tmp_path):
    # Arrange — a chain that is NOT one of the five pre-mechanization
    # records claims dev-chain/1 to skip the closeout evidence rules.
    # The next chain templates its record from the previous one and S13/S17
    # are v1, so this is a silent-by-copying escape, not an adversarial
    # act (end-segment appeal-1). Bounded tolerance: v1 belongs only to
    # N0/S1/S2/S13/S17.
    path = _write_record(
        _settled_record(chain="S20", schema="dev-chain/1", merge_sha=None),
        tmp_path)

    # Act
    r = _run_tool("check", str(path))

    # Assert
    assert r.returncode == RC_REFUSE
    assert "dev-chain/2" in r.stdout
    assert "S17" in r.stdout  # the message names the whitelist


@pytest.mark.skipif(
    not (_chain_home() / "N0" / "chain.json").exists(),
    reason="real chain history is local-only (~/.claude/kunglao-chains)")
def test_real_history_records_read_clean():
    # The five pre-mechanization chain records must read clean under legacy
    # tolerance — they are the evidence the reader must not misreport.
    for name in HISTORY_NAMES:
        path = _chain_home() / name / "chain.json"
        r = _run_tool("check", str(path), "--stale-hours", "12")
        assert r.returncode == RC_PASS, f"{name}: {r.stdout}{r.stderr}"


# ---------- schema / structure ----------

@pytest.mark.parametrize("schema", [None, "dev-chain/9"])
def test_missing_or_unknown_schema_refuses(schema, tmp_path):
    # Arrange — the reader cannot vouch for a shape it does not know; a
    # missing schema is malformed, an unknown one a version the reader
    # predates (fail loud: upgrade the reader).
    record = _settled_record(merge_sha=None)
    if schema is None:
        del record["schema"]
    else:
        record["schema"] = schema

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE
    assert "schema" in r.stdout


def test_last_segment_not_closeout_refuses(tmp_path):
    # Arrange — spec §6: the final segment must be the closeout.
    record = _settled_record(merge_sha=None)
    record["segments"][-1]["kind"] = "develop"

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE
    assert "closeout" in r.stdout


@pytest.mark.parametrize("segments", [None, [], "segments", [{"id": "x"}]])
def test_malformed_segments_list_refuses(segments, tmp_path):
    # Arrange — shape invariant: a non-empty list of segment objects.
    record = _settled_record(merge_sha=None)
    record["segments"] = segments

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE


def test_duplicate_segment_ids_refuses(tmp_path):
    # Arrange — ids are the keys of the segment list; duplicates make the
    # record ambiguous.
    record = _settled_record(merge_sha=None)
    record["segments"].append(dict(record["segments"][0]))

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE
    assert "duplicate" in r.stdout


@pytest.mark.parametrize("field,value", [("status", "done"), ("kind", "review")])
def test_unknown_status_or_kind_refuses(field, value, tmp_path):
    # Arrange — enums are the shape's vocabulary.
    record = _settled_record(merge_sha=None)
    record["segments"][0][field] = value

    # Act
    r = _run_tool("check", str(_write_record(record, tmp_path)))

    # Assert
    assert r.returncode == RC_REFUSE


# ---------- tool edges: unverifiable / invalid input ----------

def test_missing_chain_file_exits_unverifiable(tmp_path):
    # Act
    r = _run_tool("check", str(tmp_path / "nope.json"))

    # Assert
    assert r.returncode == RC_UNVERIFIABLE


def test_non_json_record_exits_unverifiable(tmp_path):
    # Arrange
    path = tmp_path / "chain.json"
    path.write_text("{not json", encoding="utf-8")

    # Act
    r = _run_tool("check", str(path))

    # Assert
    assert r.returncode == RC_UNVERIFIABLE


@pytest.mark.parametrize("repo_arg", [None, "repo-without-dev"])
def test_ancestry_unverifiable_exits_2(repo_arg, tmp_path):
    # Arrange — ancestry is a hard requirement of the mechanized closeout
    # evidence and CANNOT be skipped: no --repo, or --repo without the
    # origin/dev ref, means the check did not run (fail closed, exit 2).
    repo, _dev_tip = _mk_repo_with_dev(tmp_path)
    if repo_arg == "repo-without-dev":
        subprocess.run(["git", "-C", str(repo), "update-ref", "-d",
                        "refs/remotes/origin/dev"], check=True)
        arg = ["--repo", str(repo)]
    else:
        arg = []
    path = _write_record(_settled_record(merge_sha=SAMPLE_SHA), tmp_path)

    # Act
    r = _run_tool("check", str(path), *arg)

    # Assert
    assert r.returncode == RC_UNVERIFIABLE


def test_pr_state_best_effort_reported_on_refusal(tmp_path):
    # Arrange — the refusal reports the actual PR state when asked
    # (--pr-state): a --repo without a github remote degrades to an explicit
    # "unavailable" instead of spawning anything or guessing.
    repo, dev_tip = _mk_repo_with_dev(tmp_path)
    record = _settled_record(merge_sha="a" * 40)  # not on dev
    path = _write_record(record, tmp_path)

    # Act
    r = _run_tool("check", str(path), "--repo", str(repo), "--pr-state")

    # Assert
    assert r.returncode == RC_REFUSE
    assert "PR state" in r.stdout
    assert "unavailable" in r.stdout


def test_help_exits_zero():
    # Act
    r = _run_tool("--help")

    # Assert
    assert r.returncode == RC_PASS
    assert "check" in r.stdout