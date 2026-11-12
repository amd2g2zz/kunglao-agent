"""Synthetic artifacts cross real dispatch/completion/Stop and credit owners."""
from __future__ import annotations

import random

import yaml

import _rl_e2e as H
from _factories import write_hook_state
from test_production_terminal_1005 import invoke_stop
from rlvr import consolidated_ledger as cl, episode_pool, learning_seal as seal
from rlvr import q_cells
import verifier_identity


def test_armed_production_stop_banks_dispatch_credit_once(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    monkeypatch.setenv("HOME", str(profile))
    monkeypatch.setattr(seal, "KEY_PATH", profile / ".claude" / seal.KEY_PATH.name)
    assert seal.provision()["armed"]
    monkeypatch.setenv("KUNGLAO_EVAL_SETTLE", "0")
    ws = H.build_workspace(tmp_path, seed=11, n_claims=1)
    write_hook_state(ws, active_hooks=["completion_gate", "round_closure"])
    family, claim = "static-symbolic", "C-001"
    dispatched = H.dispatch_round(ws, claim, family)
    sig = dispatched["observation"]["signature_hash"]
    ak = q_cells.arm_key(family, "facts_snapshot", "none", 1)
    before = q_cells.cell_posterior(q_cells.fold(q_cells.default_store(ws), gamma=1),
                                    sig, family, arm_key=ak)
    assert before == (1.0, 1.0)
    candidates = {family: 0.5, "strings-first": 0.5}
    def receipts():
        return [q_cells.sample_method_family(sig, candidates,
            q_cells.default_store(ws), rng=random.Random(seed), gamma=1,
            arm_context={"tier": 1}) for seed in range(64)]
    decisions_before = receipts()
    H.complete_round(ws, claim, artifact_rel="evidence/synthetic.bin",
                     payload=b"synthetic bounded evidence")
    H.close_round(ws, claim, "maker-session")
    H.rule_round(ws, claim, credit=0.8, oracle_verdict="pass")
    checker = ws / "runs" / f"verification-{claim}.md"
    checker.write_text("verifier-identity: checker-session\nverdict: verified\n")
    verifier_identity.anchor(ws, claim, checker.name, "checker-session")
    p = ws / "claim-register.yaml"
    register = yaml.safe_load(p.read_text())
    register["claims"][0].update(status="PROVEN", maker_identity="maker-session")
    p.write_text(yaml.safe_dump(register))
    from rlvr import settlement_wire
    from pathlib import Path
    parked = settlement_wire.load_parked(ws, claim)
    assert parked["question"], parked
    assert Path(parked["rules"]["path"]).is_absolute()
    assert parked["artifacts"]
    H.close_round(ws, claim, "checker-session")
    assert H.task_settlement(ws, claim) is not None
    (ws / "task-oracle.yaml").write_text(yaml.safe_dump({
        "task_text": "what is the sample's behaviour chain?",
        "workspace_path": str(ws),
        "open_items": [{"id": "OC-1", "closed_by": claim}]}))
    stopped = invoke_stop(ws, profile=profile)
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    assert len(episode_pool.list_episodes(ws)) == 1
    after = q_cells.cell_posterior(q_cells.fold(q_cells.default_store(ws), gamma=1),
                                   sig, family, arm_key=ak)
    assert after != before, "production Stop never banked Q-cell credit"
    decisions_after = receipts()
    assert any(a["family"] != b["family"] for a, b in
               zip(decisions_before, decisions_after))
    (ws / "runs" / "production-learning-decisions.json").write_text(
        __import__("json").dumps({"before": decisions_before, "after": decisions_after}))
    observations = cl.read(ws, "experience", schema_prefix="q-cell-obs")
    credit = [r for r in observations if r.get("source") == "settlement"]
    assert credit and all(r["dispatch_id"] == dispatched["journal_id"] for r in credit)
    round_rows = [r for r in cl.read(ws, "settlement", schema_prefix="rollout-ledger")
                  if r.get("kind") == "round_credit"]
    assert round_rows and all(seal.verify_row(r)[0] for r in round_rows)
    H.close_round(ws, claim, "maker-session")
    again = invoke_stop(ws, profile=profile)
    assert again.returncode == 0, again.stdout
    assert q_cells.cell_posterior(q_cells.fold(q_cells.default_store(ws), gamma=1),
                                 sig, family, arm_key=ak) == after
    assert len(episode_pool.list_episodes(ws)) == 1
