# -*- coding: utf-8 -*-
"""tests/test_phi_tree_796.py — the Φ-tree economy (#796).

Φ-v2 replaces the dilution-dominated graded-fraction core with decisive
mass on the closure hypothesis tree. The ACCEPTANCE ANCHOR is the
three-scenario replay E2E: the reward vector must rank
scenario 3 (compounding critical-path chain + oracle green)
> scenario 2 (small monotone incremental identification)
> scenario 1 (identity churn, strictly net-negative).

Panel pre-conditions pinned here: chain multiplier INSIDE Φ, Φ-regime
versioning on ledger rows, uniform birth masses (dilution ban), signed
clawbacks OUTSIDE the non-negative credit stream. Adversarial patches:
decisive-evidence gate (straw-man farming), escrow timing, store
mirror (laundering), and the L9 censor fold-in. Synthetic fixtures
only — no production log enters the repo.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

from hypothesis_store import Hypothesis, HypothesisStore  # noqa: E402
from rlvr import consolidated_ledger as _cl  # noqa: E402
from rlvr import incremental_reward as ir  # noqa: E402
from rlvr import phi_tree  # noqa: E402
from rlvr import reward as rs  # noqa: E402
from rlvr import strategy_store as ss  # noqa: E402


# ---- fixtures ---------------------------------------------------------------

@pytest.fixture(autouse=True)
def _unarmed_seal(monkeypatch, tmp_path):
    """Deterministic seal posture: the learning channel rides UNARMED in
    this suite (rows pass through unsigned); one test arms its own key."""
    from rlvr import learning_seal as seal
    monkeypatch.setattr(seal, "KEY_PATH", tmp_path / "absent.key")
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})


@pytest.fixture(autouse=True)
def _isolated_store_root(monkeypatch, tmp_path):
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "posterior-root"))


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "hypotheses").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    return ws


def _store(ws: Path) -> HypothesisStore:
    return HypothesisStore(ws / "hypotheses")


def _mk(store: HypothesisStore, hid: str, *, parent: str = "",
        critical: bool = True, claim: str = "C-9") -> None:
    store.create(Hypothesis(id=hid, claim_id=claim,
                            competitor_group="cipher", candidates=["aes"],
                            parent_id=parent, critical_path=critical))


def _resolve(ws: Path, hid: str, *, kind: str = "machine-witness",
             ref: str = "ev-mech", step: str = "step-1",
             claim: str = "C-9", store: HypothesisStore | None = None):
    return phi_tree.settle_resolution(ws, hid, evidence_kind=kind,
                                      evidence_ref=ref, step_ref=step,
                                      claim_ref=claim)


def _oracle_all_pass(ws: Path) -> None:
    import json
    (ws / "runs" / "oracle-status.json").write_text(json.dumps(
        {"schema": "oracle-status/1",
         "cases": {"case-1": {"status": "pass"}}}), encoding="utf-8")


# ---- the acceptance anchor: three-scenario replay ---------------------------

def _scenario_churn(ws: Path) -> float:
    """S1 — identity churn: AES → AES-256-CBC → both wrong. Resolve two
    trunk nodes (the second chain-connected), overturn both, claw back.
    Strictly net-negative is the contract."""
    st = _store(ws)
    _mk(st, "H-1")
    _mk(st, "H-2", parent="H-1")
    assert _resolve(ws, "H-1", step="s1") is not None
    assert _resolve(ws, "H-2", step="s2") is not None
    ir.record_launch(ws, "C-S1", "probe")
    st.transition("H-1", "refuted", refuting_fact_id="ev-x")
    phi_tree.clawback(ws, "H-1", reason="family wrong")
    st.transition("H-2", "refuted", refuting_fact_id="ev-x")
    phi_tree.clawback(ws, "H-2", reason="refinement died with family")
    row = ir.append_transition(ws, "C-S1", "KILLED", status="done")
    assert row is not None
    total = row["r_incr"]
    total -= sum(r["penalty"] for r in phi_tree.read_clawbacks(ws))
    return total


def _scenario_incremental(ws: Path) -> float:
    """S2 — incremental identification: routine found (+trunk), AES
    confirmed mechanically, a failed key attempt eliminates one live
    candidate. Small, positive, monotone."""
    st = _store(ws)
    _mk(st, "H-1")
    _mk(st, "H-2", parent="H-1")
    ir.record_launch(ws, "C-S2", "probe")
    assert _resolve(ws, "H-1", step="s1") is not None
    elim = phi_tree.elimination_credit(
        ws, "H-2", candidate="XOR-key",
        evidence_kind="machine-witness", evidence_ref="ev-fail",
        step_ref="s2", claim_ref="C-S2")
    assert elim is not None and elim["credit"] > 0.0
    assert _resolve(ws, "H-2", step="s3") is not None
    row = ir.append_transition(ws, "C-S2", "DISPATCHED", status="done")
    assert row is not None
    return row["r_incr"] + elim["credit"]


def _scenario_chain(ws: Path) -> float:
    """S3 — the good chain: cipher → key → decryption proof, then the
    oracle-green terminal close (never_demoted hard currency)."""
    st = _store(ws)
    _mk(st, "H-1")
    _mk(st, "H-2", parent="H-1")
    _mk(st, "H-3", parent="H-2")
    ir.record_launch(ws, "C-S3", "probe")
    assert _resolve(ws, "H-1", step="s1", claim="C-S3") is not None
    assert _resolve(ws, "H-2", step="s2", claim="C-S3") is not None
    assert _resolve(ws, "H-3", step="s3", claim="C-S3") is not None
    _oracle_all_pass(ws)
    row = ir.append_transition(ws, "C-S3", "PASS", status="done",
                               r_settle=ir.verify_credit("verified"),
                               done=True)
    assert row is not None
    assert row["r_settle"] == 1.0
    return row["r_incr"] + row["r_settle"]


def test_three_scenario_ranking_is_the_acceptance_anchor(tmp_path):
    # separate workspaces: one scenario each, no cross-contamination
    r1 = _scenario_churn(_ws(tmp_path / "s1"))
    r2 = _scenario_incremental(_ws(tmp_path / "s2"))
    r3 = _scenario_chain(_ws(tmp_path / "s3"))
    assert r3 > r2 > r1, f"ranking broken: S3={r3} S2={r2} S1={r1}"
    assert r1 < 0.0, "churn must be strictly unprofitable"
    assert r2 > 0.0, "real-but-small progress must stay positive"


def test_terminal_close_reconciles_and_releases_escrow(tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    _resolve(ws, "H-1", claim="C-R")
    res = phi_tree.read_resolutions(ws)[0]
    assert res["escrow"]["released"] is False
    _scenario_chain_close(ws, "C-R")  # terminal close fires the pass
    cal = phi_tree.read_calibrations(ws)
    assert len(cal) == 1
    assert cal[0]["claim"] == "C-R"
    assert cal[0]["oracle_outcome"] == "PASS"
    assert res["id"] in cal[0]["released"]
    assert phi_tree.escrow_open(ws, "H-1") is False
    # a second terminal close does not duplicate the calibration row
    _scenario_chain_close(ws, "C-R")
    assert len(phi_tree.read_calibrations(ws)) == 1


def _scenario_chain_close(ws: Path, claim: str) -> None:
    ir.record_launch(ws, claim, "probe")
    ir.append_transition(ws, claim, "PASS", status="done", done=True,
                         r_settle=1.0)


# ---- Φ core: dilution ban, chain-in-Φ, decisive masses ----------------------

def test_dilution_ban_filing_open_nodes_never_moves_phi(tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    assert _resolve(ws, "H-1") is not None
    phi_before = phi_tree.tree_phi(ws)
    for i in range(5):
        _mk(st, f"H-D{i}", claim=f"C-D{i}")
    assert phi_tree.tree_phi(ws) == pytest.approx(phi_before)
    # and through the transition face: no negative r from discovery
    ir.record_launch(ws, "C-X", "probe")
    _mk(st, "H-DX")
    row = ir.append_transition(ws, "C-X", "DISPATCHED", status="done")
    assert row["phi_delta"] == pytest.approx(0.0)


def test_chain_multiplier_lives_inside_phi(tmp_path):
    ws_parent = _ws(tmp_path / "a")
    st = _store(ws_parent)
    _mk(st, "H-1")
    _resolve(ws_parent, "H-1")
    phi_parent = phi_tree.tree_phi(ws_parent)
    # same two nodes, jointly resolved on one trunk (chain-connected)
    ws_chain = _ws(tmp_path / "b")
    st2 = _store(ws_chain)
    _mk(st2, "H-1")
    _mk(st2, "H-2", parent="H-1")
    _resolve(ws_chain, "H-1")
    _resolve(ws_chain, "H-2")
    phi_chain = phi_tree.tree_phi(ws_chain)
    # the child's marginal value when chain-connected...
    child_chain_marginal = phi_chain - phi_parent
    # ...exceeds the same child resolving ISOLATED (no resolved parent)
    ws_alone = _ws(tmp_path / "c")
    st3 = _store(ws_alone)
    _mk(st3, "H-2b", parent="", critical=True)
    _resolve(ws_alone, "H-2b")
    phi_alone = phi_tree.tree_phi(ws_alone)
    assert child_chain_marginal > phi_alone > 0.0
    # and the multiplier is a Φ-term: it rides the potential, so the
    # banked r_incr carries it (never an additive settlement bonus)
    assert phi_chain > phi_parent + phi_alone * (
        1.0 / phi_tree.PHI_NORM * phi_tree.PHI_NORM) - 1e-9


def test_machine_and_referee_masses_differ_at_resolution(tmp_path):
    ws_m = _ws(tmp_path / "m")
    _mk(_store(ws_m), "H-1")
    _resolve(ws_m, "H-1", kind="machine-witness", ref="ev-kat")
    ws_r = _ws(tmp_path / "r")
    _mk(_store(ws_r), "H-1")
    _resolve(ws_r, "H-1", kind="referee-confirm", ref="ev-ref")
    assert phi_tree.tree_phi(ws_m) > phi_tree.tree_phi(ws_r) > 0.0


def test_off_trunk_resolved_node_carries_discounted_mass(tmp_path):
    ws = _ws(tmp_path)
    _mk(_store(ws), "H-1", critical=False)
    _resolve(ws, "H-1")
    ws_t = _ws(tmp_path / "t")
    _mk(_store(ws_t), "H-1", critical=True)
    _resolve(ws_t, "H-1")
    assert phi_tree.tree_phi(ws_t) > phi_tree.tree_phi(ws)
    assert 0.0 < phi_tree.tree_phi(ws) <= 1.0


def test_tree_absent_is_honest_none_and_potential_reads_oracle_only(
        tmp_path):
    ws = _ws(tmp_path)
    assert phi_tree.tree_phi(ws) is None
    ir.record_launch(ws, "C-E", "probe")
    _oracle_all_pass(ws)
    row = ir.append_transition(ws, "C-E", "PASS", status="done")
    assert row is not None
    # no tree: the tree dim is honest-absent; Φ rides the oracle dim
    assert row["s_prime_phi"] == pytest.approx(1.0)
    assert row["phi_regime"] == phi_tree.PHI_REGIME


# ---- decisive-evidence gate (straw-man patch) -------------------------------

def test_assertion_flip_settles_neutral_and_moves_no_mass(tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    row = _resolve(ws, "H-1", kind="worker-assertion", ref="ev-say")
    assert row is not None
    assert row["band"] == "NEUTRAL"
    assert row["credit"] == 0.0
    assert phi_tree.tree_phi(ws) == pytest.approx(0.0)
    # no escrow opens for an assertion flip
    assert phi_tree.escrow_open(ws, "H-1") is False


def test_resolution_requires_machine_or_referee_evidence_ref(tmp_path):
    ws = _ws(tmp_path)
    _mk(_store(ws), "H-1")
    assert _resolve(ws, "H-1", kind="machine-witness", ref="") is None
    assert _resolve(ws, "H-1", kind="oracle-said-so",
                    ref="ev-x") is None
    assert phi_tree.read_resolutions(ws) == []


def test_valuation_and_attribution_ride_together(tmp_path):
    ws = _ws(tmp_path)
    _mk(_store(ws), "H-1")
    # the attribution wall: a credited row without a step ref is invalid
    assert _resolve(ws, "H-1", step="") is None
    row = _resolve(ws, "H-1", step="s-9", claim="C-ATT")
    assert row is not None
    assert row["band"] == "SETTLED_CREDIT"
    assert row["dphi"] > 0.0 and row["step_ref"] == "s-9"
    assert row["escrow"]["released"] is False


# ---- churn clawback (escrow patch + mirror patch) ---------------------------

def test_clawback_refuses_uncredited_or_still_live_nodes(tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    # open (never credited): nothing to claw
    st.transition("H-1", "refuted", refuting_fact_id="ev-x")
    assert phi_tree.clawback(ws, "H-1") is None
    # confirmed but never settled: still nothing to claw
    _mk(st, "H-2")
    st.transition("H-2", "confirmed", confirming_fact_id="ev-y")
    assert phi_tree.clawback(ws, "H-2") is None


def test_clawback_names_the_proposing_step_and_is_net_negative(
        tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    _resolve(ws, "H-1", step="the-proposer")
    st.transition("H-1", "superseded", superseded_by="H-9")
    row = phi_tree.clawback(ws, "H-1", reason="overturned")
    assert row is not None
    assert row["step_ref"] == "the-proposer"
    assert row["penalty"] == pytest.approx(phi_tree.CHURN_PENALTY)
    assert row["clawed_credit"] > 0.0
    assert row["amount"] == pytest.approx(
        row["clawed_credit"] + row["penalty"])
    # one clawback per credited resolution: a second is refused
    assert phi_tree.clawback(ws, "H-1", reason="again") is None


def test_clawback_row_is_sealed_negative_face_and_mirrors_to_store(
        tmp_path, monkeypatch):
    from rlvr import learning_seal as seal
    key = tmp_path / "learning.key"
    key.write_text("k" * 40, encoding="utf-8")
    monkeypatch.setattr(seal, "KEY_PATH", key)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    _resolve(ws, "H-1", step="s-1", claim="C-M")
    st.transition("H-1", "refuted", refuting_fact_id="ev-x")
    row = phi_tree.clawback(ws, "H-1", reason="overturn")
    assert row is not None
    # sealed negative face: armed write sealed the row; the armed read
    # keeps it (never folded into any non-negative credit stream)
    assert "seal" in row
    assert phi_tree.read_clawbacks(ws)[0]["id"] == row["id"]
    # the shared-store mirror: censored, zero credit, negative phi_delta
    mirrored = [r for r in ss.load_rows(ws=None)
                if r.get("status") == "phi-clawback"]
    assert len(mirrored) == 1
    assert mirrored[0]["censored"] is True
    assert mirrored[0]["credit"] == 0.0
    assert mirrored[0]["phi_delta"] < 0.0
    assert mirrored[0]["claim"] == "C-M"


# ---- elimination credit (saturating) ----------------------------------------

def test_elimination_credit_decays_and_saturates(tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    credits = []
    for i in range(6):
        row = phi_tree.elimination_credit(
            ws, "H-1", candidate=f"key-{i}",
            evidence_kind="machine-witness", evidence_ref=f"ev-{i}",
            step_ref="s-1", claim_ref="C-EL")
        credits.append(row["credit"] if row else 0.0)
    assert credits[0] == pytest.approx(phi_tree.ELIMINATION_CREDIT)
    granted = [c for c in credits if c > 0.0]
    assert all(a > b for a, b in zip(granted, granted[1:]))
    assert len(granted) == phi_tree.ELIMINATION_MAX_REPEATS
    assert credits[len(granted)] == 0.0  # saturated: no row, no credit
    total = sum(credits)
    first_resolution = 0.0
    _resolve(ws, "H-1")
    first_resolution = phi_tree.read_resolutions(ws)[0]["dphi"]
    assert total < first_resolution


def test_elimination_requires_decisive_witness_and_live_node(tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    # worker-authored failure: farms nothing
    assert phi_tree.elimination_credit(
        ws, "H-1", candidate="k", evidence_kind="worker-assertion",
        evidence_ref="ev", step_ref="s", claim_ref="C") is None
    # refuted node: no live candidate to eliminate
    st.transition("H-1", "refuted", refuting_fact_id="ev-x")
    assert phi_tree.elimination_credit(
        ws, "H-1", candidate="k", evidence_kind="machine-witness",
        evidence_ref="ev", step_ref="s", claim_ref="C") is None


# ---- regime stamping + the Φ swap in incremental_reward ---------------------

def test_transition_rows_stamp_phi_regime_and_swap_is_potential_based(
        tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    ir.record_launch(ws, "C-P", "probe")
    phi_launch = ir.potential(ws)
    _resolve(ws, "H-1")
    phi_after = ir.potential(ws)
    assert phi_after > phi_launch  # discovery-of-truth pays, not dilutes
    row = ir.append_transition(ws, "C-P", "DISPATCHED", status="done")
    assert row["phi_regime"] == "phi-tree/1"
    assert row["phi_delta"] == pytest.approx(phi_after - phi_launch)
    # Ng 1999: the shaping term is a pure potential difference
    assert ir.incremental_reward(phi_launch, phi_after) == \
        pytest.approx(phi_after - phi_launch)


def test_potential_renormalizes_over_present_dims_v2(tmp_path):
    # no organs: 0.0 (absent dims drop, never fabricate)
    assert ir.potential(_ws(tmp_path / "a")) == 0.0
    # tree only: the tree term alone (renormalized over present dims)
    ws = _ws(tmp_path / "b")
    _mk(_store(ws), "H-1")
    _resolve(ws, "H-1")
    assert ir.potential(ws) == pytest.approx(phi_tree.tree_phi(ws))
    # tree + oracle: weighted mean
    _oracle_all_pass(ws)
    expect = (ir.W_TREE * phi_tree.tree_phi(ws) + ir.W_ORACLE * 1.0)
    assert ir.potential(ws) == pytest.approx(expect)


# ---- hypothesis_store schema v2 ---------------------------------------------

def test_hypothesis_store_v2_tree_fields_roundtrip(tmp_path):
    st = _store(_ws(tmp_path))
    st.create(Hypothesis(id="H-2", claim_id="C-1",
                         competitor_group="g", candidates=["a"],
                         parent_id="H-1", critical_path=True))
    h = st.get("H-2")
    assert h.parent_id == "H-1"
    assert h.critical_path is True
    raw = (st.root / "H-2.md").read_text(encoding="utf-8")
    assert "parent_id: H-1" in raw
    assert "critical_path: true" in raw


def test_v1_hypothesis_file_parses_with_honest_defaults(tmp_path):
    st = _store(_ws(tmp_path))
    (st.root / "H-1.md").write_text(
        "---\nid: H-1\nclaim_id: C-1\ncompetitor_group: g\n"
        "candidates: [AES]\nstatus: open\nschema_rev: 1\n---\n\nbody\n",
        encoding="utf-8")
    h = st.get("H-1")
    assert h.parent_id == ""
    assert h.critical_path is False
    # round-tripping a v1 file through a NON-tree write must not invent
    # tree fields (v1 shape stays byte-identical)
    st.transition("H-1", "refuted", refuting_fact_id="ev")
    raw = (st.root / "H-1.md").read_text(encoding="utf-8")
    assert "parent_id" not in raw
    assert "critical_path" not in raw


def test_resolution_persists_evidence_and_attribution(tmp_path):
    ws = _ws(tmp_path)
    st = _store(ws)
    _mk(st, "H-1")
    _resolve(ws, "H-1", kind="machine-witness", ref="ev-kat",
             step="s-7")
    h = st.get("H-1")
    assert h.status == "confirmed"
    assert h.resolved_evidence == "machine-witness"
    assert h.resolved_ref == "ev-kat"
    assert h.resolved_step_ref == "s-7"
    assert h.posterior == pytest.approx(phi_tree.MACHINE_MASS)


# ---- reward-rules v4 + registration trio ------------------------------------

def test_reward_rules_v4_hypothesis_classes_are_registered_and_classify(
        ):
    doc = rs.load_rules()  # unregistered kind would raise ValueError
    assert doc["version"] == 4
    decisive = rs.classify("hypothesis", [
        {"type": "resolution_decisive", "value": True, "source": "phi"},
        {"type": "machine_witness", "value": True, "source": "phi"},
        {"type": "delta_phi_at_threshold", "value": True, "source": "phi"},
    ], doc)
    assert decisive["rule_id"] == "hypothesis/decisive-resolution"
    assert decisive["band"] == "SETTLED_CREDIT"
    churn = rs.classify("hypothesis", [
        {"type": "churn_clawback", "value": True, "source": "phi"},
        {"type": "escrow_attribution", "value": True, "source": "phi"},
    ], doc)
    assert churn["rule_id"] == "hypothesis/churn"
    assert churn["band"] == "CLAWBACK"
    # assertion-only flips never match the decisive rule
    neutral = rs.classify("hypothesis", [
        {"type": "resolution_decisive", "value": False, "source": "phi"},
    ], doc)
    assert neutral["band"] == "NEUTRAL"


def test_economy_stamps_registered_in_the_consolidated_registry():
    native = _cl.NATIVE_SCHEMAS["experience"]
    for stamp in (phi_tree.RESOLUTION_SCHEMA, phi_tree.CLAWBACK_SCHEMA,
                  phi_tree.CALIBRATION_SCHEMA,
                  phi_tree.ELIMINATION_SCHEMA):
        assert stamp in native, f"{stamp} unregistered"


# ---- L9 fold-in: absorbed-at-kill rows ride censored ------------------------

def test_l9_absorbed_verify_rows_are_censored_in_the_shared_store(
        tmp_path, monkeypatch):
    from rlvr import refutation_fold as rf
    ws = tmp_path / "l9ws"
    ws.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE",
                       str(tmp_path / "l9-store"))
    res = rf.record_verify_outcome(ws, verdict="verified",
                                   boundary="verify", absorbed=True)
    assert res.get("appended") is True
    rows = [r for r in ss.load_rows(ws=None)
            if r.get("arm_key") == rf.STORE_ARM]
    assert len(rows) == 1
    assert rows[0]["censored"] is True  # a kill-banked verdict never
    # propagates as clean cross-workspace evidence
    # the clean path stays uncensored
    res2 = rf.record_verify_outcome(ws, verdict="verified",
                                    boundary="verify")
    assert res2.get("appended") is True
    rows = [r for r in ss.load_rows(ws=None)
            if r.get("arm_key") == rf.STORE_ARM]
    assert rows[-1]["censored"] is False
