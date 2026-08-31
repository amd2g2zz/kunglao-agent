# -*- coding: utf-8 -*-
"""A3 (#823): priority_ratio feed-side value terms (N-arm only).

The formula shape stays numerator/cost×weight; the N-arm only changes
what is FED into cost (rework-inflated by the bucket's P(complete)) and
adds a capability bonus multiplier for claims holding a validated
capability card. Flag off → byte-identical ranking.
"""
import sys
from pathlib import Path

import priority_ratio as pr
import value_config


def _claim(cid, tier=1, **extra):
    c = {"id": cid, "status": "OPEN", "statement": "c2 config extract",
         "evidence_tier_attempted": tier, "promotion_attempts": 0}
    c.update(extra)
    return c


def _view(**kw):
    return pr.EvidenceView(**kw)


def _rank(claims, view, deps=None):
    return [a.claim_id for a in pr.priority_ratio(claims, deps or {}, view)]


def test_flag_off_identical_scores(monkeypatch):
    monkeypatch.delenv(value_config.ENV_NAME, raising=False)
    claims = [_claim("C-001"), _claim("C-002", tier=2)]
    base = pr.priority_ratio(claims, {}, _view())
    # neutral defaults must not perturb the formula even when fields present
    polluted = pr.priority_ratio(claims, {}, _view(prior_p_complete=0.25))
    assert [a.score for a in base] == [a.score for a in polluted]


def test_flag_on_low_prior_inflates_cost(monkeypatch):
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    claims = [_claim("C-001")]
    scores = {}
    for tag, view in (("pessimistic", _view(prior_p_complete=0.25)),
                      ("optimistic", _view(prior_p_complete=0.9))):
        scores[tag] = pr.priority_ratio(claims, {}, view)[0].score
    assert scores["pessimistic"] < scores["optimistic"]


def test_flag_on_capability_claim_outranks_plain(monkeypatch):
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    claims = [_claim("C-001"), _claim("C-002")]
    view = _view(validated_capabilities=(("C-001", "frida hooking validated"),))
    ranked = _rank(claims, view)
    assert ranked.index("C-001") < ranked.index("C-002")


def test_flag_off_capability_ignored(monkeypatch):
    monkeypatch.delenv(value_config.ENV_NAME, raising=False)
    claims = [_claim("C-001"), _claim("C-002")]
    plain = _rank(claims, _view())
    with_cap = _rank(claims, _view(
        validated_capabilities=(("C-001", "frida hooking validated"),)))
    assert plain == with_cap  # tie broken identically — no bonus applied


def test_prior_floor_bounds_cost_inflation(monkeypatch):
    monkeypatch.setenv(value_config.ENV_NAME, "1")
    claims = [_claim("C-001", tier=3)]
    floor_view = _view(prior_p_complete=0.001)
    a = pr.priority_ratio(claims, {}, floor_view)[0]
    assert a.cost == 10.0  # tier cost unchanged; the correction lives in score math
    tiny_view = _view(prior_p_complete=0.05)
    a2 = pr.priority_ratio(claims, {}, tiny_view)[0]
    assert a.score == a2.score  # 0.001 clamps to the 0.05 floor
