#!/usr/bin/env python3
"""tools/audit_legacy_proven.py — M4 issue #16: 46 假 PROVEN 审计工具.

读 workspace 的 claim-register.yaml + facts/_INDEX.md, 列全部 PROVEN claim,
按 BLIND 签字分类:
  - verified:               至少一条 fact 在 _INDEX 中有 "BLIND" 签字
  - has-evidence-no-signoff: 有 VERIFIED-BY-* (verifier 工作过) 但无 BLIND
  - unverified:             仅 PROVEN, 无任何 verifier 痕迹

用法:
  python tools/audit_legacy_proven.py <workspace>
  python tools/audit_legacy_proven.py <workspace> --output audit.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


# ---------- parsing ----------

def _parse_claim_register(ws: Path) -> list[dict]:
    """Parse claim-register.yaml, return list of claim dicts."""
    reg_path = ws / "claim-register.yaml"
    if not reg_path.exists():
        return []
    data = yaml.safe_load(reg_path.read_text(encoding="utf-8"))
    if not data or "claims" not in data:
        return []
    return data["claims"]


def _parse_index(ws: Path) -> dict[str, list[dict]]:
    """Parse facts/_INDEX.md.

    Returns: { claim_id: [ {fact_id, status, description}, ... ] }
    """
    index_path = ws / "facts" / "_INDEX.md"
    if not index_path.exists():
        return {}

    mapping: dict[str, list[dict]] = {}
    # Read bytes to handle mixed encodings, decode utf-8 with errors='replace'
    raw = index_path.read_bytes().decode("utf-8", errors="replace")

    for line in raw.splitlines():
        line = line.strip()
        if not line or not re.match(r"^F\d+", line):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        fact_id = parts[0]
        status = parts[1]
        claim_id = parts[2]
        description = parts[3] if len(parts) > 3 else ""
        mapping.setdefault(claim_id, []).append({
            "fact_id": fact_id,
            "status": status,
            "description": description,
        })
    return mapping


# ---------- classification ----------

def _classify(facts_for_claim: list[dict]) -> str:
    """Classify a PROVEN claim based on its fact statuses in _INDEX.

    Priority: BLIND > VERIFIED-BY > plain PROVEN
    """
    statuses = [f["status"].upper() for f in facts_for_claim]

    has_blind = any("BLIND" in s for s in statuses)
    has_verified_by = any(s.startswith("VERIFIED-BY") for s in statuses)

    if has_blind:
        return "verified"
    if has_verified_by:
        return "has-evidence-no-signoff"
    return "unverified"


# ---------- core audit ----------

def audit_workspace(ws: Path) -> dict:
    """Audit a workspace for legacy PROVEN claims without BLIND verification.

    Returns dict with:
      - workspace: str
      - total_proven: int
      - summary: {verified, has-evidence-no-signoff, unverified}
      - entries: [{claim_id, claim_statement, category, facts: [...]}]
    """
    claims = _parse_claim_register(ws)
    index_map = _parse_index(ws)

    proven_claims = [c for c in claims if c.get("status", "").upper() == "PROVEN"]

    entries = []
    for claim in proven_claims:
        cid = claim["id"]
        facts_for_claim = index_map.get(cid, [])
        category = _classify(facts_for_claim) if facts_for_claim else "unverified"
        entries.append({
            "claim_id": cid,
            "claim_statement": claim.get("statement", ""),
            "category": category,
            "facts": [
                {"fact_id": f["fact_id"], "status": f["status"]}
                for f in facts_for_claim
            ],
        })

    # Sort by claim_id for deterministic output
    entries.sort(key=lambda e: e["claim_id"])

    summary = {
        "verified": sum(1 for e in entries if e["category"] == "verified"),
        "has-evidence-no-signoff": sum(1 for e in entries if e["category"] == "has-evidence-no-signoff"),
        "unverified": sum(1 for e in entries if e["category"] == "unverified"),
    }

    return {
        "workspace": str(ws),
        "total_proven": len(proven_claims),
        "summary": summary,
        "entries": entries,
    }


# ---------- CLI ----------

def run_audit(ws: Path, output: str | None = None) -> dict:
    """Run audit and optionally write JSON output. Returns the result dict."""
    result = audit_workspace(ws)
    result["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # Human-readable summary to stdout
    _print_summary(result)
    return result


def _safe_print(msg: str) -> None:
    """Print with utf-8 fallback for Windows GBK console."""
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", errors="replace"))


def _print_summary(result: dict) -> None:
    """Print human-readable summary to stdout."""
    s = result["summary"]
    total = result["total_proven"]
    _safe_print(f"{'=' * 70}")
    _safe_print(f"  AUDIT: Legacy PROVEN — {result['workspace']}")
    _safe_print(f"  Total PROVEN claims: {total}")
    _safe_print(f"{'=' * 70}")
    _safe_print(f"  verified:                {s['verified']:>4}  (BLIND signoff)")
    _safe_print(f"  has-evidence-no-signoff: {s['has-evidence-no-signoff']:>4}  (verifier worked, no BLIND)")
    _safe_print(f"  unverified:              {s['unverified']:>4}  (plain PROVEN, no verifier)")
    _safe_print(f"{'=' * 70}")
    if total > 0:
        blind_rate = s["verified"] / total * 100
        _safe_print(f"  BLIND coverage: {blind_rate:.1f}%  ({s['verified']}/{total})")
        unverified_total = s["unverified"] + s["has-evidence-no-signoff"]
        _safe_print(f"  Needs action:  {unverified_total} claims without BLIND verification")
    _safe_print("")

    # List entries by category (most actionable first)
    for cat in ("unverified", "has-evidence-no-signoff", "verified"):
        cat_entries = [e for e in result["entries"] if e["category"] == cat]
        if cat_entries:
            _safe_print(f"\n--- {cat.upper()} ({len(cat_entries)}) ---")
            for e in cat_entries:
                stmt = e["claim_statement"][:80]
                _safe_print(f"  {e['claim_id']:12s} {stmt}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit legacy PROVEN claims for BLIND verification coverage."
    )
    parser.add_argument(
        "workspace",
        type=Path,
        help="Path to the workspace to audit.",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="Output JSON file path (default: audit-<ws_name>-<timestamp>.json in cwd).",
    )
    args = parser.parse_args(argv)

    ws = args.workspace
    if not ws.exists():
        print(f"Error: workspace does not exist: {ws}", file=sys.stderr)
        return 1

    output = args.output
    if output is None:
        ws_name = ws.name
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = f"audit-{ws_name}-{ts}.json"

    run_audit(ws, output=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
