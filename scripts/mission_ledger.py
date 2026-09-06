#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mission_ledger.py — #823-P1 主线欠账表 + V_m。

欠账表 = primary_questions × 三态（answered/blocked/unattempted），V_m 锚定
欠账表而非活动量——防傻性质：边角料 claims 全 PROVEN 而与 PQ 零关联时，
V_m 增量严格为 0（测试锚定，蓝图 §7.2）。

Shadow/live 边界（#104 修正，旧文"全程不改任何决策路径"已不准确）；
#107 再修正：priority_ratio 重建为 Thompson 排序后，本账本的派生量
（v_norm/d_slope_norm 及旧排序键首位）不再是任何排序输入——V_m 数据面
（init/value_m/update + cockpit/tuition 消费）保留，独立于排序层。

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
from harness_common import utc_now  # #14 IN_PROGRESS freshness clock (claim_expiry-aligned)
from status_defs import PARTIAL_STATUSES as _PARTIAL_STATUSES  # #14 single source (#34)
from status_defs import IN_PROGRESS_STATUSES as _IN_PROGRESS_STATUSES


# ---- #14 sub-PQ progress granularity ---------------------------------------
# Per-claim credit weights — POLICY constants (values are tunable, not law);
# each carries its one-line rationale.
CREDIT_TERMINAL = 1.0    # PROVEN/VERIFIED settled with stamped evidence — full credit.
CREDIT_PARTIAL = 0.5     # PARTIALLY-VERIFIED: evidence, no independent verification — half.
CREDIT_ACTIVE = 0.25     # IN_PROGRESS with recent activity: work in flight — quarter.
CREDIT_OPEN = 0.0        # OPEN / untouched in-flight: no movement — credit nothing.
ACTIVE_FRESH_HOURS = 24  # "recent" = claim_expiry stale window; past it, in-flight work is dead.
DAMP_HARD = 0.75         # hard tier: damp 25% — an open PQ on hard hides real remaining work.
DAMP_MAX = 0.5           # max tier: strongest damping — max open PQs overstate the most.
DAMP_NONE = 1.0          # easy/medium/unknown/missing: no damping (absence ≠ difficulty, #15).
# settlement-family terminals; others stay 0.0 (PROVEN-only settlement, #69).
_CREDIT_FULL = frozenset({"PROVEN", "VERIFIED"})
_BAR_WIDTH = 10          # progress_report --progress bar cells per PQ row.


def _parse_pqs(task_spec: dict) -> list[dict]:
    """欠账表条目：[{id, question, ...}]，四形状 + 校验合同与 decide 一致。"""
    raw = task_spec.get("primary_questions")
    if raw is None or raw == [] or raw == {}:
        return []
    if not isinstance(raw, list) and not isinstance(raw, dict):
        raise ValueError(
            f"mission_ledger: primary_questions must be list/mapping, "
            f"got {type(raw).__name__}")
    (list(raw.items()) if isinstance(raw, dict)
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


def _claim_last_activity(claim: dict):
    """Single source: claim_expiry.last_activity_for (same field order); lazy
    import keeps mission_ledger importable without the telemetry chain."""
    from claim_expiry import last_activity_for
    return last_activity_for(claim or {})


def claim_credit(claim: dict, now=None) -> float:
    """#14 per-claim credit ladder (pure; constants above carry the rationale).

    PROVEN/VERIFIED → 1.0; PARTIALLY-VERIFIED family → 0.5; IN_PROGRESS with
    recent (or unknown-age) worker activity → 0.25; everything else → 0.0.
    Unknown activity counts as fresh (claim_expiry precedent: unknown age is
    never staleness); other terminal statuses credit 0.0 because settlement
    authority is PROVEN-only (PR #69) — understates rather than overstates.
    """
    st = ((claim or {}).get("status") or "").upper()
    if st in _CREDIT_FULL:
        return CREDIT_TERMINAL
    if st in _PARTIAL_STATUSES:
        return CREDIT_PARTIAL
    if st in _IN_PROGRESS_STATUSES:
        last = _claim_last_activity(claim)
        if last is None:
            return CREDIT_ACTIVE
        ref = now or utc_now()
        age_h = (ref - last).total_seconds() / 3600.0
        if age_h <= ACTIVE_FRESH_HOURS:
            return CREDIT_ACTIVE
    return CREDIT_OPEN


def _damping_for(tier: str | None) -> float:
    """#14 difficulty damping: only hard/max damp; missing/unknown → none."""
    return {"hard": DAMP_HARD, "max": DAMP_MAX}.get(
        (tier or "").lower(), DAMP_NONE)


def pq_progress(pq: dict, claims: list, now=None,
                tier: str | None = None) -> dict:
    """#14 sub-PQ progress (pure, no IO).

    progress = max(1.0 if answered else 0.0, credit / max(1, claim_count)
    × damping). Settlement (state answered, PR #69) stays authoritative at
    exactly 1.0 and is never damped; unresolved PQs earn fractional credit
    from their linked claims (answers_question == pq id) — edge claims with
    no link stay out (the #823 anti-stupid rule, extended). Damping applies
    ONLY to the unresolved fraction on hard/max tiers so remaining work is
    understated, not overstated; missing difficulty → undamped.
    """
    answered = pq.get("state") == "answered"
    linked = [c for c in (claims or [])
              if str(c.get("answers_question") or "") == str(pq.get("id"))]
    credit = sum(claim_credit(c, now) for c in linked)
    frac = credit / max(1, len(linked))
    damping = DAMP_NONE if answered else _damping_for(tier)
    progress = min(max(1.0 if answered else 0.0, frac * damping), 1.0)
    return {"progress": round(progress, 6), "credit": round(credit, 6),
            "claim_count": len(linked), "damping": damping,
            "damped": damping != DAMP_NONE}


def read_difficulty_tier(ws) -> str | None:
    """Difficulty tier for #14 damping: evidence/difficulty.json first, then
    the ``difficulty:`` key difficulty_calibration.mount() copies into
    task_spec.yaml (#16 open-loop contract, both mounts canonical). Missing,
    unreadable, or non-mapping → None (no damping; absence is never scored
    as difficulty — #15 gap rule)."""
    ws = Path(ws)
    doc = None
    p = ws / "evidence" / "difficulty.json"
    if p.exists():
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
    if not isinstance(doc, dict):
        try:
            spec = (yaml.safe_load(
                (ws / "task_spec.yaml").read_text(encoding="utf-8")) or {})
        except (OSError, yaml.YAMLError):
            return None
        doc = spec.get("difficulty") if isinstance(spec, dict) else None
    tier = doc.get("tier") if isinstance(doc, dict) else None
    return str(tier) if tier else None


def progress_face(ws, now=None) -> dict:
    """#14 read-only progress face (no history append, no ledger write).

    {"progress_fraction": Σw·progress/Σw ∈ [0,1] (Σw<=0 → 0.0),
     "per_pq": [{id, state, progress, credit, claim_count, damping,
                 damped, weight}]}. Never raises on a missing claim register
    or difficulty evidence — those degrade to zero-credit / undamped.
    """
    led = load(ws)
    pqs = led.get("mission", {}).get("pqs", [])
    reg = Path(ws) / "claim-register.yaml"
    claims = []
    if reg.exists():
        try:
            claims = ((yaml.safe_load(reg.read_text(encoding="utf-8"))
                       or {}).get("claims")) or []
        except yaml.YAMLError:
            claims = []
    tier = read_difficulty_tier(ws)
    rows = []
    total_w = 0.0
    weighted = 0.0
    for p in pqs:
        w = float(p.get("weight", 1.0))
        row = pq_progress(p, claims, now=now, tier=tier)
        rows.append(dict(id=p.get("id"), state=p.get("state"),
                         weight=w, **row))
        total_w += w
        weighted += w * row["progress"]
    return {"progress_fraction":
            round(weighted / total_w, 6) if total_w > 0 else 0.0,
            "per_pq": rows}


def value_m(ws, now=None) -> dict:
    """V_m + A_t。history 只由此函数追加（增量结算即时入账）。

    #10 归一化（additive，raw 字段原样保留）：
      - v_norm = v_m / Σweight ∈ [0,1]（欠账表条目自带 weight，缺省 1.0；
        未加权工作区 Σweight == len(pqs)；Σweight <= 0 → 0.0，不除零）。
      - a_t_norm = v_norm 的每轮增量（上一 history 点的 v_norm 为基线；
        legacy 点缺 v_norm 时按 prev_v_m/Σweight 推导）。
    单位语义：密度按结算轮计——一次 value_m() 调用 = 一条 history 点 =
    一轮；全程无 wall-clock 参与（墙钟 ETA 由 rho_checkpoint.eta_min /
    statusline tick 面单独承载，不与 V_m 混用）。
    #14 sub-PQ 进度（additive，raw 字段原样保留）：新增顶层
    progress_fraction（Σw·progress/Σw）与 per_pq_progress 列表
    （每行 id/state/weight/progress/credit/claim_count/damping/damped）。
    per_pq 行保持 #10 原样投影（byte-identical 守卫在
    test_vm_normalization_10）——进度绝不写进 raw 面；V_m/A_t 数学原样
    不动——欠账结算仍是唯一权威；``now`` 仅参与 IN_PROGRESS 新鲜度
    分类，不入 V_m 单位。
    """
    led = load(ws)
    beta = float(led.get("mission", {}).get("beta", BETA))
    pqs = led.get("mission", {}).get("pqs", [])
    tier = read_difficulty_tier(ws)
    reg = Path(ws) / "claim-register.yaml"
    claims = []
    if reg.exists():
        try:
            claims = ((yaml.safe_load(reg.read_text(encoding="utf-8"))
                       or {}).get("claims")) or []
        except yaml.YAMLError:
            claims = []
    v_m = 0.0
    total_w = 0.0
    weighted_progress = 0.0
    pq_rows = []
    per_pq = {}
    for p in pqs:
        w = float(p.get("weight", 1.0))
        total_w += w
        cov = float(p.get("coverage", 0.0))
        st = p.get("state")
        contrib = w * cov if st == "answered" else (
            beta * w if st == "blocked" else 0.0)
        v_m += contrib
        row = pq_progress(p, claims, now=now, tier=tier)
        weighted_progress += w * row["progress"]
        pq_rows.append(dict(id=p.get("id"), state=st, weight=w, **row))
        per_pq[str(p.get("id"))] = {"state": st,
                                    "contrib": round(contrib, 6)}
    progress_fraction = (round(weighted_progress / total_w, 6)
                         if total_w > 0 else 0.0)
    v_norm = max(0.0, min(1.0, v_m / total_w)) if total_w > 0 else 0.0
    hist = led.get("mission", {}).get("history") or []
    prev = float(hist[-1].get("v_m", 0.0)) if hist else 0.0
    if hist and "v_norm" in hist[-1]:
        prev_norm = float(hist[-1]["v_norm"])
    else:
        prev_norm = (prev / total_w) if total_w > 0 else 0.0
    a_t = v_m - prev
    a_t_norm = v_norm - prev_norm
    hist.append({"ts": _utc_now(), "v_m": round(v_m, 6),
                 "v_norm": round(v_norm, 6)})
    led["mission"]["history"] = hist
    _save(ws, led)
    n_answered = sum(1 for p in pqs if p.get("state") == "answered")
    n_blocked = sum(1 for p in pqs if p.get("state") == "blocked")
    n_unattempted = sum(1 for p in pqs if p.get("state") == "unattempted"
                        )
    return {"v_m": round(v_m, 6), "prev_v_m": prev, "a_t": round(a_t, 6),
            "v_norm": round(v_norm, 6), "a_t_norm": round(a_t_norm, 6),
            "total_weight": round(total_w, 6),
            "progress_fraction": progress_fraction,
            "per_pq_progress": pq_rows,
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
            # #10 additive: normalized value + per-round normalized delta
            "v_norm": val["v_norm"], "a_t_norm": val["a_t_norm"],
            "total_weight": val["total_weight"],
            # #14 additive: sub-PQ progress aggregate (see value_m)
            "progress_fraction": val["progress_fraction"],
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
