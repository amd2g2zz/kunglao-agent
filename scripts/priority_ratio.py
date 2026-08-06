#!/usr/bin/env python3
"""priority_ratio.py — M1 DECIDE 比值键动作排序 (design-spec §3.2 / module-design.md M1.2).

与 priority.py(加法权重, legacy, 留给旧消费者)不同, 本模块实现"比值键":
  score(a) = [0.35·Δdisc(a) + 0.35·E_unlock(a) + 0.10·unc(a)] / cost(a)

分量(契约空白, specs/phase-4/contract.md §1):
  Δdisc(a)     = marginal_discriminator: claim 已有 terminal fact → 0.0(已得证据去重), 否则 1.0
  E_unlock(a)  = leverage_v2(传递闭包 sigmoid+gateway, [0,1]) × P(success=1/(1+attempts))
  unc(a)       = freshness = 1/(1+attempts)
  cost(a)      = NEXT_TIER_CHEAP[evidence_tier_attempted]  (与 priority.py L44 同源常量;
                 字面照抄 design-spec L142-143 — 高 eta 的 claim 比值放大, 鼓励深推)

用法:
  python priority_ratio.py <workspace> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

try:
    from priority import NEXT_TIER_CHEAP, _leverage_v2  # 单源常量与传递闭包(不修改)
except ImportError:  # 独立运行兜底: 与 priority.py L44 等值
    NEXT_TIER_CHEAP = {0: 1.0, 1: 0.5, 2: 0.2}

    def _leverage_v2(cid, depends_on, by_id, open_set):  # pragma: no cover
        raise NotImplementedError("priority.py 不可导入时 leverage_v2 不可用")

TERMINAL = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED"}
WEIGHTS = {"disc": 0.35, "unlock": 0.35, "unc": 0.10}


@dataclass(frozen=True)
class EvidenceView:
    """证据视图(facts/_INDEX 派生, 不可变)."""

    terminal_fact_claims: frozenset[str] = frozenset()
    verified_fact_count: int = 0
    raw_lines: tuple[str, ...] = ()

    @classmethod
    def from_workspace(cls, ws: Path) -> "EvidenceView":
        """解析 facts/_INDEX.md 行 "F<id> | <status> | <claim_id> | <conclusion>".

        兼容 fixture 布局: 无 facts/ 目录时回退读 <ws>/_INDEX.md(评估快照扁平化放置).

        terminal_fact_claims: 状态含 TERMINAL 任一 token 的 fact 所引用的 claim;
        verified_fact_count:  状态含 PROVEN/VERIFIED 的 fact 数(explore_gate 输入).
        """
        index = ws / "facts" / "_INDEX.md"
        if not index.exists():  # fixture 布局回退
            index = ws / "_INDEX.md"
        if not index.exists():
            return cls()
        lines = tuple(
            ln for ln in index.read_text(encoding="utf-8", errors="replace").splitlines()
            if "|" in ln
        )
        terminal_claims: set[str] = set()
        verified = 0
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            status, claim_id = parts[1].upper(), parts[2]
            if any(t in status for t in TERMINAL):
                terminal_claims.add(claim_id)
            if "PROVEN" in status or "VERIFIED" in status:
                verified += 1
        return cls(frozenset(terminal_claims), verified, lines)


@dataclass(frozen=True)
class Action:
    """可派发动作(M1.3 top_actions 的评分形态; skill 由 method_router 填充)."""

    claim_id: str
    action: str
    score: float
    skill: str | None
    tier: int
    attempts: int
    delta_disc: float
    expected_unlock: float
    unc: float
    cost: float

    def to_dict(self) -> dict:
        return {"claim_id": self.claim_id, "action": self.action,
                "score": round(self.score, 3), "skill": self.skill}


def is_open(claim: dict) -> bool:
    """非 terminal 且非 IN_PROGRESS(与 priority.py L60-64 同规则)."""
    return claim.get("status") not in TERMINAL and claim.get("status") != "IN_PROGRESS"


def freshness(attempts: int) -> float:
    """unc = 1/(1+attempts): 尝试越少越新鲜."""
    return 1.0 / (1.0 + max(0, attempts))


def marginal_discriminator(claim_id: str, evidence: EvidenceView) -> float:
    """对已得证据去重: claim 已有 terminal fact → 0.0(已区分), 否则 1.0."""
    return 0.0 if claim_id in evidence.terminal_fact_claims else 1.0


def expected_unlock(claim_id: str, depends_on: dict, by_id: dict, open_ids: set) -> float:
    """E_unlock = leverage_v2 传递闭包([0,1], priority._leverage_v2) × P(success=1/(1+attempts))."""
    lev, _direct, _trans = _leverage_v2(claim_id, depends_on, by_id, open_ids)
    p_success = freshness(int(by_id.get(claim_id, {}).get("promotion_attempts", 0)))
    return lev * p_success


# 关键词分类器(契约空白): 类别 ↔ design-spec §6.5 方法 + E4.1 设计价值序
_KEYWORD_MAP: list[tuple[tuple[str, ...], str]] = [
    (("c2", "mpd", "pegasus", "dead-drop", "dead drop", "c2 配置"), "c2_config_extract"),
    (("命令表", "command table", "命令分发"), "command_table"),
    (("协议", "protocol", "runtime 行为", "network io", "网络"), "protocol_restore"),
    (("持久化", "persistence", "autorun", "注册表"), "persistence"),
    (("注入", "injection", "reflective", "createremotethread"), "injection"),
    (("反分析", "anti-analysis", "anti analysis", "garble", "诱饵", "decoy", "cff", "混淆"), "anti_analysis"),
    (("家族", "family", "归属", "vidar", "wingo", "gsb"), "family_attribution"),
]
DEFAULT_ACTION = "evidence_collection"


def classify_action(claim: dict) -> str:
    """statement + answers_question 关键词 → 动作类型; 未命中 → evidence_collection.

    计分制(修正 2026-08-06 in-session): 每个类别累计命中关键词次数, 取最高分;
    平局按 _KEYWORD_MAP 顺序(类别优先序)。防 incidental 关键词误分类——
    例: C-201 "家族归属 ... garble-obfuscated ..." 含 garble, 但 family 命中 5 次
    (家族/归属/vidar/wingo/gsb) > anti_analysis 1 次(garble) → family_attribution。
    """
    text = " ".join([
        str(claim.get("statement", "")),
        str(claim.get("answers_question", "")),
    ]).lower()
    best, best_score = DEFAULT_ACTION, 0
    for keywords, action in _KEYWORD_MAP:
        score = sum(text.count(k) for k in keywords)
        if score > best_score:
            best, best_score = action, score
    return best


def next_tier_cost(claim: dict) -> float:
    """cost = NEXT_TIER_CHEAP[evidence_tier_attempted], 越界 0.1."""
    eta = int(claim.get("evidence_tier_attempted", 0))
    return float(NEXT_TIER_CHEAP.get(eta, 0.1))


def priority_ratio(claims: list[dict], deps: dict, evidence: EvidenceView) -> list[Action]:
    """比值键排序(design-spec §3.2 步骤 2-4; 探索阶段由 explore_gate 另行判定).

    dispatchable: 非 terminal / attempts<3 / depends_on 全部 terminal / 非 failure-blocked
    (failure-blocked 过滤由调用方做 — 签名无 ws, 纯函数可测).
    """
    by_id = {c.get("id"): c for c in claims if c.get("id")}
    depends_on = (deps or {}).get("depends_on", {}) or {}
    open_ids = {cid for cid, c in by_id.items() if is_open(c)}
    terminal_ids = {cid for cid, c in by_id.items() if not is_open(c)}

    actions: list[Action] = []
    for c in claims:
        cid = c.get("id")
        if not cid or not is_open(c):
            continue
        if int(c.get("promotion_attempts", 0)) >= 3:
            continue
        parents = depends_on.get(cid, []) or []
        if any(p not in terminal_ids for p in parents):
            continue
        disc = marginal_discriminator(cid, evidence)
        e_unlock = expected_unlock(cid, depends_on, by_id, open_ids)
        unc = freshness(int(c.get("promotion_attempts", 0)))
        cost = next_tier_cost(c)
        value = WEIGHTS["disc"] * disc + WEIGHTS["unlock"] * e_unlock + WEIGHTS["unc"] * unc
        actions.append(Action(
            claim_id=cid,
            action=classify_action(c),
            score=value / cost,
            skill=None,
            tier=min(int(c.get("evidence_tier_attempted", 0)) + 1, 3),
            attempts=int(c.get("promotion_attempts", 0)),
            delta_disc=disc,
            expected_unlock=e_unlock,
            unc=unc,
            cost=cost,
        ))
    actions.sort(key=lambda a: a.score, reverse=True)
    return actions


def _resolve_ws(arg: str | None) -> Path:
    if arg:
        return Path(arg)
    cwd = Path.cwd()
    sub = cwd / "malware-analysis-workspace"
    return sub if (sub / "claim-register.yaml").exists() else cwd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="kunglao-agent M1 priority_ratio 比值键排序")
    ap.add_argument("workspace", nargs="?", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    ws = _resolve_ws(args.workspace)
    reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
    deps = yaml.safe_load((ws / "claim_deps.yaml").read_text(encoding="utf-8")) or {}
    evidence = EvidenceView.from_workspace(ws)
    actions = priority_ratio(reg.get("claims") or [], deps, evidence)
    if args.json:
        print(json.dumps({
            "workspace": str(ws),
            "verified_fact_count": evidence.verified_fact_count,
            "n_dispatchable": len(actions),
            "actions": [a.to_dict() | {"tier": a.tier, "delta_disc": round(a.delta_disc, 3),
                                        "expected_unlock": round(a.expected_unlock, 3),
                                        "unc": round(a.unc, 3), "cost": a.cost}
                        for a in actions],
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"priority_ratio (verified facts: {evidence.verified_fact_count}, dispatchable: {len(actions)})")
    for i, a in enumerate(actions, 1):
        print(f"  {i:>2} {a.claim_id:<6} {a.action:<22} score={a.score:6.3f} "
              f"disc={a.delta_disc:.2f} unlock={a.expected_unlock:.2f} unc={a.unc:.2f} cost={a.cost:.2f} T{a.tier}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
