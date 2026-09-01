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

With --reliability, instead reports ICD-203 source_reliability coverage
of evidence/_index.json entries (P3 metric).

Exit 0 always — this is a measurement tool, not a gate.

Usage:
  python tools/auxiliary/measure_blind_coverage.py <workspace>
  python tools/auxiliary/measure_blind_coverage.py <workspace> --json
  python tools/auxiliary/measure_blind_coverage.py <workspace> --json --out cov.json
  python tools/auxiliary/measure_blind_coverage.py <workspace> --reliability

#277 CLI contract: --json emits machine JSON (stdout or --out FILE). Exit 0
always — this is a measurement tool, not a gate.
"""
from __future__ import annotations
import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
ensure_utf8_stdout()


import argparse
import json
import sys
from pathlib import Path

# scripts/ is on sys.path via pytest.ini pythonpath; for standalone CLI add it.
# #340: this script lives in tools/auxiliary/ — repo root is parents[2].
_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_TOOLS = Path(__file__).resolve().parent
for _p in (_SCRIPTS, _TOOLS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import yaml  # noqa: E402

from blind_gate import extract_verifier_signoff, find_fact_file  # noqa: E402

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.


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


def measure_reliability(ws: Path) -> dict:
    """Measure ICD-203 source_reliability coverage in evidence/_index.json.

    Returns dict with: total, with_reliability, missing, coverage,
    breakdown (per-type count + per-reliability-code count).
    """
    idx_path = ws / "evidence" / "_index.json"
    if not idx_path.exists():
        return {
            "total": 0,
            "with_reliability": 0,
            "missing": 0,
            "coverage": 0.0,
            "breakdown": {},
        }
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    entries = data.get("entries", [])
    total = len(entries)
    with_rel = sum(1 for e in entries if e.get("source_reliability"))
    missing = total - with_rel
    coverage = with_rel / total if total > 0 else 0.0

    by_type: dict[str, int] = {}
    by_code: dict[str, int] = {}
    for e in entries:
        t = e.get("type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
        code = e.get("source_reliability", "(missing)")
        by_code[code] = by_code.get(code, 0) + 1

    return {
        "total": total,
        "with_reliability": with_rel,
        "missing": missing,
        "coverage": round(coverage, 4),
        "by_type": by_type,
        "by_code": by_code,
    }


def _emit_json(payload: str, out: str | None) -> None:
    """Write JSON payload to --out FILE or stdout (#277)."""
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(payload, encoding="utf-8")
    else:
        print(payload)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure BLIND verifier coverage of PROVEN claims")
    ap.add_argument("workspace", type=Path, help="workspace root")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="machine-readable JSON output")
    ap.add_argument("--out", metavar="FILE",
                    help="write the JSON result to FILE instead of stdout (#277)")
    ap.add_argument("--reliability", action="store_true",
                    help="report ICD-203 source_reliability coverage instead")
    args = ap.parse_args(argv)

    if args.reliability:
        result = measure_reliability(args.workspace)
        if args.as_json:
            _emit_json(json.dumps(result, ensure_ascii=False, indent=2), args.out)
            return 0
        print(f"Total evidence entries: {result['total']}")
        print(f"With source_reliability: {result['with_reliability']}")
        print(f"Missing: {result['missing']}")
        pct = result["coverage"] * 100
        print(f"Coverage: {pct:.1f}%")
        if result.get("by_code"):
            print()
            print("By Admiralty code:")
            for code in sorted(result["by_code"]):
                print(f"  {code}: {result['by_code'][code]}")
        return 0

    result = measure(args.workspace)

    if args.as_json:
        _emit_json(json.dumps(result, ensure_ascii=False, indent=2), args.out)
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
