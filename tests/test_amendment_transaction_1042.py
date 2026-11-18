# -*- coding: utf-8 -*-
"""tests/test_amendment_transaction_1042.py — the case-amendment is one
transaction, and revocation retries until it lands.

Two defect classes pinned here:

  1. The pair-amendment used to mutate the case posterior BEFORE the
     ``case-amendment/1`` append and persisted the ledger regardless of
     the append's result: a refused row left a flipped belief with ZERO
     ledger rows, and every following pass flipped the belief AGAIN (the
     ±1 compounded while the fold never saw a row). The shipped shape is
     COMMIT-FIRST: the audit row lands first, the posterior moves only
     after ``ok``, a refusal mutates nothing, and the next pass retries
     idempotently (the fold still sees the pair unamended).

  2. ``_revoke_derived_rows`` was fire-and-forget: a revoke failure was
     one warn with no retry channel, and because the amendment row HAD
     landed, the pair never re-entered the amendment entries — the stale
     derived knowledge stayed forever with a null error field. The
     shipped shape is DISCOVERY-BASED RETRY: every reconcile pass
     re-attempts revocation for claims whose amendments have landed
     while derived rows still match the claim in the workspace-local
     knowledge family (the stale source itself is the durable pending
     marker — no new state family). Failures surface on the sibling
     ``case_revocations_error`` field so decide()/telemetry see them.

The save-failure window stays loud and unswallowed: a landed row followed
by a failed posterior save raises into the telemetry error field (the
belief then waits for a later successful save; no silent re-derivation).

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import settle_round_credit as src  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import crystallize  # noqa: E402
from rlvr import marl  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402

FAM = "upx-unpack"


# ---------- fixtures --------------------------------------------------------

def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    """Workspace with a REAL dispatch ledger row per claim (a fixture
    without one settles nothing under the no-backcompat contract)."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    from _dispatch_fixture import mint_dispatches

    mint_dispatches(ws, claims, pending=False)
    return ws


def _arm_case(ws: Path, cid: str, pq: str) -> None:
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{cid}.yaml").write_text(yaml.safe_dump({
        "id": cid,
        "channel": "probe",
        "target_pq": pq,
        "hypothesis_ref": "H-001",
        "update_map": {"red_up": ["H-002"]},
        "expected": [{"field": "probe", "value": "observed",
                      "evidence_refs": ["E-001"]}],
        "mutations": [{"kind": "omit", "target": "E-001"}],
    }), encoding="utf-8")


def _observe(ws: Path, cid: str, claim: str, passed: bool) -> None:
    """Drive the production first-observation face directly for setup."""
    src._apply_case_observations(ws, [(cid, claim, passed)], source="fresh")


def _belief(ws: Path, cid: str) -> tuple[float, float]:
    import posteriors_case as po
    led = po.PosteriorLedger.load(ws)
    cp = led.cases.get(cid)
    return (cp.alpha, cp.beta) if cp else (1.0, 1.0)


def _amendment_rows(ws: Path) -> list[dict]:
    return cl.read(ws, "experience", schema_prefix="case-amendment")


def _flip_register(ws: Path, claim: str, pq: str, status: str) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": claim, "status": status,
                                    "answers_question": pq}]}),
        encoding="utf-8")


def _refuse_experience_appends(monkeypatch) -> None:
    """Every experience-family append returns False (the refusal face)."""
    def _refused(*_a, **_k):
        return False

    monkeypatch.setattr(cl, "append", _refused)


def _seed_negative(ws: Path, claim: str) -> None:
    """One derived class-negative attributed to ``claim`` (the derived
    knowledge a flip must revoke), through the REAL write face."""
    qc.append_observation(ws, "eeee00000000", FAM, None,
                          source="dispatch", claim=claim, agent="analyst",
                          tools=["upx", "strings"],
                          arm_key_col=qc.arm_key(
                              FAM, "facts_snapshot", "none", 0))
    out = crystallize.crystallize_settlement(
        ws, claim=claim, step_id="step-1", outcome="blocked")
    assert out["negative"] is True, out


def _neg_rows(ws) -> list[dict]:
    return [r for r in marl.read_negatives(ws)
            if str(r.get("claim_ref") or "")]


def _armed_seal(tmp_path, monkeypatch):
    """Arm the learning channel on the conftest-isolated key path."""
    from rlvr import learning_seal as seal

    key = seal.KEY_PATH
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(b"k" * 48)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    return key


# ---------- 1. commit-first: refusal touches nothing ------------------------

def test_append_refusal_leaves_belief_and_ledger_unchanged(
        tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    _refuse_experience_appends(monkeypatch)

    out = src.reconcile_case_settlements(ws)
    assert out.get("case_amendments_error"), out
    assert out["case_amendments"] == 0
    assert _belief(ws, "case-q2") == (2.0, 1.0)   # untouched
    assert _amendment_rows(ws) == []              # nothing landed


def test_repeated_refused_passes_do_not_drift(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    _refuse_experience_appends(monkeypatch)

    for _ in range(4):
        out = src.reconcile_case_settlements(ws)
        assert out.get("case_amendments_error"), out
        assert _belief(ws, "case-q2") == (2.0, 1.0)
    assert _amendment_rows(ws) == []


# ---------- 2. the save window stays loud -----------------------------------

def test_save_failure_is_loud(tmp_path, monkeypatch):
    import posteriors_case as po

    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")

    def _boom(self, _ws):
        raise OSError("synthetic save failure")

    monkeypatch.setattr(po.PosteriorLedger, "save", _boom)
    out = src.reconcile_case_settlements(ws)
    assert out.get("case_amendments_error"), out
    assert "OSError" in out["case_amendments_error"]
    # the row landed (append-only history keeps it) and the next pass
    # sees the pair amended — no double-apply
    monkeypatch.undo()
    assert len(_amendment_rows(ws)) == 1
    again = src.reconcile_case_settlements(ws)
    assert again["case_amendments"] == 0, again


# ---------- 3. revocation retries until it lands -----------------------------

def test_revoke_failure_is_loud_and_retries_next_pass(
        tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _seed_negative(ws, "C-1")
    _flip_register(ws, "C-1", "q2", "REFUTED")

    def _boom(*_a, **_k):
        raise OSError("synthetic revoke failure")

    monkeypatch.setattr(crystallize, "revoke_claim", _boom)
    out1 = src.reconcile_case_settlements(ws)
    assert out1["case_amendments"] == 1, out1      # the flip landed
    assert len(_amendment_rows(ws)) == 1
    assert len(_neg_rows(ws)) == 1                 # derived row survived
    assert out1.get("case_revocations_error"), out1   # the LOUD face

    # the store heals: the next pass re-attempts and completes
    monkeypatch.undo()
    out2 = src.reconcile_case_settlements(ws)
    assert _neg_rows(ws) == [], out2
    assert out2.get("revoked_claims") == ["C-1"], out2
    assert not out2.get("case_revocations_error"), out2
    assert out2["case_amendments"] == 0            # no double-apply


def test_revoke_success_is_idempotent_second_pass(tmp_path):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _seed_negative(ws, "C-1")
    _flip_register(ws, "C-1", "q2", "REFUTED")

    out1 = src.reconcile_case_settlements(ws)
    assert out1["case_amendments"] == 1, out1
    assert _neg_rows(ws) == []
    assert out1.get("revoked_claims") == ["C-1"], out1

    rows_before = _amendment_rows(ws)
    out2 = src.reconcile_case_settlements(ws)
    assert out2["case_amendments"] == 0, out2
    assert out2.get("revoked_claims") == [], out2  # no re-attempt
    assert not out2.get("case_revocations_error"), out2
    assert _amendment_rows(ws) == rows_before      # no new rows


# ---------- 4. the armed seal round-trips -----------------------------------

def test_armed_seal_round_trip_still_settles(tmp_path, monkeypatch):
    import posteriors_case as po

    _armed_seal(tmp_path, monkeypatch)
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")

    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 1, out
    assert _belief(ws, "case-q2") == (1.0, 2.0)
    led = po.PosteriorLedger.load(ws)
    assert not led.degraded, led.warnings
    assert len(_amendment_rows(ws)) == 1


# ---------- 5. the pass surface carries the revocation error -----------------

def test_run_surfaces_the_revocation_error(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _seed_negative(ws, "C-1")
    _flip_register(ws, "C-1", "q2", "REFUTED")

    def _boom(*_a, **_k):
        raise OSError("synthetic revoke failure")

    monkeypatch.setattr(crystallize, "revoke_claim", _boom)
    out = src.run(ws)
    assert out.get("case_amendments") == 1, out
    assert out.get("case_observations_error"), out
    assert "C-1" in out["case_observations_error"]


# ---------- 7. discovery mirrors revoke's pre-move window --------------------

def test_pre_move_stale_row_is_discovered_and_retried(
        tmp_path, monkeypatch):
    """The R4 pre-move window: a stale derived row sitting in a pre-move
    knowledge rel (not yet migrated) must read PENDING to the discovery
    face, or a revoke that failed before reaching it stays silent until
    migration resurrects the row."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    import consolidate_ledgers as _migrate_cli

    rel = "marl-negative.jsonl"
    assert rel in _migrate_cli.LEGACY_SOURCES["knowledge"]
    (ws / rel).write_text(json.dumps({
        "schema": "marl-negative/1", "ts": "2026-11-17T00:00:00Z",
        "signature_class": "unknown", "agent_type": None,
        "method_family": "upx-unpack", "tool_chain": "upx", "fails": 1,
        "claim_ref": "C-1", "step_ref": "step-1"}) + "\n",
        encoding="utf-8")

    def _boom(*_a, **_k):
        raise OSError("synthetic revoke failure")

    monkeypatch.setattr(crystallize, "revoke_claim", _boom)
    out1 = src.reconcile_case_settlements(ws)
    assert out1["case_amendments"] == 1, out1
    assert out1.get("case_revocations_error"), out1   # PENDING is loud
    assert (ws / rel).is_file()                       # sweep never ran

    # healed: the sweep removes the pre-move row (no resurrection)
    monkeypatch.undo()
    out2 = src.reconcile_case_settlements(ws)
    assert out2.get("revoked_claims") == ["C-1"], out2
    assert not out2.get("case_revocations_error"), out2
    assert not (ws / rel).exists()


# ---------- 8. mixed land/refuse counts per entry ----------------------------

def test_mixed_land_and_refuse_counts_per_entry(tmp_path, monkeypatch):
    """One entry lands, a LATER append refuses: the landed entry applied
    and saved, the refused entry re-fires alone next pass, and the
    counts are per-entry exact."""
    ws = _ws(tmp_path, [
        {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
        {"id": "C-2", "status": "PROVEN", "answers_question": "q2"},
    ])
    _arm_case(ws, "case-q1", "q1")
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q1", "C-1", True)
    _observe(ws, "case-q2", "C-2", True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "REFUTED", "answers_question": "q1"},
            {"id": "C-2", "status": "REFUTED", "answers_question": "q2"},
        ]}), encoding="utf-8")

    calls = {"n": 0}
    real_append = cl.append

    def _fail_second(*a, **k):
        calls["n"] += 1
        if calls["n"] >= 2:
            return False
        return real_append(*a, **k)

    monkeypatch.setattr(cl, "append", _fail_second)
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 1, out
    assert "1 amendment row(s) refused" in out["case_amendments_error"], out
    assert _belief(ws, "case-q1") == (1.0, 2.0)   # landed entry applied
    assert _belief(ws, "case-q2") == (2.0, 1.0)   # refused entry untouched
    assert len(_amendment_rows(ws)) == 1

    # next pass, healed: ONLY the refused entry re-fires, exactly once
    monkeypatch.undo()
    out2 = src.reconcile_case_settlements(ws)
    assert out2["case_amendments"] == 1, out2
    assert not out2.get("case_amendments_error"), out2
    assert len(_amendment_rows(ws)) == 2
    assert _belief(ws, "case-q1") == (1.0, 2.0)   # no double-apply
    assert _belief(ws, "case-q2") == (1.0, 2.0)
