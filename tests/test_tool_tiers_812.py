# -*- coding: utf-8 -*-
"""tests/test_tool_tiers_812.py — #812 工具族档位表契约测试。

对数据文件与契约注入断言（非 LLM 行为）：
  D1 schema 合法性：链上每档都已定义；链 ⊆ tiers 词表
  D2 xlarge dex 场景：降级链完整（full→targeted→structured→text），
     full 档带前置条件（mem_budget_ok）+ 硬顶（timeout/xmx）
  D3 targeted 档携带 C-006 实录手法（classes-to-decompile / baksmali xref）
  D4 混淆先验适配：renamed_symbols 先验 → structured 先行
  D5 未知场景 fallback：只有档位词汇，不发明工具名
  C1 dispatch 契约注入：build_dispatch_context 带 tool_tiers 可选键，
     validate_context_shape 接受；加载器失败 → 键缺席
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tool_tiers as tt  # noqa: E402


def _load():
    data = tt.load()
    assert data, "tool_tiers.yaml must load"
    return data


# ---------- D1 schema ----------

def test_d1_schema_valid():
    data = _load()
    tiers = set(data["tiers"])
    for key, scene in data["scenes"].items():
        chain = scene.get("downgrade_chain") or []
        assert chain, f"scene {key}: downgrade_chain required"
        assert set(chain) <= tiers, f"scene {key}: chain ⊄ tiers"
        for t in chain:
            assert t in (scene.get("tier_defs") or scene.get("tiers")
                         or {}), f"scene {key}: tier {t} in chain undefined"


def test_d2_xlarge_chain_complete():
    scene = _load()["scenes"]["android-dex-static"]
    chain = scene["downgrade_chain"]
    assert chain == ["full", "targeted", "structured", "text"]
    full = scene["tier_defs"]["full"]
    assert "mem_budget_ok" in (full.get("preconditions") or [])
    caps = full.get("caps") or {}
    assert caps.get("timeout_s") and caps.get("xmx_gb"), caps


# ---------- D3 C-006 field wisdom ----------

def test_d3_targeted_carries_c006_practices():
    scene = _load()["scenes"]["android-dex-static"]
    targeted = scene["tier_defs"]["targeted"]
    blob = yaml.safe_dump(targeted, allow_unicode=True)
    assert "classes-to-decompile" in blob
    assert "baksmali" in blob


def test_d4_obfuscation_prior_adapts():
    scene = _load()["scenes"]["android-dex-static"]
    prior = scene.get("obfuscation_prior") or {}
    entry = prior.get("renamed_symbols") or {}
    blob = yaml.safe_dump(entry, allow_unicode=True)
    assert "structured" in blob.lower()


# ---------- D5 unknown scene fallback ----------

def test_d5_unknown_scene_fallback():
    chain = tt.chain_for("no-such-scene-xyz")
    assert chain == ["full", "targeted", "structured", "text"]
    # fallback 不发明工具名：各档 tools 为空或缺失
    entry = tt.tier_entry("no-such-scene-xyz", "full")
    assert not (entry or {}).get("tools"), \
        "fallback tiers must not invent tool names"


# ---------- C1 dispatch contract ----------

def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": "C-1", "status": "OPEN"}]},
                       allow_unicode=True), encoding="utf-8")
    return ws


def _build_ctx(ws: Path) -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    import dispatch_context as dc
    return dc.build_dispatch_context(
        ws=ws, claim_id="C-1", tier=2, tools=["strings"], agent_name="x")


def test_c1_contract_carries_tool_tiers(tmp_path):
    ws = _mk_ws(tmp_path)
    ctx = _build_ctx(ws)
    assert "tool_tiers" in ctx, "dispatch contract must carry tool_tiers"
    block = ctx["tool_tiers"]
    assert isinstance(block, str) and "downgrade chain" in block.lower()
    dc = sys.modules["dispatch_context"]
    dc.validate_context_shape(ctx)  # optional key accepted


def test_c1_loader_failure_key_absent(tmp_path, monkeypatch):
    ws = _mk_ws(tmp_path)
    monkeypatch.setattr(tt, "load", lambda: None)
    import dispatch_context as dc
    ctx = dc.build_dispatch_context(
        ws=ws, claim_id="C-1", tier=2, tools=["strings"], agent_name="x")
    assert "tool_tiers" not in ctx, "loader failure → key absent"


def test_c1_inject_renders_block(tmp_path):
    ws = _KUNGLAO_TMP = _mk_ws(tmp_path)
    block = tt.inject_block("android-dex-static")
    assert isinstance(block, str) and "downgrade" in block.lower()
    assert "#670" in block or "#812" in block  # source citation carried
