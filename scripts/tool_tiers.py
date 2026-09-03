#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tool_tiers.py — #812 工具族档位表加载器/选择器（契约层，fail-open）。

数据在 scripts/tool_tiers.yaml（场景×工具档位表，来源 #670 估算 + #812
C-006 实录）。本模块只做加载/选择/注入块渲染，零运行时打分（Q 表消费
属 #823-P3）；执行包装器（timeout 硬杀）为后续 PR。

 Faces:
  load()                     -> dict | None     yaml 加载，失败 None
  scene_for(ws)              -> str             task_spec 平台嗅探（best-effort）
  chain_for(scene_key, ws)   -> list[str]       降级链；未知场景 fallback；
                                                ws 带运行时计数表时按 β-Bernoulli
                                                池化 utility 稳定重排（#881 接线①）
  tier_entry(scene_key, tier)-> dict | None     单档定义；fallback 场景 None
  inject_block(scene_key, ws)-> str | None      契约注入块（人类可读+来源引用）；
                                                ws 计数同时驱动链序与档内工具序
"""
from __future__ import annotations

from pathlib import Path

import yaml

_DATA = Path(__file__).resolve().parent / "tool_tiers.yaml"
_FALLBACK_CHAIN = ["full", "targeted", "structured", "text"]
_SCENE_HINTS = {
    "android-dex-static": ("android", "apk", "dex", "baksmali"),
    "generic-binary": ("binary", "pe", "elf", "ghidra"),
}


def _runtime_counts(ws: Path | str | None):
    """#881 wiring 1: (tool_value module, pooled per-tool utilities) when the
    workspace table carries real runtime evidence (cite/burn>0). Otherwise
    (None, None) — the static ordering is returned byte-for-byte unchanged
    (reject-only data never reorders: it does not enter the posterior)."""
    if ws is None:
        return None, None
    try:
        import tool_value as _tv
        table = _tv.load_table(Path(ws))
        if not table:
            return None, None
        pooled = _tv.pooled_utilities(table)
        if not any(c["cite"] + c["burn"] > 0 for c in pooled.values()):
            return None, None
        return _tv, pooled
    except Exception:  # noqa: BLE001 — runtime counts are additive, fail-open
        return None, None


def load() -> dict | None:
    """加载档位表。任何异常 → None（调用方键缺席）。"""
    try:
        return yaml.safe_load(_DATA.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None


def scene_for(ws: Path | None) -> str:
    """task_spec.yaml 平台字段嗅探（best-effort）。无信号 → generic-binary。"""
    if ws is not None:
        try:
            spec = yaml.safe_load(
                (Path(ws) / "task_spec.yaml").read_text(encoding="utf-8")) or {}
            blob = " ".join(str(v) for v in (
                spec.get("platform"),
                spec.get("project_type"),
                spec.get("target"),
                spec.get("language"),
            ) if v).lower()
            for scene, hints in _SCENE_HINTS.items():
                if any(h in blob for h in hints):
                    return scene
        except (OSError, yaml.YAMLError):
            pass
    return "generic-binary"


def chain_for(scene_key: str, ws: Path | str | None = None) -> list[str]:
    """降级链。未知场景 → 通用词汇 fallback（不发明工具名）。

    #881 接线①（ws 面可省——省略或无运行时计数表 = 静态链原序）：ws 带计数表
    时按各档成员工具的池化 cite/burn 算 β-Bernoulli 后验（先验=静态链 rank），
    稳定重排——平分保持静态序；先验有重力（零数据 = 现状同序），计数累积后
    自然翻转，不写死也不强制。"""
    data = load()
    if not data:
        return list(_FALLBACK_CHAIN)
    scene = (data.get("scenes") or {}).get(scene_key)
    if scene and scene.get("downgrade_chain"):
        chain = list(scene["downgrade_chain"])
    else:
        chain = list((data.get("fallback") or {}).get(
            "downgrade_chain", _FALLBACK_CHAIN))
    tv, pooled = _runtime_counts(ws)
    if not pooled:
        return chain
    tier_defs = (scene or {}).get("tier_defs") or {}
    total = len(chain)

    def _tier_score(rank: int, tier: str) -> float:
        members = [tv.normalize_tool(t)
                   for t in ((tier_defs.get(tier) or {}).get("tools") or [])]
        cite = sum(pooled[m]["cite"] for m in members if m in pooled)
        burn = sum(pooled[m]["burn"] for m in members if m in pooled)
        p0 = (total - rank) / (total + 1) if total else 0.5
        return tv.beta_utility(cite, burn, p0)

    return sorted(chain, key=lambda t: -_tier_score(chain.index(t), t))


def tier_entry(scene_key: str, tier: str) -> dict | None:
    """单档定义。fallback 场景/未知档 → None。"""
    data = load()
    if not data:
        return None
    scene = (data.get("scenes") or {}).get(scene_key)
    if not scene:
        return None
    return (scene.get("tier_defs") or {}).get(tier)


def inject_block(scene_key: str | None = None,
                 ws: Path | str | None = None) -> str | None:
    """渲染契约注入块（人类可读 + 来源引用）。加载失败 → None。

    #881 接线①：ws 带运行时计数表时，链序 = chain_for（同上）且档内工具按
    池化 utility 稳定重排（有证据工具先行，无证据保原相对序）；无表 = 输出
    逐字节与改造前一致（tests/test_tool_tiers_812.py C1 契约不回退）。"""
    data = load()
    if not data:
        return None
    scene_key = scene_key or "generic-binary"
    tv, pooled = _runtime_counts(ws)
    scene = (data.get("scenes") or {}).get(scene_key)
    if not scene:
        chain = list((data.get("fallback") or {}).get(
            "downgrade_chain", _FALLBACK_CHAIN))
        return ("[tool-tiers] scene=%s (fallback): downgrade chain: %s "
                "(unknown scene - tier vocabulary only; do not invent "
                "tool names outside the validated registry)" %
                (scene_key, " -> ".join(chain)))
    tier_defs = scene.get("tier_defs") or {}
    lines = ["[tool-tiers] scene=%s" % scene_key]
    if ws is not None:
        chain = chain_for(scene_key, ws)
    else:
        chain = list(scene.get("downgrade_chain") or _FALLBACK_CHAIN)
    lines.append("downgrade chain: " + " -> ".join(chain))
    for tier in chain:
        td = tier_defs.get(tier) or {}
        raw_tools = list(td.get("tools") or [])
        if pooled and len(raw_tools) > 1:
            def _key(item):
                idx, t = item
                cell = pooled.get(tv.normalize_tool(t))
                live = bool(cell and cell["cite"] + cell["burn"] > 0)
                return (0 if live else 1,
                        -(cell["utility"] if cell else 0.0), idx)
            raw_tools = [t for _i, t in sorted(enumerate(raw_tools), key=_key)]
        tools = ", ".join(raw_tools) or "(per registry)"
        caps = ", ".join("%s=%s" % kv for kv in sorted(
            (td.get("caps") or {}).items())) or "no cap"
        lines.append("  %s: %s | caps: %s" % (tier, tools, caps))
        pre = td.get("preconditions") or []
        if pre:
            lines.append("    preconditions: " + ", ".join(pre))
        how = td.get("how")
        if how:
            lines.append("    how: " + " ".join(str(how).split()))
    prior = scene.get("obfuscation_prior") or {}
    for k, v in prior.items():
        lines.append("  prior[%s]: %s" % (k, " ".join(str(v).split())))
    srcs = scene.get("sources") or []
    if srcs:
        lines.append("  sources: " + "; ".join(srcs))
    return "\n".join(lines)


def inject_for_workspace(ws: Path | None) -> str | None:
    """场景嗅探 + 注入块一步到位（dispatch_context 接线面）。#881：ws 透传，
    dispatch 契约构建即消费运行时计数（生产消费路径）。"""
    try:
        return inject_block(scene_for(ws), ws=ws)
    except Exception:  # noqa: BLE001 — fail-open: 契约构建永不 raise
        return None
