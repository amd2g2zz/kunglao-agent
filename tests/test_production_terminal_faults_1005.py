"""Review P1 regressions: a real Stop cannot certify unreadable obligations,
invalid learning seals or a swallowed missing-credit recovery failure.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

import claims_store
from rlvr import episode_pool, learning_seal as seal, ledger, production_terminal as terminal
from rlvr import q_cells
import test_production_learning_1005 as learning
from test_production_terminal_1005 import ROOT, invoke_stop, terminal_workspace


@pytest.mark.parametrize("content", [None, "due: [", "- malformed-root", "due: wrong-shape"])
def test_notes_internal_read_failure_blocks_and_recovers(tmp_path, content):
    ws = terminal_workspace(tmp_path)
    queue = ws / "runs" / "notes-due.yaml"
    if content is None:
        queue.mkdir()
    else:
        queue.write_text(content)
    before = ledger.read(ws)
    stopped = invoke_stop(ws, profile=tmp_path / "profile")
    assert stopped.returncode != 0
    checkpoint = terminal.inspect(ws)["checkpoint"]
    assert checkpoint["status"] == "retry" and "notes" in checkpoint["reason"]
    assert episode_pool.list_episodes(ws) == []
    assert ledger.read(ws) == before
    queue.rmdir() if content is None else queue.unlink()
    assert invoke_stop(ws, profile=tmp_path / "profile").returncode == 0
    assert terminal.inspect(ws)["checkpoint"]["status"] == "completed"


def _armed_workspace(tmp_path, monkeypatch):
    learning.test_armed_production_stop_banks_dispatch_credit_once(tmp_path, monkeypatch)
    return tmp_path / "ws-resume-11"


@pytest.mark.parametrize("fault", ["row", "missing_key", "corrupt_key"])
def test_existing_credit_seal_failure_blocks_without_replacing_evidence(
        tmp_path, monkeypatch, fault):
    ws = _armed_workspace(tmp_path, monkeypatch)
    path = ws / "runs" / "settlement.jsonl"
    original = path.read_bytes()
    key_path, key_bytes = seal.keyfile(), seal.keyfile().read_bytes()
    if fault == "row":
        docs = [json.loads(line) for line in original.decode().splitlines()]
        victim = next(r for r in docs if r.get("kind") == "round_credit" and r.get("settlement"))
        victim["reward"] += 0.001
        victim["settlement"].update(reward=victim["reward"], credit_units=victim["reward"])
        assert not seal.verify_row(victim)[0]
        path.write_text("".join(json.dumps(row) + "\n" for row in docs))
    elif fault == "missing_key":
        key_path.unlink()
    else:
        key_path.write_bytes(b"short")
    preserved = path.read_bytes()
    key_before = key_path.read_bytes() if key_path.exists() else None
    stopped = invoke_stop(ws, profile=tmp_path / "profile")
    assert stopped.returncode != 0
    checkpoint = terminal.inspect(ws)["checkpoint"]
    assert checkpoint["status"] == "retry" and "seal" in checkpoint["reason"]
    assert path.read_bytes() == preserved
    assert (key_path.read_bytes() if key_path.exists() else None) == key_before
    path.write_bytes(original)
    key_path.write_bytes(key_bytes)
    assert invoke_stop(ws, profile=tmp_path / "profile").returncode == 0
    assert terminal.inspect(ws)["checkpoint"]["status"] == "completed"


def test_real_stop_rejects_swallowed_q_cell_repair_failure_then_recovers(tmp_path, monkeypatch):
    ws = _armed_workspace(tmp_path, monkeypatch)
    did = claims_store.latest_committed_dispatch(ws, "C-001")["dispatch_id"]
    path = ws / "runs" / "experience.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows
        if not (row.get("schema", "").startswith("q-cell-obs")
                and row.get("source") == "settlement")))
    assert q_cells.banked_mass(ws, did)[2] == 0
    preserved = (ws / "runs" / "settlement.jsonl").read_bytes()
    env = dict(os.environ, HOME=str(tmp_path / "profile"),
               PYTHONPATH=os.pathsep.join((str(ROOT / "hooks"), str(ROOT / "scripts"))),
               KUNGLAO_POSTERIOR_STORE=str(tmp_path / "profile" / "posterior"))
    code = """
import runpy
from rlvr import q_cells
def fail(*args, **kwargs):
    raise OSError('injected credit bank failure')
q_cells.observe_settlement = fail
runpy.run_path(__import__('sys').argv[1], run_name='__main__')
"""
    stopped = subprocess.run([sys.executable, "-c", code, str(ROOT / "hooks/completion_gate.py")],
        input=json.dumps({"cwd": str(ws)}), text=True, capture_output=True, timeout=90, env=env)
    assert stopped.returncode != 0, (stopped.stdout, stopped.stderr)
    checkpoint = terminal.inspect(ws)["checkpoint"]
    assert checkpoint["status"] == "retry" and "credit" in checkpoint["reason"]
    assert q_cells.banked_mass(ws, did)[2] == 0
    assert (ws / "runs" / "settlement.jsonl").read_bytes() == preserved
    assert len(episode_pool.list_episodes(ws)) == 1
    assert invoke_stop(ws, profile=tmp_path / "profile").returncode == 0
    recovered = q_cells.banked_mass(ws, did)
    assert recovered is not None and recovered[2] > 0
    assert invoke_stop(ws, profile=tmp_path / "profile").returncode == 0
    assert q_cells.banked_mass(ws, did) == recovered
