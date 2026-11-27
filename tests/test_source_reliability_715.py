# -*- coding: utf-8 -*-
"""tests/test_source_reliability_715.py — learned source reliability.

The card's four pins, plus the acceptance's generalization and no-rule
faces:

  1. evidence REFUTED by later evidence raises its source's Beta beta;
     evidence CONFIRMED raises alpha — the invalidation events are the
     only teacher.
  2. a low-reliability source's step credit is discounted by the sampled
     theta (item_credit × source_reliability_theta, composed onto the
     step-credit module's own score).
  3. Thompson sampling naturally explores uncertain sources — a
     settled-bad source is effectively never retried while an uncertain
     one keeps drawing wide.
  4. no rule table: every labeled class starts Beta(1, 1); reliability
     learned for a source applies to that source in NEW contexts (the
     marginal backoff).

The credit face under test is the step-credit module's
(classify_verification / item_credit / step_credit — whose scoring this
suite discounts) with the learned weight riding on top.

Every scenario is derived from the change's spec deltas
(openspec/changes/issue-715-source-reliability), not from the
implementation.
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

from rlvr import source_reliability as sr  # noqa: E402
from rlvr import step_credit as sc  # noqa: E402

PSEUDO = {"source": "ghidra-pseudo", "reference_class": "derived",
          "eid": "E-1"}
ASM = {"source": "raw-asm", "reference_class": "raw", "eid": "E-2"}


@pytest.fixture()
def store(tmp_path, monkeypatch):
    """A workspace owning its own reliability store (cross-project
    off: the store is workspace data, each test pins its own)."""
    monkeypatch.delenv("KUNGLAO_POSTERIOR_STORE", raising=False)
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


# 1. the invalidation events are the only teacher ---------------------------

def test_refuted_evidence_updates_source_beta(store):
    before = sr.fold(ws=store).posterior(PSEUDO)
    out = sr.record_refutation(store, PSEUDO, refuted_by="E-9")
    assert out["recorded"] is True
    after = sr.fold(ws=store).posterior(PSEUDO)
    assert after["beta"] == before["beta"] + 1.0
    assert after["alpha"] == before["alpha"]          # alpha untouched
    assert after["mean"] < before["mean"]             # refuted -> worse
    # no cross-talk: an unrelated source is still at its prior
    assert sr.fold(ws=store).posterior(ASM)["basis"] == "prior"


def test_confirmed_evidence_updates_source_beta(store):
    before = sr.fold(ws=store).posterior(ASM)
    out = sr.record_confirmation(store, ASM, confirmed_by="E-9")
    assert out["recorded"] is True
    after = sr.fold(ws=store).posterior(ASM)
    assert after["alpha"] == before["alpha"] + 1.0
    assert after["beta"] == before["beta"]            # beta untouched
    assert after["mean"] > before["mean"]


# 2. credit weighting (composed onto the step-credit module's score) --------

def test_low_reliability_source_discounts_credit(store):
    for _ in range(10):
        sr.record_refutation(store, PSEUDO)
    for _ in range(10):
        sr.record_confirmation(store, ASM)

    # the step-credit module's own verification-class scale is untouched
    assert sc.CREDIT_BY_CLASS[sc.CROSS_VALIDATED] == 1.0
    assert sc.CREDIT_BY_CLASS[sc.UNVERIFIED] == 0.3
    assert sc.CREDIT_BY_CLASS[sc.REFUTED] == 0.0
    assert sc.classify_verification("PROVEN", "passes") == sc.CROSS_VALIDATED

    bad = {"status": "PROVEN", "verify_status": "passes", **PSEUDO}
    good = {"status": "PROVEN", "verify_status": "passes", **ASM}
    credit_bad = sc.weighted_step_credit([bad], rng=random.Random(7),
                                         ws=store)
    credit_good = sc.weighted_step_credit([good], rng=random.Random(7),
                                          ws=store)

    # step_credit = item_credit(meta) * source_reliability_theta
    # (the module's 6-decimal rounding is its scoring convention)
    theta_bad = sr.reliability_weight(bad, rng=random.Random(7),
                                      ws=store)
    assert credit_bad == round(sc.item_credit(bad) * theta_bad, 6)
    # Beta(1, 11) vs Beta(11, 1): the discount is not marginal
    assert credit_bad < 0.35
    assert credit_good > 0.65
    assert credit_bad < credit_good
    # the production entry (step_credit) carries the same discount
    assert sc.step_credit([bad], ws=store) == \
        sc.weighted_step_credit([bad], ws=store)
    assert sc.step_credit([bad], ws=store) < 0.35
    # unlabeled evidence rides the neutral weight — byte-identical score
    plain = {"status": "PROVEN", "verify_status": "passes"}
    assert sc.weighted_step_credit([plain]) == \
        sc.step_credit([plain]) == 1.0
    assert sr.reliability_weight({"eid": "E-x"}) == 1.0


# 3. TS exploration of uncertain sources ------------------------------------

def test_high_variance_source_triggers_exploration(store):
    settled = {"source": "trace-syscall", "reference_class": "raw"}
    uncertain = {"source": "hook-frida", "reference_class": "derived"}
    settled_bad = {"source": "pseudo-guess", "reference_class": "inferred"}
    for _ in range(15):
        sr.record_confirmation(store, settled)
        sr.record_refutation(store, settled)          # Beta(16, 16)
    sr.record_confirmation(store, settled_bad)
    for _ in range(17):
        sr.record_refutation(store, settled_bad)      # Beta(2, 18)

    view = sr.fold(ws=store)
    # uncertainty is measured, not declared
    assert view.posterior(uncertain)["width"] > \
        3.0 * view.posterior(settled)["width"]

    # TS exploration: the uncertain source keeps drawing wide enough to
    # win some rounds; the settled-bad source effectively cannot.
    rng = random.Random(11)
    wins_uncertain = wins_bad = 0
    for _ in range(300):
        t_u = view.theta(uncertain, rng=rng)
        t_s = view.theta(settled, rng=rng)
        t_b = view.theta(settled_bad, rng=rng)
        if t_u > t_s and t_u > t_b:
            wins_uncertain += 1
        if t_b > t_s and t_b > t_u:
            wins_bad += 1
    assert wins_uncertain >= 60                       # >=20%: exploration alive
    assert wins_bad <= 3                              # settled-bad: ~never


# 4. generalization + no rule table -----------------------------------------

def test_reliability_generalizes_to_new_contexts(store):
    for _ in range(8):
        sr.record_refutation(store, PSEUDO, context_class="ctx-a")
    view = sr.fold(ws=store)
    # the observed context reads its own cell
    cell = view.posterior(PSEUDO, context_class="ctx-a")
    assert cell["basis"] == "cell"
    # a NEW context reads the source-class marginal — the learning applies
    fresh = view.posterior(PSEUDO, context_class="ctx-b")
    assert fresh["basis"] == "marginal"
    assert fresh["beta"] > 1.0
    theta = view.theta(PSEUDO, context_class="ctx-b", rng=random.Random(0))
    assert theta < 0.5


def test_no_rule_table_prior_is_uniform(store):
    """Every labeled class starts Beta(1, 1): the reference-class
    taxonomy orders labels, never trust, and no rule table ranks
    sources."""
    view = sr.fold(ws=store)
    for source, ref in (("ghidra-pseudo", "derived"), ("raw-asm", "raw"),
                        ("mitm-capture", "raw"),
                        ("llm-inferred", "inferred")):
        post = view.posterior(source, ref)
        assert (post["alpha"], post["beta"]) == (1.0, 1.0)
        assert post["basis"] == "prior"
    # the SAME tool in a different reference frame is a separate, equally
    # un-trusted cell — no tier shortcut exists
    assert view.posterior("ghidra-pseudo", "raw")["mean"] == 0.5
    assert view.posterior("ghidra-pseudo", "derived")["mean"] == 0.5


def test_invalid_labels_are_refused_not_recorded(store):
    out = sr.record_refutation(store,
                               {"source": "x", "reference_class": "rumor"})
    assert out["recorded"] is False
    assert "reference_class" in (out["reason"] or "")
    assert sr.fold(ws=store).posterior("x", "raw")["basis"] == "prior"
