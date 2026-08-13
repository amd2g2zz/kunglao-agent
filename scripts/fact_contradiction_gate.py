# -*- coding: utf-8 -*-
"""fact_contradiction_gate — same-topic PROVEN contradiction detection (#47).

a2b5e25c problem 2: F035 and F040 were both PROVEN on the same routing topic
with conflicting conclusions and no supersedes relationship; the register
machinery never noticed and the report froze the wrong routing conclusion.

This gate scans facts/_INDEX.md + fact frontmatter and flags same-topic
multi-PROVEN pairs whose conclusions differ, unless a supersedes /
superseded_by link resolves the pair. Promotion paths (claim_migrator,
worker_budget backstop) downgrade to STAMP (needs-resolution) on CONFLICT.

Topic (design D2): two facts are same-topic iff their topic-key sets
(claim_id, else sample_refs, else cites) intersect.

Usage:
    python fact_contradiction_gate.py <ws>   # print conflicts, exit 0 clean / 1 conflict
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

# Shared promotion-downgrade status (mirrors blind_gate.STAMP — the effective
# status written when a gate fails, non-terminal).
STAMP = "STAMP"

PROVEN = "PROVEN"

# _INDEX.md row separator (scripts/update_index.py)
_SEP = " | "

_FRONTMATTER_KEYS = ("sample_refs", "cites", "supersedes", "superseded_by")

_F_ID_RE = re.compile(r"F-?(\w+)", re.IGNORECASE)


def _norm_id(raw: str) -> str:
    """Normalize a fact-id reference: F035 / F-035 / f-035 → F035."""
    m = _F_ID_RE.search(str(raw))
    return f"F{m.group(1)}" if m else str(raw).strip()


def _extract_yaml_keys(fact_text: str) -> dict[str, list[str]]:
    """Collect values for the frontmatter keys of interest from a fact file.

    Sources, in order: fenced ```yaml blocks (yaml.safe_load), then line-level
    `key: value` fallback (works for plain lines and comma-separated values;
    trailing `#` comments are stripped).
    """
    collected: dict[str, list[str]] = {k: [] for k in _FRONTMATTER_KEYS}
    if yaml is not None:
        for m in re.finditer(r"```yaml\s*(.*?)```", fact_text, re.DOTALL):
            try:
                parsed = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                continue
            if not isinstance(parsed, dict):
                continue
            for key in _FRONTMATTER_KEYS:
                val = parsed.get(key)
                if val is None:
                    continue
                if isinstance(val, str):
                    collected[key].append(val)
                elif isinstance(val, (list, tuple)):
                    collected[key].extend(str(v) for v in val)
    for key in _FRONTMATTER_KEYS:
        for m in re.finditer(rf"^\s*{key}:\s*(.+)$", fact_text, re.MULTILINE):
            raw = m.group(1).split("#")[0].strip()
            if raw:
                collected[key].extend(p.strip() for p in raw.split(",") if p.strip())
    return collected


def _read_fact_text(facts_dir: Path, fact_id: str) -> str:
    f = facts_dir / f"{fact_id}.md"
    if f.exists():
        return f.read_text(encoding="utf-8", errors="replace")
    return ""


def _read_index_rows(index_path: Path) -> list[dict]:
    """Parse facts/_INDEX.md rows: F<id> | <status> | <claim_id> | <conclusion>."""
    if not index_path.exists():
        return []
    rows = []
    for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in s.split(_SEP)]
        if len(parts) >= 4:
            rows.append({
                "fact_id": parts[0],
                "status": parts[1],
                "claim_id": parts[2],
                "conclusion": _SEP.join(parts[3:]),
            })
    return rows


def _topic_keys(row: dict, meta: dict) -> set[str]:
    """Topic key set (design D2): claim_id ∪ sample_refs ∪ cites.

    Two facts are same-topic iff their key sets intersect (claim_id equality,
    sample_refs overlap, or cites overlap). A fact with no keys at all can
    never be same-topic with anything.
    """
    keys: set[str] = set()
    if row.get("claim_id"):
        keys.add(f"claim:{row['claim_id']}")
    for r in meta.get("sample_refs") or []:
        keys.add(f"ref:{r}")
    for c in meta.get("cites") or []:
        keys.add(f"cite:{c}")
    return keys


def _supersedes_links(meta: dict) -> set[str]:
    """Normalized set of fact ids this fact supersedes / is superseded by."""
    links: set[str] = set()
    for key in ("supersedes", "superseded_by"):
        for raw in meta.get(key) or []:
            for token in re.split(r"[\s,]+", str(raw)):
                if token:
                    links.add(_norm_id(token))
    return links


def _conclusion_key(conclusion: str) -> str:
    """Whitespace-normalized conclusion for equality comparison (design D3)."""
    return " ".join(conclusion.split())


def scan_conflicts(index_path: Path, facts_dir: Path) -> list[dict]:
    """Return CONFLICT pairs among PROVEN facts (design D1/D4).

    A pair conflicts when all hold:
      - both rows have status PROVEN
      - topic-key intersection is non-empty
      - conclusions differ (whitespace-normalized)
      - neither side declares a supersedes / superseded_by link naming the other
    """
    rows = [r for r in _read_index_rows(index_path) if r["status"] == PROVEN]
    if len(rows) < 2:
        return []
    metas: dict[str, dict] = {}
    for r in rows:
        metas[r["fact_id"]] = _extract_yaml_keys(_read_fact_text(facts_dir, r["fact_id"]))
    conflicts: list[dict] = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            keys_a = _topic_keys(a, metas[a["fact_id"]])
            keys_b = _topic_keys(b, metas[b["fact_id"]])
            if not (keys_a and keys_b and (keys_a & keys_b)):
                continue
            if _conclusion_key(a["conclusion"]) == _conclusion_key(b["conclusion"]):
                continue  # same conclusion on the same topic = converged
            links_a = _supersedes_links(metas[a["fact_id"]])
            links_b = _supersedes_links(metas[b["fact_id"]])
            if a["fact_id"] in links_b or b["fact_id"] in links_a:
                continue  # supersedes / superseded_by link resolves the pair
            conflicts.append({
                "fact_a": a["fact_id"],
                "fact_b": b["fact_id"],
                "claim_a": a["claim_id"],
                "claim_b": b["claim_id"],
                "conclusion_a": a["conclusion"],
                "conclusion_b": b["conclusion"],
            })
    return conflicts


def check_proven_contradiction(
    claim_id: str,
    facts_dir: Path,
    index_path: Path | None = None,
) -> tuple[bool, str]:
    """Whether promoting claim_id to PROVEN is contradiction-free (D5 wire 1).

    Returns (allowed, reason). On CONFLICT the reason names every pair whose
    topic includes the claim being promoted.
    """
    index_path = index_path or facts_dir / "_INDEX.md"
    conflicts = scan_conflicts(index_path, facts_dir)
    involved = [c for c in conflicts
                if c["claim_a"] == claim_id or c["claim_b"] == claim_id]
    if involved:
        pairs = "; ".join(f"{c['fact_a']} <-> {c['fact_b']}" for c in involved)
        return (False,
                f"CONFLICT (needs-resolution): same-topic PROVEN facts with "
                f"differing conclusions and no supersedes link: {pairs}")
    return (True, "no same-topic PROVEN contradiction")


def main(argv: list[str] | None = None) -> int:
    """CLI (D6): print conflicts; exit 0 clean / 1 if any CONFLICT."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ws", type=Path, help="workspace root (facts/ inside)")
    args = ap.parse_args(argv)
    conflicts = scan_conflicts(args.ws / "facts" / "_INDEX.md", args.ws / "facts")
    for c in conflicts:
        print(f"CONFLICT: {c['fact_a']} <-> {c['fact_b']} "
              f"(claims {c['claim_a']}/{c['claim_b']}) — different conclusions, "
              f"no supersedes link (needs-resolution)")
    if conflicts:
        return 1
    print("no same-topic PROVEN contradictions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
