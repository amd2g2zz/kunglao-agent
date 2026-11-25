#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""M1 (#1005): the production learning switch — KUNGLAO_SCHEDULER=uniform
must take effect at the production sampling entries
(strategy_store.method_sample / reconcile_declaration, the face
``method_lead`` renders too) without touching the default path.

Two hard pins — the acceptance bar of the slice:

  * default behavior is byte-identical to the pre-change tree: the
    receipts below were captured from dev 2556d74b BEFORE the switch
    was wired (see the capture script and output under
    ~/.claude/kunglao-chains/M1/s1/, outside the repo) and any drift
    in the default path fails here;
  * the uniform arm draws without the learned Q (day-one Beta(1,1)
    cells), with equal-weight candidates, and never touches recording.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rlvr import priors, q_cells, strategy_store


#: pre-change capture (dev 2556d74b, 2026-11-25): method_sample on the
#: learned fixture below — real cell mass (alpha 1.6 / beta 1.4), the
#: history_weight provenance tag, the learned prior share.
METHOD_SAMPLE_GOLDEN = json.loads('''
{
  "candidate_sources": {
    "dynamic-trace": [
      "llm_prior",
      "intake:runs/llm-prior.json"
    ],
    "static-decompile": [
      "llm_prior",
      "intake:runs/llm-prior.json",
      "history_weight"
    ]
  },
  "candidates": {
    "dynamic-trace": {
      "alpha": 1.0,
      "beta": 1.0,
      "p_llm": 0.3333333333333333,
      "theta": 0.626003,
      "weight": 0.20866777751260437
    },
    "static-decompile": {
      "alpha": 1.6,
      "beta": 1.4,
      "p_llm": 0.6666666666666666,
      "theta": 0.12602,
      "weight": 0.0840134329725829
    }
  },
  "family": "static-decompile",
  "gamma": 0.906,
  "prior_source": "llm_prior",
  "probability_source": "unknown",
  "schema": "q-cell-sample/1",
  "signature_hash": "aaaaaaaaaaaa"
}
''')

RECONCILE_GOLDEN = json.loads('''
{
  "actual_method_family": "static-decompile",
  "candidate_sources": {
    "dynamic-trace": [
      "llm_prior",
      "intake:runs/llm-prior.json"
    ],
    "static-decompile": [
      "llm_prior",
      "intake:runs/llm-prior.json",
      "history_weight"
    ]
  },
  "candidates": {
    "dynamic-trace": {
      "alpha": 1.0,
      "beta": 1.0,
      "p_llm": 0.3333333333333333,
      "theta": 0.626003,
      "weight": 0.20866777751260437
    },
    "static-decompile": {
      "alpha": 1.6,
      "beta": 1.4,
      "p_llm": 0.6666666666666666,
      "theta": 0.12602,
      "weight": 0.0840134329725829
    }
  },
  "conditional_sampler_weight": 0.2870475792870717,
  "deviates": false,
  "method_source": "sampled-adoption",
  "prior_source": "llm_prior",
  "probability_source": "unknown",
  "propensity": null,
  "round_lead": null,
  "sampled_conditional_weight": 0.2870475792870717,
  "sampled_family": "static-decompile",
  "sampled_propensity": null,
  "supported": true
}
''')


def _build_case(root: Path, *, learned: bool) -> Path:
    """One intake-seeded workspace; ``learned`` additionally banks one
    settled observation into the static-decompile cell (the fixture the
    default-identity goldens were captured on)."""
    ws = root
    (ws / "runs").mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        "family: native-signature\nlane: binary\n"
        "verification_method: replay-evidence\n"
        "constraints:\n  dynamic_re: allowed\n"
        "primary_questions:\n  - id: PQ1\n    q: derive the result\n"
        "    candidates: [static-decompile, dynamic-trace]\n",
        encoding="utf-8",
    )
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n"
        "    answers_question: PQ1\n",
        encoding="utf-8",
    )
    assert priors.seed_intake_prior(
        ws, families=["static-decompile", "dynamic-trace"])
    if learned:
        assert q_cells.append_observation(
            ws, "aaaaaaaaaaaa", "static-decompile", 0.8,
            source="dispatch", claim="C-first", dispatch_id="dispatch-1",
            arm_key_col=q_cells.arm_key(
                "static-decompile", "facts_snapshot", "none", 1),
        )["appended"]
    return ws


@pytest.fixture
def learned_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "case"
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "isolated"))
    return _build_case(ws, learned=True)


# ------------------------------------------------------ default identity

def test_default_method_sample_matches_pre_change_golden(learned_ws: Path,
                                                         monkeypatch):
    monkeypatch.delenv("KUNGLAO_SCHEDULER", raising=False)
    receipt = strategy_store.PosteriorStrategyStore(
        learned_ws).method_sample("aaaaaaaaaaaa")
    assert receipt == METHOD_SAMPLE_GOLDEN


def test_default_reconcile_matches_pre_change_golden(learned_ws: Path,
                                                     monkeypatch):
    monkeypatch.delenv("KUNGLAO_SCHEDULER", raising=False)
    view = strategy_store.reconcile_declaration(learned_ws, None)
    assert view == RECONCILE_GOLDEN


@pytest.mark.parametrize("value", ["dts", "TRUE", "1", "uniform ", " Uniform"])
def test_non_exact_switch_values_leave_the_default_path_identical(
        learned_ws: Path, monkeypatch, value):
    monkeypatch.setenv("KUNGLAO_SCHEDULER", value)
    receipt = strategy_store.PosteriorStrategyStore(
        learned_ws).method_sample("aaaaaaaaaaaa")
    assert receipt == METHOD_SAMPLE_GOLDEN


# ------------------------------------------------------- the uniform arm

def test_uniform_sample_flattens_prior_and_drops_learned_cells(
        learned_ws: Path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "uniform")
    receipt = strategy_store.PosteriorStrategyStore(
        learned_ws).method_sample("aaaaaaaaaaaa")
    assert receipt["scheduler"] == "uniform"
    # the switch changes the draw law, never the authorized candidate set
    assert set(receipt["candidates"]) == set(METHOD_SAMPLE_GOLDEN["candidates"])
    for family, cand in receipt["candidates"].items():
        # no learned Q: every cell posterior stays the day-one Beta(1,1)
        assert (cand["alpha"], cand["beta"]) == (1.0, 1.0), family
        # equal-weight candidates: the flat 1.0 prior
        assert cand["p_llm"] == 1.0, family
        # the flat law: weight = p_llm * theta, no learned extras
        assert cand["weight"] == pytest.approx(cand["theta"], abs=1e-4), family
        # learned provenance withheld: no history/case weight tags
        assert not any(tag.endswith("_weight")
                       for tag in receipt["candidate_sources"][family]), family
    assert receipt["prior_source"] == "llm_prior"
    assert receipt["probability_source"] == "unknown"


def test_uniform_draw_matches_its_own_cold_start(
        tmp_path: Path, monkeypatch):
    import random

    learned = _build_case(tmp_path / "learned", learned=True)
    virgin = _build_case(tmp_path / "virgin", learned=False)
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "uniform")
    # the same seed: what differs between the two draws must then be
    # ONLY the learned state — and under uniform there is none.
    monkeypatch.setattr(q_cells, "q_cells_seed_state",
                        lambda _ws: (random.Random(3), 0))
    learned_receipt = strategy_store.PosteriorStrategyStore(
        learned).method_sample("aaaaaaaaaaaa")
    virgin_receipt = strategy_store.PosteriorStrategyStore(
        virgin).method_sample("aaaaaaaaaaaa")
    assert learned_receipt == virgin_receipt
    assert learned_receipt["scheduler"] == "uniform"
    for cand in learned_receipt["candidates"].values():
        assert (cand["alpha"], cand["beta"]) == (1.0, 1.0)


def test_uniform_lead_and_reconcile_suggestions_ignore_credit(
        learned_ws: Path, monkeypatch):
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "uniform")
    store = strategy_store.PosteriorStrategyStore(learned_ws)
    # the advisory lead face renders the uniform draw, not the learned one
    lead = store.method_lead("aaaaaaaaaaaa")
    assert lead is not None
    assert lead in METHOD_SAMPLE_GOLDEN["candidates"]
    view = strategy_store.reconcile_declaration(learned_ws, None)
    assert view["sampled_family"] == view["actual_method_family"]
    for family, cand in view["candidates"].items():
        assert cand["p_llm"] == 1.0, family
        assert (cand["alpha"], cand["beta"]) == (1.0, 1.0), family
        assert not any(tag.endswith("_weight")
                       for tag in view["candidate_sources"][family]), family
    # the probability/credit attribution faces are NOT part of this
    # switch (recording stays untouched): the honest unknown-law face
    assert view["propensity"] is None
    assert view["probability_source"] == "unknown"


def test_uniform_sampling_records_nothing_new(learned_ws: Path,
                                              monkeypatch):
    log = learned_ws / "runs" / "experience.jsonl"
    before = log.read_text() if log.exists() else ""
    monkeypatch.setenv("KUNGLAO_SCHEDULER", "uniform")
    store = strategy_store.PosteriorStrategyStore(learned_ws)
    store.method_sample("aaaaaaaaaaaa")
    strategy_store.reconcile_declaration(learned_ws, None)
    after = log.read_text() if log.exists() else ""
    assert after == before


# ------------------------------------------------------ registry sync

def test_registry_syncs_scheduler_owner_to_strategy_store():
    import runtime_switches as rs

    spec = rs.SWITCHES["KUNGLAO_SCHEDULER"]
    assert (spec.type, spec.default) == ("str", "")
    assert spec.owner == "scripts/rlvr/strategy_store.py"
    assert "strategy_store" in spec.doc and "checkpoints" in spec.doc