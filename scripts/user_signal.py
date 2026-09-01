# -*- coding: utf-8 -*-
"""user_signal.py — #868 用户信号捕获/分类/路由核心。

原则（issue #868 设计定稿）：用户信号 = 高先验、零真值特权。
本体三类路由（分类只做路由，不做使用资格过滤——分错不丢信号，
一级兜底 = 全量进上下文）：
  volition（意愿：goal/pref/constraint）→ 主权域，自动生效 + 可撤销
  factual（事实断言：fix/因果）        → 双门立案（scripts/dual_gate.py）
  meta / unrouted                      → 只记录（一级兜底）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

import kunglao_log
import mission_ledger as ml

SIGNALS_DIR = "runs/user-signals"

_PREFIX_RE = re.compile(r"^\[(goal|pref|constraint|fix)\]\s*", re.IGNORECASE)
_VOLITION_ROUTES = {"goal", "pref", "constraint"}
_KW_VOLITION = ("目标", "优先", "才算", "改目标", "重排", "换目标")
_KW_FACTUAL = ("不是", "错了", "应改", "证伪", "复现失败", "是因为",
               "看错了", "方向不对")
_KW_META = ("少给我", "别再", "避免输出")


# ---------- 分类 ----------

def classify(text: str) -> dict:
    """本体三类路由。classified_by ∈ {prefix, keyword, fallback}；
    fallback = 未识别（unrouted）——仍落账（一级兜底），仅不路由。"""
    text = str(text)
    m = _PREFIX_RE.match(text.strip())
    if m:
        route = m.group(1).lower()
        return {"ontype": "volition" if route in _VOLITION_ROUTES else
                "factual",
                "route": route, "classified_by": "prefix",
                "payload": _PREFIX_RE.sub("", text.strip(), count=1)}
    low = text.lower()
    if any(k in text for k in _KW_FACTUAL):
        return {"ontype": "factual", "route": "fix",
                "classified_by": "keyword", "payload": text}
    if any(k in text for k in _KW_VOLITION):
        return {"ontype": "volition", "route": "goal",
                "classified_by": "keyword", "payload": text}
    if any(k in text for k in _KW_META):
        return {"ontype": "meta", "route": "meta",
                "classified_by": "keyword", "payload": text}
    return {"ontype": "unrouted", "route": "unrouted",
            "classified_by": "fallback", "payload": text}


# ---------- 落账 + 记录 ----------

def _emit(ws, action, sig, extra=None):
    detail = {"signal_class": sig.get("ontype"),
              "route": sig.get("route"),
              "classified_by": sig.get("classified_by"),
              "text_digest": str(sig.get("payload", ""))[:120]}
    if extra:
        detail.update(extra)
    kunglao_log.emit(ws, actor="user", action=action,
                     detail=json.dumps(detail, ensure_ascii=False))


def _next_sig_id(ws) -> str:
    d = Path(ws) / SIGNALS_DIR
    top = 0
    if d.is_dir():
        for p in d.glob("sig-*.json"):
            try:
                top = max(top, int(p.stem.split("-")[-1]))
            except ValueError:
                continue
    return f"sig-{top + 1:03d}"


def _save_signal(ws, sig: dict, extra: dict) -> str:
    sig_id = _next_sig_id(ws)
    d = Path(ws) / SIGNALS_DIR
    d.mkdir(parents=True, exist_ok=True)
    rec = {"id": sig_id, "ontype": sig["ontype"], "route": sig["route"],
           "classified_by": sig["classified_by"],
           "payload_digest": str(sig.get("payload", ""))[:200],
           **extra}
    (d / f"{sig_id}.json").write_text(
        json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    return sig_id


# ---------- 意愿域：自动生效 + 可撤销 ----------

_KV_RE = re.compile(r"(add|remove)\s*=\s*([^;]+)", re.IGNORECASE)


def _parse_repin_payload(payload: str):
    add, remove = [], []
    for k, v in _KV_RE.findall(payload or ""):
        for frag in v.split(","):
            m = re.match(r"\s*(\S+)", frag)
            if m:
                (add if k.lower() == "add" else remove).append(m.group(1))
    return (add, remove) if (add or remove) else (None, None)


def apply_volition(ws, sig: dict) -> dict:
    """意愿域：可机器解析的 re-pin 指令立即生效（最后者赢，历史留痕，
    可再 re-pin 撤销）；不可解析 → 只记录（pending_signals 可见）。"""
    add, remove = _parse_repin_payload(sig.get("payload", ""))
    out = {"applied": False}
    if add is not None:
        ml.repin(ws, add=add, remove=remove)
        out = {"applied": True, "add": add, "remove": remove}
        # task_spec value_frame 追加（append-only 留痕）
        ts_path = Path(ws) / "task_spec.yaml"
        if ts_path.exists():
            try:
                ts = yaml.safe_load(ts_path.read_text(encoding="utf-8")) or {}
                vf = ts.setdefault("value_frame", [])
                vf.append({"ts": sig.get("signal_id", ""),
                           "add": add, "remove": remove})
                ts_path.write_text(yaml.safe_dump(ts, allow_unicode=True,
                                                  sort_keys=False),
                                   encoding="utf-8")
            except (OSError, yaml.YAMLError):
                pass
    sig_id = _save_signal(ws, sig, {"applied": out["applied"]})
    out["signal_id"] = sig_id
    _emit(ws, "user_signal", sig)
    _emit(ws, "user_signal_processed", sig,
          {"applied": out["applied"], "signal_id": sig_id})
    return out


# ---------- 事实域：双门立案 ----------

def file_factual(ws, sig: dict) -> dict:
    """事实域：立案进双门（scripts/dual_gate.py）——redteam 找反例 +
    verifier 正向核验，全票才采信。"""
    import dual_gate
    sig_id = _save_signal(ws, sig, {"queued": True})
    case_id = dual_gate.open_case(
        ws, f"user-{sig_id}",
        str(sig.get("payload", ""))[:200], source="user")
    _emit(ws, "user_signal", sig, {"signal_id": sig_id, "case_id": case_id})
    _emit(ws, "user_signal_processed", sig,
          {"applied": False, "queued_dual_gate": True,
           "signal_id": sig_id, "case_id": case_id})
    return {"signal_id": sig_id, "case_id": case_id}


# ---------- 通用入口（hook 调这个）----------

def ingest(ws, prompt: str) -> dict:
    """hook 唯一入口：分类 → 路由 → 落账。任何异常由调用方双笼。"""
    sig = classify(prompt)
    if sig["ontype"] == "volition":
        return {"ontype": "volition", **apply_volition(ws, sig)}
    if sig["ontype"] == "factual":
        return {"ontype": "factual", **file_factual(ws, sig)}
    # meta / unrouted：一级兜底——只记录（进上下文的账本可见），不路由
    sig_id = _save_signal(ws, sig, {"routed": False})
    _emit(ws, "user_signal", sig, {"signal_id": sig_id})
    return {"ontype": sig["ontype"], "signal_id": sig_id,
            "routed": False}


# ---------- 座舱数据面 ----------

def cockpit_face(ws) -> dict:
    """pending_signals + 最近信号（用户可见自己信号被如何对待）。"""
    dg_dir = Path(ws) / "runs" / "dual-gate"
    pending = 0
    recent = []
    if dg_dir.is_dir():
        for p in sorted(dg_dir.glob("*.json")):
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
    sg_dir = Path(ws) / SIGNALS_DIR
    if sg_dir.is_dir():
        for p in sorted(sg_dir.glob("sig-*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if s.get("ontype") == "unrouted":
                pending += 1
    recent.sort(key=lambda e: e.get("case_id") or "")
    return {"pending_signals": pending, "recent": recent[-5:]}
