#!/usr/bin/env python3
"""method_router.py — M1 DECIDE 方法路由 (module-design.md M1.2 L115-117 / M1.5 L160-164,
design-spec §6.5 L464-477, §6.7.1 L483-497).

纯机械 Dijkstra(heapq), **0 LLM 调用**(escalate 是输出信号, LLM 图生长由 orchestrator 接):

- 节点 = 方法(method-graph.yaml: nodes{id, skill, tier, alternatives[]}), 边 = edges{from, to, kind}
- tool_health{skill: "down"|"healthy"|"unknown"}: 仅 "down" 使 skill 不可用(其余含 unknown 可用)
- 节点可执行 ⇔ 主 skill 或任一 alternatives 可用; 选序: 主 skill 优先, 之后按 alternatives 顺序
- 起点可执行 → 直达路径
- 起点全挂 → Dijkstra: 可执行子图上沿出边(权重: 每边 1.0 + 终点 DONE 边权重 TIER_COST),
  输出 [起点(blocked), …, 可执行终点(带 skill)]
- 图断(无可达可执行节点)或节点缺失 → escalated=True + reason(M1.5 L162 "缺节点 → 视为图断 → escalate")

用法:
  python method_router.py <action_type> [--method-graph <path>] [--tool-health k=v,k2=v2]
"""
from __future__ import annotations

import argparse
import heapq
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = ROOT / "data" / "method-graph.yaml"

# DONE 边权重(终点成本): 越深越贵 — 与 priority_ratio 的 cost 语义互补
TIER_COST = {1: 1.0, 2: 2.0, 3: 4.0}
EDGE_KINDS = {"sequence", "alternative"}
DOWN = "down"


@dataclass(frozen=True)
class PathStep:
    """路径一步: 方法 + 选定 skill(起点被堵时为 None)+ tier."""

    method: str
    skill: str | None
    tier: int | None


@dataclass(frozen=True)
class RoutedPath:
    """路由结果: steps + escalate 信号 + llm_calls(恒 0 — 模块无 LLM 路径)."""

    steps: tuple[PathStep, ...] = ()
    escalated: bool = False
    reason: str = ""
    llm_calls: int = 0


def load_method_graph(path: Path) -> dict:
    """加载并校验 method-graph.yaml; 格式违规 → ValueError(显式错误处理)."""
    if not path.exists():
        raise FileNotFoundError(f"method-graph 不存在: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    nodes_raw = raw.get("nodes")
    edges_raw = raw.get("edges") or []
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise ValueError(f"method-graph.yaml: nodes 缺失或为空 ({path})")
    nodes: dict[str, dict] = {}
    for n in nodes_raw:
        if not isinstance(n, dict):
            raise ValueError(f"method-graph.yaml: 节点非法 {n!r}")
        # 环境节点(注册器产物, type=skill/mcp/script/tool)只需 id;
        # 方法节点(type=action)需 skill/tier/alternatives
        is_action = n.get("type") == "action"
        if is_action:
            for req in ("id", "skill", "tier", "alternatives"):
                if req not in n:
                    raise ValueError(f"method-graph.yaml: 节点缺字段 {req}: {n}")
            if n["tier"] not in (1, 2, 3):
                raise ValueError(f"method-graph.yaml: tier 非法 {n['tier']!r} (节点 {n.get('id')})")
            if not isinstance(n["alternatives"], list):
                raise ValueError(f"method-graph.yaml: alternatives 须为列表 (节点 {n.get('id')})")
        elif "id" not in n:
            raise ValueError(f"method-graph.yaml: 环境节点缺 id: {n}")
        nodes[n["id"]] = n
    for e in edges_raw:
        if not isinstance(e, dict) or e.get("from") not in nodes or e.get("to") not in nodes:
            raise ValueError(f"method-graph.yaml: edge 引用未知节点 {e!r}")
        if e.get("kind") not in EDGE_KINDS:
            raise ValueError(f"method-graph.yaml: edge kind 非法 {e!r}")
    return {"nodes": nodes, "edges": edges_raw, "_path": path}


def _skill_available(skill: str, tool_health: dict) -> bool:
    """仅显式 "down" 不可用(M1.5: VM 掉线显式标记)."""
    return tool_health.get(skill, "unknown") != DOWN


def _chosen_skill(node: dict, tool_health: dict) -> str | None:
    """选主 skill, 否则第一个健康替代; 全挂 → None."""
    for skill in [node["skill"]] + list(node.get("alternatives", [])):
        if _skill_available(skill, tool_health):
            return skill
    return None


def _reroute(start: str, nodes: dict, edges: list, tool_health: dict):
    """Dijkstra: 起点(全挂) → 最近可执行终点(沿出边, 只经可执行节点).

    权重: 每条边 1.0; 终点候选总权重 = dist + TIER_COST[tier](DONE 边)。
    返回 (路径方法 id 列表, 总权重) 或 (None, inf)。
    """
    chosen = {nid: _chosen_skill(n, tool_health) for nid, n in nodes.items()}
    executable = {nid for nid, s in chosen.items() if s is not None}
    adj: dict[str, list[str]] = {nid: [] for nid in nodes}
    for e in edges:
        adj.setdefault(e["from"], []).append(e["to"])

    dist: dict[str, float] = {start: 0.0}
    prev: dict[str, str] = {}
    heap: list[tuple[float, str]] = [(0.0, start)]
    visited: set[str] = set()
    best: tuple[float, str] | None = None  # (总权重, 终点)

    while heap:
        d, cur = heapq.heappop(heap)
        if cur in visited:
            continue
        visited.add(cur)
        if cur in executable and cur != start:
            total = d + TIER_COST.get(nodes[cur]["tier"], 4.0)
            if best is None or total < best[0]:
                best = (total, cur)
        for nxt in adj.get(cur, []):
            if nxt == start or nxt not in executable:  # 非可执行节点不可通行(出边∞)
                continue
            nd = d + 1.0
            if nd < dist.get(nxt, float("inf")):
                dist[nxt] = nd
                prev[nxt] = cur
                heapq.heappush(heap, (nd, nxt))

    if best is None:
        return None, float("inf")
    # 重建路径: start → ... → 终点
    chain = [best[1]]
    cur = best[1]
    while cur in prev and prev[cur] != start:
        cur = prev[cur]
        chain.append(cur)
    chain.append(start)
    chain.reverse()
    return chain, best[0]


def method_router(action_type: str, method_graph: dict,
                  tool_health: dict | None = None) -> RoutedPath:
    """Dijkstra 选路径; 失败 → 出边∞ → 重算换替代; 图断/缺节点 → escalate(0 LLM)."""
    th = tool_health or {}
    nodes = method_graph["nodes"]
    edges = method_graph.get("edges", [])
    node = nodes.get(action_type)
    if node is None:
        return RoutedPath(
            steps=(), escalated=True,
            reason=f"method-graph 缺节点 {action_type!r} — 视为图断, 需 LLM 图生长 (本模块 0 LLM)",
            llm_calls=0,
        )
    primary = _chosen_skill(node, th)
    if primary is not None:
        return RoutedPath(
            steps=(PathStep(node["id"], primary, node["tier"]),),
            escalated=False, reason="", llm_calls=0,
        )
    chain, total = _reroute(action_type, nodes, edges, th)
    if chain is None:
        return RoutedPath(
            steps=(), escalated=True,
            reason=f"图断: {action_type!r} 全部工具不可用且无替代路径 — 需 LLM 图生长 (本模块 0 LLM)",
            llm_calls=0,
        )
    chosen = {nid: _chosen_skill(n, th) for nid, n in nodes.items()}
    steps = [
        PathStep(mid, None if mid == action_type else chosen[mid], nodes[mid]["tier"])
        for mid in chain
    ]
    return RoutedPath(
        steps=tuple(steps), escalated=False,
        reason=f"主路径工具不可用, Dijkstra 重路由至 {chain[-1]} (总成本 {total:.1f})",
        llm_calls=0,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="kunglao-agent M1 method_router (0 LLM, Dijkstra)")
    ap.add_argument("action_type", help="method-graph.yaml 节点 id")
    ap.add_argument("--method-graph", default=str(DEFAULT_GRAPH))
    ap.add_argument("--tool-health", default="", help="skill=down[,skill=down...]")
    args = ap.parse_args(argv)
    tool_health = {}
    for pair in args.tool_health.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            tool_health[k.strip()] = v.strip()
    graph = load_method_graph(Path(args.method_graph))
    p = method_router(args.action_type, graph, tool_health)
    print(f"escalated={p.escalated} llm_calls={p.llm_calls} reason={p.reason!r}")
    for s in p.steps:
        print(f"  {s.method} -> skill={s.skill!r} (T{s.tier})")
    return 2 if p.escalated else 0


if __name__ == "__main__":
    sys.exit(main())
