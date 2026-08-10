"""provenance_gate — evidence provenance gate (P2, PRD evidence-integrity-icd203).

Every fact must cite its evidence via the evidence index (evidence/_index.json).
Refs must resolve to an index entry (by eid or path) whose sha256 matches the
file on disk. Derived files (summary.json, correlated.json, verdict.json, etc.)
are excluded from the index by the P1 builder, so citing them fails naturally.

This module is pure (no I/O side effects): callers pass a fact path and
workspace root; the function reads the index + target files and returns a
verdict. Wiring into the promotion pipeline lives elsewhere (same pattern as
blind_gate.py).

check_provenance_gate(fact_path, ws) -> (ok, reason)
  ok=True   — all provenance refs resolve to index entries with matching hash
  ok=False  — at least one ref is missing, derived, or hash-mismatched

Provenance block format in fact markdown:
    ```yaml
    provenance:
      - eid: E001
      - path: evidence/x64dbg-c206-capture.txt
    ```
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_provenance_refs(fact_text: str) -> list[dict]:
    """Parse provenance block from fact text.

    Returns a list of ref dicts, each containing 'eid' and/or 'path'.
    Returns [] if no provenance block is found.
    """
    if not fact_text or "provenance" not in fact_text:
        return []
    # Try fenced yaml block
    m = re.search(r"```ya?ml\s*(provenance:\s*.*?)```", fact_text, re.DOTALL)
    if m:
        return _parse_provenance_yaml(m.group(1))
    # Fallback: bare yaml form
    m = re.search(
        r"provenance:\s*\n(.*?)(?:\n\n|\n```|\Z)", fact_text, re.DOTALL
    )
    if m:
        return _parse_provenance_yaml("provenance:\n" + m.group(1))
    return []


def _parse_provenance_yaml(yaml_text: str) -> list[dict]:
    """Parse a provenance YAML snippet into a list of ref dicts."""
    try:
        import yaml

        parsed = yaml.safe_load(yaml_text) or {}
    except Exception:
        return []
    if not isinstance(parsed, dict) or "provenance" not in parsed:
        return []
    refs = parsed["provenance"]
    if not isinstance(refs, list):
        return []
    result: list[dict] = []
    for item in refs:
        if isinstance(item, dict) and ("eid" in item or "path" in item):
            result.append(item)
    return result


def _load_index(ws: Path) -> dict | None:
    """Load evidence/_index.json from workspace root."""
    idx_path = ws / "evidence" / "_index.json"
    if not idx_path.exists():
        return None
    try:
        return json.loads(idx_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def check_provenance_gate(fact_path: Path, ws: Path) -> tuple[bool, str]:
    """Check that a fact's provenance refs are all valid.

    A ref is valid when:
      1. It cites an eid or path that exists in evidence/_index.json
      2. The referenced file exists at ws / entry["path"]
      3. The file's sha256 matches the index entry's sha256

    Returns (ok, reason):
      ok=True, reason="..."  — all refs valid
      ok=False, reason="..." — at least one ref invalid (reason explains why)
    """
    # --- Load index ---
    idx = _load_index(ws)
    if idx is None:
        return (False, "evidence/_index.json not found — cannot verify provenance")

    entries = idx.get("entries", [])
    if not entries:
        return (False, "evidence/_index.json has no entries")

    by_eid: dict[str, dict] = {e["eid"]: e for e in entries if "eid" in e}
    by_path: dict[str, dict] = {
        e["path"]: e for e in entries if "path" in e
    }

    # --- Parse fact ---
    if not fact_path.exists():
        return (False, f"fact file not found: {fact_path}")

    fact_text = fact_path.read_text(encoding="utf-8", errors="replace")
    refs = extract_provenance_refs(fact_text)
    if not refs:
        return (
            False,
            f"no provenance block found in {fact_path.name} — "
            f"fact must cite evidence via eid or path",
        )

    # --- Validate each ref ---
    for i, ref in enumerate(refs):
        eid = ref.get("eid")
        path = ref.get("path")

        # Resolve ref to index entry
        entry = None
        if eid:
            entry = by_eid.get(eid)
            if entry is None:
                return (
                    False,
                    f"provenance ref {i+1}: eid {eid!r} not found in "
                    f"evidence index",
                )
        elif path:
            entry = by_path.get(path)
            if entry is None:
                return (
                    False,
                    f"provenance ref {i+1}: path {path!r} not in evidence "
                    f"index (it may be a derived artifact)",
                )
        else:
            return (
                False,
                f"provenance ref {i+1}: neither 'eid' nor 'path' specified",
            )

        # Verify file exists
        target = ws / entry["path"]
        if not target.exists():
            return (
                False,
                f"provenance ref {i+1}: file {entry['path']!r} "
                f"(eid {entry.get('eid', '?')}) does not exist on disk",
            )

        # Verify hash
        actual_hash = _sha256(target)
        expected_hash = entry.get("sha256", "")
        if actual_hash != expected_hash:
            return (
                False,
                f"provenance ref {i+1}: sha256 mismatch for "
                f"{entry['path']!r} (eid {entry.get('eid', '?')}) — "
                f"index={expected_hash[:12]} actual={actual_hash[:12]}",
            )

    return (True, f"all {len(refs)} provenance ref(s) verified")
