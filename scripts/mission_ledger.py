#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mission_ledger.py — #823-P1 主线欠账表 + V_m（shadow 形态）。

欠账表 = primary_questions × 三态（answered/blocked/unattempted），V_m 锚定
欠账表而非活动量——防傻性质：边角料 claims 全 PROVEN 而与 PQ 零关联时，
V_m 增量严格为 0（测试锚定，蓝图 §7.2）。本模块 shadow：只计算+落盘，
不改任何决策路径（decide/priority 行为改动属 P3）。

PQ 解析复用 convergence_check._parse_primary_questions（单一解析合同，
canonical/legacy/string/mapping 四形状），文本取自原始条目。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

BETA = 0.3
_LEDGER_REL = "runs/mission_ledger.yaml"
_TERMINAL_STAMPED = {"PROVEN"}


from harness_common import utc_now_z as _utc_now  # #863 Family F: single source (was a local def)


def _parse_pqs(task_spec: dict) -> list[dict]:
    """欠账表条目：[{id, question, ...}]，四形状 + 校验合同与 decide 一致。"""
    raw = task_spec.get("primary_questions")
    if raw is None or raw == [] or raw == {}:
        return []
    if not isinstance(raw, list) and not isinstance(raw, dict):
        raise ValueError(
            f"mission_ledger: primary_questions must be list/mapping, "
            f"got {type(raw).__name__}")
    items = (list(raw.items()) if isinstance(raw, dict)
             else list(enumerate(raw)))
    pqs = []
    if isinstance(raw, dict):
        for k, v in raw.items():
            if not isinstance(k, str) or not k:
                raise ValueError(f"mission_ledger: bad PQ key {k!r}")
            pqs.append({"id": k, "question": v if isinstance(v, str) else k})
        return pqs
    # 列表形状：校验合同复用 convergence_check（含 legacy one-key/canonical）
    from convergence_check import _parse_primary_questions as _ppq
    questions, err = _ppq({"primary_questions": raw})
    if err:
        raise ValueError("mission_check: " + err.replace(
            "primary_questions", "mission primary_questions"))
    for item, (qid, need) in zip(raw, questions):
        if isinstance(item, str):
            pqs.append({"id": qid, "question": item})
        elif isinstance(item, dict):
            text = (item.get("question") or item.get("q")
                    or need or qid)
            pqs.append({"id": qid, "question": text})
    return pqs


def init(ws, task_spec: dict | None = None) -> dict:
    """从 primary_questions 机械生成欠账表（幂等：已存在则拒绝重写）。"""
    ws = Path(ws)
    if task_spec is None:
        p = ws / "task_spec.yaml"
        task_spec = (yaml.safe_load(p.read_text(encoding="utf-8"))
                     if p.exists() else {})
    task_spec = task_spec or {}
    pqs = _parse_pqs(task_spec)
    led = {
        "mission": {
            "pqs": [dict(p, state="unattempted", coverage=0.0,
                         answered_by=[], blocker=None, wake=None,
                         weight=1.0) for p in pqs],
            "beta": BETA,
            "history": [],
            "feature_used": bool(pqs),
        }
    }
    dest = ws / _LEDGER_REL
    if dest.exists():
        raise FileExistsError(f"mission_ledger already initialized: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(yaml.safe_dump(led, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return led


def load(ws) -> dict:
    return yaml.safe_load(
        (Path(ws) / _LEDGER_REL).read_text(encoding="utf-8")) or {}


def _save(ws, led: dict) -> None:
    (Path(ws) / _LEDGER_REL).write_text(
        yaml.safe_dump(led, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _pq(led: dict, pq_id: str) -> dict:
    for p in led.get("mission", {}).get("pqs", []):
        if str(p.get("id")) == str(pq_id):
            return p
    raise ValueError(f"mission_ledger: unknown PQ id {pq_id!r}")


def update(ws) -> dict:
    """PROVEN claim 的 answers_question 归属 → PQ answered/coverage 1.0。

    幂等：重复 update 不改状态（history 只由 value_m 追加）。
    """
    led = load(ws)
    reg_path = Path(ws) / "claim-register.yaml"
    reg = (yaml.safe_load(reg_path.read_text(encoding="utf-8"))
           if reg_path.exists() else {}) or {}
    for c in (reg.get("claims") or []):
        if (c.get("status") or "").upper() not in _TERMINAL_STAMPED:
            continue
        aq = c.get("answers_question")
        if not aq:
            continue
        try:
            pq = _pq(led, aq)
        except ValueError:
            continue  # 未知 PQ 引用：不计入（边角料归属不入账）
        pq["state"] = "answered"
        pq["coverage"] = 1.0
        pq["blocker"] = None
        pq["wake"] = None
        if c.get("id") not in (pq.get("answered_by") or []):
            pq.setdefault("answered_by", []).append(c.get("id"))
    _save(ws, led)
    return led


def mark_blocked(ws, pq_id: str, blocker: str, wake: str) -> dict:
    """blocked 必带 blocker + wake_condition（蓝图 §7.1），缺失即拒绝。"""
    if not (blocker and str(blocker).strip()):
        raise ValueError("mission_ledger.mark_blocked: blocker required")
    if not (wake and str(wake).strip()):
        raise ValueError("mission_ledger.mark_blocked: wake_condition required")
    led = load(ws)
    pq = _pq(led, pq_id)
    if pq.get("state") == "answered":
        raise ValueError(f"mission_ledger: PQ {pq_id!r} already answered; "
                         f"blocked mark refused")
    pq["state"] = "blocked"
    pq["blocker"] = str(blocker)
    pq["wake"] = str(wake)
    pq["coverage"] = 0.0
    _save(ws, led)
    return led


def value_m(ws) -> dict:
    """V_m + A_t。history 只由此函数追加（增量结算即时入账）。"""
    led = load(ws)
    beta = float(led.get("mission", {}).get("beta", BETA))
    pqs = led.get("mission", {}).get("pqs", [])
    v_m = 0.0
    per_pq = {}
    for p in pqs:
        w = float(p.get("weight", 1.0))
        cov = float(p.get("coverage", 0.0))
        st = p.get("state")
        contrib = w * cov if st == "answered" else (
            beta * w if st == "blocked" else 0.0)
        v_m += contrib
        per_pq[str(p.get("id"))] = {"state": st,
                                    "contrib": round(contrib, 6)}
    hist = led.get("mission", {}).get("history") or []
    prev = float(hist[-1].get("v_m", 0.0)) if hist else 0.0
    a_t = v_m - prev
    hist.append({"ts": _utc_now(), "v_m": round(v_m, 6)})
    led["mission"]["history"] = hist
    _save(ws, led)
    n_answered = sum(1 for p in pqs if p.get("state") == "answered")
    n_blocked = sum(1 for p in pqs if p.get("state") == "blocked")
    n_unattempted = sum(1 for p in pqs if p.get("state") == "unattempted"
                        )
    return {"v_m": round(v_m, 6), "prev_v_m": prev, "a_t": round(a_t, 6),
            "per_pq": per_pq, "answered": n_answered,
            "blocked": n_blocked, "unattempted": n_unattempted}


def emit_snapshot(ws, epoch: int | None = None, arm: str | None = None,
                  hypothesis_ref: str | None = None) -> None:
    """mission 覆盖快照走 #818 schema（version 自动 git SHA）。Never-raises
    语义继承 kunglao_log.emit（写失败降级 stderr）。"""
    try:
        import kunglao_log
        val = value_m(ws)
        detail = json.dumps({
            "v_m": val["v_m"], "prev_v_m": val["prev_v_m"],
            "a_t": val["a_t"], "answered": val["answered"],
            "blocked": val["blocked"], "unattempted": val["unattempted"],
        }, ensure_ascii=False)
        kunglao_log.emit(ws, "mission_ledger", "mission_snapshot",
                         detail=detail, arm=arm, epoch=epoch,
                         hypothesis_ref=hypothesis_ref)
    except Exception as exc:  # noqa: BLE001 — snapshot 永不打断主流程
        import sys
        print(f"[mission_ledger] snapshot degraded: {exc}", file=sys.stderr)


def repin(ws, add=(), remove=(), note: str | None = None) -> dict:
    """#868 意愿类信号：欠账表 delta re-pin（最后者赢，历史留痕）。

    已答 PQ 不被重置；remove 连同其作答一并移除；add 幂等（已存在跳过）。
    """
    led = load(ws)
    mission = led.get("mission", {})
    pqs = mission.get("pqs", [])
    for rid in remove:
        pqs[:] = [p for p in pqs if str(p.get("id")) != str(rid)]
    existing = {str(p.get("id")) for p in pqs}
    for pid in add:
        if str(pid) in existing:
            continue
        pqs.append(dict(id=str(pid), question=str(pid), state="unattempted",
                        coverage=0.0, answered_by=[], blocker=None,
                        wake=None, weight=1.0))
        existing.add(str(pid))
    mission.setdefault("history", []).append({
        "ts": _utc_now(), "action": "repin",
        "add": [str(a) for a in add], "remove": [str(r) for r in remove],
        "note": note})
    _save(ws, led)
    return led
