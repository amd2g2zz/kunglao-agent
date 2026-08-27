#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-decide.py — M1 DECIDE standalone CLI (design-spec §6.7.5 L568, module-design.md M1.3-M1.5).

Combines: convergence_check.decide (5-branch matrix, golden F-01..F-16 frozen)
    + explore_gate (exploration verdict) + priority_ratio (ratio key)
    + selfcheck (counter-question / self-cap behavior-contract scan).
Output: DecideOutput (M1.3 frozen schema, schemas/decide-output.json); exit_code 0-4 same as convergence_check.

Usage:
  python kunglao-decide.py <ws> [--json] [--scan-text <text>]
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
import ask_for_direction_gate as afdg

try:
    import worker_budget as wb
except ImportError:  # must not crash when hooks are unimportable: self-cap scan degrades to counter-question only
    wb = None

EXPLORE_THRESHOLD = eg.EXPLORE_THRESHOLD


def selfcheck(text: str) -> list[str]:
    """Behavior-contract scan (M1.1 L99): counter-questions / self-redirect
    (ask_for_direction_gate, implemented) + self-imposed time caps
    (worker_budget.detect_self_cap). Returns a list of violation descriptions."""
    violations: list[str] = []
    for vtype, _pat, match in afdg.find_violations(text):
        violations.append(f"ask-for-direction Type {vtype}: {match!r}")
    if wb is not None:
        try:
            found, offenders = wb.detect_self_cap(text)
            if found:
                violations.extend(f"self-imposed time cap: {o!r}" for o in offenders)
        except Exception as exc:  # a scanner exception must not block the decision
            violations.append(f"self-cap scan error: {exc}")
    return violations


def _load_yaml(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def _cheapness_order(claims: list[dict], deps: dict) -> list[pr.Action]:
    """Explore mode (design-spec §3.2 L132-134): same dispatchable filter; score = cheapness descending (T1 spread)."""
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
        ch = pr.cheapness(c)
        rows.append(pr.Action(
            claim_id=cid, action=pr.classify_action(c), score=ch, skill=None,
            tier=min(int(c.get("evidence_tier_attempted", 0)) + 1, 3),
            attempts=int(c.get("promotion_attempts", 0)),
            leverage=0.0, discriminator=0.0, novelty=0.0, cost=pr.action_cost(c),
        ))
    rows.sort(key=lambda a: a.score, reverse=True)
    return rows


def _conservative_blocked(ws: Path, exc: Exception) -> dict:
    """M1.5 L164: script exception → conservative BLOCKED (never falsely report convergence).

    Intentionally does NOT write to the convergence ledger: on the exception
    path we have no reliable open_count / partial_count / facts_total, and writing
    sentinel values (e.g. -1) would poison the trajectory that convergence_health.py
    consumes.  The missing ledger entry is harmless — health assessment treats
    gaps as "no data for that turn" rather than an error.

    #569 AUDIT: leaves a decide_fail_open trace in the unified event log so the
    audit can see when the script took the exception path. The BLOCKED shape
    is identical to a healthy BLOCKED, so without this trace the FAIL_OPEN
    would be invisible to post-mortem. Logging is fail-open (stderr note
    only on write failure) — the BLOCKED contract must survive any emit crash.
    """
    try:
        import kunglao_log
        kunglao_log.emit(ws, actor="kunglao-decide", action="decide_fail_open",
                         detail=f"{type(exc).__name__}: {exc}")
    except Exception as emit_exc:  # noqa: BLE001 — emit must not block BLOCKED
        print(f"kunglao-decide: trace emit failed ({emit_exc!r})",
              file=sys.stderr, flush=True)
    return {
        "decision": "BLOCKED", "exit_code": cc.EXIT_BLOCKED,
        "top_actions": [], "blocked": [], "failure_blocked": [], "stale": [],
        "drifts": [], "explore_mode": False, "selfcheck": [],
        "error": f"{type(exc).__name__}: {exc}",
    }


def decide(ws: Path, scan_text: str | None = None) -> dict:
    """Composed decide (M1.4 state machine); exception → conservative BLOCKED.

    The routing layer was experimentally falsified and CUT (issue #1): LLM
    workers self-select / self-swap tools, routing is ~zero value. The
    top_actions skill field is always None; the worker self-selects.

    Three decide layers with intentionally different schemas (issue #97):
      1. convergence_check.decide() — base convergence matrix.
         Schema: decision, exit_code, action, open_claims, open_count,
         unblocked_open_count, blocked_open_count, failure_blocked,
         partial_facts, partial_count, active_workers, free_slots,
         worker_cap, stuck_workers, done_artifact_violations (#444 W-15
         diagnostic), active_blockers, orphan_claims,
         unverified_primary_qs, note_layer_gaps, pq_parse_error.
         Validated against convergence-check-output.json.
      2. kunglao-decide.decide() (this function) — composed M1 DecideOutput.
         Schema: decision, exit_code, top_actions, blocked, failure_blocked,
         stale, drifts, explore_mode, selfcheck, open_count, partial_count,
         free_slots (+ optional error from _conservative_blocked).
         Validated against decide-output.json.
      3. _conservative_blocked() — error fallback, subset of (2) + error.
         Schema: decision, exit_code, top_actions, blocked, failure_blocked,
         stale, drifts, explore_mode, selfcheck, error.
         Intentionally omits open_count/partial_count/free_slots because
         those values are unreliable on the exception path.
    """
    try:
        base = cc.decide(ws)
        out: dict = {
            "decision": base["decision"],
            "exit_code": base["exit_code"],
            "top_actions": [],
            "blocked": [c["id"] for c in base["open_claims"] if c.get("blocked")],
            "failure_blocked": list(base["failure_blocked"]),
            "stale": [w["worker"] for w in base["stuck_workers"]],
            "drifts": [],  # not computed in phase 4 (plan_drift_detector is a separate gate)
            "explore_mode": False,
            "selfcheck": selfcheck(scan_text) if scan_text else [],
            "open_count": base["open_count"],
            "partial_count": base["partial_count"],
            "free_slots": base["free_slots"],
        }
        if base["decision"] != "DISPATCH":
            return out
        reg = _load_yaml(ws / "claim-register.yaml")
        deps = _load_yaml(ws / "claim_deps.yaml")
        evidence = pr.EvidenceView.from_workspace(ws)
        failure_blocked_ids = set(base["failure_blocked"])
        claims = [c for c in (reg.get("claims") or []) if c.get("id") not in failure_blocked_ids]
        if eg.explore_gate(evidence.verified_fact_count, EXPLORE_THRESHOLD):
            out["explore_mode"] = True
            actions = _cheapness_order(claims, deps)
        else:
            actions = pr.priority_ratio(claims, deps, evidence)
        for a in actions[: max(base["free_slots"], 0)]:
            out["top_actions"].append({
                "claim_id": a.claim_id, "action": a.action,
                "score": round(a.score, 3),
                "skill": None,  # routing CUT (issue #1); worker self-selects tools
            })
        return out
    except Exception as exc:  # noqa: BLE001 — last-resort guard at the decide entry
        return _conservative_blocked(ws, exc)


def _human(out: dict) -> str:
    lines = [f"=== KUNGLAO-DECIDE: {out['decision']} (exit {out['exit_code']}) ==="]
    if out.get("explore_mode"):
        lines.append("explore_mode: EXPLORE (verified facts < 5) — cheap T1 spread")
    if out["top_actions"]:
        lines.append("top_actions:")
        for a in out["top_actions"]:
            lines.append(f"  {a['claim_id']:<6} {a['action']:<22} score={a['score']:<7} skill={a['skill']}")
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
    ap = argparse.ArgumentParser(prog="kunglao-decide.py", description="kunglao-agent M1 decide (standalone CLI)")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true", help="machine-readable DecideOutput")
    ap.add_argument("--scan-text", default=None, help="orchestrator output text for the selfcheck scan")
    args = ap.parse_args(argv)

    out = decide(Path(args.workspace), scan_text=args.scan_text)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        print(_human(out))
    return out["exit_code"]


from _entry import run

if __name__ == "__main__":
    run(globals())
