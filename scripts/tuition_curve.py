#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tuition_curve.py — #823-P4 学费曲线聚合器 + 座舱 V/D/ETA 数据面。

全部离线：只消费 ledger（rho_pair 结算行）与 runs/mission_ledger.yaml。
cost 口径（#873 起）：rho_pair 行携带真实 cost（cost_events 最新
amount，会话累计口径）；无 cost 字段的行不入样。stratum 暂固定 "default"。
"""
from __future__ import annotations

import json
from pathlib import Path

_LEDGER = "runs/logs"
_WINDOW = 5


COST_EVENTS = "cost_events.jsonl"
HARD_CAP_DEFAULT = 50.0


def cost_state(ws, hard_cap: float = HARD_CAP_DEFAULT) -> dict:
    """cost_events.jsonl → {"spent","remaining","latest"}（#873 缺口2/3）。

    文件缺失/空 = 零花销；坏行跳过。remaining = hard_cap − spent（下限 0）。
    """
    ws = Path(ws)
    spent = 0.0
    latest = None
    p = ws / COST_EVENTS
    if p.exists():
        for line in p.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            amt = row.get("amount")
            if isinstance(amt, (int, float)):
                spent += float(amt)
                latest = float(amt)
    return {"spent": round(spent, 4),
            "remaining": round(max(hard_cap - spent, 0.0), 4),
            "latest": latest}


def missions_from_ledger(ws):
    """settled rho_pair 行 → mission 记录（z=None / 无 duration 不入样）。"""
    ws = Path(ws)
    rows = []
    for p in sorted((ws / _LEDGER).glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("action") != "rho_pair":
                continue
            d = r.get("detail")
            if isinstance(d, str):
                try:
                    d = json.loads(d)
                except (json.JSONDecodeError, TypeError):
                    continue
            if not isinstance(d, dict) or d.get("z") is None:
                continue
            cost = d.get("cost")
            if cost is None:
                continue  # #873: 无真实 cost 的行不入样（duration 代理已废）
            rows.append({"stratum": "default", "ordinal": len(rows),
                         "cost": float(cost),
                         "passed": float(d["z"]) >= 1.0})
    return rows


def curve(records):
    """按 stratum 聚合：points（按 ordinal 排序）+ n + pass_rate_overall。"""
    by = {}
    for r in records:
        by.setdefault(r["stratum"], []).append(r)
    strata = {}
    for s, rs in by.items():
        rs = sorted(rs, key=lambda r: r["ordinal"])
        n = len(rs)
        pts = [{"ordinal": r["ordinal"], "cost": r["cost"],
                "passed": r["passed"]} for r in rs]
        strata[s] = {"points": pts, "n": n,
                     "pass_rate_overall": round(
                         sum(1 for r in rs if r["passed"]) / n, 4)}
    return {"strata": strata}


def got_cheaper(records, stratum, min_side=2):
    """"第 N 个应比第 1 个便宜"：前半 vs 后半均值，每侧 >= min_side；
    不足返回 None（insufficient，不是 False）。"""
    rs = sorted((r for r in records if r["stratum"] == stratum),
                key=lambda r: r["ordinal"])
    n = len(rs)
    half = n // 2
    if half < min_side:
        return None
    first = sum(r["cost"] for r in rs[:half]) / half
    last = sum(r["cost"] for r in rs[n - half:]) / half
    return last < first


def summarize(data):
    """文本摘要（座舱文本面）。"""
    lines = []
    for s, d in sorted((data or {}).get("strata", {}).items()):
        pts = d.get("points") or []
        first_c = pts[0]["cost"] if pts else 0.0
        last_c = pts[-1]["cost"] if pts else 0.0
        lines.append(f"{s}: n={d['n']} "
                     f"pass_rate={d['pass_rate_overall']} "
                     f"cost {first_c}->{last_c}")
    return "\n".join(lines)


def _slope(ys):
    """末窗线性拟合斜率（下标 0..n-1）。"""
    n = len(ys)
    if n < 2:
        return 0.0
    si = sum(range(n))
    sy = sum(ys)
    si2 = sum(i * i for i in range(n))
    siy = sum(i * y for i, y in enumerate(ys))
    den = n * si2 - si * si
    if den == 0:
        return 0.0
    return (n * siy - si * sy) / den


def cockpit_summary(ws):
    """V/D/ETA 一阶信号（消费 mission_ledger + tuition），结构化 dict。"""
    import mission_ledger
    led = mission_ledger.load(ws)
    mission = led.get("mission", {})
    pqs = mission.get("pqs", [])
    total_w = sum(float(p.get("weight", 1.0)) for p in pqs)
    hist = [float(h.get("v_m", 0.0))
            for h in (mission.get("history") or [])]
    v = hist[-1] if hist else 0.0
    slope = _slope(hist[-_WINDOW:])
    eta = ((total_w - v) / slope) if slope > 0 else None
    recs = missions_from_ledger(ws)
    cs_cost = cost_state(ws)
    return {"v": v, "d_slope": round(slope, 6),
            "eta_checkpoints": eta, "total_weight": total_w,
            "answered": sum(1 for p in pqs if p.get("state") == "answered"),
            "blocked": sum(1 for p in pqs if p.get("state") == "blocked"),
            "unattempted": sum(1 for p in pqs
                               if p.get("state") == "unattempted"),
            "cost": cs_cost["latest"],
            "burn": {"spent": cs_cost["spent"],
                     "remaining": cs_cost["remaining"]},
            "tuition": {"got_cheaper": got_cheaper(recs, "default"),
                        "n_missions": len(recs)}}
