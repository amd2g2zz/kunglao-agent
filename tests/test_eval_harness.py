"""tests/test_eval_harness.py — eval harness oracle 自检 (issue #4, plan §7).

RED: oracle 10/10 (确定性核心); 三臂配置; 故障注入骨架。
三臂 A/B/C 真实测量 deferred (需 #5/#6 完成后才有意义)。
"""
from __future__ import annotations

import kunglao_eval as ke


def test_oracle_selfcheck_10_10():
    """oracle 自检 10/10: 10 个已知答案例全过。"""
    results = ke.oracle_selfcheck()
    assert len(results) == 10, f"应有 10 个 oracle case, 实际 {len(results)}"
    failures = [r for r in results if not r["passed"]]
    assert not failures, f"oracle 失败: {[r['name'] + ': ' + r['reason'] for r in failures]}"


def test_oracle_cases_cover_core_behaviors():
    """oracle 覆盖核心行为 (leverage/discriminator/novelty/cost/dispatchable)。"""
    names = {r["name"] for r in ke.oracle_selfcheck()}
    must = [
        "terminal_leverage_zero", "downstream_leverage_high",
        "competitor_group_disc_top", "answers_question_disc_mid", "else_disc_floor",
        "tier_cost_penalty", "saturated_novelty_low", "fresh_novelty_high",
        "impossible_claim_excluded", "deterministic_pure",
    ]
    missing = [m for m in must if m not in names]
    assert not missing, f"oracle 缺 case: {missing}"


def test_arm_configs_defined():
    """三臂 A/B/C 配置存在且机制开关互斥。"""
    a = ke.ARM_CONFIGS["A"]
    b = ke.ARM_CONFIGS["B"]
    c = ke.ARM_CONFIGS["C"]
    assert a["mechanisms_enabled"] is True
    assert b["mechanisms_enabled"] is False
    assert c["single_agent"] is True


def test_arm_config_unknown_rejected():
    try:
        ke.run_arm("D")
        assert False, "未知 arm 应报错"
    except (ValueError, KeyError):
        pass


def test_fault_injection_types_defined():
    """五类故障注入类型定义 (plan §7)。"""
    for ftype in ("throttle", "implicit_fail", "explicit_fail", "impossible", "adversarial"):
        assert ftype in ke.FAULT_TYPES, f"缺故障类型: {ftype}"


def test_impossible_fault_detected():
    """impossible 故障: 无证据路径的 claim 被排除出 top_actions。"""
    result = ke.inject_fault("impossible")
    assert result["applied"] is True
    assert "no dispatchable path" in result["effect"].lower() or "excluded" in result["effect"].lower()
