#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plan_stages.py — #822 plan 工件阶段模型 + BIG_BANG 检测 + 盘点裁决回路。

工件 runs/plan-stages.yaml：stages[]（结构见 validate）+ reviews[]（盘点史）。

规则（校验面 fail-closed，--check 非零退出）：
  BIG_BANG_PLAN: yaml 缺失 / 活跃 stage ≤1 / global_plan.txt 仍为 init stub。
  盘点裁决: adjust/replan 必带 trigger reason；replan 必须携带替换 stages。
  裁决 = yaml reviews[] 追加 + runs/plan-review-<ts>.md + ledger plan_review
  事件（EMIT_ACTIONS 注册，字母序）。

PARK 前置重规划与 drift→replan 的 convergence 接线为后继 hook 点（proposal
Impact 节记录），本模块提供 should_review()/review() API。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ARTIFACT = "runs/plan-stages.yaml"
PLAN_STUB_MARK = "# global_plan — kunglao-init v1 stub"
_REQUIRED = ("id", "name", "goal", "claims", "expected_evidence",
             "exit_criteria")
_STATUSES = ("pending", "active", "done", "dropped")
_VERDICTS = ("maintain", "adjust", "replan")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load(ws) -> dict:
    """读取 stage 工件；缺失返回空骨架（不视为错误——check 面才裁决）。"""
    ws = Path(ws)
    data = yaml.safe_load(
        (ws / ARTIFACT).read_text(encoding="utf-8")) if (
        ws / ARTIFACT).exists() else {}
    data = data if isinstance(data, dict) else {}
    data.setdefault("stages", [])
    data.setdefault("reviews", [])
    return data


def write_stages(ws, stages: list) -> None:
    """写入 stages[]（保留 reviews[]）。"""
    ws = Path(ws)
    data = load(ws)
    data["stages"] = stages
    p = ws / ARTIFACT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")


def validate(data: dict) -> dict:
    """stage 结构校验（机器可校验合同）。"""
    violations = []
    seen = set()
    for i, s in enumerate(data.get("stages") or []):
        sid = str(s.get("id") or "").strip()
        for f in _REQUIRED:
            if not str(s.get(f) or "").strip():
                violations.append(
                    f"stage[{i}] ({sid or '<missing id>'}): missing "
                    f"required field '{f}'")
        st = s.get("status") or "pending"
        if st not in _STATUSES:
            violations.append(
                f"stage {sid}: illegal status {st!r} "
                f"(allowed: {', '.join(_STATUSES)})")
        if sid and sid in seen:
            violations.append(f"stage id duplicate: {sid}")
        if sid:
            seen.add(sid)
    return {"ok": not violations, "violations": violations}


def check(ws) -> dict:
    """plan 校验面：结构校验 + BIG_BANG_PLAN 检测（fail-closed）。"""
    ws = Path(ws)
    data = load(ws)
    violations = list(validate(data)["violations"])
    p = ws / ARTIFACT
    active = [s for s in data.get("stages", [])
              if (s.get("status") or "pending") != "dropped"]
    plan_txt = ""
    gp = ws / "global_plan.txt"
    if gp.exists():
        try:
            plan_txt = gp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    has_model = p.exists() and len(active) >= 2
    if not p.exists():
        violations.append("BIG_BANG_PLAN: " + ARTIFACT + " missing - "
                          "plan has no stage model (#822)")
    elif len(active) <= 1:
        violations.append(
            "BIG_BANG_PLAN: only " + str(len(active)) + " active stage(s) "
            "- cold-start plan covers all work in one stage (#822)")
    if not has_model and plan_txt.strip().startswith(PLAN_STUB_MARK):
        violations.append(
            "BIG_BANG_PLAN: global_plan.txt is still the init stub (#822)")
    return {"ok": not violations, "violations": violations}


def review(ws, verdict, stage_id, reason="", new_stages=None) -> dict:
    """盘点裁决三选一并落盘。adjust/replan 必带 reason；replan 必带替换
    stages（validate 过检才写入）。返回 {ok, violations[]}。"""
    ws = Path(ws)
    verdict = (verdict or "").strip()
    stage_id = (stage_id or "").strip()
    reason = (reason or "").strip()
    if verdict not in _VERDICTS:
        return {"ok": False, "violations": [
            "illegal verdict %r (allowed: %s)"
            % (verdict, ", ".join(_VERDICTS))]}
    violations = []
    data = load(ws)
    stages = data.get("stages") or []
    stage = next((s for s in stages if s.get("id") == stage_id), None)
    if stage is None:
        stage = next((s for s in stages
                      if (s.get("status") or "") == "active"), None)
    if stage is None:
        violations.append("no stage %r and no active stage" % stage_id)
        return {"ok": False, "violations": violations}
    if verdict in ("adjust", "replan") and not reason:
        violations.append("verdict %s requires a trigger reason (#822)"
                          % verdict)
    if verdict == "replan":
        if not new_stages:
            violations.append(
                "verdict replan requires replacement stages (#822)")
        else:
            violations.extend(
                validate({"stages": new_stages})["violations"])
    if violations:
        return {"ok": False, "violations": violations}
    return _commit_review(ws, data, stage, verdict, reason, new_stages)


def _commit_review(ws, data, stage, verdict, reason, new_stages) -> dict:
    """裁决三落盘：yaml reviews[] + runs/plan-review-<ts>.md + ledger 事件。"""
    ts = _utc_now()
    entry = {"ts": ts, "verdict": verdict, "stage_id": stage["id"],
             "reason": reason}
    if verdict == "replan":
        data["stages"] = new_stages
        entry["stages_replaced"] = True
    data.setdefault("reviews", []).append(entry)
    p = ws / ARTIFACT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    doc = ws / "runs" / ("plan-review-%s.md"
                         % ts.replace(":", "").replace("-", ""))
    doc.write_text(
        "# plan review %s\n\n- verdict: %s\n- stage: %s\n- reason: %s\n"
        % (ts, verdict, stage["id"], reason or "(maintain - no reason "
           "required)"), encoding="utf-8")
    import kunglao_log
    kunglao_log.emit(ws, actor="orchestrator", action="plan_review",
                     claim=stage["id"], artifact=doc.name,
                     detail=json.dumps({"verdict": verdict,
                                        "reason": reason},
                                       ensure_ascii=False))
    return {"ok": True, "violations": []}


def should_review(ws, rounds_since_review=0, k_threshold=6) -> dict:
    """盘点触发信号（供 convergence/heartbeat 调用的纯 API）：距上次盘点
    ≥K checkpoint 或从不曾盘点 → due。PARK 前置重规划接线的判定面。"""
    ws = Path(ws)
    data = load(ws)
    reviews = data.get("reviews") or []
    active = [s for s in data.get("stages", [])
              if (s.get("status") or "") != "dropped"]
    if not reviews:
        return {"due": bool(active), "why": "never reviewed with active "
                "stages" if active else "no stages"}
    return {"due": rounds_since_review >= k_threshold,
            "why": "K checkpoint threshold"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", metavar="WORKSPACE")
    ap.add_argument("--review", metavar="WORKSPACE")
    ap.add_argument("--stage")
    ap.add_argument("--verdict")
    ap.add_argument("--reason")
    a = ap.parse_args()
    if a.check:
        r = check(a.check)
        for v in r["violations"]:
            print("PLAN: " + v)
        print("OK" if r["ok"] else "FAIL")
        return 0 if r["ok"] else 2
    if a.review:
        r = review(a.review, a.verdict, a.stage or "", a.reason or "")
        for v in r["violations"]:
            print("PLAN: " + v)
        print("OK" if r["ok"] else "FAIL")
        return 0 if r["ok"] else 2
    ap.print_help()
    return 2


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
