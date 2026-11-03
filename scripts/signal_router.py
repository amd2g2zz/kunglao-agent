# -*- coding: utf-8 -*-
"""signal_router.py — 本卡 用户信号意图路由器（信号面）。

生产实证（本卡）：46 行 user_signal 里 45 行 classified_by=fallback
route=unrouted，1 行真实指令被 keyword 劫走——"我不是要续跑，是要开一个
新的研究方向" 落进 前置信号卡 的 factual/fix（"不是" 关键字），用户被迫重述。
本模块是那 46 行的去处：前置信号卡 本体层留在 unrouted/meta 的信号，在持久化
之前先过意图路由。

六类意图 → 动作路由（动作与统一模型的 commit 动作空间对齐，
rlvr/episode_schema.COMMIT_ACTIONS = select/persist/tune/switch/verify/
deliver；新方向 = switch = 新 episode）：

    continuation   → action=continue      commit=persist（同 episode）
    new_direction  → action=new_direction commit=switch（新 episode）
    pause          → action=pause         commit=None（非提交算子，
                                            operator 面先于 commit 菜单）
    clarify        → action=clarify       commit=None（ask_back 算子）
    status_query   → route_target=narration（本卡 状态叙事面）
    connectivity   → route_target=env（环境/连通性，env-repair 面）

否定转折先行（pivot pre-pass）：「不是要X，是要Y」→ 只用 Y 分类——
生产误路由钉就钉在这条形态上。全类 miss → fallback（intent=None），
一级兜底语义不变（仍落账，分错不丢信号）。

零存储：路由字段由调用方（user_signal）持久化；遥测 route_health 只读
runs/user-signals。发点：signal_routed（event_taxonomy.EMIT_ACTIONS 在
册）由 user_signal 发（单发点纪律）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

#: 钉死的 unrouted 率阈值（策略常数，非拟合）：路由器上线后，落账信号里
#: 拿不到动作路由的占比必须低于此线（遥测 route_health.ok）。
MAX_UNROUTED_RATE = 0.50

SIGNALS_DIR = Path("runs") / "user-signals"

#: 意图 → (action, commit_action, new_episode, route_target)
#: commit_action ∈ rlvr/episode_schema.COMMIT_ACTIONS；None = 非提交算子。
INTENT_ACTIONS: dict[str, tuple[str, str | None, bool, str | None]] = {
    "continuation": ("continue", "persist", False, None),
    "new_direction": ("new_direction", "switch", True, None),
    "pause": ("pause", None, False, None),
    "clarify": ("clarify", None, False, None),
    "status_query": ("status", None, False, "narration"),
    "connectivity": ("env_check", None, False, "env"),
}

#: 扫描优先序（生产形态：新方向 > 暂停 > 继续 > 澄清 > 状态 > 连通性；
#: 「别续跑了，换个新方向」必须赢在 new_direction）
_SCAN_ORDER = ("new_direction", "pause", "continuation", "clarify",
               "status_query", "connectivity")

#: 否定转折：「不是要X，是要Y」→ 后半句 Y 是真意图（生产误路由形态）。
_PIVOT_SPLIT_RE = re.compile(r"[，,；;。！？!?]")
_NEG_MARKERS = ("不是", "并非", "不想", "不要", "别想", "无需")

#: 关键词表（生产实证词形：本卡 issue 四类 + 生产 46 行 + 座舱三问）
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "new_direction": (
        "新的研究方向", "新方向", "新的方向", "开一个新的", "开个新的",
        "换个方向", "换方向", "换一条", "另起", "换个思路", "新路线",
        "new direction", "pivot"),
    "pause": (
        "暂停", "先停", "停一下", "停下", "别跑了", "挂起",
        "pause", "hold on"),
    "continuation": (
        "继续", "接着", "续跑", "往下", "跑下去", "go on",
        "continue", "keep going"),
    "clarify": (
        "澄清", "说清楚", "没说清", "什么意思", "说明白", "再描述",
        "补充一下", "clarify"),
    "status_query": (
        "什么情况", "什么状态", "现在是什么", "进展如何", "进展怎样",
        "介绍一下", "分析结果", "到哪了", "跑到哪", "怎么样了", "什么地步",
        # 座舱三问（生产 how-to 形态）→ 叙事面的 next/how 要素回答
        "进入下一步", "下一步怎么", "怎么开", "如何开", "用什么命令",
        "什么命令", "status"),
    "connectivity": (
        "网络不通", "连不上", "无法连接", "断网", "网络断", "vm 连接",
        "ssh 连", "connect", "network down"),
}


# ---------- 分类 ----------

def _post_pivot(text: str) -> str | None:
    """「不是要X，是要Y」→ 返回 Y（转折后半段）。无转折 → None。"""
    clauses = [c.strip() for c in _PIVOT_SPLIT_RE.split(text) if c.strip()]
    for i, clause in enumerate(clauses[:-1]):
        if any(m in clause for m in _NEG_MARKERS):
            rest = "".join(clauses[i + 1:])
            return rest or None
    return None


def _scan(text: str) -> tuple[str, str] | tuple[None, None]:
    """按优先序扫关键词表；(intent, matched_keyword) 或 (None, None)。"""
    low = text.lower()
    for intent in _SCAN_ORDER:
        for kw in _KEYWORDS[intent]:
            if kw in low or kw in text:
                return intent, kw
    return None, None


def classify_intent(text: str) -> dict:
    """意图分类（只路由，不做使用资格过滤）。classified_by ∈
    {pivot, keyword, fallback}；fallback = 无意图（intent=None）——
    调用方仍落账（一级兜底不变）。"""
    text = str(text)
    pivot = _post_pivot(text)
    if pivot:
        intent, kw = _scan(pivot)
        if intent:
            return _result(intent, "pivot")
    intent, kw = _scan(text)
    if intent:
        return _result(intent, "keyword")
    return {"intent": None, "classified_by": "fallback", "action": None,
            "commit_action": None, "new_episode": False,
            "route_target": None}


def _result(intent: str, classified_by: str) -> dict:
    action, commit, new_episode, target = INTENT_ACTIONS[intent]
    return {"intent": intent, "classified_by": classified_by,
            "action": action, "commit_action": commit,
            "new_episode": new_episode, "route_target": target}


# ---------- 遥测（只读） ----------

def route_health(ws) -> dict:
    """unrouted 率遥测：落账信号里拿不到任何动作路由的占比。
    routed = 本体层已路由（route != unrouted）或意图层拿到动作（intent）。
    只读；total=0 时 rate=0.0、ok=True（无信号不是失守）。"""
    d = Path(ws) / SIGNALS_DIR
    total = routed = 0
    if d.is_dir():
        for p in sorted(d.glob("sig-*.json")):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            total += 1
            if rec.get("intent") or rec.get("route") not in (None, "unrouted"):
                routed += 1
    unrouted = total - routed
    rate = (unrouted / total) if total else 0.0
    return {"total": total, "routed": routed, "unrouted": unrouted,
            "rate": round(rate, 4), "threshold": MAX_UNROUTED_RATE,
            "ok": rate <= MAX_UNROUTED_RATE}


# ---------- CLI（遥测查询面） ----------

def main(argv: list[str] | None = None) -> int:
    """`--health <ws>`：unrouted 率遥测（JSON 一行）。
    exit 0 = rate 落在钉死阈值内；exit 1 = 见红（路由器失守，查
    runs/user-signals/ 里 intent 为空的记录形态）。"""
    import argparse

    ap = argparse.ArgumentParser(
        description="signal router — 意图路由（本卡）；--health 查遥测")
    ap.add_argument("--health", metavar="WS",
                    help="workspace root；打印 route_health JSON")
    args = ap.parse_args(argv)
    if not args.health:
        ap.error("nothing to do: pass --health <ws>")
    health = route_health(args.health)
    print(json.dumps(health, ensure_ascii=False, sort_keys=True))
    return 0 if health["ok"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
