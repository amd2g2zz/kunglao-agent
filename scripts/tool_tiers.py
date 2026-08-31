#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tool_tiers.py — #812 工具族档位表加载器/选择器（契约层，fail-open）。

数据在 scripts/tool_tiers.yaml（场景×工具档位表，来源 #670 估算 + #812
C-006 实录）。本模块只做加载/选择/注入块渲染，零运行时打分（Q 表消费
属 #823-P3）；执行包装器（timeout 硬杀）为后续 PR。

 Faces:
  load()                     -> dict | None     yaml 加载，失败 None
  scene_for(ws)              -> str             task_spec 平台嗅探（best-effort）
  chain_for(scene_key)       -> list[str]       降级链；未知场景 fallback
  tier_entry(scene_key, tier)-> dict | None     单档定义；fallback 场景 None
  inject_block(scene_key)    -> str | None      契约注入块（人类可读+来源引用）
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


def chain_for(scene_key: str) -> list[str]:
    """降级链。未知场景 → 通用词汇 fallback（不发明工具名）。"""
    data = load()
    if not data:
        return list(_FALLBACK_CHAIN)
    scene = (data.get("scenes") or {}).get(scene_key)
    if scene and scene.get("downgrade_chain"):
        return list(scene["downgrade_chain"])
    return list((data.get("fallback") or {}).get(
        "downgrade_chain", _FALLBACK_CHAIN))


def tier_entry(scene_key: str, tier: str) -> dict | None:
    """单档定义。fallback 场景/未知档 → None。"""
    data = load()
    if not data:
        return None
    scene = (data.get("scenes") or {}).get(scene_key)
    if not scene:
        return None
    return (scene.get("tier_defs") or {}).get(tier)


def inject_block(scene_key: str | None = None) -> str | None:
    """渲染契约注入块（人类可读 + 来源引用）。加载失败 → None。"""
    data = load()
    if not data:
        return None
    scene_key = scene_key or "generic-binary"
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
    chain = scene.get("downgrade_chain") or _FALLBACK_CHAIN
    lines.append("downgrade chain: " + " -> ".join(chain))
    for tier in chain:
        td = tier_defs.get(tier) or {}
        tools = ", ".join(td.get("tools") or []) or "(per registry)"
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
    """场景嗅探 + 注入块一步到位（dispatch_context 接线面）。"""
    try:
        return inject_block(scene_for(ws))
    except Exception:  # noqa: BLE001 — fail-open: 契约构建永不 raise
        return None
