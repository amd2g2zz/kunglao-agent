#!/usr/bin/env python3
"""tools/auxiliary/audit_legacy_proven.py — M4 issue #16 + P5 issue #26: PROVEN audit tool.

Reads the workspace's claim-register.yaml + facts/_INDEX.md, lists every PROVEN claim,
and classifies along two independent dimensions:

BLIND sign-off dimension (issue #16):
  - verified:               at least one fact carries a "BLIND" sign-off in _INDEX
  - has-evidence-no-signoff: has VERIFIED-BY-* (a verifier worked) but no BLIND
  - unverified:             PROVEN only, no verifier trace at all

Index-traceability dimension (issue #26 / P5):
  - has-raw-evidence:       fact provenance cites a raw evidence/_index.json entry (path+hash validated)
  - derivation-only:        provenance cites only derived artifacts (not in the index) or a nonexistent path
  - unverifiable:           no provenance, no fact file, or nothing traceable in the index

Usage:
  python tools/auxiliary/audit_legacy_proven.py <workspace>
  python tools/auxiliary/audit_legacy_proven.py <workspace> --output audit.json
  python tools/auxiliary/audit_legacy_proven.py <workspace> --json        # JSON → stdout

#277 CLI contract: --output/--out/-o persists the JSON; --json emits it to
stdout. Exit codes: 0 = success, 2 = operational error (missing workspace).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)


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


# ---------- traceability (P5 issue #26) ----------

def _sha256(p: Path) -> str:
    """Compute sha256 hex digest of a file."""
    import hashlib
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_or_build_index(ws: Path) -> dict | None:
    """Load evidence/_index.json if present, otherwise build in-memory.

    Uses P1 build_evidence_index.build_index (no side effects — does not write).
    Returns None if no evidence dirs exist and no index file found.
    """
    idx_path = ws / "evidence" / "_index.json"
    if idx_path.exists():
        try:
            return json.loads(idx_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    # Try building in-memory (P1 builder). #340: build_evidence_index lives in
    # tools/pipelines/ — put that dir on sys.path for the lazy sibling import
    # (pytest.ini pythonpath already covers it under the test runner).
    try:
        _pipelines_dir = str(Path(__file__).resolve().parent.parent / "pipelines")
        if _pipelines_dir not in sys.path:
            sys.path.insert(0, _pipelines_dir)
        import build_evidence_index as bei
        return bei.build_index(ws)
    except Exception:
        return None


def _find_fact_file(ws: Path, fact_id: str) -> Path | None:
    """Find a fact markdown file matching fact_id (e.g. F001 → F001-*.md)."""
    facts_dir = ws / "facts"
    if not facts_dir.exists():
        return None
    # Exact match first
    exact = facts_dir / f"{fact_id}.md"
    if exact.exists():
        return exact
    # Glob prefix match (F001-*.md)
    matches = sorted(facts_dir.glob(f"{fact_id}*.md"))
    return matches[0] if matches else None


def _extract_fact_provenance(fact_path: Path) -> list[dict]:
    """Extract provenance refs from a fact file.

    Handles two formats:
    1. YAML frontmatter (--- delimited) with a 'provenance' key — the format
       used by real workspace facts. Each item is a flow dict {role, path,
       content_sha256}.
    2. Fenced or bare YAML provenance block — the P2 provenance_gate format.
       Falls back to provenance_gate.extract_provenance_refs.

    Returns a list of dicts, each containing at least 'path' and optionally
    'eid', 'content_sha256', 'role'.
    """
    fact_text = fact_path.read_text(encoding="utf-8", errors="replace")

    # Strategy 1: YAML frontmatter (real workspace format)
    refs = _extract_frontmatter_provenance(fact_text)
    if refs:
        return refs

    # Strategy 2: P2 provenance_gate parser (fenced/bare yaml blocks)
    try:
        from provenance_gate import extract_provenance_refs
        refs = extract_provenance_refs(fact_text)
        if refs:
            return refs
    except ImportError:
        pass

    return []


def _extract_frontmatter_provenance(text: str) -> list[dict]:
    """Parse YAML frontmatter and extract provenance entries.

    Frontmatter is delimited by --- at start and end of the file.
    Returns [] if no frontmatter or no provenance key.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return []
    # Find closing ---
    lines = stripped.splitlines()
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return []
    fm_text = "\n".join(lines[1:end_idx])
    try:
        parsed = yaml.safe_load(fm_text)
    except Exception:
        return []
    if not isinstance(parsed, dict):
        return []
    prov = parsed.get("provenance")
    if not isinstance(prov, list):
        return []
    result: list[dict] = []
    for item in prov:
        if isinstance(item, dict) and ("path" in item or "eid" in item):
            result.append(item)
    return result


def _classify_traceability(fact_path: Path | None, ws: Path, index: dict | None) -> str:
    """Classify a fact's evidence traceability via the evidence index.

    Returns:
      'has-raw-evidence' — at least one provenance ref resolves to an index entry
                           with matching sha256
      'derivation-only'  — has provenance refs but none resolve to indexed raw
                           (all derived, wrong path, or hash mismatch)
      'unverifiable'     — no provenance block, no fact file, or no index
    """
    # No index → can't trace anything
    if index is None or not index.get("entries"):
        return "unverifiable"

    # No fact file → can't trace
    if fact_path is None or not fact_path.exists():
        return "unverifiable"

    refs = _extract_fact_provenance(fact_path)
    if not refs:
        return "unverifiable"

    # Build path → index entry map
    entries = index.get("entries", [])
    by_path: dict[str, dict] = {e["path"]: e for e in entries if "path" in e}

    for ref in refs:
        path = ref.get("path")
        if not path:
            continue
        entry = by_path.get(path)
        if entry is None:
            continue  # not in index (derived or unknown)
        target = ws / path
        if not target.exists():
            continue
        actual_hash = _sha256(target)
        expected_hash = entry.get("sha256", "")
        if actual_hash == expected_hash:
            return "has-raw-evidence"

    # Has refs but none resolved to indexed raw with matching hash
    return "derivation-only"


# ---------- core audit ----------

def audit_workspace(ws: Path) -> dict:
    """Audit a workspace for legacy PROVEN claims.

    Returns dict with:
      - workspace: str
      - total_proven: int
      - summary: {verified, has-evidence-no-signoff, unverified}
      - traceability_summary: {has-raw-evidence, derivation-only, unverifiable}
      - entries: [{claim_id, claim_statement, category, index_traceability, facts: [...]}]
    """
    claims = _parse_claim_register(ws)
    index_map = _parse_index(ws)

    # Build evidence index for traceability (P5)
    ev_index = _get_or_build_index(ws)

    proven_claims = [c for c in claims if c.get("status", "").upper() == "PROVEN"]

    entries = []
    for claim in proven_claims:
        cid = claim["id"]
        facts_for_claim = index_map.get(cid, [])
        category = _classify(facts_for_claim) if facts_for_claim else "unverified"

        # Traceability: check each fact's provenance against evidence index
        fact_traceabilities: list[str] = []
        if facts_for_claim:
            for f in facts_for_claim:
                fact_path = _find_fact_file(ws, f["fact_id"])
                t = _classify_traceability(fact_path, ws, ev_index)
                fact_traceabilities.append(t)
        else:
            fact_traceabilities.append("unverifiable")

        # Claim-level traceability = best of its facts
        # (has-raw-evidence > derivation-only > unverifiable)
        if "has-raw-evidence" in fact_traceabilities:
            claim_traceability = "has-raw-evidence"
        elif "derivation-only" in fact_traceabilities:
            claim_traceability = "derivation-only"
        else:
            claim_traceability = "unverifiable"

        entries.append({
            "claim_id": cid,
            "claim_statement": claim.get("statement", ""),
            "category": category,
            "index_traceability": claim_traceability,
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

    traceability_summary = {
        "has-raw-evidence": sum(1 for e in entries if e["index_traceability"] == "has-raw-evidence"),
        "derivation-only": sum(1 for e in entries if e["index_traceability"] == "derivation-only"),
        "unverifiable": sum(1 for e in entries if e["index_traceability"] == "unverifiable"),
    }

    return {
        "workspace": str(ws),
        "total_proven": len(proven_claims),
        "summary": summary,
        "traceability_summary": traceability_summary,
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
    ts = result.get("traceability_summary", {})
    total = result["total_proven"]
    _safe_print(f"{'=' * 70}")
    _safe_print(f"  AUDIT: Legacy PROVEN — {result['workspace']}")
    _safe_print(f"  Total PROVEN claims: {total}")
    _safe_print(f"{'=' * 70}")
    _safe_print(f"  BLIND SIGNATURE DIMENSION:")
    _safe_print(f"    verified:                {s['verified']:>4}  (BLIND signoff)")
    _safe_print(f"    has-evidence-no-signoff: {s['has-evidence-no-signoff']:>4}  (verifier worked, no BLIND)")
    _safe_print(f"    unverified:              {s['unverified']:>4}  (plain PROVEN, no verifier)")
    if ts:
        _safe_print(f"  INDEX TRACEABILITY DIMENSION:")
        _safe_print(f"    has-raw-evidence:        {ts.get('has-raw-evidence', 0):>4}  (provenance cites index raw)")
        _safe_print(f"    derivation-only:         {ts.get('derivation-only', 0):>4}  (cites derived, not indexed)")
        _safe_print(f"    unverifiable:            {ts.get('unverifiable', 0):>4}  (no provenance / no index)")
    _safe_print(f"{'=' * 70}")
    if total > 0:
        blind_rate = s["verified"] / total * 100
        _safe_print(f"  BLIND coverage:     {blind_rate:.1f}%  ({s['verified']}/{total})")
        if ts:
            raw_rate = ts.get("has-raw-evidence", 0) / total * 100
            _safe_print(f"  Index traceability: {raw_rate:.1f}%  ({ts['has-raw-evidence']}/{total})")
        unverified_total = s["unverified"] + s["has-evidence-no-signoff"]
        _safe_print(f"  Needs BLIND action: {unverified_total} claims without BLIND verification")
    _safe_print("")

    # List entries by BLIND category (most actionable first)
    for cat in ("unverified", "has-evidence-no-signoff", "verified"):
        cat_entries = [e for e in result["entries"] if e["category"] == cat]
        if cat_entries:
            _safe_print(f"\n--- {cat.upper()} ({len(cat_entries)}) ---")
            for e in cat_entries:
                stmt = e["claim_statement"][:60]
                trace = e.get("index_traceability", "?")
                _safe_print(f"  {e['claim_id']:12s} [trace: {trace:20s}] {stmt}")


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
        "--output", "--out", "-o",
        type=str,
        default=None,
        help="Output JSON file path (default: audit-<ws_name>-<timestamp>.json in cwd).",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="emit the audit JSON to stdout instead of the human summary (#277)",
    )
    args = parser.parse_args(argv)

    ws = args.workspace
    if not ws.is_dir():
        print(f"Error: workspace does not exist: {ws}", file=sys.stderr)
        return 2

    result = audit_workspace(ws)
    result["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    output = args.output
    if output is None:
        ws_name = ws.name
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = f"audit-{ws_name}-{ts}.json"

    if output:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    if args.as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        _print_summary(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
