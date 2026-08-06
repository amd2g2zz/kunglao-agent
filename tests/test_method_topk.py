"""阶段 4 修订 v3: 任务感知 top-k 方法排序(用户纠正 — 路由应是 top-k 而非单路径).

用户场景(核心用例): "agent 调用路由说我要分析 JNI 程序, 本地没有 jadx,
最高价值应是 anysearch(先搜索理解), 而不是 x64dbg(JNI 任务价值≈0)."

Step 1 RED — 当前状态: scripts/method_topk.py 不存在 → import 即 RED。

GREEN 目标:
- score(method) = 任务域匹配 × 本地可用性 × 价值因子
- 任务域空置(所需类目无本地工具) → research 类(anysearch)升顶
- 输出 top-k(k=3), top-1 失败直接用 top-2(自带降级, 不需重路由)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _env_graph(ws: Path, nodes: list[dict]) -> Path:
    """构造 method-graph.yaml(节点 = 注册器产物格式)."""
    import yaml
    graph = {"version": 1, "kind": "method-graph", "nodes": nodes}
    out = ws / "method-graph.yaml"
    out.write_text(yaml.safe_dump(graph, sort_keys=False), encoding="utf-8")
    return out


def test_jni_no_local_tool_ranks_research_first(ws_factory) -> None:
    """核心用例: 分析 JNI 程序, 本地无 jadx → anysearch(研究)最高, x64dbg 垫底."""
    ws = ws_factory()
    nodes = [
        {"id": "x64dbg", "type": "mcp", "skill": "x64dbg", "tier": 3,
         "keywords": ["windows", "debug", "assembly"]},
        {"id": "ghidra", "type": "skill", "skill": "ghidra-re", "tier": 2,
         "keywords": ["static", "re", "binary", "assembly"]},
        {"id": "anysearch", "type": "tool", "skill": "anysearch", "tier": 1,
         "keywords": ["search", "web", "research", "docs"]},
        {"id": "jadx", "type": "skill", "skill": "jadx", "tier": 2,
         "keywords": ["java", "android", "dex", "smali"], "present": False},  # 本地没有
    ]
    graph = _env_graph(ws, nodes)
    sys.path.insert(0, str(SCRIPTS))
    from method_topk import topk_methods
    ranked = topk_methods("分析 JNI 程序, java android native 交叉", graph, k=3)
    assert ranked, "top-k must return candidates"
    assert ranked[0]["id"] == "anysearch", \
        f"JNI 无本地 jadx → anysearch 应第一, 实际 {ranked[0]['id']}"
    ids = [r["id"] for r in ranked]
    assert "x64dbg" not in ids[:2], f"x64dbg 对 JNI 价值≈0, 不应进前 2: {ids}"
    assert all("score" in r and "reason" in r for r in ranked), "each rank needs score+reason"


def test_local_tool_ranks_over_research(ws_factory) -> None:
    """本地有 jadx → jadx 最高(高于 anysearch)."""
    ws = ws_factory()
    nodes = [
        {"id": "jadx", "type": "skill", "skill": "jadx", "tier": 2,
         "keywords": ["java", "android", "dex", "smali"]},
        {"id": "anysearch", "type": "tool", "skill": "anysearch", "tier": 1,
         "keywords": ["search", "web", "research", "docs"]},
    ]
    graph = _env_graph(ws, nodes)
    sys.path.insert(0, str(SCRIPTS))
    from method_topk import topk_methods
    ranked = topk_methods("分析 JNI 程序", graph, k=3)
    assert ranked[0]["id"] == "jadx", f"本地有 jadx → jadx 应第一, 实际 {ranked[0]['id']}"


def test_top1_failure_uses_top2(ws_factory) -> None:
    """top-1 失败 → 直接用 top-2(自带降级, 不需重路由)."""
    ws = ws_factory()
    nodes = [
        {"id": "a", "type": "skill", "skill": "a", "tier": 1, "keywords": ["x"]},
        {"id": "b", "type": "skill", "skill": "b", "tier": 1, "keywords": ["x"]},
    ]
    graph = _env_graph(ws, nodes)
    sys.path.insert(0, str(SCRIPTS))
    from method_topk import topk_methods
    ranked = topk_methods("分析 x", graph, k=3)
    assert len(ranked) == 2 and ranked[0]["id"] == "a" and ranked[1]["id"] == "b"
    # top-1 失败 → fallback top-2
    fallback = ranked[1]
    assert fallback["id"] == "b", f"top-1 失败应直接用 top-2: {fallback['id']}"
