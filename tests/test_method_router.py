"""阶段 4 RED/GREEN — M1.2 method_router 契约测试 (E4.2 故障注入).

契约: specs/phase-4/contract.md §1 method_router 语义; 设计: module-design.md
M1.2 (L115-117) / M1.5 错误处理 (L160-164) / M1.6 测试点 (L170), design-spec §6.5.

核心断言:
- Dijkstra 选路径(起点可执行 → 直达; 起点全挂 → 沿替代/衔接边重路由)
- 注入 tool_health 失败 → 换替代路径, **0 次 LLM 调用**(纯机械)
- 图断 → escalate=True 信号; 节点缺失 → escalate=True
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import method_router as mr
from method_router import RoutedPath, load_method_graph

ROOT = Path(__file__).resolve().parents[1]
REAL_GRAPH = load_method_graph(ROOT / "data" / "method-graph.yaml")


def _th(**kw) -> dict:
    """tool_health 构造器: 下划线 kwargs → skill id(连字符); 未列出的 skill 视为 unknown(可用)."""
    return {k.replace("_", "-"): v for k, v in kw.items()}


# ---------- 主路径(Dijkstra 直达) ----------

def test_primary_path_selected() -> None:
    p = mr.method_router("c2_config_extract", REAL_GRAPH, _th())
    assert p.escalated is False
    assert p.llm_calls == 0
    assert len(p.steps) == 1
    assert p.steps[0].method == "c2_config_extract"
    assert p.steps[0].skill == "ghidra-re"  # 主 skill 优先


def test_primary_skill_preferred_over_alternative() -> None:
    p = mr.method_router("protocol_restore", REAL_GRAPH, _th())
    assert p.steps[0].skill == "rev-frida"  # 主 skill
    assert p.llm_calls == 0


# ---------- E4.2 故障注入: 主 skill 挂 → 替代 skill ----------

def test_tool_failure_reroutes_to_alternative_skill() -> None:
    """注入 tool_health: ghidra-re down → c2_config_extract 换 rev-frida; 0 LLM 调用."""
    p = mr.method_router("c2_config_extract", REAL_GRAPH, _th(ghidra_re="down"))
    assert p.escalated is False
    assert p.steps[0].skill == "rev-frida"
    assert p.llm_calls == 0


def test_alternative_preference_order() -> None:
    """主 skill 与第一个替代都挂 → 用第二个替代(ghidra-malware)."""
    p = mr.method_router("c2_config_extract", REAL_GRAPH, _th(ghidra_re="down", rev_frida="down"))
    assert p.steps[0].skill == "ghidra-malware"
    assert p.llm_calls == 0


# ---------- Dijkstra 跨节点重路由(起点全挂) ----------

def test_dijkstra_reroutes_via_alternative_edge() -> None:
    """c2_config_extract 三个 skill 全挂 → 沿 alternative 边重路由到 dynamic_observe(vmr-shell)."""
    th = _th(ghidra_re="down", rev_frida="down", ghidra_malware="down")
    p = mr.method_router("c2_config_extract", REAL_GRAPH, th)
    assert p.escalated is False
    assert p.llm_calls == 0
    methods = [s.method for s in p.steps]
    assert methods[0] == "c2_config_extract"
    assert methods[-1] == "dynamic_observe"
    assert p.steps[0].skill is None  # 起点 blocked
    assert p.steps[-1].skill == "vmr-shell"


def test_dijkstra_prefers_cheaper_reachable_method() -> None:
    """起点全挂且两条替代出边通向不同 tier 终点 → Dijkstra 选总成本更低者 (T1 < T3)."""
    graph = {
        "nodes": {
            "start": {"id": "start", "skill": "s0", "tier": 2, "alternatives": []},
            "cheap": {"id": "cheap", "skill": "s1", "tier": 1, "alternatives": []},
            "pricey": {"id": "pricey", "skill": "s2", "tier": 3, "alternatives": []},
        },
        "edges": [
            {"from": "start", "to": "cheap", "kind": "alternative"},
            {"from": "start", "to": "pricey", "kind": "alternative"},
        ],
    }
    th = {"s0": "down"}  # 仅起点挂; cheap(总成本 1+1=2) vs pricey(总成本 1+4=5)
    p = mr.method_router("start", graph, th)
    assert p.escalated is False
    assert p.llm_calls == 0
    methods = [s.method for s in p.steps]
    assert methods[-1] == "cheap"
    assert p.steps[-1].skill == "s1"


def test_dijkstra_uses_sequence_edges_too() -> None:
    """替代边全挂 → 仍可经 sequence 边(衔接)到达可执行终点."""
    graph = {
        "nodes": {
            "start": {"id": "start", "skill": "s0", "tier": 2, "alternatives": []},
            "mid": {"id": "mid", "skill": "s1", "tier": 3, "alternatives": []},
            "goal": {"id": "goal", "skill": "s2", "tier": 1, "alternatives": []},
        },
        "edges": [
            {"from": "start", "to": "mid", "kind": "sequence"},
            {"from": "mid", "to": "goal", "kind": "sequence"},
        ],
    }
    th = {"s0": "down"}
    # mid 总成本 1+4=5; goal 总成本 2+1=3 → Dijkstra 穿越 mid 选 goal
    p = mr.method_router("start", graph, th)
    assert p.escalated is False
    assert [s.method for s in p.steps] == ["start", "mid", "goal"]
    assert p.steps[0].skill is None          # 起点 blocked
    assert p.steps[1].skill == "s1"          # 中间节点可执行(带 skill)
    assert p.steps[2].skill == "s2"
    assert p.llm_calls == 0


# ---------- 图断 escalate ----------

def _all_skills_down() -> dict:
    """图中每个节点引用的全部 skill 标 down(从图推导, 防图变更后漏标)."""
    skills = set()
    for n in REAL_GRAPH["nodes"].values():
        skills.add(n["skill"])
        skills.update(n.get("alternatives", []))
    return {s: "down" for s in skills}


def test_graph_disconnected_escalates() -> None:
    """全部 skill down → 无可执行节点 → escalate=True, path 空, 0 LLM."""
    p = mr.method_router("c2_config_extract", REAL_GRAPH, _all_skills_down())
    assert p.escalated is True
    assert p.steps == ()
    assert p.llm_calls == 0
    assert p.reason  # escalate 信号携带原因


def test_missing_node_escalates() -> None:
    """method-graph 缺节点 → 视为图断 → escalate (M1.5 L162)."""
    p = mr.method_router("bogus_method", REAL_GRAPH, _th())
    assert p.escalated is True
    assert "bogus_method" in p.reason
    assert p.llm_calls == 0


# ---------- 0 LLM 机械门禁 ----------

def test_zero_llm_import_guard() -> None:
    """模块源码不含任何 LLM 客户端 import — 机械性证明 0 LLM 调用."""
    src = Path(mr.__file__).read_text(encoding="utf-8")
    forbidden = re.findall(r"^\s*(?:import|from)\s+(anthropic|openai|langchain)\b", src, re.MULTILINE)
    assert not forbidden, f"module imports LLM client: {forbidden}"
    assert "llm_calls" in src  # 字段存在供断言


def test_escalation_never_has_llm_calls() -> None:
    for kwargs in (
        dict(action_type="bogus", method_graph=REAL_GRAPH, tool_health=_th()),
        dict(action_type="c2_config_extract", method_graph=REAL_GRAPH, tool_health=_all_skills_down()),
    ):
        p = mr.method_router(**kwargs)
        assert p.escalated is True and p.llm_calls == 0


# ---------- 图格式校验 ----------

def test_load_method_graph_rejects_bad_format(tmp_path) -> None:
    bad = tmp_path / "bad-graph.yaml"
    bad.write_text("nodes: [{id: x, type: action}]\n", encoding="utf-8")  # 方法节点缺 skill/tier
    with pytest.raises(ValueError):
        load_method_graph(bad)
    bad2 = tmp_path / "bad-edge.yaml"
    bad2.write_text("nodes: [{id: a, type: action, skill: ghidra-re, tier: 1}]\n"
                    "edges: [{from: a, to: ghost, kind: sequence}]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_method_graph(bad2)
    bad3 = tmp_path / "bad-kind.yaml"
    bad3.write_text("nodes: [{id: a, type: action, skill: ghidra-re, tier: 1}]\n"
                    "edges: [{from: a, to: a, kind: teleport}]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_method_graph(bad3)


def test_load_method_graph_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_method_graph(tmp_path / "nope.yaml")


def test_routed_path_is_immutable_dataclass() -> None:
    p = RoutedPath(steps=(), escalated=False, reason="", llm_calls=0)
    assert p.steps == () and p.llm_calls == 0
