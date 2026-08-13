#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-monitor — M5 MONITOR 独立 CLI (phase 5, E5.3).

组合 heartbeat_check + loop_reconcile + help_watch + stuck_watch + health_check
→ TickOutput(schemas/tick-output.json, M5.3 L396-406 冻结)。

后台进程 (2026-08-12, #88): 本 CLI 作为 BACKGROUND process 运行 — 其输出是
advisory。loop 的定时 tick 动作 (re-dispatch / verify / TaskStop) 绝不等待
monitor 输出; tick 依据文件状态推进 (worker-status-*.md 新鲜度 / .heartbeat.json),
monitor 的 `next` 只是建议, 不是 gate。

隔离边界 (#88): 不使用 agent team 特性 (CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
never enabled / no teammates / no team setup / 无 worker↔worker messaging);
SendMessage orchestrator→worker ping 是 sanctioned heartbeat channel。

可复用(不改): loop_state.reconcile(TEMP mtime → loop-state)、
convergence_health.assess(HEALTHY/STALLED/SPINNING)、
active_intervention.find_help_requests/find_responses、
backtrack_gate.parse_status/parse_backtrack。

用法: python kunglao-monitor.py <ws> [--json]
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

HEARTBEAT_FILE = "runs/.heartbeat.json"
HEARTBEAT_MAX_MIN = 35          # 与 worker_budget.check_heartbeat_alive 同阈值
STUCK_MIN = 20                  # 与 backtrack_gate --stuck-min 默认一致
VALID_BACKTRACK_DECISIONS = ("continue", "retry_different", "escalate", "redispatch")


def utc_now() -> str:
    """UTC ISO-8601 秒级, Z 后缀(schema ts pattern)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_now_dt() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def heartbeat_check(ws: Path) -> tuple[str, str]:
    """M5.2 L382: 查 runs/.heartbeat.json last_tick_ts(< 35min) → (alive|STALE, detail).

    文件缺失/损坏 → STALE + re-register 提示(M5.5 L424-425).
    """
    path = ws / HEARTBEAT_FILE
    if not path.exists():
        return ("STALE", "no runs/.heartbeat.json — monitoring never registered")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        last_str = data.get("last_tick_ts", "")
        last = datetime.datetime.fromisoformat(last_str.replace("Z", "+00:00"))
    except Exception as exc:
        return ("STALE", f".heartbeat.json unreadable ({exc}) — re-register (--heartbeat-on)")
    age = _utc_now_dt() - last
    if age > datetime.timedelta(minutes=HEARTBEAT_MAX_MIN):
        return ("STALE", f"last tick {last_str} ({int(age.total_seconds() // 60)} min > {HEARTBEAT_MAX_MIN})")
    return ("alive", f"last tick {last_str}")


def loop_reconcile(ws: Path) -> dict:
    """M5.2 L385: TEMP mtime → loop-state; 与上一快照 diff → gone 事件.

    TEMP glob 失败/导入失败 → 空态(不崩溃, M5.5 L423); 无快照 → 全当首次(NEW).
    """
    prev: dict = {}
    prev_path = ws / "runs" / "loop-state.json"
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            prev = {}
    try:
        from loop_state import reconcile
        state = reconcile(ws)
    except Exception as exc:
        state = {"ts": utc_now(), "agent_count": 0, "active": [], "stale": [],
                 "agents": {}, "error": str(exc)}
    prev_active = set(prev.get("active") or [])
    current_ids = set(state.get("agents") or {})
    gone = sorted(prev_active - current_ids)
    try:
        (ws / "runs").mkdir(parents=True, exist_ok=True)
        prev_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass  # 快照写失败不崩溃 — 下次 tick 全当首次
    return {"state": state, "gone_events": gone, "prev_ts": prev.get("ts")}


def help_watch(ws: Path) -> list[str]:
    """M5.1 help_watch: 未响应的 help_request 所在 worker-status 文件(active_intervention 语义)."""
    try:
        import active_intervention as ai
    except Exception:
        return []
    reqs = ai.find_help_requests(ws)
    if not reqs:
        return []
    responded = {r.get("claim_id") for r in ai.find_responses(ws)}
    return sorted({r["file"] for r in reqs if r.get("claim_id") not in responded})


def stuck_watch(ws: Path) -> list[str]:
    """M5.1 stuck_watch: in_progress 且 ≥20min 无有效 backtrack 的 worker 文件."""
    try:
        import backtrack_gate as bg
    except Exception:
        return []
    workers_dir = ws / "runs"
    if not workers_dir.exists():
        return []
    now = _utc_now_dt()
    stuck: list[str] = []
    for p in sorted(workers_dir.glob("worker-status-*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if bg.parse_status(text) != "in_progress":
            continue
        age = now - datetime.datetime.fromtimestamp(p.stat().st_mtime, tz=datetime.timezone.utc)
        if age < datetime.timedelta(minutes=STUCK_MIN):
            continue
        bt = bg.parse_backtrack(text)
        if bt is None or bt.get("decision", "").lower() not in VALID_BACKTRACK_DECISIONS:
            stuck.append(p.name)
    return stuck


def health_check(ws: Path) -> dict:
    """M5.2 L388: .convergence_ledger.jsonl 轨迹 → HEALTHY|STALLED|SPINNING.

    NO_DATA(无账本/不可评估) → HEALTHY(不能无据判 STALLED), raw 字段保留原值.
    """
    try:
        import convergence_health as ch
        r = ch.assess(ch._read_ledger(ws))
    except Exception as exc:
        return {"verdict": "HEALTHY", "raw": "NO_DATA",
                "detail": f"convergence_health unavailable ({exc})"}
    raw = r.get("verdict", "NO_DATA")
    verdict = raw if raw in ("HEALTHY", "STALLED", "SPINNING") else "HEALTHY"
    return {"verdict": verdict, "raw": raw, "detail": r.get("action", ""),
            "rounds": r.get("rounds", 0)}


def decide_next(hb: str, health: dict, help_reqs: list[str], stuck: list[str],
                gone: list[str], active_workers: int) -> str:
    """M5.4 L418 机械推断下一步(优先级: 心跳 → 健康 → help → stuck → gone → 空闲)."""
    if hb == "STALE":
        return "re-register heartbeat: python hook_activation.py <ws> --heartbeat-on"
    if health["verdict"] == "SPINNING":
        return health["detail"] or "STOP dispatching — spinning (see convergence_health)"
    if health["verdict"] == "STALLED":
        return health["detail"] or "diagnose before dispatching — stalled (see convergence_health)"
    if help_reqs:
        return f"respond to help_request(s): {', '.join(help_reqs)} (SendMessage workaround / redispatch / B1d)"
    if stuck:
        return f"force `## backtrack` on stuck worker(s): {', '.join(stuck)}"
    if gone:
        return f"reconcile ledger for gone agent(s): {', '.join(gone)}"
    if active_workers == 0:
        return "converged-check: run convergence_check.py (no active workers)"
    return "poll active workers (SATURATED — no free slot)"


def tick(ws: Path) -> dict:
    """M5.4 L410-420: heartbeat → loop_reconcile → help/stuck/health → next → TickOutput."""
    hb, hb_detail = heartbeat_check(ws)
    ls = loop_reconcile(ws)
    state = ls["state"]
    active_workers = len(state.get("active") or [])
    help_reqs = help_watch(ws)
    stuck = stuck_watch(ws)
    health = health_check(ws)
    gone = ls["gone_events"]
    return {
        "ts": utc_now(),
        "heartbeat": hb,
        "active_workers": active_workers,
        "stale_agents": state.get("stale") or [],
        "gone_events": gone,
        "help_requests": help_reqs,
        "stuck": stuck,
        "health": health["verdict"],
        "next": decide_next(hb, health, help_reqs, stuck, gone, active_workers),
        "heartbeat_detail": hb_detail,
        "health_detail": health["detail"],
    }


def main(argv: list[str] | None = None) -> int:
    """独立 CLI: python kunglao-monitor.py <ws> [--json]."""
    ap = argparse.ArgumentParser(description="kunglao-monitor — M5 MONITOR tick")
    ap.add_argument("ws", type=Path, help="workspace root")
    ap.add_argument("--json", action="store_true", help="machine-readable JSON output")
    args = ap.parse_args(argv)
    out = tick(args.ws)
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"heartbeat={out['heartbeat']} | active_workers={out['active_workers']} | "
              f"health={out['health']} | help={out['help_requests']} | stuck={out['stuck']}")
        print(f"next: {out['next']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
