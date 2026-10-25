# -*- coding: utf-8 -*-
"""tests/test_case_prior_779.py — the case-posterior fourth prior source
(issue #779 Face 3, the learning→decision bridge).

The measured defect: real learning DID happen — ``runs/posteriors.yaml``
case posteriors moved — but ``method_sample``'s prior chain had NO
case source (consumers were writer-side only), so the sampler never
consumed what the oracle taught. The fix: ``proposal_prior_labeled``
gains the ``case`` source — case Betas fold into family weights (join:
case update_map ids → hypothesis claim_id → the method-family usage row
keyed by that claim), SHRINK-capped like every source, labeled
``prior_source: "case"``. Chain order: history → llm_prior → case →
(cross-task store fallback). All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

FAM_A = "kdf-chain-reconstruction"   # registered
FAM_B = "dynamic-trace"              # registered


def _ws(tmp_path, name="ws"):
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    return ws


def _case_doc(ws, case_id: str, green: list[str], red: list[str] | None = None,
              *, retired: bool = False, with_map: bool = True) -> None:
    doc: dict = {"id": case_id, "target_pq": "PQ-1", "status":
                 "retired" if retired else "active"}
    if with_map:
        doc["update_map"] = {"green_up": green, "red_up": red or []}
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{case_id}.yaml").write_text(yaml.safe_dump(doc),
                                          encoding="utf-8")


def _hypothesis(ws, hid: str, claim_id: str) -> None:
    hdir = ws / "hypotheses"
    hdir.mkdir(parents=True, exist_ok=True)
    (hdir / f"{hid}.md").write_text(
        f"---\nid: {hid}\nclaim_id: {claim_id}\ncompetitor_group: pq-PQ-1\n"
        f"candidates: [x]\nstatus: open\nschema_rev: 1\n---\nbody\n",
        encoding="utf-8")


def _usage_row(ws, cid: str, family: str) -> None:
    import method_families as mf

    mf.append_usage_row(ws, cid, family, "w-test")


def _set_case(ws, case_id: str, alpha: float, beta: float) -> None:
    import posteriors_case as po

    led = po.PosteriorLedger.load(ws)
    led.cases[case_id] = po.CasePosterior(case_id, alpha=alpha, beta=beta)
    led.save(ws)


def _store(ws):
    from rlvr.strategy_store import PosteriorStrategyStore

    return PosteriorStrategyStore(ws)


def _sig(ws):
    from rlvr import state as rlvr_state

    return rlvr_state.signature_hash(rlvr_state.snapshot(ws))


# ------------------------------------------------------- the case source


def test_case_prior_is_the_fourth_source(tmp_path):
    """Settled case Betas join to a family through the update_map →
    hypothesis claim → usage-row chain and label ``case``."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)  # one green observation
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "case"
    assert prior == {FAM_A: pytest.approx(1.0)}


def test_history_and_llm_prior_win_over_case(tmp_path):
    """Chain order: measured history → llm_prior → case. A workspace with
    its own proposal history keeps source=history."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)
    from rlvr import q_cells

    q_cells.record_dispatch_observation(
        ws, "envelope", envelope_meta={"method_family": FAM_B}, claim="C-9")
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "history" and prior.get(FAM_B) is not None


def test_case_prior_red_case_teaches_nothing_upward(tmp_path):
    """A red-dominated case folds zero upward weight — a family taught
    only by failures is not a candidate the case source proposes."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=1.0, beta=2.0)  # one red observation
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "none" and prior == {}


def test_case_prior_unobserved_case_contributes_nothing(tmp_path):
    """A Beta(1,1) case carries zero evidence over the support — no
    weight, no source."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=1.0, beta=1.0)
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "none" and prior == {}


def test_case_prior_shrink_cap_bounds_the_fold(tmp_path):
    """The SHRINK cap bounds one case's folded mass: a huge Beta folds as
    SHRINK_CAP mass, never raw counts (contract rl-signal-contract/1 §1.1
    — counts are bounded by the γ/cap folding, never normalized)."""
    from rlvr import q_cells

    ws = _ws(tmp_path)
    _case_doc(ws, "case-a", ["H-1"])
    _case_doc(ws, "case-b", ["H-2"])
    _hypothesis(ws, "H-1", "C-1")
    _hypothesis(ws, "H-2", "C-2")
    _usage_row(ws, "C-1", FAM_A)
    _usage_row(ws, "C-2", FAM_B)
    _set_case(ws, "case-a", alpha=101.0, beta=1.0)   # evidence mass 100
    _set_case(ws, "case-b", alpha=101.0, beta=1.0)   # identical evidence
    # case-c: a THIRD of the raw mass but still above the cap
    _case_doc(ws, "case-c", ["H-3"])
    _hypothesis(ws, "H-3", "C-3")
    _usage_row(ws, "C-3", FAM_B)
    _set_case(ws, "case-c", alpha=35.0, beta=1.0)    # evidence mass 34
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "case"
    # capped masses: A = 8.0, B = 8.0 + 8.0 = 16.0 -> share 1/3 vs 2/3
    # (UNCAPPED it would be 100 vs 134 -> 0.43/0.57)
    assert prior[FAM_A] == pytest.approx(1.0 / 3.0, abs=1e-6)
    assert prior[FAM_B] == pytest.approx(2.0 / 3.0, abs=1e-6)
    assert q_cells.SHRINK_CAP == 8.0  # the documented policy constant


def test_case_prior_unregistered_family_is_filtered(tmp_path):
    """The registry wall: a case joined to a retired/unregistered token
    never rides the prior (the same filter as every prior face)."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", "win-kdf-ladder-totally-unregistered")
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "none" and prior == {}


def test_case_prior_skips_retired_cases(tmp_path):
    """A retired case left the acceptance net — it keeps collecting no
    decision-side weight either."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"], retired=True)
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "none" and prior == {}


def test_case_prior_without_update_map_is_silent(tmp_path):
    """No update_map = no join = no weight (a case doc that discriminates
    nothing teaches the sampler nothing)."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", [], with_map=False)
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "none" and prior == {}


def test_case_prior_broken_ledger_fails_open(tmp_path):
    """An unreadable/unknown-schema posteriors.yaml degrades to the empty
    source with the chain continuing — never a raise at the seam."""
    ws = _ws(tmp_path)
    (ws / "runs" / "posteriors.yaml").write_text(
        "schema: posteriors-schema/999\n", encoding="utf-8")
    prior, source = _store(ws).proposal_prior_labeled()
    assert source == "none" and prior == {}


def test_method_sample_labels_the_case_source(tmp_path):
    """The sampler receipt carries prior_source=case when only cases have
    settled — the issue's Face 3 acceptance read."""
    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)
    receipt = _store(ws).method_sample(_sig(ws))
    assert receipt is not None
    assert receipt["prior_source"] == "case"
    assert receipt["family"] == FAM_A


# ------------------------- the decision-side consumption (usage row read)


def test_reconcile_declaration_gains_the_case_draw(tmp_path):
    """The #691 reconciliation view — the usage row's sampled_family
    source — draws from the case prior on a case-only workspace: the
    sampled family is non-empty where it used to be the cold gap."""
    from rlvr import strategy_store as ss

    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)
    view = ss.reconcile_declaration(ws, FAM_A)
    assert view["sampled_family"] == FAM_A
    assert view["prior_source"] == "case"
    assert view["propensity"] is not None and view["propensity"] > 0.0


def test_usage_row_records_nonempty_sampled_family(tmp_path):
    """The acceptance metric: usage rows carry a non-empty
    ``sampled_family`` once the case prior exists — written through THE
    producer face (append_usage_row) with the reconciliation view."""
    from rlvr import strategy_store as ss

    ws = _ws(tmp_path)
    _case_doc(ws, "case-kdf", ["H-1"])
    _hypothesis(ws, "H-1", "C-1")
    _usage_row(ws, "C-1", FAM_A)   # the join row (the dispatch's family)
    _set_case(ws, "case-kdf", alpha=2.0, beta=1.0)
    view = ss.reconcile_declaration(ws, FAM_A)
    assert view["sampled_family"], view
    import method_families as mf

    # the retry's ALLOW tail records the reconciliation view (the #773
    # W2 wiring) — the sampled exit is durable in the usage row
    mf.append_usage_row(ws, "C-1", FAM_A, "w-test",
                        propensity=view.get("propensity"),
                        sampled_family=view.get("sampled_family"),
                        prior_source=view.get("prior_source"))
    rows = mf.read_usage(ws)
    assert rows and rows[-1]["sampled_family"] == FAM_A
    assert rows[-1]["prior_source"] == "case"
