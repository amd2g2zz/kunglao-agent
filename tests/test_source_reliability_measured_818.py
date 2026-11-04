# -*- coding: utf-8 -*-
"""tests/test_source_reliability_measured_818.py — the learned
source-reliability Betas (#715) in the MEASURED leg (issue #818 climb).

The behavior pins live in tests/test_source_reliability_715.py (fast
tier — invisible to the CI measured-set coverage leg). This file
re-pins, on the REAL isolated store (the conftest points
KUNGLAO_POSTERIOR_STORE at a tmp path): label validation, the
invalidation-event teacher, the fold's cell/marginal/prior backoff
ladder, deterministic Thompson draws, and the credit weight face.
"""
from __future__ import annotations

import random

from rlvr import source_reliability as sr  # noqa: E402  (scripts/ on path)
from rlvr.posteriors import PRIOR_ALPHA_DEFAULT, PRIOR_BETA_DEFAULT

EV = {"source": "ghidra", "reference_class": "derived"}


# ---------- labels ----------

def test_evidence_labels_validate_the_taxonomy() -> None:
    labels = sr.evidence_labels("ghidra", "Derived")
    assert labels == {"source": "ghidra", "reference_class": "derived"}
    for bad in (("", "raw"), ("ghidra", "trusted"), (None, None)):
        try:
            sr.evidence_labels(*bad)
            raised = False
        except ValueError:
            raised = True
        assert raised, bad


def test_source_class_is_tool_plus_frame() -> None:
    assert sr.source_class_of("ghidra", "raw") == "ghidra|raw"
    assert sr.source_class_of("ghidra", "derived") \
        != sr.source_class_of("ghidra", "raw")


def test_resolve_and_has_source_labels() -> None:
    assert sr._resolve(EV) == ("ghidra", "derived")
    assert sr._resolve("ghidra", "raw") == ("ghidra", "raw")
    assert sr._resolve("ghidra", "made-up") is None
    assert sr._resolve(None, None) is None
    assert sr.has_source_labels(EV) is True
    assert sr.has_source_labels({"unlabeled": True}) is False


def test_norm_context_defaults_to_the_unnamed_bucket() -> None:
    assert sr._norm_context(None) == sr.DEFAULT_CONTEXT
    assert sr._norm_context(" packed-js ") == "packed-js"


# ---------- the write faces ----------

def test_record_confirmation_appends_the_teacher_event() -> None:
    res = sr.record_confirmation(EV, confirmed_by="E-2",
                                 context_class="packed-js",
                                 ts="2026-10-24T00:00:00Z")
    assert res["recorded"] is True and res["reason"] is None
    row = res["row"]
    assert row["schema"] == sr.SCHEMA
    assert row["source_class"] == "ghidra|derived"
    assert row["context_class"] == "packed-js"
    assert row["event"] == "confirmed"
    assert row["alpha_add"] == 1.0 and row["beta_add"] == 0.0
    assert row["by"] == "E-2"


def test_record_refutation_bumps_beta() -> None:
    res = sr.record_refutation(EV, refuted_by="E-3")
    assert res["recorded"] is True
    assert res["row"]["event"] == "refuted"
    assert res["row"]["beta_add"] == 1.0
    assert res["row"]["context_class"] == sr.DEFAULT_CONTEXT


def test_record_outcome_refuses_bad_outcome_and_bad_labels() -> None:
    bad_outcome = sr.record_outcome(EV, "vibes")
    assert bad_outcome == {"recorded": False,
                           "reason": "outcome: one of ('confirmed', "
                                     "'refuted') required, got 'vibes'"}
    bad_labels = sr.record_outcome({"no": "labels"}, "confirmed")
    assert bad_labels["recorded"] is False
    assert "reference_class" in bad_labels["reason"]
    assert sr.store_path().exists() is False or \
        sr._read_events() == []              # nothing was recorded


# ---------- fold: cell -> marginal -> prior backoff ----------

def test_fold_reads_cells_and_marginals_from_the_store() -> None:
    sr.record_confirmation(EV, context_class="packed-js")
    sr.record_confirmation(EV, context_class="packed-js")
    sr.record_refutation(EV, context_class="obfuscated")
    view = sr.fold()
    cell = view.posterior(EV, context_class="packed-js")
    assert cell["basis"] == "cell"
    assert (cell["alpha"], cell["beta"], cell["n"]) == (3.0, 1.0, 2.0)
    assert cell["mean"] == 0.75
    marg = view.posterior(EV)                 # no context: the marginal
    assert marg["basis"] == "marginal"
    # prior (1,1) + 2 confirmed (+2 alpha) + 1 refuted (+1 beta), pooled
    assert (marg["alpha"], marg["beta"]) == (3.0, 2.0)
    other = view.posterior({"source": "frida", "reference_class": "raw"})
    assert other["basis"] == "prior"
    assert (other["alpha"], other["beta"]) == \
        (PRIOR_ALPHA_DEFAULT, PRIOR_BETA_DEFAULT)


def test_explicit_context_read_backs_off_to_marginal_when_cell_empty() \
        -> None:
    sr.record_confirmation(EV, context_class="packed-js")
    view = sr.fold()
    # an explicit context with no cell observations answers the marginal
    post = view.posterior(EV, context_class="never-seen")
    assert post["basis"] == "marginal"


def test_fold_ignores_foreign_schema_rows() -> None:
    view = sr.fold([{"schema": "other/9", "event": "confirmed",
                     "source_class": "x|raw"}])
    assert view.posterior("x", "raw")["basis"] == "prior"


def test_theta_draws_are_deterministic_under_a_seeded_rng() -> None:
    sr.record_confirmation(EV)
    view = sr.fold()
    a = view.theta(EV, rng=random.Random(7))
    b = view.theta(EV, rng=random.Random(7))
    assert a == b
    assert 0.0 < a < 1.0
    assert sr.reliability_weight({"unlabeled": 1}) == 1.0
    w = sr.reliability_weight(EV, view=view, rng=random.Random(7))
    assert w == a
