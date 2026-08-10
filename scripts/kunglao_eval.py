#!/usr/bin/env python3
"""kunglao_eval.py — eval harness module (issue #4, plan §7, design-spec §6.7.6).

确定性核心: oracle 10/10 自检。三臂 A/B/C 配置 + 五类故障注入; 真实测量 deferred。
CLI 入口: scripts/kunglao-eval.py (薄包装)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import priority_ratio as pr

ARM_CONFIGS = {
    "A": {"mechanisms_enabled": True, "single_agent": False,
          "desc": "所有重构机制全开 (priority_ratio VoI + gates + digest + verify)"},
    "B": {"mechanisms_enabled": False, "single_agent": False,
          "desc": "全关基线 (legacy 加法权重 + 无 gate) — 对照"},
    "C": {"mechanisms_enabled": False, "single_agent": True,
          "desc": "单 agent 无编排 (直接 LLM 跑) — 下界对照"},
}

FAULT_TYPES = {
    "throttle": {"desc": "限流: 工具调用配额耗尽 → orchestrator 须换路"},
    "implicit_fail": {"desc": "隐式失败: 工具返回空/错误但无异常 → 须识别非结论"},
    "explicit_fail": {"desc": "显式失败: 工具抛异常 → 须 failure_analysis 不重派"},
    "impossible": {"desc": "不可能: claim 无证据路径 → 须排除出 top_actions"},
    "adversarial": {"desc": "对抗: 诱饵串/反分析 → 须识别非 benign 也非真 IOC"},
}


def run_arm(arm: str) -> dict:
    if arm not in ARM_CONFIGS:
        raise ValueError(f"未知 arm: {arm}; 合法: {list(ARM_CONFIGS)}")
    return ARM_CONFIGS[arm]


def inject_fault(ftype: str) -> dict:
    if ftype not in FAULT_TYPES:
        raise ValueError(f"未知故障类型: {ftype}; 合法: {list(FAULT_TYPES)}")
    applied = True
    if ftype == "impossible":
        claims = [{"id": "IMP", "status": "OPEN", "statement": "impossible claim"}]
        deps = {"depends_on": {"IMP": ["BLOCKED-FOREVER"]}}
        out = pr.priority_ratio(claims, deps, pr.EvidenceView())
        applied = len(out) == 0
        effect = "impossible claim excluded from top_actions (no dispatchable path)"
    else:
        effect = FAULT_TYPES[ftype]["desc"] + " (scaffold — 真实注入 deferred)"
    return {"type": ftype, "applied": applied, "effect": effect}


def _C(cid, **kw):
    c = {"id": cid, "status": "OPEN", "evidence_tier_attempted": 0,
         "promotion_attempts": 0, "statement": cid}
    c.update(kw)
    return c


def oracle_selfcheck() -> list[dict]:
    results = []
    def check(name, cond, reason):
        results.append({"name": name, "passed": bool(cond), "reason": reason if not cond else "ok"})

    out = pr.priority_ratio([_C("C-1"), _C("C-2")], {"depends_on": {"C-2": ["C-1"]}},
                            pr.EvidenceView(terminal_fact_claims=frozenset({"C-1"})))
    by = {a.claim_id: a for a in out}
    check("terminal_leverage_zero", by["C-1"].leverage == 0.0, f"L={by['C-1'].leverage}")

    out = pr.priority_ratio([_C("HUB"), _C("LA"), _C("LB"), _C("ORPH")],
                            {"depends_on": {"LA": ["HUB"], "LB": ["HUB"]}}, pr.EvidenceView())
    by = {a.claim_id: a for a in out}
    check("downstream_leverage_high", by["HUB"].leverage > by["ORPH"].leverage,
          f"HUB={by['HUB'].leverage} ORPH={by['ORPH'].leverage}")

    out = pr.priority_ratio([_C("CA", competitor_group="q1"), _C("CB", competitor_group="q1")],
                            {"competitor_groups": {"q1": ["CA", "CB"]}}, pr.EvidenceView())
    by = {a.claim_id: a for a in out}
    check("competitor_group_disc_top", by["CA"].discriminator == 1.0, f"D={by['CA'].discriminator}")

    out = pr.priority_ratio([_C("C", answers_question="q")], {}, pr.EvidenceView())
    check("answers_question_disc_mid", out[0].discriminator == 0.5, f"D={out[0].discriminator}")

    out = pr.priority_ratio([_C("C")], {}, pr.EvidenceView())
    check("else_disc_floor", out[0].discriminator == 0.2, f"D={out[0].discriminator}")

    out = pr.priority_ratio([_C("CHEAP", evidence_tier_attempted=0), _C("DEEP", evidence_tier_attempted=2)],
                            {}, pr.EvidenceView())
    by = {a.claim_id: a for a in out}
    check("tier_cost_penalty", by["CHEAP"].cost < by["DEEP"].cost,
          f"CHEAP={by['CHEAP'].cost} DEEP={by['DEEP'].cost}")

    claims = [_C("C1", statement="c2 mpd"), _C("C2", statement="c2 pegasus")]
    o_sat = pr.priority_ratio(claims, {}, pr.EvidenceView(fact_count_by_category={"c2_config_extract": 3}))
    o_fr = pr.priority_ratio(claims, {}, pr.EvidenceView(fact_count_by_category={"c2_config_extract": 0}))
    check("saturated_novelty_low", o_sat[0].novelty < o_fr[0].novelty,
          f"sat={o_sat[0].novelty} fresh={o_fr[0].novelty}")
    check("fresh_novelty_high", o_fr[0].novelty == 1.0, f"N={o_fr[0].novelty}")

    out = pr.priority_ratio([_C("IMP")], {"depends_on": {"IMP": ["MISSING"]}}, pr.EvidenceView())
    check("impossible_claim_excluded", len(out) == 0, f"got {len(out)} actions")

    claims = [_C("A", statement="c2"), _C("B", statement="家族 vidar")]
    deps = {"depends_on": {"B": ["A"]}}
    o1 = pr.priority_ratio(claims, deps, pr.EvidenceView())
    o2 = pr.priority_ratio(claims, deps, pr.EvidenceView())
    check("deterministic_pure",
          [a.to_dict() for a in o1] == [a.to_dict() for a in o2], "two runs differ")

    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kunglao-eval.py", description="eval harness")
    ap.add_argument("--oracle-selfcheck", action="store_true")
    ap.add_argument("--arm", default=None, choices=list(ARM_CONFIGS))
    ap.add_argument("--inject", default=None, choices=list(FAULT_TYPES))
    args = ap.parse_args(argv)
    if args.oracle_selfcheck:
        results = oracle_selfcheck()
        passed = sum(r["passed"] for r in results)
        print(f"oracle selfcheck: {passed}/{len(results)}")
        for r in results:
            mark = "OK" if r["passed"] else "FAIL"
            print(f"  [{mark}] {r['name']}: {r['reason']}")
        return 0 if passed == len(results) else 1
    if args.arm:
        print(f"arm {args.arm}: {run_arm(args.arm)}"); return 0
    if args.inject:
        print(inject_fault(args.inject)); return 0
    ap.print_help(); return 0


if __name__ == "__main__":
    sys.exit(main())
