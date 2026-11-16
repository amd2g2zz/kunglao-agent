# -*- coding: utf-8 -*-
"""Producer attribution and dispatch-id alignment.

Settlement must bank a fact's PRODUCTION credit on the dispatch that
created the fact — the harness-stamped ``created_by_dispatch``, never the
claim's latest dispatch. The stamp is write-once (an edit never
re-stamps the producer), worker-supplied stamps are dropped at write,
and a fact without a trusted stamp degrades to the named
``creator-stamp-missing`` fallback. A verifying dispatch keeps its own
verification credit on its own arm (inadmissible to the solve posterior)
and can never claim the maker's credit. The q-cell dispatch observation
written at the dispatch ALLOW tail must carry the exact dispatch_id the
dispatch ledger recorded for that dispatch, so ``observe_settlement``
matches and banks.

Fixtures are synthetic (no workspace data)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import claims_store  # noqa: E402
import settle_round_credit as src  # noqa: E402
from rlvr import q_cells, strategy_store  # noqa: E402
from _dispatch_fixture import mint_dispatches  # noqa: E402

FAM_WORKER = "static-decompile"
FID1 = "F001-finding"
FID2 = "F002-verified"
FAM_REDTEAM = "red-team-verification"

_SHA = "b" * 64
_FACT_TMPL = """---
id: {fid}
type: fact
title: {fid}
status: PROVEN
created: 2026-08-20
last_reviewed: 2026-08-20
claim_id: {claim}
claim: sample resolves imports dynamically
boundary_type: observation
promotion_gate: resolve the loader stub under dynamic-trace
source: static-decompile
confidence: high
verify_status: passes
reproduce: python runs/verify.py
expected: {_SHA}
verified: 2026-08-20
verifier_sign_off:
  verifier_id: independent-checker-1
  verdict: CONFIRMED
provenance:
  - {{role: decompiled_c, path: evidence/{fid}.c, content_sha256: {_SHA}, credibility: B2}}
---

# {fid}

## Status
PROVEN
"""


def _fact_text(fid: str, claim: str, *, stamp: str | None = None) -> str:
    text = _FACT_TMPL.format(fid=fid, claim=claim, _SHA=_SHA)
    if stamp:
        text = text.replace("---\n", f"---\ncreated_by_dispatch: {stamp}\n", 1)
    return text


def _ws(tmp_path: Path, claim: dict | None = None) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    claim = claim or {"id": "C-001", "status": "OPEN",
                      "answers_question": "q-x"}
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [claim]}), encoding="utf-8")
    return ws


def _run_write_guard(payload: dict) -> dict:
    """Drive write_guard.main() as the harness does; return the parsed
    stdout JSON (the updatedInput emission), {} when none was emitted."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8",
               PYTHONPATH=os.pathsep.join([str(ROOT), str(HOOKS),
                                           str(SCRIPTS)]))
    proc = subprocess.run(
        [sys.executable, str(HOOKS / "write_guard.py")],
        input=json.dumps(payload), capture_output=True, text=True,
        timeout=60, env=env)
    assert proc.returncode == 0, proc.stderr
    out: dict = {}
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            out = json.loads(line)
    return out


def _stamp_payload(ws: Path, target: Path, text: str, tool: str = "Write",
                   **tool_input) -> dict:
    return {"tool_name": tool, "cwd": str(ws),
            "tool_input": {"file_path": str(target),
                           **({"content": text} if tool == "Write" else {}),
                           **tool_input}}


def _updated(out: dict) -> dict:
    return (out.get("hookSpecificOutput") or {}).get("updatedInput") or {}


def _write_fact(ws: Path, fid: str, claim: str, *, text: str | None = None,
                tool: str = "Write", **tool_input) -> str:
    """Write one fact THROUGH write_guard.main() — the harness stamp
    rides the tool's own write (updatedInput); the content the hook
    returns is what lands. Returns the landed text."""
    target = ws / "facts" / f"{fid}.md"
    body = text if text is not None else _fact_text(fid, claim)
    out = _run_write_guard(_stamp_payload(ws, target, body, tool,
                                          **tool_input))
    updated = _updated(out)
    if tool == "Write":
        landed = updated.get("content", body)
    elif tool == "Edit":
        landed = updated.get("new_string", body)
    else:
        landed = updated.get("edits", [{}])[0].get("new_string", body)
    target.write_text(landed, encoding="utf-8")
    return landed


def _settle_rows(ws: Path) -> list[dict]:
    return [r for r in q_cells.JSONLQStore(ws).observations()
            if r.get("source") == "settlement"]


def _mint(ws: Path, claim: dict, family: str) -> str:
    did = mint_dispatches(ws, [claim], family=family)[str(claim["id"])]
    assert claims_store.confirm_dispatch(ws, str(claim["id"]))
    return did


# --------------------------------------------------------------------------
# acceptance 1: production credit -> the creating dispatch's arm; the
# verifier's verification credit stays on the verifier's own arm.
# --------------------------------------------------------------------------

def test_production_credit_lands_on_the_creating_dispatch(tmp_path):
    ws = _ws(tmp_path)
    claim = {"id": "C-001", "status": "OPEN", "answers_question": "q-x"}
    # dispatch A (the worker) creates the fact; dispatch B (the redteam)
    # verifies it later — so B is the claim's LATEST committed dispatch.
    did_a = _mint(ws, claim, FAM_WORKER)
    landed = _write_fact(ws, FID1, "C-001")
    assert f"created_by_dispatch: {did_a}" in landed, landed
    did_b = _mint(ws, claim, FAM_REDTEAM)
    assert claims_store.latest_committed_dispatch(
        ws, "C-001")["dispatch_id"] == did_b, "B must be the latest dispatch"
    # B's own verification credit — keyed on B's arm, inadmissible to the
    # solve posterior.
    ver = q_cells.observe_settlement(ws, did_b, 1.0,
                                     credit_kind="verification")
    assert ver["matched"] and ver["beta_updated"] is False
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-001", "status": "PROVEN",
         "answers_question": "q-x"}]}), encoding="utf-8")

    out = src.run(ws)
    assert out["settled"] == 1, out

    rows = _settle_rows(ws)
    solve = [r for r in rows if not r.get("credit_kind")]
    verify = [r for r in rows
              if str(r.get("credit_kind") or "") == "verification"]

    # the fact's production credit banks on A's arm — the worker's family
    assert len(solve) == 1, solve
    assert solve[0]["dispatch_id"] == did_a, solve
    assert solve[0]["method_family"] == FAM_WORKER, solve
    assert solve[0]["credit"] == 1.0, solve

    # B's verification credit stays on B's own arm
    assert len(verify) == 1, verify
    assert verify[0]["dispatch_id"] == did_b, verify
    assert verify[0]["method_family"] == FAM_REDTEAM, verify

    # worker credit can never be claimed by a verifier dispatch
    assert not [r for r in solve if r.get("dispatch_id") == did_b]


# --------------------------------------------------------------------------
# acceptance 2: q-cell observation id == dispatch-ledger id; observe_
# settlement matches and banks against those rows.
# --------------------------------------------------------------------------

def test_qcell_observation_id_matches_the_dispatch_ledger(tmp_path):
    sys.path.insert(0, str(HOOKS))
    try:
        import worker_budget_sinks as sinks
    finally:
        sys.path.pop(0)
    ws = _ws(tmp_path)
    paths = {"workspace": str(ws), "state": ws / "analysis_state.txt",
             "register": ws / "claim-register.yaml",
             "deps": ws / "claim_deps.yaml",
             "task_spec": ws / "task_spec.yaml"}
    prompt = (json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": "C-001", "tier": 1, "tools": ["grep"],
        "agent": "w-test", "method_family": FAM_WORKER}})
        + "\nfacts-snapshot: 1 facts")
    rc = sinks.pre_check(
        {"tool_input": {"name": "w-test", "description": "",
                        "prompt": prompt}}, paths)
    assert rc == 0

    q_rows = [r for r in q_cells.JSONLQStore(ws).observations()
              if r.get("source") == "dispatch"]
    assert q_rows, "the ALLOW tail must record one dispatch observation"
    ledger = [json.loads(line) for line in
              (ws / "runs" / "dispatch-ledger.jsonl").read_text(
                  encoding="utf-8").splitlines() if line.strip()]
    committed = [r for r in ledger if r.get("state") == "committed"]
    assert committed, ledger

    # the exact id the ledger recorded is the id the observation carries
    assert q_rows[-1].get("dispatch_id") == committed[-1]["dispatch_id"], (
        q_rows[-1].get("dispatch_id"), committed[-1]["dispatch_id"])

    # observe_settlement matches and banks against those rows
    res = q_cells.observe_settlement(ws, committed[-1]["dispatch_id"], 1.0)
    assert res["matched"] is True and res["appended"] is True, res


# --------------------------------------------------------------------------
# the stamp is write-once: a later dispatch's edit never re-stamps the
# producer to itself.
# --------------------------------------------------------------------------

def test_fact_stamp_is_write_once_across_dispatches(tmp_path):
    ws = _ws(tmp_path)
    claim = {"id": "C-001", "status": "OPEN", "answers_question": "q-x"}
    did_a = _mint(ws, claim, FAM_WORKER)
    landed = _write_fact(ws, FID1, "C-001")
    assert f"created_by_dispatch: {did_a}" in landed

    # the claim is re-dispatched to the redteam; the launch stash now
    # carries B — an EDIT that FORGES the stamp to B must leave A intact.
    did_b = _mint(ws, claim, FAM_REDTEAM)
    forged = landed.replace(f"created_by_dispatch: {did_a}",
                            f"created_by_dispatch: {did_b}")
    forged = forged.replace("dynamic-trace", "dynamic-trace v2")
    after = _write_fact(ws, FID1, "C-001", text=forged, tool="Edit",
                        old_string=landed, new_string=forged)
    assert f"created_by_dispatch: {did_a}" in after, after
    assert did_b not in after, after
    assert "dynamic-trace v2" in after, after


# --------------------------------------------------------------------------
# a worker-typed stamp is dropped at write and can never steal credit.
# --------------------------------------------------------------------------

def test_worker_typed_stamp_is_dropped_and_never_steals_credit(tmp_path):
    ws = _ws(tmp_path)
    claim = {"id": "C-001", "status": "OPEN", "answers_question": "q-x"}
    # V is a real dispatch that did NOT create the fact; A is the
    # dispatch running when the fact is written.
    did_victim = _mint(ws, claim, FAM_REDTEAM)
    did_a = _mint(ws, claim, FAM_WORKER)
    forged = _fact_text(FID1, "C-001", stamp=did_victim)
    landed = _write_fact(ws, FID1, "C-001", text=forged)
    assert did_victim not in landed, landed
    assert f"created_by_dispatch: {did_a}" in landed, landed

    # an unresolvable dispatch drops the field outright (the named
    # creator-stamp-missing degradation) — never carries the forge.
    (ws / "runs" / "dispatch-launch-C-001.json").unlink(missing_ok=True)
    forged2 = _fact_text(FID2, "C-001", stamp=did_victim)
    landed2 = _write_fact(ws, FID2, "C-001", text=forged2)
    assert "created_by_dispatch" not in landed2, landed2
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-001", "status": "PROVEN",
         "answers_question": "q-x"}]}), encoding="utf-8")

    src.run(ws)
    assert not [r for r in _settle_rows(ws)
                if r.get("dispatch_id") == did_victim], \
        "a forged stamp must never steal the victim's arm"


# --------------------------------------------------------------------------
# two producers in one round never double-count the cross-task store.
# --------------------------------------------------------------------------

def test_multi_producer_store_rows_never_double_count(tmp_path):
    ws = _ws(tmp_path)
    claim = {"id": "C-001", "status": "OPEN", "answers_question": "q-x"}
    did_a = _mint(ws, claim, FAM_WORKER)
    landed_a = _write_fact(ws, FID1, "C-001")
    assert f"created_by_dispatch: {did_a}" in landed_a
    did_b = _mint(ws, claim, "obfuscation-peeling")
    landed_b = _write_fact(ws, FID2, "C-001")
    assert f"created_by_dispatch: {did_b}" in landed_b
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-001", "status": "PROVEN",
         "answers_question": "q-x"}]}), encoding="utf-8")

    out = src.run(ws)
    assert out["settled"] == 1, out

    store = [r for r in strategy_store.load_rows(ws)
             if str((r.get("provenance") or {}).get("dispatch_id"))
             in (did_a, did_b)]
    assert len(store) == 2, store
    # each producer's row carries only its own share — no fact is
    # claimed twice and the round's total is never inflated
    assert sorted(str(r["provenance"]["dispatch_id"]) for r in store) == \
        sorted([did_a, did_b]), store
    assert all(r["facts_citing"] == 1 for r in store), store
    assert all(r["credit"] == 1.0 for r in store), store
    assert sum(r["facts_citing"] for r in store) == 2
    # the Q-cell bank splits the same way
    assert q_cells.banked_mass(ws, did_a)[0] == 1.0
    assert q_cells.banked_mass(ws, did_b)[0] == 1.0


# --------------------------------------------------------------------------
# a verifier-last claim must never deadlock mission completion.
# --------------------------------------------------------------------------

def test_settle_stop_completes_when_a_verifier_is_the_latest_dispatch(
        tmp_path):
    from test_production_terminal_1005 import invoke_stop, terminal_workspace
    ws = terminal_workspace(tmp_path)
    (ws / "facts").mkdir(exist_ok=True)
    claim = {"id": "C-001", "status": "PROVEN", "title": "synthetic result",
             "answers_question": "pq1",
             "maker_identity": "synthetic-worker-1"}
    did_a = _mint(ws, claim, FAM_WORKER)
    landed = _write_fact(ws, FID1, "C-001")
    assert f"created_by_dispatch: {did_a}" in landed
    did_b = _mint(ws, claim, FAM_REDTEAM)
    ver = q_cells.observe_settlement(ws, did_b, 1.0,
                                     credit_kind="verification")
    assert ver["matched"] and ver["beta_updated"] is False

    stopped = invoke_stop(ws, profile=tmp_path / "isolated-profile")
    assert stopped.returncode == 0, (stopped.stdout, stopped.stderr)
    from rlvr import episode_pool
    assert len(episode_pool.list_episodes(ws)) == 1, \
        "a verifier-last claim must still complete the mission"
    assert q_cells.banked_mass(ws, did_a)[2] == 1
    assert q_cells.banked_mass(ws, did_b)[2] == 0, \
        "verification rows are inadmissible to the solve bank"


# --------------------------------------------------------------------------
# the updatedInput emission shapes (Write / Edit / MultiEdit).
# --------------------------------------------------------------------------

def test_write_guard_emits_the_updated_input_shapes(tmp_path):
    ws = _ws(tmp_path)
    claim = {"id": "C-001", "status": "OPEN", "answers_question": "q-x"}
    did_a = _mint(ws, claim, FAM_WORKER)
    target = ws / "facts" / f"{FID1}.md"

    # Write: the content shape carries the stamp
    out = _run_write_guard(_stamp_payload(ws, target,
                                          _fact_text(FID1, "C-001")))
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    updated = _updated(out)
    assert set(updated) == {"file_path", "content"}, updated
    assert updated["file_path"] == str(target)
    assert f"created_by_dispatch: {did_a}" in updated["content"]
    target.write_text(updated["content"], encoding="utf-8")

    # Edit: the whole-file replacement shape — an edit that DROPS the
    # stamp gets it restored through updatedInput.
    current = target.read_text(encoding="utf-8")
    dropped = current.replace(f"created_by_dispatch: {did_a}\n", "")
    dropped = dropped.replace("dynamic-trace", "dynamic-trace v2")
    out = _run_write_guard(_stamp_payload(
        ws, target, dropped, "Edit",
        old_string=current, new_string=dropped))
    updated = _updated(out)
    assert set(updated) == {"file_path", "old_string", "new_string",
                            "replace_all"}, updated
    assert updated["old_string"] == current, "Edit carries the current text"
    assert f"created_by_dispatch: {did_a}" in updated["new_string"]

    # MultiEdit: the edits-list shape
    out = _run_write_guard(_stamp_payload(
        ws, target, dropped, "MultiEdit",
        edits=[{"old_string": current, "new_string": dropped}]))
    updated = _updated(out)
    assert set(updated) == {"file_path", "edits"}, updated
    assert set(updated["edits"][0]) == {"old_string", "new_string"}, updated
    assert f"created_by_dispatch: {did_a}" in updated["edits"][0]["new_string"]


# --------------------------------------------------------------------------
# an absent or malformed stamp degrades to the named fallback, never a
# silent guess.
# --------------------------------------------------------------------------

def test_unstamped_fact_names_the_fallback_and_banks_on_the_named_target(
        tmp_path):
    ws = _ws(tmp_path)
    claim = {"id": "C-001", "status": "OPEN", "answers_question": "q-x"}
    did_a = _mint(ws, claim, FAM_WORKER)
    did_b = _mint(ws, claim, FAM_REDTEAM)
    # F001 predates the stamp (written with no creating id at all)
    plain = _fact_text(FID1, "C-001")
    assert "created_by_dispatch" not in plain
    (ws / "facts" / "F001.md").write_text(plain, encoding="utf-8")
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-001", "status": "PROVEN",
         "answers_question": "q-x"}]}), encoding="utf-8")

    out = src.run(ws)
    assert out["settled"] == 1, out
    rows = _settle_rows(ws)
    solve = [r for r in rows if not r.get("credit_kind")]
    assert len(solve) == 1, solve
    # the named fallback — never a silent guess
    assert solve[0]["dispatch_id"] == did_b, solve
    from rlvr import ledger as rl
    st = rl.fold(ws, "round_credit/C-001")["settlement"]
    assert st["producer_attribution"] == {
        "fallback": "creator-stamp-missing", "facts": [FID1]}, st
