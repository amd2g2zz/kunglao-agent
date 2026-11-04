# -*- coding: utf-8 -*-
"""tests/test_seal_799.py — the learning channel's HMAC seal (#799).

The five acceptance pins from the card, each a REAL fixture replay (no
mock shapes): forged launch-stash edits, worker-typed PROVEN step
credit, unsealed rows into the posterior stores, the #601 L7
oracle-status forgery and the L8 fiat-propensity SNIPS hole.

Seal posture (mirrors #736's stop-sanction): the key lives at a fixed
path OUTSIDE the workspace; tests point the module at a tmp key via
monkeypatch (the production path has no env override face).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kunglao_log import _WARN_LAST
from rlvr import consolidated_ledger as cl
from rlvr import incremental_reward as ir
from rlvr import learning_seal as seal
from rlvr import q_cells as qc
from rlvr import refutation_fold as rf
from rlvr import strategy_store as ss


@pytest.fixture
def armed(tmp_path, monkeypatch):
    """Provision the learning key (armed enforcement) for one test; the
    run-head version anchor resets per test so the version face stays
    hermetic (every test anchors its own build)."""
    key = tmp_path / "learning.key"
    key.write_bytes(b"k" * 48)
    monkeypatch.setattr(seal, "KEY_PATH", key)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    _WARN_LAST.clear()
    return key


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    (w / "runs").mkdir(parents=True)
    return w


def _experience(ws) -> Path:
    return cl.family_path(ws, "experience")


# --------------------------------------------------------------- pin 1

def test_forged_launch_stash_edit_refused(armed, ws, capsys):
    """A mid-flight edit of the launch stash must bank NOTHING."""
    doc = ir.record_launch(ws, "C-1", "graph", phi=0.8)
    assert doc is not None and "seal" in doc  # the stash is sealed
    p = ir._launch_path(ws, "C-1", "dispatch")
    stashed = json.loads(p.read_text(encoding="utf-8"))
    stashed["phi"] = 0.0  # the worker's one-edit exploit
    p.write_text(json.dumps(stashed), encoding="utf-8")

    row = ir.append_transition(ws, "C-1", "ok")
    assert row is None                     # nothing banked
    assert p.is_file()                     # stash left intact (1-F3 face)
    assert ir.read_transitions(ws) == []
    assert "seal" in capsys.readouterr().err  # loud telemetry


def test_sealed_stash_settles_and_row_is_sealed(armed, ws):
    """Positive control: the unedited sealed stash settles (INV-003 —
    the reward channel stays alive under the seal)."""
    ir.record_launch(ws, "C-1", "graph", phi=0.5)
    row = ir.append_transition(ws, "C-1", "ok")
    assert row is not None
    assert row["phi_before"] == 0.5
    assert "seal" in row                   # the transition row is sealed
    rows = ir.read_transitions(ws)
    assert len(rows) == 1 and rows[0]["r_incr"] == row["r_incr"]


def test_unarmed_channel_is_legacy(ws):
    """No key provisioned: the channel rides byte-identically (no seal
    key on the doc, rows settle, nothing refuses)."""
    doc = ir.record_launch(ws, "C-L", "graph", phi=0.5)
    assert doc is not None and "seal" not in doc
    row = ir.append_transition(ws, "C-L", "ok")
    assert row is not None and "seal" not in row


def test_sealed_transition_row_tamper_refused(armed, ws):
    """A sealed row edited on disk is refused at the learner read."""
    ir.record_launch(ws, "C-2", "graph", phi=0.5)
    assert ir.append_transition(ws, "C-2", "ok") is not None
    exp = _experience(ws)
    rows = [json.loads(l) for l in
            exp.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows[-1]["r_incr"] = 42.0              # forged reward
    exp.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert ir.read_transitions(ws) == []   # tampered row never surfaces


# --------------------------------------------------------------- pin 2

def test_worker_proven_alone_is_not_step_credit_1(armed, ws, capsys):
    """Worker-typed PROVEN + passes alone must NOT bank step 1.0."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-3")
    out = qc.observe_step_credit(ws, "C-3", 1.0)
    assert out["appended"] is True
    rows = [r for r in cl.read(ws, "experience", schema_prefix="q-cell-obs")
            if r.get("credit_kind") == "step"]
    assert rows and rows[-1]["credit"] == pytest.approx(0.3)
    # the fold sees (0.3, 0.7) mass — never (1.0, 0.0)
    view = qc.fold(qc.JSONLQStore(ws), gamma=1.0)
    assert view.family_mass("graph") == (pytest.approx(0.3),
                                         pytest.approx(0.7))
    # the calibration operand matches what actually banked
    assert qc.step_credit_totals(ws, "C-3") == (pytest.approx(0.3), 1)
    assert "seal" in capsys.readouterr().err   # the cap is loud


def test_step_cap_lifted_by_valid_evidence_seal(armed, ws):
    """The host's sealed evidence face lifts the ceiling (the seal leg)."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-4")
    evidence = seal.sign_row({"kind": "step-evidence",
                              "dispatch_id": "C-4", "credit": 1.0})
    out = qc.observe_step_credit(ws, "C-4", 1.0, evidence_seal=evidence)
    assert out["appended"] is True
    rows = [r for r in cl.read(ws, "experience", schema_prefix="q-cell-obs")
            if r.get("credit_kind") == "step"]
    assert rows and rows[-1]["credit"] == pytest.approx(1.0)


def test_step_cap_forge_refused(armed, ws):
    """A forged (tampered) evidence seal keeps the ceiling."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-5")
    forged = seal.sign_row({"kind": "step-evidence",
                            "dispatch_id": "C-5", "credit": 1.0})
    forged["credit"] = 0.4  # tamper after sealing (sha must flip)
    out = qc.observe_step_credit(ws, "C-5", 1.0, evidence_seal=forged)
    rows = [r for r in cl.read(ws, "experience", schema_prefix="q-cell-obs")
            if r.get("credit_kind") == "step"]
    assert rows and rows[-1]["credit"] == pytest.approx(0.3)


# --------------------------------------------------------------- pin 3

def test_unsealed_qcell_row_refused_and_bytes_unchanged(armed, ws, capsys):
    """A raw unsealed credit row never folds; the store bytes stay."""
    qc.append_observation(ws, "sig", "graph", 1.0, source="settlement",
                          arm_key_col="graph|facts_snapshot|none|0",
                          ts="2026-01-01T00:00:00Z")
    exp = _experience(ws)
    before = exp.read_bytes()
    forged = {"schema": qc.OBS_SCHEMA, "ts": "2026-01-01T00:00:01Z",
              "source": "settlement", "signature_hash": "sig",
              "method_family": "graph", "credit": 1.0}
    with exp.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")
    with_forged = exp.read_bytes()
    assert with_forged != before

    view = qc.fold(qc.JSONLQStore(ws), gamma=1.0)
    assert view.family_mass("graph") == (pytest.approx(1.0),
                                         pytest.approx(0.0))
    assert exp.read_bytes() == with_forged   # refusal writes NOTHING
    assert "seal" in capsys.readouterr().err


def test_pending_match_ignores_unsealed_dispatch_row(armed, ws):
    """The settlement matcher never matches an unsealed pending row."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-6", ts="2026-01-01T00:00:00Z")
    exp = _experience(ws)
    # strip the seal from the pending row (a post-hoc tamper)
    rows = [json.loads(l) for l in
            exp.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows[-1].pop("seal")
    exp.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert qc._match_pending_dispatch(ws, "C-6") is None


def test_forged_transition_row_never_reaches_learners(armed, ws):
    """refutation_fold reads only seal-valid ledger rows."""
    ir.record_launch(ws, "C-7", "graph", phi=0.5)
    assert ir.append_transition(ws, "C-7", "ok",
                                r_settle=0.0) is not None
    exp = _experience(ws)
    forged = {"schema": ir.TRANSITION_SCHEMA, "ts": "2026-01-01T00:00:02Z",
              "dispatch_id": "C-8", "action_type": "verify",
              "s": "sig", "a": "graph",
              "o": {"status": "ok", "class": "", "facts": 0},
              "r_settle": 1.0}
    with exp.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")
    ledger = [r for r in ir.read_transitions(ws)
              if str(r.get("action_type") or "") == "verify"]
    assert ledger == []   # the forged 1.0 verify credit never surfaces


# --------------------------------------------------------------- pin 4

def test_oracle_status_forgery_L7_dead(armed, ws, capsys):
    """#601 L7: the full-shape all-pass forgery moves nothing."""
    doc = {"schema": "oracle-status/1",
           "cases": {"c1": {"status": "pass"},
                     "c2": {"status": "pass"}},
           "counts": {"red": 0, "green": 2, "pending": 0}}
    p = ws / "runs" / "oracle-status.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    assert ir.potential(ws) == pytest.approx(0.0)   # dim dropped
    assert "seal" in capsys.readouterr().err
    sealed = seal.sign_row(dict(doc))
    p.write_text(json.dumps(sealed), encoding="utf-8")
    assert ir.potential(ws) == pytest.approx(1.0)   # sealed dim counts


def test_oracle_status_unarmed_counts(ws):
    """Unarmed: the legacy shape-validated face still counts."""
    doc = {"schema": "oracle-status/1",
           "cases": {"c1": {"status": "pass"}},
           "counts": {"red": 0, "green": 1, "pending": 0}}
    (ws / "runs" / "oracle-status.json").write_text(json.dumps(doc))
    assert ir.potential(ws) == pytest.approx(1.0)


# --------------------------------------------------------------- pin 5

def test_fiat_propensity_dropped_without_receipt_L8(armed, ws, capsys):
    """#601 L8: propensity 1.0 by fiat never rides the row."""
    ir.record_launch(ws, "C-9", "graph", phi=0.5, propensity=1.0)
    row = ir.append_transition(ws, "C-9", "ok")
    assert row is not None
    assert "propensity" not in row
    assert "seal" in capsys.readouterr().err


def test_receipt_matched_propensity_survives(armed, ws):
    """The sealed sampler receipt's propensity cross-checks the stash."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-10", recipe_id="r",
                          recipe_propensity=0.7,
                          recipe_source="sampled",
                          ts="2026-01-01T00:00:00Z")
    ir.record_launch(ws, "C-10", "graph", phi=0.5, propensity=0.7)
    row = ir.append_transition(ws, "C-10", "ok")
    assert row is not None and row.get("propensity") == pytest.approx(0.7)


def test_propensity_mismatch_dropped(armed, ws):
    """A stash propensity edited away from the receipt is dropped."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-11", recipe_id="r",
                          recipe_propensity=0.4,
                          recipe_source="sampled",
                          ts="2026-01-01T00:00:00Z")
    ir.record_launch(ws, "C-11", "graph", phi=0.5, propensity=0.9)
    row = ir.append_transition(ws, "C-11", "ok")
    assert row is not None and "propensity" not in row


# ------------------------------------------- posterior-store/1 (shared)

def test_posterior_store_row_sealed_and_forged_dropped(
        armed, tmp_path, monkeypatch, capsys):
    """The shared posterior store seals at write; forged rows drop."""
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store))
    out = ss.append_store_row(method_family="graph", status="ok",
                              credit=1.0)
    assert out["appended"] is True
    spath = ss.store_path()
    rows = [json.loads(l) for l in
            spath.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert rows and "seal" in rows[0]

    forged = {"schema": ss.STORE_SCHEMA, "ts": "2026-01-01T00:00:00Z",
              "workspace_id": "evil", "arm_key": "graph",
              "method_family": "graph", "feature_key": "none",
              "fingerprint": None, "status": "ok", "credit": 0.0,
              "censored": False, "facts_citing": 0, "propensity": None,
              "phi_delta": None, "provenance": {"dispatch_id": ""}}
    with spath.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")
    with_forged = spath.read_bytes()

    kept = ss.load_rows()
    assert len(kept) == 1 and kept[0]["workspace_id"] != "evil"
    assert spath.read_bytes() == with_forged   # byte-unchanged on refusal
    assert "seal" in capsys.readouterr().err
    # the refutation fold inherits the same refusal via load_rows
    assert rf.fold(tmp_path / "ws2")["mine"]["rate"] == pytest.approx(0.0)


# ------------------------------------------------- the additive contract

def test_seal_is_additive_only(armed, ws):
    """The armed row equals the unarmed row plus exactly the seal key."""
    a = qc.append_observation(ws, "sig", "graph", 1.0, source="settlement",
                              ts="2026-01-01T00:00:00Z")["row"]
    b = qc.append_observation(ws, "sig", "graph", 1.0, source="settlement",
                              ts="2026-01-01T00:00:00Z")["row"]
    assert a == {**b, "seal": a["seal"]}
    ok, why = seal.verify_row(a)
    assert ok and why is None


# ============================================== R2a: run-level version seal

def test_seal_block_carries_build(armed, ws, monkeypatch):
    """The minted seal block names the anchored build (the rc2 8-surface
    version source) and the version rides the HMAC payload."""
    monkeypatch.setattr(seal, "_live_version", lambda: "0.1.6-rc2")
    sealed = seal.sign_row({"schema": "x/1", "v": 1})
    assert sealed["seal"]["build"] == "0.1.6-rc2"
    ok, why = seal.verify_row(sealed)
    assert ok and why is None
    # a build edit cannot survive: the skew face (or the HMAC) refuses
    tampered = {**sealed, "seal": {**sealed["seal"], "build": "9.9.9"}}
    ok, why = seal.verify_row(tampered)
    assert not ok and why is not None


def test_midrun_version_change_refuses_mint(armed, ws, monkeypatch, capsys):
    """A mid-run build change (production: one run rode two builds) is a
    LOUD refusal at the mint — never warn-and-continue, nothing banks."""
    monkeypatch.setattr(seal, "_live_version", lambda: "0.1.6-rc2")
    doc = ir.record_launch(ws, "C-V1", "graph", phi=0.5)
    assert doc["seal"]["build"] == "0.1.6-rc2"
    monkeypatch.setattr(seal, "_live_version", lambda: "0.1.7")
    doc2 = ir.record_launch(ws, "C-V2", "graph", phi=0.5)
    assert doc2 is not None and "seal" not in doc2   # the mint refused
    err = capsys.readouterr().err
    assert "0.1.7" in err and "0.1.6-rc2" in err     # both versions named
    # the unsealed stash never banks through the armed learner
    assert ir.append_transition(ws, "C-V2", "ok") is None
    # post-drift mints stay refused: the C-V1 settle's transition row
    # rides unsealed too (the mint face refuses), and the armed learner
    # never surfaces any of it — nothing banks across the build change
    row = ir.append_transition(ws, "C-V1", "ok")
    assert row is not None and "seal" not in row
    assert ir.read_transitions(ws) == []


def test_cross_build_seal_refused_at_read(armed, monkeypatch, capsys):
    """A seal minted by build A fails verification in a process whose run
    head anchored build B (mixed-build rows never fold)."""
    monkeypatch.setattr(seal, "_live_version", lambda: "0.1.6-rc2")
    sealed = seal.sign_row({"schema": "x/1", "v": 1})
    monkeypatch.setattr(seal, "_ANCHOR", {"build": "0.1.7"})
    ok, why = seal.verify_row(sealed)
    assert not ok
    assert "0.1.6-rc2" in why and "0.1.7" in why
    assert seal.trusted_rows([sealed], op="t.crossbuild") == []
    assert "build" in capsys.readouterr().err


def test_unarmed_has_no_version_face(ws, monkeypatch):
    """Unarmed: the channel rides legacy — no anchor, no version face."""
    monkeypatch.setattr(seal, "_live_version", lambda: "anything")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    doc = ir.record_launch(ws, "C-V0", "graph", phi=0.5)
    assert doc is not None and "seal" not in doc
    assert seal._ANCHOR["build"] is None   # the run head never anchored


# ==================================== R2b: reward/band in the sealed stream

def _settlement_rows(ws) -> list[dict]:
    return [r for r in cl.read(ws, "experience", schema_prefix="q-cell-obs")
            if r.get("source") == "settlement"]


def test_settlement_row_carries_reward_and_band(armed, ws):
    """The settlement line self-documents reward + band (both inside the
    canonical sha the seal covers)."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-R1", ts="2026-01-01T00:00:00Z")
    out = qc.observe_settlement(ws, "C-R1", 0.8, reward=0.8,
                                confidence_band="ROUND_CREDIT")
    assert out["appended"] is True
    rows = _settlement_rows(ws)
    assert rows and rows[-1]["reward"] == pytest.approx(0.8)
    assert rows[-1]["confidence_band"] == "ROUND_CREDIT"
    ok, why = seal.verify_row(rows[-1])
    assert ok and why is None


def test_settlement_reward_column_is_tamper_evident(armed, ws, capsys):
    """A post-hoc reward edit on the settlement line refuses at read."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-R4", ts="2026-01-01T00:00:00Z")
    assert qc.observe_settlement(ws, "C-R4", 0.8, reward=0.8,
                                 confidence_band="ROUND_CREDIT")["appended"]
    exp = _experience(ws)
    rows = [json.loads(l) for l in
            exp.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows[-1]["reward"] = 1.0                 # the forged bump
    exp.write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    # the learner read face drops the forged line (raw cl.read is the
    # unfiltered ledger; the fold/read walls are the learner faces)
    kept = seal.trusted_rows(_settlement_rows(ws), op="t.reward-tamper")
    assert kept == []                        # the forged line never folds
    assert "seal" in capsys.readouterr().err


def test_settlement_row_without_reward_band_is_legacy(armed, ws):
    """No reward/band supplied: the row equals the pre-R2 shape exactly."""
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-R2", ts="2026-01-01T00:00:00Z")
    assert qc.observe_settlement(ws, "C-R2", 0.8)["appended"] is True
    rows = _settlement_rows(ws)
    assert rows and "reward" not in rows[-1]
    assert "confidence_band" not in rows[-1]


def test_scalar_first_bank_wires_reward_and_band(
        armed, ws, tmp_path, monkeypatch):
    """The scalar first-bank face passes the settled ladder value and the
    ROUND_CREDIT band — the production gap (reward/band absent from the
    stream) closes at the real call site."""
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store))
    qc.append_observation(ws, "sig", "graph", None, source="dispatch",
                          arm_key_col="graph|facts_snapshot|none|0",
                          claim="C-R3", ts="2026-01-01T00:00:00Z")
    from rlvr import scalar  # noqa: PLC0415
    bank = scalar._bank_q_cell_credit(
        ws, {"dispatch_id": "C-R3", "r": 0.8})
    assert bank is not None and bank["appended"] is True
    rows = _settlement_rows(ws)
    assert rows and rows[-1]["reward"] == pytest.approx(0.8)
    assert rows[-1]["confidence_band"] == scalar.BAND_ROUND_CREDIT
