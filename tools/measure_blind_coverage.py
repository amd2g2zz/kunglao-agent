#!/usr/bin/env python3
"""measure_blind_coverage.py — measure BLIND verifier coverage of PROVEN claims.

PRD verified-convergence M1 metric: what fraction of PROVEN claims have valid
independent verifier sign-off? Target: 98% → 100%.

Reads:
  - claim-register.yaml: all claims with status
  - facts/*.md: verifier_sign_off blocks

Outputs (human + --json):
  proven: N           # total claims with status=PROVEN
  blind_signed: M     # PROVEN claims with valid verifier_sign_off
  unverified: N-M    # PROVEN claims lacking sign-off (= STAMP candidates)
  coverage: M/N      # ratio [0.0, 1.0]

Exit 0 always — this is a measurement tool, not a gate.

Usage:
  python tools/measure_blind_coverage.py <workspace>
  python tools/measure_blind_coverage.py <workspace> --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# scripts/ is on sys.path via pytest.ini pythonpath; for standalone CLI add it.
_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import yaml  # noqa: E402

from blind_gate import extract_verifier_signoff, find_fact_file  # noqa: E402


def _load_claims(ws: Path) -> list[dict]:
    reg = ws / "claim-register.yaml"
    if not reg.exists():
        return []
    data = yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    return data.get("claims", []) or []


def measure(ws: Path) -> dict:
    """Compute BLIND coverage for PROVEN claims in the workspace.

    Returns dict with keys: proven, blind_signed, unverified, coverage,
    details (per-claim breakdown for PROVEN claims).
    """
    claims = _load_claims(ws)
    facts_dir = ws / "facts"
    proven_claims = [c for c in claims if (c.get("status") or "").upper() == "PROVEN"]
    total = len(proven_claims)
    blind_signed = 0
    details = []

    for c in proven_claims:
        cid = c.get("id", "?")
        fact = find_fact_file(facts_dir, cid)
        signoff = None
        if fact is not None:
            signoff = extract_verifier_signoff(
                fact.read_text(encoding="utf-8", errors="replace"))
        # only CONFIRMED (or legacy without verdict) counts as valid sign-off;
        # REFUTE means the verifier found a problem — claim should not be PROVEN
        verdict = (signoff.get("verdict") or "CONFIRMED").upper() if signoff else None
        signed = signoff is not None and verdict != "REFUTE"
        if signed:
            blind_signed += 1
        details.append({
            "claim_id": cid,
            "blind_signed": signed,
            "verifier_id": signoff.get("verifier_id") if signoff else None,
            "verdict": verdict,
            "fact_file": fact.name if fact else None,
        })

    coverage = blind_signed / total if total > 0 else 0.0
    return {
        "proven": total,
        "blind_signed": blind_signed,
        "unverified": total - blind_signed,
        "coverage": round(coverage, 4),
        "details": details,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure BLIND verifier coverage of PROVEN claims")
    ap.add_argument("workspace", type=Path, help="workspace root")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)

    result = measure(args.workspace)

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"PROVEN: {result['proven']}")
    print(f"BLIND-signed: {result['blind_signed']}")
    print(f"unverified (STAMP candidates): {result['unverified']}")
    pct = result["coverage"] * 100
    print(f"coverage: {pct:.1f}%")
    if result["details"]:
        print()
        for d in result["details"]:
            tag = "OK " if d["blind_signed"] else "STAMP"
            verifier = d["verifier_id"] or "(none)"
            print(f"  [{tag}] {d['claim_id']}  verifier={verifier}  "
                  f"fact={d['fact_file'] or '(missing)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
