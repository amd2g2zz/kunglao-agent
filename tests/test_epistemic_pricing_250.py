# -*- coding: utf-8 -*-
"""Issue 250 — epistemic ΔH enters priority_ratio ranking.

priority_ratio prices `LAMBDA_DH * dh` where dh is the standing entropy of
`ledger.pqs[claim.answers_question]`. Before issue 250 nothing ever wrote
ledger.pqs for situational questions (EXP-3: dh ≡ 0 STRUCTURALLY), so an
epistemic claim was unpriced. After mint+seed, the epistemic claim's ΔH
term is nonzero — same formula, same single LAMBDA_DH parameter. The dh
feed line names the situational/epistemic source.

The issue 251 boundary is pinned too: the seed region (case_face_seed /
posterior_rng) is NOT touched by this lane.
"""
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import priority_ratio as pr  # noqa: E402
import plan_epistemics as pe  # noqa: E402


SPEC = {
    "lane": "malware",
    "primary_questions": [],
}


def _vmp_ws(ws: Path) -> Path:
    ev = ws / "evidence"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "die.json").write_text(
        '{"derived": {"detected_packer": "vmprotect"}}', encoding="utf-8")
    return ws


def _register(ws: Path, claims: list[dict]) -> None:
    import yaml
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False), encoding="utf-8")


def _mint_and_seed(ws: Path) -> list[dict]:
    unknowns = pe.derive_must_master("vmp", SPEC)
    minted = pe.mint_epistemic_claims(
        [], unknowns, next_id_fn=lambda i: f"C-{900 + i}")
    _register(ws, minted)
    pe.seed_situational_pqs(ws, minted, SPEC)
    return minted


def test_epistemic_claim_prices_nonzero_dh(tmp_path):
    _vmp_ws(tmp_path)
    minted = _mint_and_seed(tmp_path)
    evidence = pr.EvidenceView(terminal_fact_claims=frozenset({"C-000"}),
                               ws=tmp_path)
    actions = pr.priority_ratio(minted, {}, evidence, rng=None)
    assert actions, "minted epistemic claims must be rankable candidates"
    for a in actions:
        dh_state = a.feeds.get("dh_pq", "")
        assert dh_state, "every action carries the dh feed"
        assert "categorical H=0.0 bit" not in dh_state, (
            "seeded situational categorical must price nonzero dH")
        assert a.score > 0


def test_dh_feed_names_situational_source_for_epistemic_claims(tmp_path):
    _vmp_ws(tmp_path)
    minted = _mint_and_seed(tmp_path)
    evidence = pr.EvidenceView(terminal_fact_claims=frozenset({"C-000"}),
                               ws=tmp_path)
    actions = pr.priority_ratio(minted, {}, evidence, rng=None)
    for a in actions:
        assert "situational" in a.feeds.get("dh_pq", ""), (
            "the dh feed must distinguish the situational/epistemic source")


def test_landa_dh_unchanged():
    assert pr.LAMBDA_DH == 0.25


def test_seed_region_untouched():
    """issue 251 boundary pin: the seed-region functions keep their signatures —
    this lane adds nothing to them."""
    import inspect
    # seed contract v2 (dev issue 251): case_face_seed threads round_no
    assert list(inspect.signature(pr.case_face_seed).parameters) == [
        "ledger", "round_no"]
    assert list(inspect.signature(pr.posterior_rng).parameters) == ["ws"]


def test_unseeded_register_still_zero_dh(tmp_path):
    """Without mint+seed, epistemic claims price dh=0 exactly as before —
    the pricing enters ONLY through the seeded ledger."""
    _vmp_ws(tmp_path)
    unknowns = pe.derive_must_master("vmp", SPEC)
    minted = pe.mint_epistemic_claims(
        [], unknowns, next_id_fn=lambda i: f"C-{900 + i}")
    _register(tmp_path, minted)  # NO seed_situational_pqs call
    evidence = pr.EvidenceView(terminal_fact_claims=frozenset({"C-000"}),
                               ws=tmp_path)
    actions = pr.priority_ratio(minted, {}, evidence, rng=None)
    assert all("H=0" in a.feeds.get("dh_pq", "") or
               "no PQ categorical" in a.feeds.get("dh_pq", "")
               for a in actions)
