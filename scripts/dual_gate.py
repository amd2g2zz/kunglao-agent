# -*- coding: utf-8 -*-
"""dual_gate.py — #868 双门验证引擎（worker claim 与用户事实信号对称）。

Redteam（对抗/证伪：本体证伪 + 归因证伪）与 Verifier（正向/求证）并行，
全票通过才有效。文献锚点：CEGAR（合作精化器全披露反例收敛最优）、
强 Goodhart（Sohl-Dickstein：对披露反例的优化压力 → held-out 复检
机制）、weak-to-strong（Kenton：通过裁决必须携带搜索边界声明）、
#825（双门不可同一身份投票）。

宪法隔离：本引擎只产出裁决/升级建议（runs/dual-gate/*.json + ledger
事件），绝不直接改写 claim-register 终态。
"""
from __future__ import annotations

import json
from pathlib import Path

import kunglao_log

CASE_DIR = "runs/dual-gate"
MAX_REPLANS = 3          # #868: replan 超限 → 升级 PARK 建议
HELD_OUT_N = 1           # 默认扣留 1 条反例作 held-out 复检


# ---------- 状态 IO ----------

def _case_path(ws, case_id: str) -> Path:
    return Path(ws) / CASE_DIR / f"{case_id}.json"


def _load(ws, case_id) -> dict:
    return json.loads(
        _case_path(ws, case_id).read_text(encoding="utf-8"))


def _save(ws, case: dict) -> dict:
    p = _case_path(ws, case["case_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(case, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return case


def _emit(ws, action, case, extra=None):
    detail = {"case_id": case["case_id"], "status": case.get("status"),
              "disclosure_mode": case.get("disclosure_mode")}
    if extra:
        detail.update(extra)
    kunglao_log.emit(ws, actor="dual_gate", action=action,
                     detail=json.dumps(detail, ensure_ascii=False))


# ---------- 生命周期 ----------

def open_case(ws, case_id: str, assertion: str, source: str = "user") -> str:
    if _case_path(ws, case_id).exists():
        raise FileExistsError(f"dual-gate case exists: {case_id}")
    _save(ws, {"case_id": case_id, "source": source,
               "assertion": str(assertion)[:300], "status": "open",
               "redteam": None, "verifier": None, "replans": 0,
               "disclosure_mode": None, "goodhart": False,
               "escalated": False, "search_boundary": None,
               "invalid_reason": None, "history": []})
    return case_id


def file_redteam(ws, case_id: str, *, identity: str,
                 counterexamples=(), search_boundary: str = "",
                 held_out_n: int = HELD_OUT_N) -> dict:
    """对抗门：反例清单（本体/归因两类）+ 搜索边界声明（强制）。
    反例切分：disclosed（给精炼方）/ held_out（扣留复检）。"""
    if not identity:
        raise ValueError("redteam verdict requires verifier-identity (#825)")
    case = _load(ws, case_id)
    ces = [dict(c) for c in counterexamples]
    # 单反例不扣留（否则 CEGAR 无精炼燃料）；扣留至多一半
    n_hold = min(held_out_n, len(ces) // 2) if ces else 0
    held = ces[-n_hold:] if n_hold > 0 else []
    disclosed = ces[:-n_hold] if held else ces
    case["redteam"] = {"identity": identity,
                       "counterexamples": ces,
                       "disclosed": disclosed, "held_out": held,
                       "search_boundary": str(search_boundary)}
    case["history"].append({"event": "redteam_filed",
                            "found": len(ces),
                            "held_out": len(held)})
    _emit(ws, "signal_gate_reject" if ces else "signal_gate_pass",
          case, {"gate": "redteam"})
    return _save(ws, case)


def file_verifier(ws, case_id: str, *, identity: str,
                  evidence_refs=(), findings: str = "") -> dict:
    """正向门：证据链正向核验（机械可查引用），身份绑定强制。"""
    if not identity:
        raise ValueError("verifier verdict requires verifier-identity (#825)")
    case = _load(ws, case_id)
    case["verifier"] = {"identity": identity,
                        "evidence_refs": [str(e) for e in evidence_refs],
                        "findings": str(findings)[:300]}
    case["history"].append({"event": "verifier_filed",
                            "evidence": len(case["verifier"]["evidence_refs"])})
    _emit(ws, "signal_gate_pass" if case["verifier"]["evidence_refs"]
          else "signal_gate_reject", case, {"gate": "verifier"})
    return _save(ws, case)


# ---------- 全票裁决 ----------

def resolve(ws, case_id: str) -> dict:
    """全票：双门齐 + 异票（#825）+ 边界声明 + 正向证据 → passed；
    任一不满足 → rejected，按失败签名分流披露模式。"""
    case = _load(ws, case_id)
    rt, vf = case.get("redteam"), case.get("verifier")
    if not rt or not vf:
        case["history"].append({"event": "resolve_incomplete"})
        return _save(ws, case)
    if rt["identity"] == vf["identity"]:
        case["invalid_reason"] = ("dual-gate same-identity vote (#825): "
                                  f"{rt['identity']}")
        case["status"] = "invalid"
        case["history"].append({"event": "invalid_same_identity"})
        _emit(ws, "signal_gate_reject", case, {"reason": "same_identity"})
        return _save(ws, case)
    rt_pass = (not rt["counterexamples"]) and rt["search_boundary"].strip()
    vf_pass = bool(vf["evidence_refs"])
    if rt_pass and vf_pass:
        case["status"] = "passed"
        case["search_boundary"] = rt["search_boundary"]
        case["history"].append({"event": "passed",
                                "search_boundary": rt["search_boundary"]})
        _emit(ws, "signal_gate_pass", case)
        return _save(ws, case)
    # 驳回 → 失败签名分流
    case["status"] = "rejected"
    if case.get("goodhart"):
        case["disclosure_mode"] = "minimal"   # 对抗模式：最小信号
    else:
        case["disclosure_mode"] = "cegar_full"  # 诚实失败：全披露精炼
    case["history"].append({
        "event": "rejected",
        "boundary_missing": not rt["search_boundary"].strip(),
        "disclosure_mode": case["disclosure_mode"]})
    _emit(ws, "signal_gate_reject", case,
          {"disclosure_mode": case["disclosure_mode"]})
    return _save(ws, case)


# ---------- replan / held-out 复检 / 升级 ----------

def replan(ws, case_id: str) -> dict:
    """强制换路径（拒绝后必调）：计数 +1；N 超限 → 升级 PARK 建议。"""
    case = _load(ws, case_id)
    case["replans"] = int(case.get("replans", 0)) + 1
    case["history"].append({"event": "replan_mandated",
                            "count": case["replans"]})
    if case["replans"] >= MAX_REPLANS and not case.get("escalated"):
        case["escalated"] = True
        case["history"].append({"event": "escalated_park_recommended"})
        _emit(ws, "signal_gate_escalate", case, {"reason": "replan_limit"})
    return _save(ws, case)


def refire_held_out(ws, case_id: str, *, still_failing: bool) -> dict:
    """replan 后扣留反例复检：仍炸 = Goodhart 实锤（对披露项的优化
    压力没有解决真问题）→ 对抗模式 + 升级。"""
    case = _load(ws, case_id)
    if still_failing and (case.get("redteam") or {}).get("held_out"):
        case["goodhart"] = True
        case["disclosure_mode"] = "minimal"
        case["escalated"] = True
        case["history"].append({"event": "goodhart_confirmed_held_out"})
        _emit(ws, "signal_gate_escalate", case, {"reason": "goodhart"})
    return _save(ws, case)


# ---------- 座舱数据面 ----------

def cockpit_face(ws) -> dict:
    """pending_signals + 最近案件结算状态（用户可见信号被如何对待）。"""
    d = Path(ws) / CASE_DIR
    pending, recent = 0, []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                c = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if c.get("status") in ("open", "rejected"):
                pending += 1
            recent.append({"case_id": c.get("case_id"),
                           "verdict": c.get("status"),
                           "disclosure_mode": c.get("disclosure_mode"),
                           "escalated": c.get("escalated", False)})
    recent.sort(key=lambda e: e.get("case_id") or "")
    return {"pending_signals": pending, "recent": recent[-5:]}
