# -*- coding: utf-8 -*-
"""Production Stop-to-settlement contract using only synthetic workspace data."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _factories import write_hook_state
from rlvr import consolidated_ledger, episode_pool, ledger, pool_indexer
import verifier_identity

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "completion_gate.py"


def terminal_workspace(tmp_path: Path) -> Path:
    """One synthetic mission with a checker artifact, rollout, and cost."""
    ws = tmp_path / "workspace"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({
        "claims": [{"id": "C-001", "status": "PROVEN",
                    "title": "synthetic result", "answers_question": "pq1",
                    "maker_identity": "synthetic-worker-1"}]
    }), encoding="utf-8")
    (ws / "task_spec.yaml").write_text(yaml.safe_dump({
        "family": "synthetic-static",
        "primary_questions": [{"id": "pq1", "q": "analyze synthetic result"}]
    }), encoding="utf-8")
    (ws / "task-oracle.yaml").write_text(yaml.safe_dump({
        "task_text": "analyze synthetic result",
        "workspace_path": str(ws),
        "open_items": [{"id": "OC-1", "closed_by": "C-001"}],
    }), encoding="utf-8")
    write_hook_state(ws, active_hooks=["completion_gate"], expires_minutes=30)
    check = ws / "runs" / "verification-C-001.md"
    check.write_text(
        "verifier-identity: independent-checker-1\n"
        "verdict: verified\nclaim: C-001\n", encoding="utf-8")
    verifier_identity.anchor(ws, "C-001", check.name, "independent-checker-1")
    assert ledger.record(ws, kind="task", anchor="test-1",
                         rollout_id="task/test-1", signals=[],
                         ts="2026-01-01T00:00:00Z")["appended"]
    assert consolidated_ledger.append(ws, "settlement", {
        "schema": "cost-event/1", "amount": 0.25,
    })
    return ws


def invoke_stop(ws: Path, *, profile: Path, **payload) -> subprocess.CompletedProcess:
    profile.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, HOME=str(profile),
               KUNGLAO_POSTERIOR_STORE=str(profile / "posterior"),
               KUNGLAO_EVAL_SETTLE="0")
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps({"cwd": str(ws), **payload}),
                          capture_output=True, text=True, timeout=60, env=env)


def test_eligible_stop_settles_once_and_is_readable(tmp_path):
    ws = terminal_workspace(tmp_path)
    profile = tmp_path / "isolated-profile"
    assert episode_pool.list_episodes(ws) == []
    assert len(ledger.pending_settlement(ws)) == 1

    stopped = invoke_stop(ws, profile=profile)
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    episodes = episode_pool.list_episodes(ws)
    assert len(episodes) == 1, "eligible production Stop did not settle mission"
    episode, _ = episode_pool.es.read_episode_file(episodes[0])
    assert episode["claim"] == "C-001"
    assert episode["outcome"]["status"] == "completed"
    assert episode["cost"]["spend_usd"] == pytest.approx(0.25)
    assert not ledger.pending_settlement(ws)
    assert pool_indexer.value_table(ws), "settled episode is absent from the value view"

    first_rows = ledger.read(ws)
    stopped_again = invoke_stop(ws, profile=profile)
    assert stopped_again.returncode == 0, (stopped_again.stdout, stopped_again.stderr)
    assert episode_pool.list_episodes(ws) == episodes
    assert ledger.read(ws) == first_rows


@pytest.mark.parametrize("failure,code,reason", [
    ("oracle", 1, "OC-1"),
    ("notes_due", 5, "NOTES_DUE"),
    ("notes_fake", 6, "NOTES_FAKE"),
    ("summary_fake", 7, "SUMMARY_FAKE"),
])
def test_final_gate_refusals_leave_ledger_and_episode_unsettled(
        tmp_path, failure, code, reason):
    ws = terminal_workspace(tmp_path)
    if failure == "oracle":
        oracle = yaml.safe_load((ws / "task-oracle.yaml").read_text())
        oracle["open_items"][0].pop("closed_by")
        (ws / "task-oracle.yaml").write_text(yaml.safe_dump(oracle))
    elif failure == "notes_due":
        (ws / "runs" / "notes-due.yaml").write_text(
            "due:\n- claim_id: C-001\n", encoding="utf-8")
    elif failure == "notes_fake":
        (ws / "notes").mkdir()
        (ws / "notes" / "C-001.md").write_text("ungrounded\n", encoding="utf-8")
    else:
        (ws / "facts").mkdir()
        (ws / "facts" / "F002.md").write_text(
            "---\nid: F002\nstatus: INFERRED\n---\n"
            "unconfirmed hypothesis pending verification\n", encoding="utf-8")
        (ws / "summary.md").write_text("# 分析收敛完成\n全部闭合。\n",
                                       encoding="utf-8")

    before = ledger.read(ws)
    stopped = invoke_stop(ws, profile=tmp_path / "profile")
    assert stopped.returncode == code, (stopped.stdout, stopped.stderr)
    assert reason in stopped.stdout
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before


def test_sanctioned_second_stop_cannot_bypass_the_remaining_checks(tmp_path):
    ws = terminal_workspace(tmp_path)
    profile = tmp_path / "isolated-profile"
    profile.mkdir()
    oracle_path = ws / "task-oracle.yaml"
    oracle = yaml.safe_load(oracle_path.read_text(encoding="utf-8"))
    oracle["adjudication"] = {"stop_hook_active": {"second_stop": True}}
    oracle_path.write_text(yaml.safe_dump(oracle), encoding="utf-8")
    (ws / "runs" / "notes-due.yaml").write_text(
        "due:\n- claim_id: C-001\n", encoding="utf-8")
    env = dict(os.environ, HOME=str(profile))
    init = subprocess.run([sys.executable, str(HOOK), "sanction-key-init"],
                          capture_output=True, text=True, timeout=60, env=env)
    assert init.returncode == 0, init.stderr
    before = ledger.read(ws)
    first = invoke_stop(ws, profile=profile)
    assert first.returncode == 5 and "NOTES_DUE" in first.stdout
    assert list((profile / ".claude" / "kunglao" / "sanctions").glob("*.json"))
    second = invoke_stop(ws, profile=profile, stop_hook_active=True)
    assert second.returncode == 0, (second.stdout, second.stderr)
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before


@pytest.mark.parametrize("mode", ["inactive", "oracle_io_error"])
def test_passthrough_is_not_terminal_evidence(tmp_path, mode):
    ws = terminal_workspace(tmp_path)
    if mode == "inactive":
        (ws / ".hook_state.json").unlink()
    else:
        (ws / "task-oracle.yaml").unlink()
        (ws / "task-oracle.yaml").mkdir()
    before = ledger.read(ws)
    stopped = invoke_stop(ws, profile=tmp_path / "profile")
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before


@pytest.mark.parametrize("status", ["OPEN", "IN_PROGRESS", "BLOCKED"])
def test_nonterminal_or_unsupported_claim_status_does_not_settle(tmp_path, status):
    ws = terminal_workspace(tmp_path)
    register = yaml.safe_load((ws / "claim-register.yaml").read_text())
    register["claims"].append({"id": "C-002", "status": status})
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(register))
    before = ledger.read(ws)
    invoke_stop(ws, profile=tmp_path / "profile")
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before


def test_surrender_disposition_does_not_prove_completed_mission(tmp_path):
    from rlvr import disposition_producer

    ws = terminal_workspace(tmp_path)
    register = yaml.safe_load((ws / "claim-register.yaml").read_text())
    register["claims"][0]["status"] = "NEGATIVE"
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(register))
    spec = yaml.safe_load((ws / "task_spec.yaml").read_text())
    spec["authorization"] = {"targets": ["target.example"], "excluded": [],
                             "authorization_ref": "ticket-test"}
    (ws / "task_spec.yaml").write_text(yaml.safe_dump(spec))
    (ws / "runs" / "verification-C-001.md").unlink()
    assert disposition_producer.produce(ws)["written"] == 1
    disposition = json.loads((ws / "runs" / "disposition" / "C-001.json")
                             .read_text(encoding="utf-8"))
    assert disposition["disposition"] == "SURRENDER"
    before = ledger.read(ws)
    invoke_stop(ws, profile=tmp_path / "profile")
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before


def test_missing_independent_checker_cannot_be_replaced_by_a_mirror(tmp_path):
    ws = terminal_workspace(tmp_path)
    (ws / "runs" / "verification-C-001.md").unlink()
    before = ledger.read(ws)
    invoke_stop(ws, profile=tmp_path / "profile")
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before
    assert not (ws / "runs" / "verification-C-001.md").exists()


def test_verified_negative_terminal_is_recorded_as_failure(tmp_path):
    ws = terminal_workspace(tmp_path)
    register = yaml.safe_load((ws / "claim-register.yaml").read_text())
    register["claims"][0]["status"] = "NEGATIVE"
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(register))
    checker = ws / "runs" / "verification-C-001.md"
    checker.write_text("verifier-identity: independent-checker-1\n"
                       "verdict: refuted\nclaim: C-001\n", encoding="utf-8")
    verifier_identity.anchor(ws, "C-001", checker.name, "independent-checker-1")
    stopped = invoke_stop(ws, profile=tmp_path / "profile")
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    episodes = episode_pool.list_episodes(ws)
    assert len(episodes) == 1, "verified failure was not settled"
    episode, _ = episode_pool.es.read_episode_file(episodes[0])
    assert episode["outcome"]["status"] == "failed"
    assert episode["outcome"]["verified"] is True
    assert episode["attribution"]


def test_durable_retry_recovers_after_derived_view_failure(tmp_path, monkeypatch):
    from rlvr import episode_settle, production_terminal

    ws = terminal_workspace(tmp_path)
    original = episode_settle.derived_views
    monkeypatch.setattr(episode_settle, "derived_views",
                        lambda _: (_ for _ in ()).throw(OSError("injected")))
    with pytest.raises(OSError):
        production_terminal.settle_stop(ws)
    checkpoint = ws / "runs" / "production-terminal.json"
    assert json.loads(checkpoint.read_text())["status"] == "retry"
    assert len(episode_pool.list_episodes(ws)) == 1
    before = ledger.read(ws)
    monkeypatch.setattr(episode_settle, "derived_views", original)
    stopped = invoke_stop(ws, profile=tmp_path / "profile")
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    assert json.loads(checkpoint.read_text())["status"] == "completed"
    assert len(episode_pool.list_episodes(ws)) == 1
    assert ledger.read(ws)[:len(before)] == before
    recovered = ledger.read(ws)
    assert invoke_stop(ws, profile=tmp_path / "profile").returncode == 0
    assert ledger.read(ws) == recovered


def test_durable_intent_precedes_any_settlement_write(tmp_path, monkeypatch):
    from rlvr import production_terminal

    ws = terminal_workspace(tmp_path)
    before = ledger.read(ws)
    monkeypatch.setattr(production_terminal, "_checkpoint",
                        lambda *_: (_ for _ in ()).throw(OSError("disk-full")))
    with pytest.raises(OSError):
        production_terminal.settle_stop(ws)
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before


def test_concurrent_production_stops_do_not_duplicate(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    ws = terminal_workspace(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(
            lambda _: invoke_stop(ws, profile=tmp_path / "profile"), range(2)))
    assert all(r.returncode == 0 for r in results), [r.stderr for r in results]
    assert len(episode_pool.list_episodes(ws)) == 1
    amendments = [r for r in ledger.read(ws) if r.get("settlement")]
    # One initial rule settlement plus the existing scalar tier amendment.
    assert len(amendments) == 2
    assert "tier" not in amendments[0]["settlement"]
    assert "tier" in amendments[1]["settlement"]
    assert len({r["rollout_id"] for r in ledger.read(ws)}) == 1
    assert not ledger.pending_settlement(ws)


@pytest.mark.parametrize("fault", ["same_identity", "tampered_checker", "no_maker"])
def test_untrusted_checker_identity_never_enters_settlement(tmp_path, fault):
    ws = terminal_workspace(tmp_path)
    if fault == "tampered_checker":
        with (ws / "runs" / "verification-C-001.md").open("a") as stream:
            stream.write("changed after anchor\n")
    else:
        p = ws / "claim-register.yaml"
        doc = yaml.safe_load(p.read_text())
        if fault == "same_identity":
            doc["claims"][0]["maker_identity"] = "independent-checker-1"
        else:
            doc["claims"][0].pop("maker_identity")
        p.write_text(yaml.safe_dump(doc))
    before = ledger.read(ws)
    stopped = invoke_stop(ws, profile=tmp_path / "profile")
    assert stopped.returncode == 0, stopped.stderr
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before
