# -*- coding: utf-8 -*-
"""Issue 250 lane, post-#295 — the epistemic ΔH face is REMOVED (ADR-001).

History: issue 250 wired `LAMBDA_DH * dh` (the standing entropy of
`ledger.pqs[claim.answers_question]`) into the ranker, and mint+seed
made epistemic claims carry nonzero ΔH. The governed application of
issue #295 (docs/adr-001-strategy-parameter-governance.md) REMOVED the
whole ΔH_PQ face: EXP-B proved ΔH ≡ 0 on 612/612 real rank events and
#294 proved the λ=0.25 vs λ=0 order digests byte-identical at every
tick — mechanically inert on all real data. These tests are the REMOVAL
pins: no dh_pq feed, no λ constant, no ΔH lift anywhere in the rank
face, even where a seeded situational categorical exists. Re-introducing
any of them requires the ADR-001 governed procedure.

The issue 251 boundary is still pinned: the seed region (case_face_seed
/ posterior_rng) signatures are untouched by any of this.
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


def test_lambda_dh_removed():
    """ADR-001 removal pin: the λ constant must NOT exist. Its reappearance
    is ungoverned drift — the ΔH term it multiplied is gone (#295)."""
    assert not hasattr(pr, "LAMBDA_DH"), (
        "LAMBDA_DH was removed by #295 (docs/adr-001-strategy-parameter-"
        "governance.md); a reappearance is ungoverned drift")


def test_seeded_situational_categorical_no_longer_lifts_score(tmp_path):
    """Even WITH mint+seed (a populated situational categorical — the exact
    shape issue 250 made price nonzero ΔH), the score carries no ΔH face:
    score > 0 from the Thompson case face alone, and no dh_pq feed."""
    _vmp_ws(tmp_path)
    minted = _mint_and_seed(tmp_path)
    evidence = pr.EvidenceView(terminal_fact_claims=frozenset({"C-000"}),
                               ws=tmp_path)
    actions = pr.priority_ratio(minted, {}, evidence, rng=None)
    assert actions, "minted epistemic claims must be rankable candidates"
    for a in actions:
        assert "dh_pq" not in a.feeds, (
            "the dh_pq feed was removed by #295 (ADR-001)")
        assert a.score > 0


def test_dh_feed_is_gone_entirely(tmp_path):
    """#295 removal pin: actions carry no dh feed at all — the situational
    source line of issue 250 died with the term."""
    _vmp_ws(tmp_path)
    minted = _mint_and_seed(tmp_path)
    evidence = pr.EvidenceView(terminal_fact_claims=frozenset({"C-000"}),
                               ws=tmp_path)
    actions = pr.priority_ratio(minted, {}, evidence, rng=None)
    for a in actions:
        assert all("dh" not in k for k in a.feeds), (
            f"unexpected ΔH feed survived: {sorted(a.feeds)}")


def test_seed_region_untouched():
    """issue 251 boundary pin: the seed-region functions keep their signatures —
    this lane adds nothing to them."""
    import inspect
    # seed contract v2 (dev issue 251): case_face_seed threads round_no
    assert list(inspect.signature(pr.case_face_seed).parameters) == [
        "ledger", "round_no"]
    assert list(inspect.signature(pr.posterior_rng).parameters) == ["ws"]


def test_unseeded_register_still_ranks_without_dh(tmp_path):
    """Without mint+seed the cold-start shape is unchanged EXCEPT the dh
    face, which no longer exists at all (#295)."""
    _vmp_ws(tmp_path)
    unknowns = pe.derive_must_master("vmp", SPEC)
    minted = pe.mint_epistemic_claims(
        [], unknowns, next_id_fn=lambda i: f"C-{900 + i}")
    _register(tmp_path, minted)  # NO seed_situational_pqs call
    evidence = pr.EvidenceView(terminal_fact_claims=frozenset({"C-000"}),
                               ws=tmp_path)
    actions = pr.priority_ratio(minted, {}, evidence, rng=None)
    assert all("dh_pq" not in a.feeds for a in actions)
