"""M2 (#1005): automatic-adoption dispatch rows carry the sampled
conditional probability under the exact selection law; declared,
overridden and flat-scheduler rows keep the honest unknown face."""
from __future__ import annotations

from pathlib import Path

import pytest

from rlvr import priors, strategy_store


def _adoption_receipt(**overrides) -> dict:
    receipt = {"family": "b",
               "candidates": {"a": {"weight": 2.0}, "b": {"weight": 6.0},
                              "c": {"weight": 2.0}}}
    receipt.update(overrides)
    return receipt


def test_adoption_row_stamps_the_draws_exact_conditional_weight():
    # Arrange
    receipt = _adoption_receipt()

    # Act
    view = strategy_store.method_decision(receipt, None)

    # Assert
    assert view["method_source"] == "sampled-adoption"
    assert view["propensity"] == view["sampled_conditional_weight"] == 0.6
    assert view["probability_source"] == "selection_law_exact"


def test_declared_row_keeps_the_unknown_face():
    # Arrange
    receipt = _adoption_receipt()

    # Act
    view = strategy_store.method_decision(receipt, "b")

    # Assert
    assert view["method_source"] == "declared"
    assert view["propensity"] is None
    assert view["probability_source"] == "unknown"


def test_override_row_keeps_the_unknown_face():
    # Arrange
    receipt = _adoption_receipt()

    # Act
    view = strategy_store.method_decision(receipt, "a")

    # Assert
    assert view["method_source"] == "override"
    assert view["propensity"] is None
    assert view["probability_source"] == "unknown"


def test_flat_scheduler_adoption_never_carries_the_learned_law_token():
    # Arrange
    receipt = _adoption_receipt(scheduler="uniform")

    # Act
    view = strategy_store.method_decision(receipt, None)

    # Assert
    assert view["method_source"] == "sampled-adoption"
    assert view["propensity"] is None
    assert view["probability_source"] == "unknown"


@pytest.mark.parametrize("receipt", [
    # the chosen family is absent from the candidates: its share is 0
    {"family": "a", "candidates": {"b": {"weight": 1.0}}},
    # a zero/non-positive weight poisons the whole proportional support
    {"family": "a", "candidates": {"a": {"weight": 0.0},
                                   "b": {"weight": 1.0}}},
    {"family": "a", "candidates": {"a": {"weight": -1.0},
                                   "b": {"weight": 3.0}}},
    # non-finite, boolean, stringy or missing weights are not numbers
    {"family": "a", "candidates": {"a": {"weight": float("nan")},
                                   "b": {"weight": 1.0}}},
    {"family": "a", "candidates": {"a": {"weight": True},
                                   "b": {"weight": 1.0}}},
    {"family": "a", "candidates": {"a": {"weight": "1.0"},
                                   "b": {"weight": 1.0}}},
    {"family": "a", "candidates": {"a": {"p_llm": 1.0},
                                   "b": {"weight": 1.0}}},
    {"family": "a", "candidates": None},
    {"family": None, "candidates": {"a": {"weight": 1.0}}},
])
def test_unreconstructable_adoption_keeps_the_old_row_bytes(receipt):
    view = strategy_store.method_decision(receipt, None)
    assert view["propensity"] is None
    assert view["probability_source"] == "unknown"


def _mk_ws(root: Path) -> Path:
    ws = root
    (ws / "runs").mkdir(parents=True)
    (ws / "task_spec.yaml").write_text(
        "family: native-signature\nlane: binary\n"
        "verification_method: replay-evidence\n"
        "constraints:\n  dynamic_re: allowed\n"
        "primary_questions:\n  - id: PQ1\n    q: derive the result\n"
        "    candidates: [static-decompile, dynamic-trace]\n",
        encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n"
        "    answers_question: PQ1\n", encoding="utf-8")
    assert priors.seed_intake_prior(
        ws, families=["static-decompile", "dynamic-trace"])
    return ws


def test_production_reconcile_adoption_view_carries_the_exact_law(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Arrange
    ws = _mk_ws(tmp_path / "case")
    monkeypatch.setenv("KUNGLAO_POSTERIOR_STORE", str(tmp_path / "isolated"))

    # Act
    view = strategy_store.reconcile_declaration(ws, None)

    # Assert
    assert view["method_source"] == "sampled-adoption"
    assert view["propensity"] == view["sampled_conditional_weight"]
    assert view["propensity"] > 0
    assert view["probability_source"] == "selection_law_exact"