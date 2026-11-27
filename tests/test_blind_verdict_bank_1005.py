# -*- coding: utf-8 -*-
"""The settled blind verdict reaches the learner (issue 1005).

A completed blind settlement riding the settlement wire must BANK into
the q-cell fold on the producing dispatch's arm:

  1. THE BOX — one continuous synthetic round (dispatch -> completion ->
     blind park -> settler ruling -> settle_parked) produces the settle
     row, a q-cell credit row, AND posterior movement, with no eval
     flag. Pre-fix the settle row landed and the learner saw nothing.
  2. IDEMPOTENCE — the same settlement replayed banks once: the learner
     state is byte-identical after the replay.
  3. AMENDMENT — a credit_amendment on the settled dispatch refines the
     bank (the same face scalar's reconcile drives), and a re-settled
     verdict never clobbers a refinement.
  4. CENSORING — the censoring routes held: a censored status or an
     unverified rule-out banks nothing; a verified rule-out still
     banks its (information-option) row.

Fixtures are synthetic (no workspace data).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import claims_store  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import ledger as rl  # noqa: E402
from rlvr import q_cells  # noqa: E402
from rlvr import settlement_wire as wire  # noqa: E402

T0 = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)
FAM = "static-decompile"
CLAIM = "C-1"


# ------------------------------------------------------------------ helpers

def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "evidence").mkdir()
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")
    return ws


def _set_status(ws: Path, cid: str, status: str) -> None:
    doc = yaml.safe_load(
        (ws / "claim-register.yaml").read_text(encoding="utf-8"))
    for claim in doc["claims"]:
        if claim["id"] == cid:
            claim["status"] = status
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump(doc), encoding="utf-8")


def _mint(ws: Path, cid: str, family: str = FAM,
          status: str = "OPEN") -> str:
    """One committed dispatch + its pending q-cell row (the production
    bank-match shape the ALLOW tail records), the register restored to
    ``status``."""
    _set_status(ws, cid, "OPEN")
    began = claims_store.begin_dispatch(
        ws, cid, "hook:worker_budget", tier=1, prompt="fixture",
        agent="w-test", method_family=family)
    assert began.ok, cid
    assert claims_store.commit_dispatch(ws, cid).ok, cid
    assert claims_store.confirm_dispatch(ws, cid)
    did = str(began.journal_id)
    out = q_cells.record_dispatch_observation(
        ws, "fixture envelope", envelope_meta={"method_family": family},
        claim=cid, agent="w-test", dispatch_id=did)
    assert out["appended"] is True, cid
    _set_status(ws, cid, status)
    return did


def _rules(tmp_path: Path) -> Path:
    p = tmp_path / "reward-rules.yaml"
    p.write_text("rules: synthetic-settlement-rules\n", encoding="utf-8")
    return p


def _park(ws: Path, tmp_path: Path, claim: str = CLAIM,
          act_outcome: str = "") -> None:
    art = ws / "evidence" / f"step-{claim}.bin"
    art.write_bytes(b"raw-step-artifact-bytes")
    out = wire.park_blind_input(ws, claim, [art.relative_to(ws).as_posix()],
                                rules_path=_rules(tmp_path),
                                act_outcome=act_outcome)
    assert out["parked"] is True, out


def _verdict(ws: Path, claim: str, credit: float) -> dict:
    parked = wire.load_parked(ws, claim)
    evidence = [a.get("path") for a in (parked.get("artifacts") or [])]
    doc = {
        "schema": "settlement-verdict/1",
        "identity": "kunglao-settler",
        "claim": claim,
        "actions": [{"action_id": f"step-{claim}", "credit": credit,
                     "evidence": evidence}],
        "trajectory_credit": credit,
    }
    (ws / "runs" / f"settlement-verdict-{claim}.json").write_text(
        json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    return doc


def _verification(ws: Path, claim: str = CLAIM, word: str = "verified") -> None:
    (ws / "runs" / f"verification-{claim}.md").write_text(
        f"verdict: {word}\n", encoding="utf-8")


def _settle(ws: Path, claim: str, *, oracle_verdict: str, at: datetime,
            verification: bool = True) -> dict:
    if verification:
        _verification(ws, claim)
    return wire.settle_parked(
        ws, claim, oracle_verdict=oracle_verdict,
        has_reproducible_evidence=True, now=at)


def _settle_rows(ws: Path) -> list[dict]:
    return [r for r in q_cells.JSONLQStore(ws).observations()
            if r.get("source") == "settlement"]


def _experience_bytes(ws: Path) -> bytes | None:
    p = cl.family_path(ws, "experience")
    return p.read_bytes() if p.is_file() else None


def _fold_mass(ws: Path) -> float:
    fold = q_cells.fold(q_cells.default_store(ws), gamma=1.0)
    return sum(float(c.success) + float(c.failure)
               for c in fold.cells.values())


# ------------------------------------------------------------- 1. the box

def test_settled_blind_verdict_banks_and_moves_the_posterior(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    ws = _ws(tmp_path, [{"id": CLAIM, "status": "OPEN"}])
    did = _mint(ws, CLAIM)
    _park(ws, tmp_path)
    _verdict(ws, CLAIM, credit=0.9)

    res = _settle(ws, CLAIM, oracle_verdict="pass", at=T0)

    # the settle row landed (the pre-fix state stopped here)
    assert res["settled"] is True, res
    assert any(r.get("settled") for r in [
        r for r in cl.read(ws, "settlement")
        if str(r.get("schema") or "") == "settlement-wire/1"
        and str(r.get("claim") or "") == CLAIM])
    st = rl.fold(ws, f"task/{CLAIM}")["settlement"]
    assert st["reward"] == 1.0, st          # the oracle pass lock

    # the learner: one q-cell credit row on the producing dispatch's arm
    bank = res["q_cell_bank"]
    assert bank["matched"] is True and bank["appended"] is True, bank
    assert bank["dispatch_id"] == did, bank
    rows = [r for r in _settle_rows(ws) if r.get("dispatch_id") == did]
    assert len(rows) == 1, rows
    assert rows[0]["credit"] == 1.0, rows

    # the posterior mass actually moved
    assert q_cells.banked_mass(ws, did) == (1.0, 0.0, 1)
    assert _fold_mass(ws) > 0.0


# --------------------------------------------------------- 2. idempotence

def test_replayed_settlement_banks_once(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    ws = _ws(tmp_path, [{"id": CLAIM, "status": "OPEN"}])
    did = _mint(ws, CLAIM)
    _park(ws, tmp_path)
    _verdict(ws, CLAIM, credit=0.9)
    _settle(ws, CLAIM, oracle_verdict="pass", at=T0)
    before = _experience_bytes(ws)
    assert before is not None

    # the SAME settlement replayed at a later wall clock
    res2 = _settle(ws, CLAIM, oracle_verdict="pass", at=T0 + timedelta(hours=1))

    assert res2["settled"] is False, res2          # ledger dedupe
    assert "q_cell_bank" not in res2, res2         # the bank gate held
    assert _experience_bytes(ws) == before, "the learner state churned"
    assert q_cells.banked_mass(ws, did) == (1.0, 0.0, 1)
    assert len([r for r in _settle_rows(ws)
                if r.get("dispatch_id") == did]) == 1


# ---------------------------------------------------------- 3. amendment

def test_credit_amendment_refines_the_bank_and_a_resettle_never_clobbers(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    ws = _ws(tmp_path, [{"id": CLAIM, "status": "OPEN"}])
    did = _mint(ws, CLAIM)
    _park(ws, tmp_path)
    _verdict(ws, CLAIM, credit=0.9)
    # no decisive oracle verdict: the settled reward IS the verifier
    # credit (no lock), so a changed ruling moves the ledger value
    _settle(ws, CLAIM, oracle_verdict="", at=T0)
    assert q_cells.banked_mass(ws, did) == (0.9, 0.1, 1)

    # the credit-amendment face (scalar's reconcile driver) refines
    from rlvr import q_cells as qc
    amended = qc.amend_settlement(ws, did, 0.5)
    assert amended["appended"] is True, amended
    assert q_cells.banked_mass(ws, did) == (0.5, 0.5, 2)

    # a content-changed re-settlement settles an amendment row on the
    # ledger but must never re-bank over the refinement
    _verdict(ws, CLAIM, credit=0.4)
    res2 = _settle(ws, CLAIM, oracle_verdict="", at=T0 + timedelta(hours=1),
                   verification=False)
    assert res2["settled"] is True, res2
    bank = res2["q_cell_bank"]
    assert bank["appended"] is False and bank["matched"] is True, bank
    assert bank["reason"] == "already-banked", bank
    assert q_cells.banked_mass(ws, did) == (0.5, 0.5, 2)


# ---------------------------------------------------------- 4. censoring

@pytest.mark.parametrize("word,cls", [
    ("api-quota", "infra"),          # the quota/API kill family
    ("timeout", "censored"),         # the end was never observed
])
def test_killed_act_outcome_banks_nothing(tmp_path, monkeypatch, word, cls):
    """The act outcome rides the park into the censoring route: an
    infra/censored act whose partial artifacts were blinded and ruled
    0.8 must settle WITHOUT any banked mass (pre-fix the ruling banked
    0.8 success onto the arm)."""
    ws = _ws(tmp_path, [{"id": CLAIM, "status": "OPEN"}])
    did = _mint(ws, CLAIM)
    _park(ws, tmp_path, act_outcome=word)
    _verdict(ws, CLAIM, credit=0.8)

    res = _settle(ws, CLAIM, oracle_verdict="", at=T0, verification=False)

    assert res["settled"] is True, res
    bank = res["q_cell_bank"]
    assert bank["appended"] is False and bank["route"] == "censored", bank
    assert bank["class"] == cls and bank["reason"] == word, bank
    assert q_cells.banked_mass(ws, did) == (0.0, 0.0, 0)
    assert _settle_rows(ws) == [], "a killed act banks no q-cell row"
    assert _fold_mass(ws) == 0.0


def test_completed_act_still_banks(tmp_path, monkeypatch):
    """The strategy-outcome words never censor: a completed act with the
    same partial-artifact ruling banks exactly as the box test does."""
    ws = _ws(tmp_path, [{"id": CLAIM, "status": "OPEN"}])
    did = _mint(ws, CLAIM)
    _park(ws, tmp_path, act_outcome="completed")
    _verdict(ws, CLAIM, credit=0.8)
    res = _settle(ws, CLAIM, oracle_verdict="", at=T0, verification=False)
    assert res["settled"] is True, res
    bank = res["q_cell_bank"]
    assert bank["appended"] is True and bank["route"] is None, bank
    assert q_cells.banked_mass(ws, did) == (0.8, 0.2, 1)


def test_censored_status_settles_but_banks_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    ws = _ws(tmp_path, [{"id": CLAIM, "status": "DEFERRED"}])
    did = _mint(ws, CLAIM, status="DEFERRED")
    _park(ws, tmp_path)
    _verdict(ws, CLAIM, credit=0.9)

    # no decisive oracle verdict: no mint, the parked status survives
    res = _settle(ws, CLAIM, oracle_verdict="", at=T0, verification=False)

    assert res["settled"] is True, res
    assert rl.fold(ws, f"task/{CLAIM}") is not None
    bank = res["q_cell_bank"]
    assert bank["appended"] is False and bank["route"] == "censored", bank
    assert q_cells.banked_mass(ws, did) == (0.0, 0.0, 0)
    assert _settle_rows(ws) == [], "a censored outcome banks no q-cell row"
    assert _fold_mass(ws) == 0.0


def test_unverified_rule_out_banks_nothing_verified_banks_a_row(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    ws = _ws(tmp_path, [{"id": "C-1", "status": "OPEN"},
                        {"id": "C-2", "status": "OPEN"}])
    did1 = _mint(ws, "C-1", status="IN_PROGRESS")
    did2 = _mint(ws, "C-2", status="IN_PROGRESS")

    def _fact(fid: str, cid: str, *, sign_off: bool) -> None:
        lines = ["---", f"id: {fid}", "type: fact", f"title: {fid}",
                 "status: NEGATIVE", "created: 2026-08-20",
                 "last_reviewed: 2026-08-20", f"claim_id: {cid}",
                 "claim: hypothesis arm eliminated",
                 "boundary_type: pure_negative", "source: static-decompile",
                 "confidence: high", "verify_status: pending"]
        if sign_off:
            lines += ["verifier_sign_off:",
                      "  verifier_id: independent-1",
                      "  refute_attempt: tried breaking it; held",
                      "  sign_off_at: 2026-08-20T00:00:00Z",
                      "  verdict: CONFIRMED"]
        lines += ["---", f"# {fid}", ""]
        (ws / "facts" / f"{fid}.md").write_text("\n".join(lines),
                                                encoding="utf-8")

    # C-1: the unverified rule-out — pending, no mass either way
    _fact("F001-ruleout", "C-1", sign_off=False)
    _park(ws, tmp_path, "C-1")
    _verdict(ws, "C-1", credit=0.9)
    res1 = _settle(ws, "C-1", oracle_verdict="fail", at=T0)
    bank1 = res1["q_cell_bank"]
    assert bank1["appended"] is False \
        and bank1["route"] == "pending_no_mass", bank1
    assert q_cells.banked_mass(ws, did1) == (0.0, 0.0, 0)
    assert not [r for r in _settle_rows(ws)
                if r.get("dispatch_id") == did1]

    # C-2: the verified rule-out — real work, its row banks (the
    # trajectory rail prices the fail at the information option)
    _fact("F002-ruleout", "C-2", sign_off=True)
    _park(ws, tmp_path, "C-2")
    _verdict(ws, "C-2", credit=0.9)
    res2 = _settle(ws, "C-2", oracle_verdict="fail", at=T0)
    bank2 = res2["q_cell_bank"]
    assert bank2["appended"] is True and bank2["route"] is None, bank2
    assert q_cells.banked_mass(ws, did2)[2] == 1


@pytest.mark.parametrize("declared", [True, False])
def test_interrupted_trajectory_can_settle_the_completed_action(
        tmp_path, declared):
    import worker_budget_sinks as sinks
    from rlvr import priors

    steps = ["C-1", "C-2", "C-3"]
    ws = _ws(tmp_path, [{"id": cid, "status": "OPEN"} for cid in steps])
    (ws / "task_spec.yaml").write_text("family: static-replay\n", encoding="utf-8")
    assert priors.seed_intake_prior(ws, families=[FAM])
    dispatch_ids = {}
    for cid in steps[:2]:
        envelope = {"version": 1, "claim": cid, "tier": 1}
        if declared:
            envelope["method_family"] = FAM
        prompt = json.dumps({"kunglao_dispatch": envelope})
        paths = {"workspace": str(ws)}
        rc, family, view = sinks._method_family_gate(paths, prompt, cid, "w-test", 1, [])
        assert rc is None and family == FAM
        began = claims_store.begin_dispatch(
            ws, cid, "hook:worker_budget", tier=1, prompt=prompt,
            agent="w-test", method_family=family)
        assert began.ok
        assert claims_store.commit_dispatch(ws, cid).ok
        assert claims_store.confirm_dispatch(ws, cid)
        dispatch_ids[cid] = str(began.journal_id)
        sinks._qcell_record_dispatch(
            paths, prompt, cid, "w-test", dispatch_id=dispatch_ids[cid],
            tier=1, tools=[], sampler_view=view)

    # The first action's evidence is available. No result returned for
    # the second action, and the third was never dispatched.
    completed, unknown, unstarted = steps
    _park(ws, tmp_path, completed)
    assert wire.load_parked(ws, unknown) is None
    rows = {r["claim"]: r for r in q_cells.dispatch_rows(ws)}
    assert set(rows) == {completed, unknown}
    assert unstarted not in rows
    for cid, row in rows.items():
        assert row["dispatch_id"] == dispatch_ids[cid]
        assert row["method_source"] == ("declared" if declared else "sampled-adoption")
        assert row["credit"] is None
    assert q_cells.banked_mass(ws, dispatch_ids[completed])[2] == 0

    _verdict(ws, completed, 0.9)
    result = _settle(ws, completed, oracle_verdict="pass", at=T0)
    assert result["q_cell_bank"]["matched"]
    assert result["q_cell_bank"]["dispatch_id"] == dispatch_ids[completed]
    assert q_cells.banked_mass(ws, dispatch_ids[completed]) == (1.0, 0.0, 1)
    assert q_cells.banked_mass(ws, dispatch_ids[unknown]) == (0.0, 0.0, 0)
    assert not _settle(ws, completed, oracle_verdict="pass", at=T0)["settled"]
    assert q_cells.banked_mass(ws, dispatch_ids[completed]) == (1.0, 0.0, 1)


def test_later_aborted_dispatch_does_not_replace_the_producer(tmp_path):
    ws = _ws(tmp_path, [{"id": CLAIM, "status": "OPEN"}])
    producer = _mint(ws, CLAIM)
    rejected = claims_store.begin_dispatch(
        ws, CLAIM, "hook:worker_budget", tier=1, prompt="fixture",
        agent="w-test", method_family=FAM)
    assert rejected.ok and claims_store.commit_dispatch(ws, CLAIM).ok
    assert claims_store.abort_dispatch(ws, CLAIM, actor="hook:dispatch_gate").ok
    assert claims_store.committed_dispatch_ids(ws, CLAIM) == [producer]
    _park(ws, tmp_path)
    _verdict(ws, CLAIM, 0.9)
    result = _settle(ws, CLAIM, oracle_verdict="pass", at=T0)
    assert result["q_cell_bank"]["matched"]
    assert result["q_cell_bank"]["dispatch_id"] == producer


def _race_execution_with_credit_publish(sinks, ws, claim, paths, after, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextlib import contextmanager
    from threading import Event, local

    import _common

    before_write = Event()
    callback_ready = Event()
    release_write = Event()
    role = local()
    actual_write = _common.atomic_write_text
    actual_lock = cl.family_lock

    def write_credit(path, *args, **kwargs):
        if str(path).endswith(".credit.json"):
            before_write.set()
            assert release_write.wait(10), "execution callback did not arrive"
        return actual_write(path, *args, **kwargs)

    @contextmanager
    def notice_callback_lock(*args, **kwargs):
        if getattr(role, "callback", False):
            callback_ready.set()
        with actual_lock(*args, **kwargs):
            yield

    def acknowledge():
        role.callback = True
        try:
            return sinks.post_check(after, paths)
        finally:
            callback_ready.set()  # also detect a callback that skips the lock

    monkeypatch.setattr(_common, "atomic_write_text", write_credit)
    monkeypatch.setattr(cl, "family_lock", notice_callback_lock)
    with ThreadPoolExecutor(max_workers=2) as pool:
        settled = pool.submit(_settle, ws, claim, oracle_verdict="pass", at=T0)
        try:
            assert before_write.wait(10)
            posted = pool.submit(acknowledge)
            assert callback_ready.wait(10)
        finally:
            release_write.set()
        assert posted.result(timeout=10) == 0
        return settled.result(timeout=10)


@pytest.mark.parametrize("ack", ["matched", "mismatched", "missing", "concurrent", "transient"])
def test_verified_credit_waits_for_the_effective_worker_input(
        tmp_path, capsys, monkeypatch, ack):
    import worker_budget_sinks as sinks
    from rlvr import priors
    from test_sampled_binds_794 import _dispatch_payload, _min_paths, _undeclared_prompt

    claim = "C-001"
    ws = _ws(tmp_path, [{"id": claim, "status": "OPEN"}])
    (ws / "task_spec.yaml").write_text("family: static-replay\n", encoding="utf-8")
    assert priors.seed_intake_prior(ws, families=[FAM])
    payload = _dispatch_payload(_undeclared_prompt())
    payload.update(tool_name="Agent", tool_use_id="toolu_late_post")
    paths = _min_paths(ws)
    assert sinks.pre_check(payload, paths) == 0
    effective = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["updatedInput"]
    assert claims_store.confirm_dispatch(ws, claim)
    did = claims_store.latest_committed_dispatch(ws, claim)["dispatch_id"]
    _park(ws, tmp_path, claim)
    _verdict(ws, claim, 0.9)

    after = dict(payload, tool_input=effective, hook_event_name="PostToolUse")
    if ack == "concurrent":
        first = _race_execution_with_credit_publish(
            sinks, ws, claim, paths, after, monkeypatch)
    else:
        first = _settle(ws, claim, oracle_verdict="pass", at=T0)
        assert q_cells.banked_mass(ws, did) == (0.0, 0.0, 0)
    assert first["settled"]
    assert first["q_cell_bank"]["reason"] == "execution-unconfirmed"

    if ack == "mismatched":
        effective["prompt"] += "\nDifferent effective input"
    if ack == "transient":
        append = cl.append

        def fail_late_bank(root, family, row):
            if family == "experience" and row.get("source") == "settlement":
                return False
            return append(root, family, row)

        with monkeypatch.context() as fault:
            fault.setattr(cl, "append", fail_late_bank)
            assert sinks.post_check(after, paths) == 0
            assert q_cells.banked_mass(ws, did) == (0.0, 0.0, 0)
    if ack in {"matched", "mismatched", "transient"}:
        assert sinks.post_check(after, paths) == 0
        assert sinks.post_check(after, paths) == 0
    expected = (0.0, 0.0, 0) if ack in {"missing", "mismatched"} else (1.0, 0.0, 1)
    assert q_cells.banked_mass(ws, did) == expected
    assert not _settle(ws, claim, oracle_verdict="pass", at=T0)["settled"]
