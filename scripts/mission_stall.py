#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mission_stall.py — #634 主线停滞指纹 + PARK 合法化语义。

三件事（蓝图 §7.3）：
  1. stall_mission: ΔV_m=0 连续 K checkpoint AND open_claims>0 —— 与动作级
     零输出指纹互补，专抓"动作各异但主线不动"。特征源 = mission_ledger
     的 V_m history（连续尾段同值）；无欠账表 = 特征不可用，不判停滞。
  2. PARK 合法化：claim 级 PARK 必带非空 wake_condition（park_violations）
     ；revive 把 PARK 翻回 OPEN 并落账 claim_revive。
  3. 提案语义：本模块只检测/标注/落账，不改派发决策（P3 Q 表才消费）。

边界：动作级零输出指纹管"同型动作零产出"（zero_output_fingerprint.py）
；心跳存活面管"进程死活"（#830 侧车）。本模块只看主线值。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

DEFAULT_K = 3
_PARK = "PARK"
_OPEN = "OPEN"


def stall_mission(ws, k: int = DEFAULT_K) -> dict:
    """ΔV_m 连续平坦 >=k 且仍有 open claims → stalled。

    open 计数用 ACTIVE_STATUSES（OPEN/IN_PROGRESS）——PARK 不算 open
    （它已退出派发队列，等待 wake_condition，不算"主线有活"也不算停滞
    的活体证据）。
    """
    from status_defs import ACTIVE_STATUSES
    ws = Path(ws)
    led_path = ws / "runs" / "mission_ledger.yaml"
    hist = []
    if led_path.exists():
        try:
            led = yaml.safe_load(led_path.read_text(encoding="utf-8")) or {}
            hist = led.get("mission", {}).get("history") or []
        except Exception:  # noqa: BLE001 — 特征不可用 → 不判停滞
            hist = []
    flat = 0
    if len(hist) >= 2:
        flat = 1
        for prev, cur in zip(reversed(hist[:-1]), reversed(hist[1:])):
            if float(prev.get("v_m", 0.0)) == float(cur.get("v_m", 0.0)):
                flat += 1
            else:
                break
    reg_path = ws / "claim-register.yaml"
    open_claims = 0
    if reg_path.exists():
        try:
            reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            reg = {}
        for c in (reg.get("claims") or []):
            if (str(c.get("status") or "").upper() in ACTIVE_STATUSES):
                open_claims += 1
    stalled = flat >= k and open_claims > 0
    return {"stalled": stalled, "consecutive_flat": flat, "k": k,
            "open_claims": open_claims,
            "v_m": float(hist[-1].get("v_m", 0.0)) if hist else 0.0}


def park_violations(ws) -> list[str]:
    """PARK claim 无非空 wake_condition → 违规（载体规则 (f) 同源）。"""
    ws = Path(ws)
    reg_path = ws / "claim-register.yaml"
    if not reg_path.exists():
        return []
    try:
        reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return []
    out = []
    for c in (reg.get("claims") or []):
        if str(c.get("status") or "").upper() != _PARK:
            continue
        wake = str(c.get("wake_condition") or "").strip()
        if not wake:
            out.append(str(c.get("id") or "<unknown>")
                       + ": PARK without wake_condition (#634)")
    return out


def revive(ws, claim_id: str, note: str = "") -> dict:
    """PARK → OPEN（复活通道）。落账 claim_revive（#818 schema）。"""
    ws = Path(ws)
    reg_path = ws / "claim-register.yaml"
    reg = yaml.safe_load(reg_path.read_text(encoding="utf-8")) or {}
    hit = None
    for c in (reg.get("claims") or []):
        if str(c.get("id") or "") == str(claim_id):
            hit = c
            break
    if hit is None:
        raise ValueError(f"mission_stall.revive: unknown claim {claim_id!r}")
    if str(hit.get("status") or "").upper() != _PARK:
        raise ValueError(f"mission_stall.revive: claim {claim_id!r} is "
                         f"{hit.get('status')!r}, not PARK")
    hit["status"] = _OPEN
    reg_path.write_text(yaml.safe_dump(reg, allow_unicode=True,
                                       sort_keys=False), encoding="utf-8")
    try:
        import kunglao_log
        kunglao_log.emit(ws, "mission_stall", "claim_revive", claim=str(claim_id),
                         detail=json.dumps({"note": note}, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — 记账失败不拦复活
        pass
    return hit
