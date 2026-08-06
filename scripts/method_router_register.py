#!/usr/bin/env python3
"""method_router_register.py — 方法路由动态注册器 (init 阶段).

用户纠正: 写死路由表无意义 — 路由应在 init 阶段把所有 tools/skill/MCP 注册进去,
环境变化自动反映。本脚本扫描真实环境, 生成 method-graph.yaml:

- 三源扫描(全部注册为节点, **不含任何手写节点**):
  1. <env>/skills/*/SKILL.md         — frontmatter(name/description/allowed-tools) → 节点
                                       (id=skill 名, type=skill, tier 按描述启发, keywords 由描述提取)
  2. <env>/settings.json 的 mcpServers — 每个 server → 节点(id=mcp 名, type=mcp)
  3. <env>/scripts/*.py              — 每个脚本 → 节点(id=脚本名去 .py, type=script)
- 边(唯一手写部分 = data/action-type-map.yaml): 动作类型 → 候选类目 → 解析为注册节点
  → alternative 边(动作 → 每个候选成员); sequence 边(动作 → 动作, 工作流衔接)
- 幂等: 每次从扫描重建; 同环境重注册 → 节点集相同(无重复节点)
- 新装 skill / 新配 MCP / 新加脚本 → 重跑注册器 → 路由自动多一条候选; 卸载 → 自动消失

产物格式 = 现有 method-graph.yaml 格式(list 形态 nodes): 消费方用
method_router.load_method_graph 装载(转 dict), 或 method_topk(直接接受 list/dict)。

用法:
  python method_router_register.py [env] [--output <method-graph.yaml>] [--action-map <path>]
  (env 默认 ~/.claude; --output 默认 data/method-graph.yaml)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = Path.home() / ".claude"
DEFAULT_OUTPUT = ROOT / "data" / "method-graph.yaml"
DEFAULT_ACTION_MAP = ROOT / "data" / "action-type-map.yaml"

# tier 启发: T3 深层(动态/内存/注入) | T1 便宜(字符串/情报/特征) | 默认 T2 中层
TIER3_KEYWORDS = ("dynamic", "debug", "frida", "x64dbg", "trace", "unicorn", "qiling",
                  "emulat", "runtime", "memory", "inject", "persist", "network",
                  "protocol", "sandbox", "vmware", "virtual", "behavior",
                  "动态", "调试", "内存", "注入", "网络")
TIER1_KEYWORDS = ("string", "floss", "ioc", "cti", "signature", "entropy", "packer",
                  "recon", "osint", "hash", "light", "quick", "triage", "score",
                  "字符串", "情报", "特征", "签名")
TOKEN_SPLIT = re.compile(r"[^0-9a-zA-Z一-鿿]+")
MIN_TOKEN_LEN = 2


# ---------- 环境扫描 ----------

def _frontmatter_of(text: str, path: Path) -> dict:
    """解析已确认以 '---' 开头的 frontmatter 块.

    先严格 yaml; 失败(真实环境存在 Claude Code 可读但非严格 YAML 的 frontmatter,
    如 description 含未引号冒号) → 行级宽松提取 name/description + stderr 警告;
    连 name 都提取不到 → ValueError(显式错误)。
    """
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"SKILL.md frontmatter 未闭合: {path}")
    block = parts[1]
    try:
        fm = yaml.safe_load(block) or {}
        if not isinstance(fm, dict):
            raise ValueError(f"SKILL.md frontmatter 须为 mapping: {path}")
        return fm
    except yaml.YAMLError as exc:
        fm = _lenient_frontmatter(block)
        if fm.get("name"):
            print(f"method_router_register: 警告: frontmatter 非严格 YAML({exc.__class__.__name__}), "
                  f"行级提取 name/description: {path}", file=sys.stderr)
            return fm
        raise ValueError(f"SKILL.md frontmatter 解析失败且无法提取 name: {path}: {exc}")


FM_FIELD = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", re.MULTILINE)


def _lenient_frontmatter(block: str) -> dict:
    """行级 key: value 提取(name/description 单行值; allowed-tools 宽松路径下不解析)."""
    fm: dict[str, object] = {}
    for m in FM_FIELD.finditer(block):
        key, val = m.group(1), m.group(2).strip().strip("\"'")
        if key == "name" and val:
            fm["name"] = val
        elif key == "description" and val:
            fm["description"] = val
    return fm


def tier_from_text(text: str) -> int:
    """tier 启发: T3 深层(动态/内存) | T1 便宜(字符串/情报) | 默认 T2(中层, 如 static RE)."""
    low = text.lower()
    if any(k in low for k in TIER3_KEYWORDS):
        return 3
    if any(k in low for k in TIER1_KEYWORDS):
        return 1
    return 2


def keywords_from_text(text: str) -> tuple[str, ...]:
    """描述 → 关键词: 按非字母数字/非 CJK 切分, 小写, 去重, 排序(确定性)."""
    out: set[str] = set()
    for tok in TOKEN_SPLIT.split(text):
        tok = tok.lower().strip()
        if len(tok) >= MIN_TOKEN_LEN:
            out.add(tok)
    return tuple(sorted(out))


def _base_node(node_id: str, node_type: str, description: str,
               allowed_tools: list, source: str) -> dict:
    """注册节点公共字段(不可变 dict)."""
    keywords = list(keywords_from_text(node_id)) + list(keywords_from_text(description))
    keywords += [str(t).lower() for t in allowed_tools]
    node = {
        "id": node_id,
        "type": node_type,
        "skill": node_id,          # 注册节点以自身为 skill(tool_health 按此键控)
        "tier": tier_from_text(description or node_id),
        "keywords": tuple(sorted(set(keywords))),
        "alternatives": [],
        "present": True,
        "source": source,
    }
    if description:
        node["description"] = description
    if allowed_tools:
        node["allowed_tools"] = list(allowed_tools)
    return node


def scan_skills(env: Path) -> list[dict]:
    """源 1: <env>/skills/*/SKILL.md → 节点(type=skill).

    无 frontmatter(不以 '---' 开头)的 SKILL.md → 以目录名注册 + stderr 警告,
    不中断整体注册(真实环境存在此类 skill, 如 content-rewriting-2601)。
    """
    skills_dir = env / "skills"
    if not skills_dir.is_dir():
        return []
    nodes: list[dict] = []
    for skill_md in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_md.read_text(encoding="utf-8")
        if not text.lstrip("﻿ \t\r\n").startswith("---"):
            print(f"method_router_register: 警告: SKILL.md 无 frontmatter, "
                  f"以目录名注册: {skill_md}", file=sys.stderr)
            nodes.append(_base_node(skill_md.parent.name, "skill", "", [],
                                    source=str(skill_md)))
            continue
        fm = _frontmatter_of(text, skill_md)
        sid = str(fm.get("name") or skill_md.parent.name).strip()
        if not sid:
            raise ValueError(f"SKILL.md 无 name 且目录名为空: {skill_md}")
        desc = str(fm.get("description") or "").strip()
        allowed = fm.get("allowed-tools") or fm.get("allowed_tools") or []
        nodes.append(_base_node(sid, "skill", desc, allowed,
                                source=str(skill_md)))
    return nodes


def scan_mcp_servers(env: Path) -> list[dict]:
    """源 2: <env>/settings.json 的 mcpServers → 节点(type=mcp).

    settings.json 缺失 → 空列表(无 MCP 配置不算错误); 存在但非 mapping → ValueError.
    """
    settings = env / "settings.json"
    if not settings.exists():
        return []
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"settings.json 解析失败: {settings}: {exc}")
    if not isinstance(data, dict):
        raise ValueError(f"settings.json 须为 mapping: {settings}")
    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"settings.json mcpServers 须为 mapping: {settings}")
    return [
        _base_node(name, "mcp", "", [],
                   source=f"{settings}#mcpServers.{name}")
        for name in sorted(servers)
    ]


def scan_scripts(env: Path) -> list[dict]:
    """源 3: <env>/scripts/*.py → 节点(id=脚本名去 .py, type=script)."""
    scripts_dir = env / "scripts"
    if not scripts_dir.is_dir():
        return []
    return [
        _base_node(p.stem, "script", "", [],
                   source=str(p))
        for p in sorted(scripts_dir.glob("*.py"))
    ]


def scan_env(env: Path) -> list[dict]:
    """三源扫描(确定性顺序: skills → mcpServers → scripts, 各源内按 id 排序)."""
    return scan_skills(env) + scan_mcp_servers(env) + scan_scripts(env)


# ---------- action-type-map 装载 ----------

def load_action_map(path: Path) -> dict:
    """装载并校验 action-type-map.yaml; categories/actions/tier/sequence 违规 → ValueError."""
    if not path.exists():
        raise FileNotFoundError(f"action-type-map 不存在: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cats = raw.get("categories")
    if not isinstance(cats, dict) or not cats:
        raise ValueError(f"action-type-map: categories 缺失或为空 ({path})")
    for cname, cat in cats.items():
        if not isinstance(cat, dict) or not isinstance(cat.get("keywords"), list):
            raise ValueError(f"action-type-map: 类目 {cname!r} 须含 keywords 列表 ({path})")
    acts = raw.get("actions")
    if not isinstance(acts, dict) or not acts:
        raise ValueError(f"action-type-map: actions 缺失或为空 ({path})")
    for aname, spec in acts.items():
        if not isinstance(spec, dict):
            raise ValueError(f"action-type-map: 动作 {aname!r} 须为 mapping ({path})")
        if spec.get("tier") not in (1, 2, 3):
            raise ValueError(f"action-type-map: 动作 {aname!r} tier 非法 {spec.get('tier')!r} ({path})")
        cl = spec.get("categories")
        if not isinstance(cl, list) or not cl:
            raise ValueError(f"action-type-map: 动作 {aname!r} categories 须为非空列表 ({path})")
        for cname in cl:
            if cname not in cats:
                raise ValueError(f"action-type-map: 动作 {aname!r} 引用未知类目 {cname!r} ({path})")
    seq = raw.get("sequence") or []
    if not isinstance(seq, list):
        raise ValueError(f"action-type-map: sequence 须为列表 ({path})")
    for pair in seq:
        if (not isinstance(pair, list) or len(pair) != 2
                or pair[0] not in acts or pair[1] not in acts):
            raise ValueError(f"action-type-map: sequence 项非法(须为 actions 内 [from, to]): {pair!r} ({path})")
    return raw


# ---------- 动作节点解析 ----------

def _node_text(node: dict) -> str:
    """类目匹配文本 = id + description(mcp/script 无描述 → 仅 id)."""
    return " ".join([node["id"], node.get("description", "")])


def category_member_ids(category: dict, registered: list[dict]) -> list[str]:
    """类目关键词(小写子串)命中注册节点 → 成员 id 列表(保持注册顺序)."""
    kws = [str(k).lower() for k in category.get("keywords", [])]
    return [n["id"] for n in registered if any(k in _node_text(n).lower() for k in kws)]


def resolve_action_nodes(action_map: dict, registered: list[dict]) -> list[dict]:
    """动作类型 → 方法节点: 候选类目解析为注册节点; 首个成员 = 主 skill, 其余 = alternatives.

    无任何本地候选的动作 → 跳过(运行时 escalate 是设计行为: 缺方法 → LLM 图生长).
    """
    cats = action_map["categories"]
    action_nodes: list[dict] = []
    for aid, spec in action_map["actions"].items():
        matched: list[str] = []
        for cname in spec["categories"]:
            for nid in category_member_ids(cats[cname], registered):
                if nid not in matched:
                    matched.append(nid)
        if not matched:
            continue
        keywords = tuple(sorted({
            str(k).lower()
            for cname in spec["categories"]
            for k in cats[cname].get("keywords", [])
        }))
        action_nodes.append({
            "id": aid,
            "type": "action",
            "skill": matched[0],
            "tier": spec["tier"],
            "keywords": keywords,
            "alternatives": matched[1:],
            "source": f"action-type-map: {aid} -> {list(spec['categories'])}",
        })
    return action_nodes


# ---------- 边生成 ----------

def build_edges(action_map: dict, action_nodes: list[dict]) -> list[dict]:
    """边 = alternative(动作 → 每个候选类目成员)+ sequence(动作间工作流衔接).

    sequence 边只保留两端都实际存在于图中的动作(无本地候选被跳过的动作不产生边 —
    否则产生指向未知节点的悬空边, load_method_graph 会拒收)。
    """
    edges: list[dict] = []
    present = {n["id"] for n in action_nodes}
    for node in action_nodes:
        for cand in [node["skill"]] + list(node["alternatives"]):
            edges.append({"from": node["id"], "to": cand, "kind": "alternative"})
    for frm, to in action_map.get("sequence", []):
        if frm in present and to in present:
            edges.append({"from": frm, "to": to, "kind": "sequence"})
    return edges


# ---------- 图组装 / 写出 ----------

def build_graph(action_map: dict, registered: list[dict],
                action_nodes: list[dict], edges: list[dict]) -> dict:
    """method-graph: 节点 = 动作节点 + 环境注册节点(全部来自扫描/映射, 无手写)."""
    return {
        "version": 1,
        "kind": "method-graph",
        "nodes": action_nodes + registered,
        "edges": edges,
    }


def write_graph(graph: dict, out_path: Path) -> None:
    """写出 method-graph.yaml(list 形态 nodes, 与现有格式一致; 确定性无时间戳)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = ("# generated by scripts/method_router_register.py — do not hand-edit;\n"
            "# re-run after environment changes (skills/ mcpServers/ scripts/).\n" +
            yaml.safe_dump(graph, sort_keys=False, allow_unicode=True))
    out_path.write_text(text, encoding="utf-8")


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="kunglao-agent 方法路由动态注册器(三源扫描 → method-graph.yaml)")
    ap.add_argument("env", nargs="?", default=str(DEFAULT_ENV),
                    help="环境目录 (默认 ~/.claude)")
    ap.add_argument("--output", default=str(DEFAULT_OUTPUT),
                    help="method-graph.yaml 输出路径")
    ap.add_argument("--action-map", default=str(DEFAULT_ACTION_MAP),
                    help="action-type-map.yaml 路径")
    args = ap.parse_args(argv)
    try:
        env = Path(args.env)
        if not env.is_dir():
            raise FileNotFoundError(f"env 目录不存在: {env}")
        action_map = load_action_map(Path(args.action_map))
        registered = scan_env(env)
        action_nodes = resolve_action_nodes(action_map, registered)
        edges = build_edges(action_map, action_nodes)
        graph = build_graph(action_map, registered, action_nodes, edges)
        write_graph(graph, Path(args.output))
        print(f"registered {len(registered)} env nodes "
              f"(skills + mcpServers + scripts) + {len(action_nodes)} action nodes, "
              f"{len(edges)} edges -> {args.output}")
        return 0
    except (FileNotFoundError, ValueError) as exc:
        print(f"method_router_register: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
