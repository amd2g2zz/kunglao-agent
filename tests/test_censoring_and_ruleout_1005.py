# -*- coding: utf-8 -*-
"""Censoring at settlement and the verified rule-out sign (issue 1005).

The round-credit close path (settle_round_credit -> rlvr.scalar.
settle_round_credit) books every TERMINAL claim as arm outcome mass.
Two defects on that path:

1. Censoring is missing. A claim whose outcome is a parked/expired class
   (DEFERRED / STALE / SUPERSEDED / DEAD) or an infrastructure failure
   (timeout, step-register-failed, API/quota errors) banks FAILURE mass
   on its arm — a parked claim pollutes the posteriors as a strategy
   failure. The censored/infra classes must settle WITHOUT moving any
   Beta/posterior mass, recorded as censored on the settlement row.

2. The verified rule-out sign is wrong. A REFUTED/NEGATIVE outcome whose
   rule-out fact carries independent verification evidence (the
   verifier_sign_off CONFIRMED block) banks a plain failure on the
   producing dispatch. A verified rule-out is real work — it eliminates
   a hypothesis — and banks SUCCESS on the producing dispatch's arm (the
   created_by_dispatch key). An UNVERIFIED rule-out is not evidence: no
   mass moves either way and the settlement row carries the
   pending/no-mass marker.

Fixtures are synthetic (no workspace data)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import claims_store  # noqa: E402
import settle_round_credit as src  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import ledger as rl  # noqa: E402
from rlvr import q_cells  # noqa: E402

FAM_WORKER = "static-decompile"
FAM_REDTEAM = "red-team-verification"

#: the blind_gate required-fields sign-off shape (the independent
#: verifier's currency), verdict CONFIRMED
SIGN_OFF = {
    "verifier_id": "independent-1",
    "refute_attempt": "tried breaking the finding; held",
    "sign_off_at": "2026-08-20T00:00:00Z",
    "verdict": "CONFIRMED",
}


# ------------------------------------------------------------------ helpers

def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
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


def _mint(ws: Path, cid: str, status: str, family: str,
          agent: str = "w-test") -> str:
    """One committed dispatch + its stamped pending q-cell row (the
    production bank-match shape), the register restored to ``status``."""
    _set_status(ws, cid, "OPEN")
    began = claims_store.begin_dispatch(
        ws, cid, "hook:worker_budget", tier=1, prompt="fixture",
        agent=agent, method_family=family)
    assert began.ok, cid
    assert claims_store.commit_dispatch(ws, cid).ok, cid
    assert claims_store.confirm_dispatch(ws, cid)
    did = str(began.journal_id)
    out = q_cells.record_dispatch_observation(
        ws, "fixture envelope", envelope_meta={"method_family": family},
        claim=cid, agent=agent, dispatch_id=did)
    assert out["appended"] is True, cid
    _set_status(ws, cid, status)
    return did


def _fact(ws: Path, fid: str, claim: str, *, status: str = "NEGATIVE",
          vs: str = "pending", did: str | None = None,
          sign_off: bool = False, creator: str | None = None,
          verifier_id: str | None = None) -> None:
    lines = ["---", f"id: {fid}", "type: fact", f"title: {fid}",
             f"status: {status}", "created: 2026-08-20",
             "last_reviewed: 2026-08-20", f"claim_id: {claim}",
             "claim: hypothesis arm eliminated",
             "boundary_type: pure_negative", "source: static-decompile",
             "confidence: high", f"verify_status: {vs}"]
    if did:
        lines.append(f"created_by_dispatch: {did}")
    if creator:
        lines.append(f"creator: {creator}")
    if sign_off:
        lines.append("verifier_sign_off:")
        signed = dict(SIGN_OFF)
        if verifier_id:
            signed["verifier_id"] = verifier_id
        lines.extend(f"  {k}: {v}" for k, v in signed.items())
    lines += ["---", f"# {fid}", ""]
    (ws / "facts" / f"{fid}.md").write_text("\n".join(lines),
                                           encoding="utf-8")


def _outcome_row(ws: Path, claim: str, reason: str) -> None:
    """The machine-written dispatch failure trace (claims_store's own
    provenance channel — a failed commit records ``step-<name>-failed``)."""
    path = ws / "runs" / "claims-provenance.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "schema": "claims-provenance/1", "ts": "2026-08-20T00:00:00Z",
            "claim": claim, "event": "dispatch", "from": "OPEN",
            "to": None, "actor": "hook:worker_budget",
            "outcome": "failed", "reason": reason, "journal": "j1"}) + "\n")


def _posterior_state(ws: Path) -> dict:
    """The posterior side: the arm-mass substrate (experience), the case
    posteriors, and the keyed knowledge store — bytes or None."""
    out: dict = {}
    for name, path in (
            ("experience", cl.family_path(ws, "experience")),
            ("posteriors", ws / "runs" / "posteriors.yaml"),
            ("knowledge", cl.family_path(ws, "knowledge"))):
        out[name] = path.read_bytes() if path.is_file() else None
    return out


def _settle_rows(ws: Path) -> list[dict]:
    return [r for r in q_cells.JSONLQStore(ws).observations()
            if r.get("source") == "settlement"]


# --------------------------------------------------------------------------
# defect 1: the censored/infra classes settle without moving posterior mass
# and are recorded as censored.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("reason,cls", [
    ("timeout", "censored"),
    # the whole commit-failure family (step-<name>-failed), not one spelling
    ("step-register-failed", "infra"),
    ("step-anchor-failed", "infra"),
    ("step-stash-failed", "infra"),
])
def test_censored_outcomes_move_no_posterior_mass_and_record_censoring(
        tmp_path, monkeypatch, reason, cls):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    claims = [{"id": "C-1", "status": "DEFERRED"},
              {"id": "C-2", "status": "STALE"},
              {"id": "C-3", "status": "SUPERSEDED"},
              {"id": "C-4", "status": "DEAD"},
              # decisive register status, infra outcome — only the
              # outcome class censors this one
              {"id": "C-5", "status": "REFUTED"}]
    ws = _ws(tmp_path, claims)
    dids = {c["id"]: _mint(ws, c["id"], c["status"], "static-symbolic")
            for c in claims}
    _outcome_row(ws, "C-5", reason)

    before = _posterior_state(ws)
    out = src.run(ws)
    assert _posterior_state(ws) == before, \
        "the posterior side must be byte-identical through the settle"

    assert set(out["censored"]) == {"C-1", "C-2", "C-3", "C-4", "C-5"}
    for c in claims:
        expected = ({"class": cls, "reason": reason} if c["id"] == "C-5"
                    else {"class": "censored",
                          "reason": str(c["status"]).upper()})
        st = rl.fold(ws, f"round_credit/{c['id']}")["settlement"]
        assert st["censored"] == expected, (c["id"], st)
    # and the arm booked nothing: pre-fix each claim banked (0.0, 1.0)
    for c in claims:
        assert q_cells.banked_mass(ws, dids[c["id"]]) == (0.0, 0.0, 0), c["id"]
    assert not _settle_rows(ws), "a censored outcome banks no q-cell row"


# --------------------------------------------------------------------------
# defect 2: the verified rule-out banks SUCCESS on the producing dispatch;
# the unverified rule-out settles pending with no mass either way.
# --------------------------------------------------------------------------

def test_rule_out_sign_success_for_verified_pending_for_unverified(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED"},
                        {"id": "C-2", "status": "REFUTED"}])

    # C-1: the verified rule-out — A produced the finding (the harness
    # stamp), B is the claim's latest dispatch (the red-team tail).
    did_a = _mint(ws, "C-1", "REFUTED", FAM_WORKER)
    _fact(ws, "F001-ruleout", "C-1", did=did_a, sign_off=True)
    did_b = _mint(ws, "C-1", "REFUTED", FAM_REDTEAM)

    # C-2: the unverified rule-out — the beike C-018 shape (NEGATIVE
    # finding, verification pending, no independent sign-off).
    did_a2 = _mint(ws, "C-2", "REFUTED", FAM_WORKER)
    _fact(ws, "F002-ruleout", "C-2", did=did_a2, sign_off=False)

    before = _posterior_state(ws)
    out = src.run(ws)
    assert out["settled"] == 2

    # verified rule-out: SUCCESS credit on the PRODUCING dispatch's arm
    solve = [r for r in _settle_rows(ws)
             if r.get("dispatch_id") == did_a and not r.get("credit_kind")]
    assert len(solve) == 1, solve
    assert solve[0]["credit"] == 1.0, solve
    assert solve[0]["method_family"] == FAM_WORKER, solve
    assert q_cells.banked_mass(ws, did_a) == (1.0, 0.0, 1)
    # never on the claim's latest dispatch (the S3 producer key holds)
    assert q_cells.banked_mass(ws, did_b) == (0.0, 0.0, 0)
    st1 = rl.fold(ws, "round_credit/C-1")["settlement"]
    assert st1["reward"] == 1.0 and "censored" not in st1 \
        and "pending_no_mass" not in st1

    # unverified rule-out: no mass moves either way, the marker records it
    assert q_cells.banked_mass(ws, did_a2) == (0.0, 0.0, 0)
    assert not [r for r in _settle_rows(ws)
                if r.get("dispatch_id") == did_a2], \
        "an unverified rule-out banks no q-cell row"
    st2 = rl.fold(ws, "round_credit/C-2")["settlement"]
    assert st2["pending_no_mass"] == {
        "reason": "unverified-rule-out", "facts": ["F002-ruleout"]}, st2
    assert set(out["pending_no_mass"]) == {"C-2"}
    # the C-2 side booked nothing on any posterior face (the C-1 success
    # store row is the producer arm's own bank and is expected)
    from rlvr import strategy_store
    assert _posterior_state(ws)["posteriors"] == before["posteriors"]
    assert not [r for r in strategy_store.load_rows(ws=None)
                if str((r.get("provenance") or {}).get("dispatch_id"))
                == did_a2], "an unverified rule-out keys no store row"


# --------------------------------------------------------------------------
# the maker-checker: a self-stamped sign-off is never independent — the
# rule-out stays UNVERIFIED (pending, no mass), never SUCCESS.
# --------------------------------------------------------------------------

def test_self_stamped_sign_off_stays_pending_and_never_banks_success(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED",
                         "worker_id": "w-evil"},
                        {"id": "C-2", "status": "REFUTED"},
                        {"id": "C-3", "status": "REFUTED"}])

    # C-1: the maker names itself through the claim's assigned worker
    # identity (blind_gate's maker-checker rule)
    did1 = _mint(ws, "C-1", "REFUTED", FAM_WORKER)
    _fact(ws, "F001-selfstamp", "C-1", did=did1, sign_off=True,
          verifier_id="w-evil")
    # C-2: the independence-positive twin — a genuinely separate checker
    did2 = _mint(ws, "C-2", "REFUTED", FAM_WORKER)
    _fact(ws, "F002-independent", "C-2", did=did2, sign_off=True,
          verifier_id="independent-1")
    # C-3: the maker names itself through its producing dispatch identity
    did3 = _mint(ws, "C-3", "REFUTED", FAM_WORKER, agent="w-evil")
    _fact(ws, "F003-selfstamp", "C-3", did=did3, sign_off=True,
          verifier_id="w-evil")

    out = src.run(ws)
    assert out["settled"] == 3

    # self-stamped sign-offs: UNVERIFIED — pending, zero movement
    for cid, fid, did in (("C-1", "F001-selfstamp", did1),
                          ("C-3", "F003-selfstamp", did3)):
        assert q_cells.banked_mass(ws, did) == (0.0, 0.0, 0), cid
        assert not [r for r in _settle_rows(ws)
                    if r.get("dispatch_id") == did], cid
        st = rl.fold(ws, f"round_credit/{cid}")["settlement"]
        assert st["pending_no_mass"] == {
            "reason": "unverified-rule-out", "facts": [fid]}, (cid, st)
    assert set(out["pending_no_mass"]) == {"C-1", "C-3"}

    # the independent sign-off keeps banking SUCCESS on the producer
    assert q_cells.banked_mass(ws, did2) == (1.0, 0.0, 1)
    st2 = rl.fold(ws, "round_credit/C-2")["settlement"]
    assert st2["reward"] == 1.0 and "pending_no_mass" not in st2


def test_write_gate_flags_a_self_stamped_sign_off_on_any_status(tmp_path):
    """Defense in depth: the write face's maker-checker fires on a
    verifier_sign_off block whatever the fact's status word says — the
    NEGATIVE rule-out face is exactly where a self-stamp farms credit."""
    import write_gate
    ws = _ws(tmp_path, [{"id": "C-1", "status": "REFUTED",
                         "worker_id": "w-evil"},
                        {"id": "C-2", "status": "REFUTED",
                         "worker_id": "w-evil"}])
    _fact(ws, "F001-selfstamp", "C-1", sign_off=True, verifier_id="w-evil")
    _fact(ws, "F002-independent", "C-2", sign_off=True,
          verifier_id="independent-1")
    v1 = write_gate._check_fact(ws, ws / "facts" / "F001-selfstamp.md")
    assert [v["rule"] for v in v1] == ["R1"], v1
    assert "self-stamp" in v1[0]["detail"] and "w-evil" in v1[0]["detail"]
    assert write_gate._check_fact(
        ws, ws / "facts" / "F002-independent.md") == []


# --------------------------------------------------------------------------
# the in-module sign-off vocabularies stay pinned to their sources (the
# scalar engine's import wall keeps the verifier modules out).
# --------------------------------------------------------------------------

def test_sign_off_vocabularies_stay_pinned_to_their_sources():
    from blind_gate import _REQUIRED_FIELDS
    from rlvr import scalar as ss
    from verifier_integrity import PASS_VERDICTS
    assert tuple(ss.SIGN_OFF_REQUIRED) == tuple(_REQUIRED_FIELDS)
    assert ss.SIGN_OFF_PASS_VERDICTS == PASS_VERDICTS


# --------------------------------------------------------------------------
# the marked settlement satisfies the production-terminal bank
# certification and the missing-rollout audit (a censored/pending close
# is a settlement, never a silent gap).
# --------------------------------------------------------------------------

def test_marked_settlements_satisfy_the_bank_certification_and_audit(
        tmp_path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))
    from rlvr import production_terminal as pt
    ws = _ws(tmp_path, [{"id": "C-2", "status": "REFUTED"},
                        {"id": "C-3", "status": "REFUTED"}])
    did = _mint(ws, "C-2", "REFUTED", FAM_WORKER)
    _fact(ws, "F002-ruleout", "C-2", did=did, sign_off=False)
    src.run(ws)

    # the pending marker IS the settlement record: certification passes
    # with zero banked rows on the committed dispatch
    pt._require_dispatch_credit(ws, {"evidence": [{"claim": "C-2"}]})
    # and the audit reports no missing rollout
    assert claims_store.audit_missing_rollouts(ws) == []

    # an UNMARKED bankless settlement still refuses loudly
    from rlvr import ledger as _rl
    _rl.record(ws, kind="round_credit", anchor="C-3", signals=[], ts="t")
    _rl.settle(ws, "round_credit/C-3",
               {"reward": 0.0, "band": "ROUND_CREDIT",
                "rule_id": "round/provenance-credit", "evidence_refs": []})
    _mint(ws, "C-3", "REFUTED", FAM_WORKER)
    with pytest.raises(pt.SettlementIncomplete):
        pt._require_dispatch_credit(ws, {"evidence": [{"claim": "C-3"}]})
