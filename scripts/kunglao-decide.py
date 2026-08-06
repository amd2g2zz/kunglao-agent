#!/usr/bin/env python3
"""kunglao-decide.py — M1 DECIDE 独立 CLI (design-spec §6.7.5 L568, module-design.md M1.3-M1.5).

组合: convergence_check.decide(5 分支矩阵, golden F-01..F-16 冻结)
    + explore_gate(探索判定) + priority_ratio(比值键) + method_router(方法路由, 0 LLM)
    + selfcheck(反问/自加 cap 行为契约扫描)。
输出: DecideOutput(M1.3 冻结 schema, schemas/decide-output.json), exit_code 0-4 同 convergence_check。

用法:
  python kunglao-decide.py <ws> [--json] [--method-graph <path>] [--tool-health skill=down,...] [--scan-text <text>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
for _p in (str(SCRIPT_DIR), str(ROOT / "hooks")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yaml

import convergence_check as cc
import priority_ratio as pr
import explore_gate as eg
import method_router as mr
import ask_for_direction_gate as afdg

try:
    import worker_budget as wb
except ImportError:  # hooks 不可导入时不崩: 自加 cap 扫描降级为仅反问
    wb = None

DEFAULT_GRAPH = ROOT / "data" / "method-graph.yaml"
EXPLORE_THRESHOLD = eg.EXPLORE_THRESHOLD


def selfcheck(text: str) -> list[str]:
    """行为契约扫描(M1.1 L99): 反问/self-redirect(ask_for_direction_gate, 已实现)
    + 自加 cap 时间帽(worker_budget.detect_self_cap)。返回违规描述列表."""
    violations: list[str] = []
    for vtype, _pat, match in afdg.find_violations(text):
        violations.append(f"ask-for-direction Type {vtype}: {match!r}")
    if wb is not None:
        try:
            found, offenders = wb.detect_self_cap(text)
            if found:
                violations.extend(f"self-imposed time cap: {o!r}" for o in offenders)
        except Exception as exc:  # 扫描器异常不阻塞决策
            violations.append(f"self-cap scan error: {exc}")
    return violations


def _load_yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def _cheapness_order(claims: list[dict], deps: dict) -> list[pr.Action]:
    """探索模式(design-spec §3.2 L132-134): 同 dispatchable 过滤, score = cheapness 降序(T1 铺开)."""
    by_id = {c.get("id"): c for c in claims if c.get("id")}
    depends_on = (deps or {}).get("depends_on", {}) or {}
    terminal_ids = {cid for cid, c in by_id.items() if not pr.is_open(c)}
    rows: list[pr.Action] = []
    for c in claims:
        cid = c.get("id")
        if not cid or not pr.is_open(c):
            continue
        if int(c.get("promotion_attempts", 0)) >= 3:
            continue
        parents = depends_on.get(cid, []) or []
        if any(p not in terminal_ids for p in parents):
            continue
        cost = pr.next_tier_cost(c)
        rows.append(pr.Action(
            claim_id=cid, action=pr.classify_action(c), score=cost, skill=None,
            tier=min(int(c.get("evidence_tier_attempted", 0)) + 1, 3),
            attempts=int(c.get("promotion_attempts", 0)),
            delta_disc=0.0, expected_unlock=0.0, unc=0.0, cost=cost,
        ))
    rows.sort(key=lambda a: a.score, reverse=True)
    return rows


def _conservative_blocked(ws: Path, exc: Exception) -> dict:
    """M1.5 L164: 脚本异常 → 记 ledger(failure_recorded) + 保守 BLOCKED(不误报收敛)."""
    try:
        cc._append_ledger(ws, {
            "decision": "BLOCKED", "open_count": -1, "open_claims": [],
            "partial_count": -1, "active_workers": 0, "active_blockers": [],
            "facts_total": -1, "error": str(exc),
        })
    except Exception:
        pass
    return {
        "decision": "BLOCKED", "exit_code": cc.EXIT_BLOCKED,
        "top_actions": [], "blocked": [], "failure_blocked": [], "stale": [],
        "drifts": [], "explore_mode": False, "selfcheck": [],
        "error": f"{type(exc).__name__}: {exc}",
    }


def decide(ws: Path, method_graph_path: Path | None = None,
           tool_health: dict[str, str] | None = None,
           scan_text: str | None = None) -> dict:
    """组合 decide(M1.4 状态机); 异常 → 保守 BLOCKED."""
    try:
        base = cc.decide(ws)
        out: dict = {
            "decision": base["decision"],
            "exit_code": base["exit_code"],
            "top_actions": [],
            "blocked": [c["id"] for c in base["open_claims"] if c.get("blocked")],
            "failure_blocked": list(base["failure_blocked"]),
            "stale": [w["worker"] for w in base["stuck_workers"]],
            "drifts": [],  # 阶段 4 不计算(plan_drift_detector 为独立 gate)
            "explore_mode": False,
            "selfcheck": selfcheck(scan_text) if scan_text else [],
            "open_count": base["open_count"],
            "partial_count": base["partial_count"],
            "free_slots": base["free_slots"],
            "escalations": [],
        }
        if base["decision"] != "DISPATCH":
            return out
        reg = _load_yaml(ws / "claim-register.yaml")
        deps = _load_yaml(ws / "claim_deps.yaml")
        evidence = pr.EvidenceView.from_workspace(ws)
        graph = mr.load_method_graph(method_graph_path or DEFAULT_GRAPH)
        th = tool_health or {}
        failure_blocked_ids = set(base["failure_blocked"])
        claims = [c for c in (reg.get("claims") or []) if c.get("id") not in failure_blocked_ids]
        if eg.explore_gate(evidence.verified_fact_count, EXPLORE_THRESHOLD):
            out["explore_mode"] = True
            actions = _cheapness_order(claims, deps)
        else:
            actions = pr.priority_ratio(claims, deps, evidence)
        for a in actions[: max(base["free_slots"], 0)]:
            routed = mr.method_router(a.action, graph, th)
            if routed.escalated:
                out["escalations"].append({
                    "claim_id": a.claim_id, "action": a.action, "reason": routed.reason,
                })
            out["top_actions"].append({
                "claim_id": a.claim_id, "action": a.action,
                "score": round(a.score, 3),
                "skill": routed.steps[-1].skill if routed.steps else None,
            })
        return out
    except Exception as exc:  # noqa: BLE001 — 决策入口兜底
        return _conservative_blocked(ws, exc)


def _human(out: dict) -> str:
    lines = [f"=== KONG-DECIDE: {out['decision']} (exit {out['exit_code']}) ==="]
    if out.get("explore_mode"):
        lines.append("explore_mode: EXPLORE (verified facts < 5) — cheap T1 spread")
    if out["top_actions"]:
        lines.append("top_actions:")
        for a in out["top_actions"]:
            lines.append(f"  {a['claim_id']:<6} {a['action']:<22} score={a['score']:<7} skill={a['skill']}")
    if out["escalations"]:
        lines.append("escalations (method_router 图断, 需 LLM 图生长):")
        for e in out["escalations"]:
            lines.append(f"  {e['claim_id']} {e['action']}: {e['reason']}")
    if out["blocked"]:
        lines.append(f"blocked: {out['blocked']}")
    if out["failure_blocked"]:
        lines.append(f"failure_blocked: {out['failure_blocked']}")
    if out["stale"]:
        lines.append(f"stale workers: {out['stale']}")
    if out["selfcheck"]:
        lines.append(f"selfcheck violations: {out['selfcheck']}")
    if out.get("error"):
        lines.append(f"error (conservative BLOCKED): {out['error']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kunglao-decide.py", description="kunglao-agent M1 decide (独立 CLI)")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true", help="machine-readable DecideOutput")
    ap.add_argument("--method-graph", default=None, help="method-graph.yaml 路径(默认 data/method-graph.yaml)")
    ap.add_argument("--tool-health", default="", help="skill=down[,skill=down...] 工具健康注入")
    ap.add_argument("--scan-text", default=None, help="orchestrator 输出文本, 供 selfcheck 扫描")
    args = ap.parse_args(argv)

    tool_health: dict[str, str] = {}
    for pair in args.tool_health.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            tool_health[k.strip()] = v.strip()

    out = decide(Path(args.workspace),
                 method_graph_path=Path(args.method_graph) if args.method_graph else None,
                 tool_health=tool_health,
                 scan_text=args.scan_text)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(_human(out))
    return out["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
