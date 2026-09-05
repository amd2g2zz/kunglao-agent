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


def _norm_series(hist, total_w):
    """#10 history -> normalized V_m series (per settlement round).

    每条带 v_m 的 history 点换算到 [0,1]：新点直接取 v_norm；legacy 点
    （只有 v_m）按当前 Σweight 推导（best-effort：repin 改权重后旧点为
    近似）。无 v_m 的行（repin 留痕）不入样。Σweight <= 0 → 全 0 序列。
    """
    out = []
    for h in (hist or []):
        if not isinstance(h, dict) or "v_m" not in h:
            continue
        if "v_norm" in h:
            out.append(float(h["v_norm"]))
        else:
            out.append(float(h["v_m"]) / total_w if total_w > 0 else 0.0)
    return out


def cockpit_summary(ws):
    """V/D/ETA 一阶信号（消费 mission_ledger + tuition），结构化 dict。

    #10 单位语义：d_slope / d_slope_norm 均为每结算轮速率（一条 history
    点 = 一轮，无 wall-clock 参与）；d_slope_norm 在归一化序列上取斜率，
    eta_checkpoints 由归一化序列外推（权重稳定时数值与旧口径一致，
    repin 变权后 scale-free）。raw v / d_slope 原样保留（additive）。
    """
    import mission_ledger
    led = mission_ledger.load(ws)
    mission = led.get("mission", {})
    pqs = mission.get("pqs", [])
    total_w = sum(float(p.get("weight", 1.0)) for p in pqs)
    hist = [float(h.get("v_m", 0.0))
            for h in (mission.get("history") or [])]
    norm = _norm_series(mission.get("history"), total_w)
    v = hist[-1] if hist else 0.0
    v_norm = norm[-1] if norm else 0.0
    slope = _slope(hist[-_WINDOW:])
    slope_norm = _slope(norm[-_WINDOW:])
    eta = ((1.0 - v_norm) / slope_norm) if slope_norm > 0 else None
    recs = missions_from_ledger(ws)
    cs_cost = cost_state(ws)
    out = {"v": v, "v_norm": round(v_norm, 6),
           "d_slope": round(slope, 6), "d_slope_norm": round(slope_norm, 6),
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
    # #882: cockpit trio (回溯滞后 / 未归因率 / 提案待审数). Additive +
    # fail-open: an absent backtrack state just ships zeros.
    try:
        from backtrack_loop import cockpit_backtrack
        out["backtrack"] = cockpit_backtrack(ws)
    except Exception:  # noqa: BLE001 — cockpit sampling never raises
        pass
    # #14: sub-PQ progress face (per-PQ credit + difficulty damping).
    # Additive + fail-open: ledger-less or malformed workspaces ship no key
    # rather than breaking the V/D/ETA surface.
    try:
        import mission_ledger as _ml
        out["progress"] = _ml.progress_face(ws)
    except Exception:  # noqa: BLE001 — cockpit sampling never raises
        pass
    return out
