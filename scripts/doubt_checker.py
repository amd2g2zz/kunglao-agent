"""doubt_checker.py - enforce independent verifier sign-off on PROVEN claims.

User pain point: "self-confident but actually wrong - claims PROVEN when
analysis is flawed, then declares convergence confidently."

kunglao-agent SKILL.md section 6-pre F-8 (new in v1.8.2 patch) calls for: every
PROVEN claim must have an independent verifier sign-off BEFORE convergence
(C0-C7). The orchestrator cannot self-stamp PROVEN. The verifier MUST be a
different agent (per section 1b maker-checker).

This script enforces: for every claim with status=PROVEN (or PROVEN-FULL
per V3 norm) in claim-register.yaml, the corresponding fact file (facts/Fxxx.md)
must contain a `verifier_sign_off` block with:
  - verifier_id: <agent-name or worker_id>
  - verifier_role: <different from claim's worker_id>
  - refute_attempt: <1-line summary of what verifier tried to break>
  - sign_off_at: <ISO 8601 UTC>

If any PROVEN claim is missing verifier_sign_off OR the verifier_id equals
the claim's worker_id (self-stamp): REJECT convergence with "B1g
verifier-sign-off-missing".

Usage:
  python doubt_checker.py <workspace>
Exit 0 if all PROVEN claims have valid verifier_sign_off; 1 otherwise.
"""
from __future__ import annotations
import gate_telemetry as _gt
import hook_activation as ha


import argparse
import re
import sys
from pathlib import Path

import yaml

TERMINAL_TRUSTED = {"PROVEN", "PROVEN-FULL"}


def _load_yaml(path: Path):
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}) if path.exists() else {}


def find_fact_file(workspace: Path, claim_id: str) -> Path | None:
    """Locate facts/<claim-id>*.md or facts/F<NNN>.md referenced by claim."""
    facts_dir = workspace / "facts"
    if not facts_dir.exists():
        return None
    direct = facts_dir / f"{claim_id}.md"
    if direct.exists():
        return direct
    for p in facts_dir.glob("*.md"):
        if claim_id in p.read_text(encoding="utf-8", errors="replace")[:2000]:
            return p
    return None


def extract_worker_id(claim: dict) -> str | None:
    return claim.get("worker_id") or claim.get("last_dispatched_worker")


def has_verifier_sign_off(fact_path: Path) -> tuple:
    if fact_path is None:
        return False, {}
    text = fact_path.read_text(encoding="utf-8", errors="replace")
    if "verifier_sign_off" not in text:
        return False, {}
    m = re.search(r"```yaml\s*verifier_sign_off:\s*(.*?)```", text, re.DOTALL)
    if not m:
        m = re.search(r"verifier_sign_off:\s*(.+?)(?:\n\n|\Z)", text, re.DOTALL)
        if not m:
            return False, {}
    try:
        parsed = yaml.safe_load(m.group(0).replace("```yaml", "").replace("```", "")) or {}
    except yaml.YAMLError:
        return False, {}
    fields = parsed.get("verifier_sign_off", parsed) if "verifier_sign_off" in parsed else parsed
    required = ["verifier_id", "refute_attempt", "sign_off_at"]
    missing = [f for f in required if not fields.get(f)]
    if missing:
        return False, {"missing": missing}
    return True, fields


@_gt.telemetry('doubt_checker')
def check(workspace: Path) -> int:
    reg = _load_yaml(workspace / "claim-register.yaml")
    claims = (reg or {}).get("claims", []) or []
    by_id = {c.get("id"): c for c in claims if c.get("id")}
    failures = []
    successes = []

    for c in claims:
        cid = c.get("id")
        status = c.get("status", "")
        if status not in TERMINAL_TRUSTED and "PROVEN" not in status.upper():
            continue
        worker_id = extract_worker_id(c) or "?"
        fact = find_fact_file(workspace, cid)
        ok, fields = has_verifier_sign_off(fact)
        if not ok:
            failures.append({
                "claim_id": cid,
                "status": status,
                "worker_id": worker_id,
                "fact_file": str(fact.relative_to(workspace)) if fact else "(not found)",
                "reason": fields.get("missing") or "verifier_sign_off block missing",
            })
            continue
        if fields.get("verifier_id") == worker_id:
            failures.append({
                "claim_id": cid,
                "status": status,
                "worker_id": worker_id,
                "verifier_id": fields.get("verifier_id"),
                "fact_file": str(fact.relative_to(workspace)) if fact else "(not found)",
                "reason": "verifier_id == worker_id (self-stamp violates section 1b maker-checker)",
            })
            continue
        successes.append({
            "claim_id": cid,
            "status": status,
            "worker_id": worker_id,
            "verifier_id": fields.get("verifier_id"),
            "sign_off_at": fields.get("sign_off_at"),
        })

    if not failures and not successes:
        print("NOOP: no PROVEN claims to verify")
        return 0

    if failures:
        print(f"REJECT: {len(failures)} PROVEN claim(s) lack valid verifier sign-off:")
        for f in failures:
            print(f"  - {f['claim_id']} (status={f['status']}, worker={f['worker_id']}, "
                  f"fact={f['fact_file']})")
            print(f"    reason: {f['reason']}")
        print()
        print("ORCHESTRATOR MUST: spawn an independent verifier agent (different from")
        print("the claim's worker_id) to attempt refutation. The verifier writes a")
        print("verifier_sign_off block to facts/<claim-id>.md with:")
        print("  verifier_id: <agent-name>")
        print("  verifier_role: <description of who they are>")
        print("  refute_attempt: <1-line summary of what was tried>")
        print("  sign_off_at: <ISO 8601 UTC>")
        print()
        print("Without independent sign-off, claims are STAMP-not-PROVEN.")
        if successes:
            print(f"OK: {len(successes)} claim(s) with valid sign-off: "
                  + ", ".join(s["claim_id"] for s in successes[:5])
                  + ("..." if len(successes) > 5 else ""))
        return 1

    print(f"OK: {len(successes)} PROVEN claim(s) with valid verifier sign-off")
    for s in successes:
        print(f"  - {s['claim_id']}: verifier={s['verifier_id']} at {s['sign_off_at']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Doubt checker - verifier sign-off enforcement")

    parser.add_argument("workspace", help="workspace root")
    args = parser.parse_args()

    # F-10 selective activation: skip if hook is paused
    if not ha.is_active(Path(args.workspace), "doubt_checker"):
        print("SKIP: doubt_checker is paused (check .hook_state.json)")
        return 0
    return check(Path(args.workspace))


if __name__ == "__main__":
    sys.exit(main())