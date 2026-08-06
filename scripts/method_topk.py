#!/usr/bin/env python3
"""method_topk.py — 任务感知 top-k 方法排序(方法路由的"选方法"层).

流水线: 任务 → topk_methods(选方法) → method_router.py(Dijkstra 规划执行) → 执行 → top-1 失败降级 top-2。

与 method_router.py 的分工:
- method_router: 给定 action_type, 在 method-graph 上 Dijkstra 找可达路径(节点=方法, 边=替代/衔接)。
- method_topk: 给定自由文本任务描述, 对 method-graph 节点打分排序 — 先"选哪几个方法",
  再交给 Dijkstra 规划"怎么执行"。top-1 失败时调用方直接用 top-2(自带降级, 不需重路由)。

评分: score(method) = 域匹配度 × 本地可用性 × tier 价值因子
  1. 任务 → 领域标签(DOMAIN_RULES 规则表; 未命中 → 任务自身 token 兜底; 空 → [unknown])
  2. 域匹配度: node.keywords ∩ 领域标签 — 直接命中 0.9 / 子串部分 0.5
  3. 可用性: present=False 或 type 无对应 → 0 分且不进 top-k(本地没有的工具不能选)
  4. 研究升顶: 任务域所需类目无任何本地可用工具 → research 类节点(anysearch/search/web)升到第一
  5. tier 价值因子: tier 越低(便宜)权重略高 {1: 1.0, 2: 0.8, 3: 0.6}

幂等稳定: 无随机、排序键确定(-score, tier, id) → 同输入同输出。

用法:
  python method_topk.py "分析 JNI 程序" [--method-graph <path>] [--k 3]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRAPH = ROOT / "data" / "method-graph.yaml"

# ---- 评分常量(契约空白决策, 见 specs/phase-4/contract.md §6) ----
DIRECT_HIT = 0.9        # 关键词 == 领域标签
PARTIAL_HIT = 0.5       # 关键词与标签互为子串(且长度 ≥ MIN_PARTIAL_LEN)
MIN_PARTIAL_LEN = 3
TIER_FACTOR = {1: 1.0, 2: 0.8, 3: 0.6}   # 便宜的工具权重略高
DEFAULT_TIER = 2
DEFAULT_TIER_FACTOR = 0.8
RESEARCH_BUMP = 10.0    # 研究升顶得分: 恒大于任何正常域匹配分(上限 3.6 = 4×0.9×1.0)
ALLOWED_TYPES = frozenset({"skill", "mcp", "tool", "script"})   # type 无对应(未知类型)→ 不可用; script=注册器本地脚本节点
RESEARCH_KEYWORDS = frozenset({"search", "web", "research", "docs"})

# ---- 任务 → 领域标签规则表(触发词为小写子串匹配; 命中任一 → 并入对应标签集) ----
DOMAIN_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("jni", "java", "android", "dex", "smali", "apk"), ("java", "android", "native", "dex")),
    (("c2", "command and control", "命令控制"), ("network", "static")),
    (("混淆", "obfuscation", "garble", "ollvm", "cff", "诱饵", "decoy"), ("obfuscation", "static")),
    (("反编译", "decompil", "逆向", "re"), ("static", "re")),
    (("动态", "runtime", "运行行为", "运行时"), ("dynamic", "runtime")),
    (("调试", "debug", "单步"), ("debug", "dynamic")),
    (("网络", "流量", "network", "packet", "抓包", "sniff"), ("network", "protocol")),
    (("注入", "injection", "线程创建"), ("injection", "dynamic")),
    (("持久化", "persistence", "注册表", "autorun", "启动项"), ("persistence", "registry")),
    (("加密", "解密", "crypto", "aes", "rc4", "xor"), ("crypto", "static")),
    (("字符串", "strings", "floss"), ("strings", "static")),
    (("内存", "memory", "dump", "转储"), ("memory", "forensics")),
    (("协议", "protocol"), ("protocol", "network")),
    (("恶意", "malware", "病毒", "样本", "木马"), ("malware", "static")),
    (("取证", "forensic", "volatility", "memdump"), ("forensics", "memory")),
    (("反沙箱", "anti-sandbox", "anti_vm", "反vm"), ("anti_analysis", "sandbox")),
)

_STOPWORDS = frozenset({"分析", "程序", "交叉", "使用", "进行", "一个", "以及", "并且", "的", "与", "和", "并", "程序集"})
_TOKEN_SPLIT = re.compile(r"[\s,，。;；:：/\\()（）\[\]{}]+")


# ---------- 图装载 ----------

def _normalize_nodes(method_graph) -> tuple[dict, ...]:
    """method_graph → 节点元组(不可变). 接受 Path(yaml) 或 dict{nodes: [...]}/{nodes: {id: ...}}."""
    if isinstance(method_graph, Path):
        if not method_graph.exists():
            raise FileNotFoundError(f"method-graph 不存在: {method_graph}")
        raw = yaml.safe_load(method_graph.read_text(encoding="utf-8")) or {}
    elif isinstance(method_graph, dict):
        raw = method_graph
    else:
        raise TypeError(f"method_graph 须为 Path 或 dict, 实际 {type(method_graph).__name__}")
    nodes_raw = raw.get("nodes")
    if isinstance(nodes_raw, dict):
        nodes_raw = list(nodes_raw.values())
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise ValueError(f"method-graph: nodes 缺失或为空 ({method_graph})")
    return tuple(_normalize_node(n) for n in nodes_raw)


def _normalize_node(node) -> dict:
    """单节点规范化: 必填 id; keywords/present/tier/type 缺省补齐; 非法 → ValueError."""
    if not isinstance(node, dict):
        raise ValueError(f"method-graph: 节点非法 {node!r}")
    if not node.get("id"):
        raise ValueError(f"method-graph: 节点缺 id: {node!r}")
    keywords = node.get("keywords") or []
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        raise ValueError(f"method-graph: 节点 {node['id']!r} keywords 须为字符串列表")
    return {
        "id": node["id"],
        "type": node.get("type", "skill"),
        "keywords": tuple(k.lower() for k in keywords),
        "tier": node.get("tier", DEFAULT_TIER),
        "present": node.get("present", True),
    }


# ---------- 任务 → 领域标签 ----------

def _task_tokens(task_desc: str) -> tuple[str, ...]:
    """任务描述分词: 按标点/空白切分, 去停用词, 小写, 去重, 排序(确定性)."""
    tokens = {t.lower() for t in _TOKEN_SPLIT.split(task_desc) if t and t.lower() not in _STOPWORDS}
    return tuple(sorted(tokens))


def _rule_labels(task_desc: str) -> tuple[str, ...]:
    """规则表匹配: 任一触发词出现在任务描述(小写子串) → 并入该规则标签集."""
    text = task_desc.lower()
    labels: set[str] = set()
    for triggers, labelset in DOMAIN_RULES:
        if any(t in text for t in triggers):
            labels.update(labelset)
    return tuple(sorted(labels))


def _domain_labels(task_desc: str) -> tuple[str, ...]:
    """领域标签 = 规则表命中 ∪ 任务自身 token(兜底); 两者皆空 → [unknown]."""
    if not isinstance(task_desc, str):
        raise TypeError(f"task_desc 须为 str, 实际 {type(task_desc).__name__}")
    labels = set(_rule_labels(task_desc)) | set(_task_tokens(task_desc))
    if not labels:
        labels = {"unknown"}
    return tuple(sorted(labels))


# ---------- 节点评分 ----------

def _match_score(keywords: tuple[str, ...], labels: tuple[str, ...]) -> tuple[float, tuple[str, ...]]:
    """域匹配度: 直接命中 0.9 / 部分(互为子串, len≥3) 0.5, 累加. 返回 (score, 命中标签)."""
    score = 0.0
    hits: list[str] = []
    for kw in keywords:
        for lab in labels:
            if kw == lab:
                score += DIRECT_HIT
                hits.append(lab)
            elif len(kw) >= MIN_PARTIAL_LEN and len(lab) >= MIN_PARTIAL_LEN \
                    and (kw in lab or lab in kw):
                score += PARTIAL_HIT
                hits.append(f"{kw}~{lab}")
    return round(score, 3), tuple(hits)


def _is_available(node: dict) -> bool:
    """本地可用性: present=False 或 type 无对应(未知类型)→ 不可选."""
    if node["present"] is False:
        return False
    return node["type"] in ALLOWED_TYPES


def _is_research(node: dict) -> bool:
    """research 类节点: keywords 含 search/web/research/docs 或 id 含 search."""
    if RESEARCH_KEYWORDS & set(node["keywords"]):
        return True
    return "search" in node["id"].lower()


def _tier_factor(tier) -> float:
    """tier 价值因子: 便宜(tier 低)权重高; 未知 tier → 0.8(确定性)."""
    return TIER_FACTOR.get(tier, DEFAULT_TIER_FACTOR)


def _reason(node: dict, labels: tuple[str, ...], match: float, hits: tuple[str, ...],
            bumped: bool) -> str:
    """可读评分理由(中文; 每条候选必带)."""
    factor = _tier_factor(node["tier"])
    if bumped:
        return (f"研究升顶: 任务域 {'/'.join(labels)} 无本地可用工具 → research 优先 "
                f"(tier {node['tier']} 因子 {factor})")
    if hits:
        return f"域匹配 {match}: 命中 {'/'.join(hits)} (tier {node['tier']} 因子 {factor})"
    return f"无域匹配(任务域: {'/'.join(labels)}); tier {node['tier']} 因子 {factor}"


def _score_node(node: dict, labels: tuple[str, ...], bumped: bool) -> dict:
    """单节点评分 → {id, score, reason}(不可变, 不触碰入参)."""
    match, hits = _match_score(node["keywords"], labels)
    factor = _tier_factor(node["tier"])
    score = RESEARCH_BUMP * factor if bumped else round(match * factor, 3)
    return {"id": node["id"], "score": score, "reason": _reason(node, labels, match, hits, bumped)}


# ---------- 主入口 ----------

def topk_methods(task_desc: str, method_graph, k: int = 3) -> list[dict]:
    """任务感知 top-k 方法排序 → [{id, score, reason}] 降序.

    - 不可用节点(present=False / type 无对应)不进结果(不能选 = 无降级价值)
    - 任务域无任何本地可用工具命中 → research 类节点升到第一(研究升顶)
    - 排序键 (-score, tier, id): 同分便宜优先, 再按 id 字典序 → 幂等稳定
    - top-1 失败降级: 调用方取 ranked[1] 即可(自带降级, 不需重路由)
    """
    if not isinstance(k, int) or isinstance(k, bool) or k < 0:
        raise ValueError(f"k 须为非负整数, 实际 {k!r}")
    nodes = _normalize_nodes(method_graph)
    if not nodes or k == 0:
        return []
    labels = _domain_labels(task_desc)

    available = tuple(n for n in nodes if _is_available(n))
    bumped = not any(_match_score(n["keywords"], labels)[0] > 0.0 for n in available)

    ranked = [_score_node(n, labels, bumped and _is_research(n)) for n in available]
    tiers = {n["id"]: n["tier"] for n in nodes}
    ranked.sort(key=lambda r: (-r["score"], _tier_key(tiers.get(r["id"], 9)), r["id"]))
    return ranked[:k]


def _tier_key(tier) -> int:
    """排序用 tier 键: 合法 int 原样; 缺失/非法排最后(确定性)."""
    return tier if isinstance(tier, int) and tier in (1, 2, 3) else 9


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="kunglao-agent method_topk (任务感知 top-k, 0 LLM)")
    ap.add_argument("task_desc", help="自由文本任务描述(如: 分析 JNI 程序)")
    ap.add_argument("--method-graph", default=str(DEFAULT_GRAPH))
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args(argv)
    for r in topk_methods(args.task_desc, Path(args.method_graph), k=args.k):
        print(f"  {r['score']:6.3f}  {r['id']:<24} {r['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
