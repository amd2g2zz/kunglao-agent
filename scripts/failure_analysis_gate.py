#!/usr/bin/env python3
"""failure_analysis_gate.py - force method reasoning after a failed attempt (v1.9.3).

THE PROBLEM THIS SOLVES (user's exact words):
  "目前我们要分析 c2 的网络协议,但是目前失败了,你能说没有网络协议行为,
   然后不分析吗?但是之前的分析办法可能存在问题,这个就需要分析,然后优化"

A failed analysis attempt is NOT evidence the behavior is absent. It is evidence
the METHOD failed — possibly. The orchestrator must NOT collapse "method failed"
into "sample doesn't do X". Before re-dispatching OR concluding NEGATIVE, it must
reason about WHY the method failed.

This gate does NOT give a fixed taxonomy of failure types (that would be a
checklist the agent picks from without thinking). It forces THREE QUESTIONS whose
answers the agent must generate from the specific situation:

  1. method_assumption   — what did the failed method assume would happen?
  2. assumption_validity — is that assumption justified given what we know?
                           (if not → method failed, not behavior absent)
  3. next_method         — what DIFFERENT method tests a different assumption?
                           (literal "retry the same thing" is forbidden here)

Only if the agent can argue assumption_validity = "justified, method was adequate"
may the claim be marked NEGATIVE — and even then it carries single-method
confidence (a different method can overturn it later).

Enforcement: a claim with a prior failed attempt (promotion_attempts > 0, status
non-terminal) that has NO current failure_analysis → BLOCKED. The orchestrator
cannot re-dispatch through the normal flow until the analysis is recorded.

Each failed attempt needs its own analysis (covers_attempt versioning) — you can't
coast on the reasoning from attempt 1 when attempt 3 also fails.

Usage:
  # check mode — which claims need analysis?
  python scripts/failure_analysis_gate.py <workspace>

  # check one claim
  python scripts/failure_analysis_gate.py <workspace> <C-NN>

  # record an analysis (unblocks re-dispatch or NEGATIVE conclusion)
  python scripts/failure_analysis_gate.py <workspace> <C-NN> --record \
      --assumption "what the failed method assumed" \
      --validity "not-justified | justified-adequate" \
      --next-method "what different method to try (or 'method was adequate' for true negative)"

Exit codes:
  0 = OK (no failed attempt pending, or analysis covers it)
  1 = BLOCKED (failed attempt, analysis missing or stale)
  2 = claim not found or terminal (no analysis needed)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

TERMINAL = {"PROVEN", "VERIFIED", "NEGATIVE", "REFUTED", "DEFERRED"}
ANALYSES_DIR = "analyses"


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def _resolve_ws(arg) -> Path:
    if arg:
        return Path(arg)
    cwd = Path(os.getcwd())
    sub = cwd / "malware-analysis-workspace"
    return sub if (sub / "claim-register.yaml").exists() else cwd


def _load_claims(workspace: Path):
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return [], None
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg


def _analysis_path(workspace: Path, claim_id: str) -> Path:
    return workspace / ANALYSES_DIR / f"failure-{claim_id}.yaml"


def _load_analysis(workspace: Path, claim_id: str):
    p = _analysis_path(workspace, claim_id)
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return None


def _needs_analysis(claim: dict) -> bool:
    """A claim needs failure analysis if it was attempted (promotion_attempts > 0)
    but hasn't reached terminal status — a dispatch happened and didn't close it."""
    status = (claim.get("status") or "UNKNOWN").upper()
    if status in TERMINAL:
        return False
    return int(claim.get("promotion_attempts") or 0) > 0


def _analysis_covers(analysis: dict, claim: dict) -> bool:
    """Does the recorded analysis cover the latest failed attempt?
    covers_attempt must match (or exceed) the claim's current promotion_attempts."""
    if not analysis:
        return False
    covers = int(analysis.get("covers_attempt") or 0)
    attempts = int(claim.get("promotion_attempts") or 0)
    return covers >= attempts


def check_claim(workspace: Path, claim_id: str) -> dict:
    claims, _ = _load_claims(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if not claim:
        return {"state": "NOT_FOUND", "claim_id": claim_id}

    status = (claim.get("status") or "UNKNOWN").upper()
    if status in TERMINAL:
        return {"state": "TERMINAL", "claim_id": claim_id, "status": status}

    if not _needs_analysis(claim):
        return {"state": "OK_NO_PRIOR_FAILURE", "claim_id": claim_id,
                "promotion_attempts": claim.get("promotion_attempts")}

    analysis = _load_analysis(workspace, claim_id)
    if _analysis_covers(analysis, claim):
        return {"state": "OK_COVERED", "claim_id": claim_id,
                "promotion_attempts": claim.get("promotion_attempts"),
                "analysis": analysis}

    return {
        "state": "BLOCKED",
        "claim_id": claim_id,
        "status": status,
        "promotion_attempts": claim.get("promotion_attempts"),
        "evidence_tier_attempted": claim.get("evidence_tier_attempted"),
        "statement": (claim.get("statement") or "")[:200],
        "evidence": claim.get("evidence") or [],
        "stale_analysis": analysis,
    }


def scan_workspace(workspace: Path) -> list:
    """Return all claims that currently BLOCK (failed attempt, no current analysis)."""
    claims, _ = _load_claims(workspace)
    blocked = []
    for c in claims:
        if not _needs_analysis(c):
            continue
        analysis = _load_analysis(workspace, c.get("id"))
        if not _analysis_covers(analysis, c):
            blocked.append(check_claim(workspace, c.get("id")))
    return blocked


def record_analysis(workspace: Path, claim_id: str, assumption: str,
                    validity: str, next_method: str) -> dict:
    claims, _ = _load_claims(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if not claim:
        return {"recorded": False, "reason": f"claim {claim_id} not found"}

    validity = (validity or "").strip().lower()
    if validity not in ("not-justified", "justified-adequate"):
        return {"recorded": False,
                "reason": "--validity must be 'not-justified' or 'justified-adequate'"}

    # not-justified REQUIRES a real different next_method (not "adequate" hand-wave)
    if validity == "not-justified":
        if not next_method or not next_method.strip():
            return {"recorded": False,
                    "reason": "validity=not-justified requires a --next-method (the different method to try)"}
        if "adequate" in next_method.lower() or "retry" == next_method.strip().lower():
            return {"recorded": False,
                    "reason": "validity=not-justified requires a DIFFERENT method, not 'adequate' or bare 'retry'"}

    adir = workspace / ANALYSES_DIR
    adir.mkdir(parents=True, exist_ok=True)
    entry = {
        "claim": claim_id,
        "covers_attempt": int(claim.get("promotion_attempts") or 0),
        "method_assumption": assumption,
        "assumption_validity": validity,
        "next_method": next_method,
        "analyzed_at": utc_now_iso(),
    }
    _analysis_path(workspace, claim_id).write_text(
        yaml.safe_dump(entry, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {"recorded": True, "entry": entry}


def _print_blocked(d: dict) -> None:
    cid = d["claim_id"]
    print(f"=== BLOCKED: {cid} (status={d.get('status')}, attempts={d.get('promotion_attempts')}) ===")
    print(f"claim: {d.get('statement','')}")
    if d.get("evidence"):
        print(f"evidence so far: {d['evidence']}")
    if d.get("stale_analysis"):
        print(f"stale analysis (covers attempt {d['stale_analysis'].get('covers_attempt')}): update it")
    print()
    print("Before re-dispatching OR concluding NEGATIVE, answer three questions")
    print("(reason from THIS specific failure — do not pick from a fixed menu):")
    print()
    print("  1. method_assumption   — what did the failed method assume would happen?")
    print("  2. assumption_validity — is that assumption justified given the evidence?")
    print("                           if NOT justified -> the METHOD failed, not the behavior absent")
    print("  3. next_method         — what DIFFERENT method tests a different assumption?")
    print("                           (literal retry is forbidden; 'method was adequate' only if Q2=justified)")
    print()
    print("Record with:")
    print(f"  python scripts/failure_analysis_gate.py <ws> {cid} --record \\")
    print(f"      --assumption \"...\" --validity not-justified|justified-adequate --next-method \"...\"")


def main() -> int:
    parser = argparse.ArgumentParser(description="kunglao-agent failure-analysis gate — reason before re-dispatch or NEGATIVE")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("claim_id", nargs="?", default=None, help="claim to check (omit to scan all)")
    parser.add_argument("--record", action="store_true", help="record a failure analysis")
    parser.add_argument("--assumption", default=None, help="what the failed method assumed")
    parser.add_argument("--validity", default=None, help="not-justified | justified-adequate")
    parser.add_argument("--next-method", default=None, help="the different method to try next")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    workspace = _resolve_ws(args.workspace)

    if args.record:
        if not args.claim_id:
            print("FAIL: --record requires a claim_id", file=sys.stderr)
            return 64
        r = record_analysis(workspace, args.claim_id, args.assumption or "",
                           args.validity or "", args.next_method or "")
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            print("RECORDED" if r.get("recorded") else f"REJECTED: {r.get('reason')}")
            if r.get("entry"):
                print(yaml.safe_dump(r["entry"], allow_unicode=True, sort_keys=False))
        return 0 if r.get("recorded") else 1

    if args.claim_id:
        r = check_claim(workspace, args.claim_id)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            if r["state"] == "BLOCKED":
                _print_blocked(r)
            elif r["state"] == "OK_COVERED":
                print(f"OK: {args.claim_id} — analysis covers attempt {r.get('promotion_attempts')}")
            elif r["state"] == "TERMINAL":
                print(f"OK: {args.claim_id} — terminal ({r.get('status')}), no analysis needed")
            elif r["state"] == "OK_NO_PRIOR_FAILURE":
                print(f"OK: {args.claim_id} — no prior failed attempt (attempts={r.get('promotion_attempts')})")
            else:
                print(f"FAIL: claim {args.claim_id} not found")
        return 1 if r["state"] == "BLOCKED" else (2 if r["state"] == "NOT_FOUND" else 0)

    # scan mode
    blocked = scan_workspace(workspace)
    if args.json:
        print(json.dumps({"blocked": blocked, "count": len(blocked)}, indent=2, ensure_ascii=False))
    elif blocked:
        print(f"=== {len(blocked)} claim(s) BLOCKED (failed attempt, no current analysis) ===\n")
        for d in blocked:
            _print_blocked(d)
            print()
    else:
        print("OK: no claims need failure analysis right now.")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
