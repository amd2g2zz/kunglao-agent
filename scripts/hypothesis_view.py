#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""hypothesis_view.py — read-only hypothesis view over the fact base.

Projects facts that carry an open `uncertainty` into the owner's
structured analysis object shape — {identity, object, hypothesis,
supporting, counter, status, next} — for human sync. This is a VIEW,
never a parallel truth: the substrate stays fact + claim + evidence,
the renderer writes nothing, and it consumes only frontmatter that
lint_facts already validates. Facts without `uncertainty` are invisible
here (absent is the common case); `next_probe` feeds the `next` slot
when present.

Relationship to promotion_gate: the gate is the CONDITION, the
next_probe field is the EXPERIMENT that tests it — the view keeps the
counter-face and the experiment-face side by side so a reviewer reads
the open hypothesis without opening each fact file.

Exit 0 = view rendered (possibly empty), 2 = usage error.

Usage:
    python scripts/hypothesis_view.py <WORKSPACE> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lint_facts import ACTIVE_SCHEMA_REV, parse_frontmatter  # noqa: E402

VIEW_FIELDS = ("identity", "object", "hypothesis", "supporting",
               "counter", "status", "next")


def _supporting(prov) -> list[dict]:
    """Minimal projection of provenance entries: locator + credibility."""
    rows: list[dict] = []
    for p in (prov if isinstance(prov, list) else []):
        if not isinstance(p, dict):
            continue
        row: dict = {"role": str(p.get("role", ""))}
        for k in ("path", "url", "bytes"):
            if p.get(k):
                row["where"] = str(p[k])
                break
        if p.get("credibility"):
            row["credibility"] = str(p["credibility"])
        rows.append(row)
    return rows


def _open_uncertainty(fm: dict) -> str:
    v = fm.get("uncertainty")
    return v.strip() if isinstance(v, str) else ""


def project_fact(fm: dict) -> dict:
    """One fact frontmatter -> the 7-key structured analysis object."""
    title = str(fm.get("title", "") or "")
    probe = fm.get("next_probe")
    return {
        "identity": str(fm.get("id", "") or ""),
        "object": title,
        "hypothesis": str(fm.get("claim", "") or title),
        "supporting": _supporting(fm.get("provenance")),
        "counter": _open_uncertainty(fm),
        "status": str(fm.get("status", "") or ""),
        "next": probe.strip() if isinstance(probe, str) else "",
    }


def collect(ws: Path) -> list[dict]:
    """Every fact with an open uncertainty, in stable id order."""
    facts_dir = Path(ws) / "facts"
    if not facts_dir.is_dir():
        return []
    entries: list[dict] = []
    for p in sorted(facts_dir.glob("F*.md")):
        if p.name == "_INDEX.md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, _body, perr = parse_frontmatter(text)
        if perr == "no-frontmatter" or not isinstance(fm, dict):
            continue
        if not _open_uncertainty(fm):
            continue
        entry = project_fact(fm)
        if not entry["identity"]:
            entry["identity"] = p.stem
        entries.append(entry)
    return entries


def render_human(entries: list[dict]) -> str:
    if not entries:
        return "no open-hypothesis facts (nothing carries uncertainty)\n"
    blocks: list[str] = []
    for e in entries:
        lines = [f"== {e['identity']} [{e['status']}] {e['object']}",
                 f"   hypothesis: {e['hypothesis']}",
                 f"   counter:    {e['counter']}"]
        for s in e["supporting"]:
            lines.append(f"   supporting: {s.get('role', '')}"
                         f" {s.get('where', '')}"
                         f" ({s.get('credibility', '')})".rstrip())
        lines.append(f"   next:       {e['next'] or '(no probe recorded)'}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + f"\n\n{len(entries)} open-hypothesis fact(s)\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="project open-uncertainty facts into the "
                    "structured analysis object shape (read-only)")
    ap.add_argument("ws", type=Path, help="workspace root (contains facts/)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    entries = collect(args.ws)
    if args.json:
        print(json.dumps({"active_schema_rev": ACTIVE_SCHEMA_REV,
                          "count": len(entries), "facts": entries},
                         ensure_ascii=False, indent=2))
    else:
        print(render_human(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())
