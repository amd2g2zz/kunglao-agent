"""tests/test_priority_ratio.py — VoI 代理打分 (issue #2, design-spec §3.2).

RED: 新公式 score = [0.45·L + 0.30·D + 0.25·N] / cost; 旧 0.35·Δdisc 公式已废。
"""
from __future__ import annotations

import priority_ratio as pr


# ---------- 合成 fixtures ----------

def _claim(cid, status="OPEN", answers_question=None, competitor_group=None,
           eta=0, attempts=0, statement=""):
    c = {"id": cid, "status": status, "evidence_tier_attempted": eta,
         "promotion_attempts": attempts, "statement": statement or cid}
    if answers_question is not None:
        c["answers_question"] = answers_question
    if competitor_group is not None:
        c["competitor_group"] = competitor_group
    return c


def _evidence(terminal_claims=(), verified=0, fact_categories=None):
    return pr.EvidenceView(
        terminal_fact_claims=frozenset(terminal_claims),
        verified_fact_count=verified,
        fact_count_by_category=dict(fact_categories or {}),
    )


def _deps(depends_on=None, competitor_groups=None):
    return {"depends_on": depends_on or {}, "competitor_groups": competitor_groups or {}}


# ---------- 公式 ----------

def test_voi_formula_not_additive_not_old():
    """score == [0.45·L + 0.30·D + 0.25·N] / cost — 比值键, 非加法, 非旧 0.35·Δdisc。"""
    claims = [_claim("C-1", statement="c2 config extract")]
    deps = _deps()
    ev = _evidence()
    out = pr.priority_ratio(claims, deps, ev)
    assert len(out) == 1
    a = out[0]
    numerator = 0.45 * a.leverage + 0.30 * a.discriminator + 0.25 * a.novelty
    assert a.score == round(numerator / a.cost, 3)
    for stale in ("delta_disc", "expected_unlock", "unc"):
        assert not hasattr(a, stale), f"Action 不应再有旧字段 {stale}"


# ---------- leverage ----------

def test_leverage_terminal_claim_is_zero():
    """claim 已有 terminal fact → L=0 (无下游解锁价值)。"""
    claims = [_claim("C-1"), _claim("C-2", status="OPEN")]
    deps = _deps(depends_on={"C-2": ["C-1"]})
    ev = _evidence(terminal_claims=["C-1"])
    out = pr.priority_ratio(claims, deps, ev)
    by = {a.claim_id: a for a in out}
    assert by["C-1"].leverage == 0.0


def test_leverage_higher_with_more_open_downstream():
    """下游 OPEN claim 多 → L 高于无下游者。"""
    claims = [_claim("HUB"), _claim("LEAF-A"), _claim("LEAF-B"), _claim("ORPHAN")]
    deps = _deps(depends_on={"LEAF-A": ["HUB"], "LEAF-B": ["HUB"]})
    ev = _evidence()
    out = pr.priority_ratio(claims, deps, ev)
    by = {a.claim_id: a for a in out}
    assert by["HUB"].leverage > by["ORPHAN"].leverage
    assert by["ORPHAN"].leverage == 0.0


# ---------- discriminator ----------

def test_discriminator_active_competitor_group_top():
    """活 competitor_group (≥2 OPEN) 的 claim → D=1.0。"""
    claims = [_claim("C-a", competitor_group="q1"), _claim("C-b", competitor_group="q1")]
    deps = _deps(competitor_groups={"q1": ["C-a", "C-b"]})
    ev = _evidence()
    out = pr.priority_ratio(claims, deps, ev)
    by = {a.claim_id: a for a in out}
    assert by["C-a"].discriminator == 1.0


def test_discriminator_answers_question_middle():
    """answers_question (primary) → D=0.5。"""
    claims = [_claim("C-1", answers_question="q_primary")]
    deps = _deps()
    ev = _evidence()
    out = pr.priority_ratio(claims, deps, ev)
    assert out[0].discriminator == 0.5


def test_discriminator_else_floor():
    """无 group 无 answers → D=0.2。"""
    claims = [_claim("C-1")]
    deps = _deps()
    ev = _evidence()
    out = pr.priority_ratio(claims, deps, ev)
    assert out[0].discriminator == 0.2


# ---------- novelty ----------

def test_novelty_drops_with_prior_facts_in_category():
    """同 action 类别已产 fact 多 → N 降。"""
    claims = [_claim("C-1", statement="c2 mpd config"), _claim("C-2", statement="c2 pegasus")]
    deps = _deps()
    ev_saturated = _evidence(fact_categories={"c2_config_extract": 3})
    ev_fresh = _evidence(fact_categories={"c2_config_extract": 0})
    out_sat = pr.priority_ratio(claims, deps, ev_saturated)
    out_fresh = pr.priority_ratio(claims, deps, ev_fresh)
    assert out_sat[0].novelty < out_fresh[0].novelty


# ---------- cost ----------

def test_cost_tier_penalty():
    """高 tier (深推/VM) → cost 大 → score 低。同 L/D/N 下 eta 高者排后。"""
    base = dict(statement="c2 config")
    claims = [_claim("C-cheap", eta=0, **base), _claim("C-deep", eta=2, **base)]
    deps = _deps()
    ev = _evidence()
    out = pr.priority_ratio(claims, deps, ev)
    by = {a.claim_id: a for a in out}
    assert by["C-cheap"].cost < by["C-deep"].cost
    assert by["C-cheap"].score >= by["C-deep"].score


# ---------- 纯函数 / 零 LLM ----------

def test_scoring_is_deterministic_pure():
    """同输入 → 同输出 (证明打分是纯机械, 无隐藏 LLM/状态)。"""
    claims = [_claim("C-1", statement="c2"), _claim("C-2", statement="家族 vidar")]
    deps = _deps(depends_on={"C-2": ["C-1"]})
    ev = _evidence()
    o1 = pr.priority_ratio(claims, deps, ev)
    o2 = pr.priority_ratio(claims, deps, ev)
    assert [a.to_dict() for a in o1] == [a.to_dict() for a in o2]


def test_c401_c402_not_tied_when_signals_differ():
    """回归: C-401(复查已强事实, L 低) vs C-402(解锁管线信任, L 高) 不应同分。"""
    c401 = _claim("C-401", statement="EP RVA byte recheck", eta=0)
    c402 = _claim("C-402", statement="reproduce re-runnability", eta=0)
    claims = [c401, c402, _claim("D-1"), _claim("D-2"), _claim("D-3")]
    deps = _deps(depends_on={"D-1": ["C-402"], "D-2": ["C-402"], "D-3": ["C-402"]})
    ev = _evidence()
    out = pr.priority_ratio(claims, deps, ev)
    by = {a.claim_id: a for a in out}
    assert by["C-402"].leverage > by["C-401"].leverage
    assert by["C-402"].score > by["C-401"].score
