"""阶段 4 修订: 方法路由动态注册(用户纠正 — 写死路由无意义).

Step 1 RED — 当前状态: data/method-graph.yaml 是 12 节点手写(固定 skill 名);
注册器 scripts/method_router_register.py 不存在 → import 即 RED。

GREEN 目标: 路由表由 init 阶段动态扫描真实环境生成 —
- 节点 = 环境注册(扫描 ~/.claude/skills + settings.json mcpServers + scripts/)
- 边 = 动作类型→候选类目映射表(唯一手写部分, 引用注册出的节点)
- 新装 skill → 重注册 → 路由多一条替代; 卸载 → 自动消失
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def test_registered_nodes_come_from_environment(ws_factory) -> None:
    """节点必须来自环境扫描: 构造 tmp 环境(skill + mcpServers + 脚本), 注册 → 节点覆盖全部, 且不含环境外 skill."""
    ws = ws_factory()
    env = ws / "env"
    (env / "skills" / "my-new-skill" / "SKILL.md").parent.mkdir(parents=True)
    (env / "skills" / "my-new-skill" / "SKILL.md").write_text(
        "---\nname: my-new-skill\ndescription: test skill\n---\n", encoding="utf-8")
    (env / "settings.json").write_text(json.dumps({
        "mcpServers": {"my-mcp": {"command": "x"}}
    }), encoding="utf-8")
    (env / "scripts").mkdir()  # 注册器源 3 需要该目录存在(冻结测试修正)
    (env / "scripts" / "my-tool.py").write_text("print(1)\n", encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "method_router_register.py"), str(env), "--output", str(ws / "method-graph.yaml")],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"register failed: {r.stderr}"

    import yaml
    graph = yaml.safe_load((ws / "method-graph.yaml").read_text(encoding="utf-8"))
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "my-new-skill" in node_ids, "scanned skill not registered"
    assert "my-mcp" in node_ids, "scanned MCP not registered"
    assert "my-tool" in node_ids, "scanned script not registered"
    # 环境外(不存在)的 skill 不得出现
    assert not any("nonexistent" in i for i in node_ids), "ghost node registered"


def test_router_uses_registered_graph(ws_factory) -> None:
    """method_router 消费注册出的图(不是手写图)."""
    ws = ws_factory()
    env = ws / "env"
    (env / "skills" / "rev-a" / "SKILL.md").parent.mkdir(parents=True)
    (env / "skills" / "rev-a" / "SKILL.md").write_text(
        "---\nname: rev-a\ndescription: static RE\n---\n", encoding="utf-8")
    (env / "settings.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    (env / "scripts").mkdir()

    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "method_router_register.py"), str(env), "--output", str(ws / "method-graph.yaml")],
        capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr

    import yaml
    from pathlib import Path as _Path
    sys.path.insert(0, str(SCRIPTS))
    from method_router import load_method_graph, method_router
    # 注册器产物是文件, 消费方经 load_method_graph 规范化(list nodes → dict)
    graph = load_method_graph(_Path(ws / "method-graph.yaml"))
    path = method_router("c2_config_extract", graph, {})
    assert path.steps, "router must route on registered graph"
    assert path.llm_calls == 0


def test_register_is_idempotent(ws_factory) -> None:
    """重注册不产生重复节点."""
    ws = ws_factory()
    env = ws / "env"
    (env / "skills" / "rev-a" / "SKILL.md").parent.mkdir(parents=True)
    (env / "skills" / "rev-a" / "SKILL.md").write_text(
        "---\nname: rev-a\ndescription: static RE\n---\n", encoding="utf-8")
    (env / "settings.json").write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    (env / "scripts").mkdir()
    out = ws / "method-graph.yaml"

    for _ in range(2):
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "method_router_register.py"), str(env), "--output", str(out)],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr

    import yaml
    graph = yaml.safe_load(out.read_text(encoding="utf-8"))
    ids = [n["id"] for n in graph["nodes"]]
    assert len(ids) == len(set(ids)), f"duplicate nodes after re-register: {ids}"
