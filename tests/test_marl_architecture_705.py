# -*- coding: utf-8 -*-
"""tests/test_marl_architecture_705.py — MARL over SMDP (#705).

Owner ruling 2026-10-15: workers are learning agents, not stateless
tools. Knowledge transfers via warm-start priors (never forced pooling),
credit decomposes into solve vs verification, and negative knowledge
lives at CLASS level — never case-specific. Every scenario here is
derived from the change's spec deltas (openspec/changes/
issue-705-marl-architecture), not from the implementation.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from rlvr import feature_prior  # noqa: E402
from rlvr import marl  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402
from rlvr import strategy_store  # noqa: E402

FAM = "hypothesis-falsification"
SIG = "aaaa0000aaaa"


def _settle_row(sig: str, arm_key: str, credit: float) -> dict:
    return {"schema": qc.OBS_SCHEMA, "ts": "2026-10-15T00:00:00Z",
            "source": "settlement", "signature_hash": sig,
            "method_family": FAM, "claim": None, "agent": None,
            "credit": credit, "arm_key": arm_key, "phi_delta": None}


def _analyst_rows(n_ok: int = 6, n_bad: int = 1) -> list[dict]:
    ak = qc.arm_key(FAM, "facts_snapshot", "none", 1, "analyst")
    return ([_settle_row(SIG, ak, 1.0) for _ in range(n_ok)]
            + [_settle_row(SIG, ak, 0.0) for _ in range(n_bad)])


def _fold(rows: list[dict]):
    return qc.fold(qc.InMemoryStore(rows), gamma=1.0)


# ---- 1. agent-conditioned Q ------------------------------------------------

def test_agent_conditioned_q_produces_different_posteriors():
    """Different agent types address DIFFERENT Beta cells: agent A's
    successes stay agent A's local mass, agent B borrows them only as a
    SHRINK-capped anchor."""
    ak_a = qc.arm_key(FAM, "facts_snapshot", "none", 1, "analyst")
    ak_b = qc.arm_key(FAM, "facts_snapshot", "none", 1, "verifier")
    assert ak_a.endswith("|analyst") and ak_b.endswith("|verifier")
    assert ak_a != ak_b

    view = _fold(_analyst_rows())
    a_a, b_a = qc.cell_posterior(view, SIG, FAM, arm_key=ak_a)
    a_b, b_b = qc.cell_posterior(view, SIG, FAM, arm_key=ak_b)

    assert (a_a, b_a) != (a_b, b_b)          # distinct posteriors
    assert a_a > a_b                          # A's local successes raise α
    assert b_b > b_a                          # B inherits them as failure-free
                                              # anchor mass (β only from prior)


def test_arm_key_agent_dim_is_additive():
    """The 5th dim is optional: a falsy agent type keeps the exact 4-dim
    key the pre-#705 surface wrote (the determinism wall)."""
    assert qc.arm_key(FAM, "facts_snapshot", "none", 1) == \
        f"{FAM}|facts_snapshot|none|1"
    assert qc.arm_key(FAM, "facts_snapshot", "none", 1, None) == \
        f"{FAM}|facts_snapshot|none|1"
    assert qc.arm_key(FAM, "facts_snapshot", "none", 1, "") == \
        f"{FAM}|facts_snapshot|none|1"
    # the family part is still addressable through the shared reader
    ak = qc.arm_key(FAM, "facts_snapshot", "none", 1, "analyst")
    assert qc.family_of_action(ak) == FAM
    assert qc.agent_of_action(ak) == "analyst"
    assert qc.agent_of_action(f"{FAM}|facts_snapshot|none|1") is None


def _bare_family_row(sig: str, credit: float) -> dict:
    """A PRE-#539 legacy row: NO arm_key, so its consumption key IS the
    bare method_family — the only cell the #545 pooling tolerance reads."""
    row = dict(_settle_row(sig, "", credit))
    row["arm_key"] = None
    return row


def test_5dim_read_never_forces_legacy_family_mass_into_local():
    """Design D2 / the R3 carve-out: a 5-dim agent read leaves the
    BARE-family legacy cell in the leave-one-out ANCHOR — forced pooling
    into the agent's own local mass is forbidden (owner: sharing happens
    through warm-start priors, never forced pooling).

    The fixture MUST be a bare-family row: a same-arm 4-dim
    family|recipe|verif|tier cell never pools under either version, so a
    fixture holding only 4-dim rows would stay green even regressed."""
    ak5 = qc.arm_key(FAM, "facts_snapshot", "none", 1, "analyst")
    legacy = [_bare_family_row(SIG, 1.0) for _ in range(3)]
    view = _fold(legacy)

    a, b = qc.cell_posterior(view, SIG, FAM, arm_key=ak5)
    # REGRESSED (guard removed): the 3 legacy successes pool into local,
    # the anchor empties out, -> (1+3, 1+0) = (4.0, 1.0).
    # CORRECT: local stays (0,0), the mass rides the anchor
    # -> (1 + 3*(4/5), 1 + 3*(1/5)) = (3.4, 1.6).
    assert a == pytest.approx(3.4, abs=1e-9)
    assert b == pytest.approx(1.6, abs=1e-9)
    assert b > 1.0                     # β untouched by the pooled mass

    # the FAMILY-keyed read (no agent) still takes it as local — the
    # carve-out is specific to agent keys, not to key-addressed reads.
    a_f, b_f = qc.cell_posterior(view, SIG, FAM)
    assert a_f == pytest.approx(4.0, abs=1e-9)
    assert b_f == pytest.approx(1.0, abs=1e-9)


# ---- 2. warm-start inheritance ---------------------------------------------

def test_warm_start_inherits_cross_agent_evidence():
    """Agent B has NO local evidence but B's prior includes agent A's —
    through the leave-one-out anchor, never a local-cell write."""
    ak_a = qc.arm_key(FAM, "facts_snapshot", "none", 1, "analyst")
    ak_b = qc.arm_key(FAM, "facts_snapshot", "none", 1, "verifier")
    view = _fold(_analyst_rows())

    assert (SIG, ak_b) not in view.cells      # B has no local cell
    a, b = qc.cell_posterior(view, SIG, FAM, arm_key=ak_b)
    assert (a, b) != (1.0, 1.0)               # inherited, not the cold prior
    assert a > 1.0                            # A's successes ride the anchor
    assert (SIG, ak_b) not in view.cells      # inheritance is NOT a write

    # the untyped reader still sees the family aggregate (A included)
    a_f, b_f = qc.cell_posterior(view, SIG, FAM)
    assert a_f > 1.0


# ---- 3. solve vs verification credit ---------------------------------------

def _dispatch(ws, claim: str) -> dict:
    prompt = ('{"kunglao_dispatch": {"version": 2, "claim": "%s", '
              '"tier": 1, "tools": ["grep"], "method_family": "%s", '
              '"action_type": "dispatch", '
              '"context_recipe": "facts_snapshot", '
              '"verification_mode": "none"}}' % (claim, FAM))
    return qc.record_dispatch_observation(
        ws, prompt,
        envelope_meta={"method_family": FAM, "action_type": "dispatch",
                       "context_recipe": "facts_snapshot",
                       "verification_mode": "none", "tier": 1},
        claim=claim)


def _posterior_at_dispatch(ws) -> tuple[float, float]:
    store = qc.JSONLQStore(str(ws))
    disp = next(r for r in store.observations()
                if r.get("source") == "dispatch")
    view = qc.fold(store, gamma=1.0)
    return qc.cell_posterior(view, disp["signature_hash"], FAM,
                             arm_key=disp["arm_key"])


def test_solve_credit_only_updates_posterior(tmp_path):
    """Verification credit confirms existing knowledge — it is recorded
    (the audit trail) but never updates the Beta."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    _dispatch(ws, "C-001")
    _dispatch(ws, "C-002")

    before = _posterior_at_dispatch(ws)
    out_solve = qc.observe_settlement(ws, "C-001", 1.0)
    assert out_solve["beta_updated"] is True
    after_solve = _posterior_at_dispatch(ws)
    assert after_solve[0] > before[0]         # solve credit moved α

    out_verify = qc.observe_settlement(ws, "C-002", 1.0,
                                       credit_kind="verification")
    assert out_verify["beta_updated"] is False
    assert _posterior_at_dispatch(ws) == after_solve   # Beta untouched

    # the verification row IS recorded (audit trail), just inadmissible
    rows = [r for r in qc.JSONLQStore(str(ws)).observations()
            if r.get("credit") is not None]
    kinds = sorted(str(r.get("credit_kind") or "solve") for r in rows)
    assert kinds == ["solve", "verification"]


def test_verification_rows_are_invisible_to_the_fold():
    """The fold excludes verification rows from success, failure AND
    n_pending — they are neither evidence nor pending mass."""
    sig = "bbbb0000bbbb"
    ak = qc.arm_key(FAM, "facts_snapshot", "none", 1)
    solve = _settle_row(sig, ak, 1.0)
    verify = dict(_settle_row(sig, ak, 1.0), credit_kind="verification")
    view = _fold([solve, verify])
    cell = view.cells[(sig, ak)]
    assert cell.success == 1.0                # one admissible row only
    assert cell.n_pending == 0


def test_default_settlement_path_is_the_legacy_solve(tmp_path):
    """credit_kind defaults to solve and the result reports it."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    _dispatch(ws, "C-009")
    out = qc.observe_settlement(ws, "C-009", 0.5)
    assert out["appended"] and out["beta_updated"] is True
    assert out["credit_kind"] == "solve"


def test_default_settlement_row_emits_no_kind_column(tmp_path):
    """The determinism wall: the default (solve) settlement row carries
    NO credit_kind key at all — byte-identical to pre-#705 rows. Only a
    verification settlement marks the row."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    _dispatch(ws, "C-010")
    _dispatch(ws, "C-011")
    qc.observe_settlement(ws, "C-010", 1.0)
    qc.observe_settlement(ws, "C-011", 1.0, credit_kind="verification")
    rows = {r["claim"]: r for r in qc.JSONLQStore(str(ws)).observations()
            if r.get("credit") is not None}
    assert "credit_kind" not in rows["C-010"]     # solve: no key at all
    assert rows["C-011"]["credit_kind"] == "verification"


def test_verification_only_family_warms_nothing(tmp_path, monkeypatch):
    """The cross-task store warms only from solve credit: a family whose
    only settled evidence is verification credit warms from nothing."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store_dir))
    other = tmp_path / "other-ws"          # a DIFFERENT workspace's row
    other.mkdir()

    strategy_store.append_store_row(other, method_family=FAM,
                                    status="proven", credit=1.0,
                                    credit_kind="verification")
    assert strategy_store.warm_pools(tmp_path / "mine", [FAM]) == {}

    strategy_store.append_store_row(other, method_family="structural-anchoring",
                                    status="proven", credit=1.0)
    pools = strategy_store.warm_pools(tmp_path / "mine",
                                      [FAM, "structural-anchoring"])
    assert FAM not in pools                # verification-only → no warm
    assert "structural-anchoring" in pools  # solve credit warms


# ---- 4. class-level negative knowledge -------------------------------------

def test_negative_knowledge_recorded_at_class_level(tmp_path, monkeypatch):
    """Failed tool chains record per (signature_class, agent_type) —
    never per instance. Another workspace of the SAME class inherits the
    dead end; a different class does not see it."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store_dir))
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    # real feature-table/1 shapes (the token projector keys)
    feats_a = {"project_type": "native",
               "packer_flags": {"detected_obfuscators": ["ollvm"]}}
    feats_b = {"project_type": "go",
               "packer_flags": {"detected_packers": ["upx"]}}

    out = marl.record_negative(ws, method_family=FAM,
                               agent_type="analyst", features=feats_a)
    assert out["appended"], out
    cls_a = out["signature_class"]
    assert cls_a == marl.signature_class(features=feats_a)
    assert cls_a != marl.signature_class(features=feats_b)

    # the scenario's THEN: the row carries class AND agent AND family
    # (each element asserted — dropping any one must go red)
    assert out["row"]["signature_class"] == cls_a
    assert out["row"]["agent_type"] == "analyst"
    assert out["row"]["method_family"] == FAM

    pools_a = marl.negative_pools(ws, [FAM], agent_type=None,
                                  signature_class=cls_a)
    cls_b = marl.signature_class(features=feats_b)
    pools_b = marl.negative_pools(ws, [FAM], agent_type=None,
                                  signature_class=cls_b)
    assert FAM in pools_a and pools_a[FAM].failure > 0
    assert pools_a[FAM].success == 0.0        # a dead end is failure mass
    assert FAM not in pools_b                 # class-scoped, not global

    # agent_type NARROWS opt-in: the default pools every agent (the
    # transfer posture), a named agent sees only that agent's rows
    assert FAM in marl.negative_pools(ws, [FAM], agent_type="analyst",
                                      signature_class=cls_a)
    assert FAM not in marl.negative_pools(ws, [FAM], agent_type="verifier",
                                          signature_class=cls_a)

    # a DIFFERENT workspace of the SAME class inherits the dead end
    ws2 = tmp_path / "ws2"
    (ws2 / "runs").mkdir(parents=True)
    pools_ws2 = marl.negative_pools(ws2, [FAM], signature_class=cls_a)
    assert pools_ws2[FAM].failure > 0


def test_negative_pool_raises_beta_and_rides_receipt(tmp_path,
                                                     monkeypatch):
    """Threaded through the sampler, class-level negative mass raises
    the arm's β (a dead end is a failure pseudo-count, never a deletion)
    and rides an additive receipt block. The MEAN is deliberately not
    pinned: the shrinkage anchor's own mean can lift a locally-failing
    cell slightly — the guarantee is β-higher + receipt + the arm stays
    samplable (see test_anti_overfit_exploration_is_maintained)."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store_dir))
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    out = marl.record_negative(ws, method_family=FAM, agent_type="analyst",
                               features={"project_type": "native",
                                         "packer_flags": {
                                             "detected_obfuscators":
                                                 ["ollvm"]}})
    pools = marl.negative_pools(ws, [FAM], signature_class=out[
        "signature_class"])

    store = qc.InMemoryStore([])
    plain = qc.sample_method_family(SIG, {FAM: 1.0}, store)
    with_neg = qc.sample_method_family(SIG, {FAM: 1.0}, store,
                                       negative_pools=pools)
    assert with_neg["candidates"][FAM]["beta"] > \
        plain["candidates"][FAM]["beta"]
    assert "negative_knowledge" in with_neg["candidates"][FAM]
    assert "negative_knowledge" not in plain["candidates"][FAM]

    # the byte-identity wall: an EMPTY pool and an ABSENT pool leave the
    # WHOLE receipt identical — not merely the receipt block's absence
    assert qc.sample_method_family(SIG, {FAM: 1.0}, store,
                                   negative_pools={}) == plain
    assert qc.sample_method_family(SIG, {FAM: 1.0}, store,
                                   negative_pools=None) == plain


def test_anti_overfit_exploration_is_maintained():
    """Negative knowledge DISCOURAGES, never deletes: Thompson Sampling
    keeps exploring — no method family collapses to zero probability
    (the ARM_FLOOR posture, no rule table, no deterministic argmax)."""
    neg = {FAM: feature_prior.FeaturePool(0.0, 8.0, 3)}  # heavy dead end
    picks = set()
    for seed in range(40):
        r = qc.sample_method_family(
            SIG, {FAM: 0.6, "structural-anchoring": 0.4},
            qc.InMemoryStore([]), rng=random.Random(seed),
            negative_pools=neg)
        picks.add(r["family"])
    assert picks == {FAM, "structural-anchoring"}   # both still samplable
    # and the receipt shows the dead end without zeroing the arm
    r = qc.sample_method_family(SIG, {FAM: 1.0}, qc.InMemoryStore([]),
                                rng=random.Random(0), negative_pools=neg)
    assert r["candidates"][FAM]["weight"] > 0.0


def test_planning_entry_consults_negative_knowledge(tmp_path, monkeypatch):
    """The transfer protocol is not write-only: the strategy store
    threads class-level dead ends into the sampler at planning entry."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store_dir))
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    # no explicit features → the row's class IS this workspace's own
    # class (both derive to the inert "unknown" here), so the planning
    # read finds it
    out = marl.record_negative(ws, method_family=FAM, agent_type="analyst")
    assert out["appended"] and out["signature_class"] == \
        marl.signature_class(ws)
    store = strategy_store.PosteriorStrategyStore(ws)
    kw = store._negative_pool_kwargs([FAM])
    assert FAM in kw["negative_pools"]
    assert kw["negative_pools"][FAM].failure > 0


# ---- 5. solution broadcast (method, never the answer) ----------------------

def test_solution_broadcast_method_not_answer(tmp_path, monkeypatch):
    """A PROVEN claim's METHOD enters the shared posterior; the answer
    text never rides the row."""
    store_dir = tmp_path / "store"
    store_dir.mkdir()
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(store_dir))

    answer = "0x7fdeadbeef is the license-check branch"
    out = marl.broadcast_solution(tmp_path / "ws", method_family=FAM,
                                  agent_type="analyst", claim="C-042",
                                  credit=1.0, answer=answer)
    assert out["appended"], out

    blob = strategy_store.store_path().read_text(encoding="utf-8")
    assert FAM in blob                        # the method is shared
    assert answer not in blob                 # the answer is NOT

    rows = strategy_store.load_rows()
    hit = [r for r in rows if r.get("method_family") == FAM]
    assert hit and hit[0].get("agent_type") == "analyst"
    assert hit[0].get("claim") == "C-042"
    assert "answer" not in hit[0]
