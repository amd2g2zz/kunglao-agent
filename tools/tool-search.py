#!/usr/bin/env python3
"""tool-search.py — deterministic tool catalog query (issue #278 P4-a).

Zero-LLM, zero-network catalog query over tools/_INDEX.yaml. The index lists
analysis tools; tool-search itself is meta and is deliberately NOT registered
in the index.

Filters (combinable, AND semantics):
  --capability <domain:op>      exact or prefix match on the capability tag
                                ("crypto:decode" matches itself and any
                                "crypto:decode:*"; "ghidra" matches every
                                "ghidra:*" tag)
  --tier T1|T2|T3               exact tier match
  --cost-max probe|cheap|deep   budget filter: probe < cheap < deep
                                (inclusive — cheap returns probe + cheap)

Output: matching entries (name/category/capability/tier/cost_tier/
input_output, plus when_not when present) as JSON (--json: {count, tools})
or compact text (one line per entry).

Exit codes:
  0  query answered (matches, or a valid query with no match → empty output)
  2  usage error
  3  index missing/unreadable

Usage:
  python tools/tool-search.py --capability crypto:decode --json
  python tools/tool-search.py --tier T1 --cost-max cheap
  python tools/tool-search.py --capability ghidra --json path/to/_INDEX.yaml
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

COST_ORDER = ("probe", "cheap", "deep")   # probe < cheap < deep (budget)
TIERS = ("T1", "T2", "T3")
PUBLIC_KEYS = ("name", "category", "capability", "tier", "cost_tier",
               "input_output")


def load_index(index_path: Path) -> list[dict]:
    """Load tools/_INDEX.yaml → list of raw entries (order preserved)."""
    import yaml
    data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    tools = data.get("tools") if isinstance(data, dict) else None
    return tools if isinstance(tools, list) else []


def capability_matches(capability: str, query: str) -> bool:
    """Exact or prefix match on the capability tag."""
    return capability == query or capability.startswith(query)


def matches(entry: dict, capability: str | None, tier: str | None,
            cost_max: str | None) -> bool:
    """AND semantics: every provided filter must match the entry."""
    if capability is not None and not capability_matches(
            str(entry.get("capability", "")), capability):
        return False
    if tier is not None and entry.get("tier") != tier:
        return False
    if cost_max is not None:
        entry_cost = entry.get("cost_tier", "")
        if entry_cost in COST_ORDER and \
                COST_ORDER.index(entry_cost) > COST_ORDER.index(cost_max):
            return False
    return True


def entry_public(entry: dict) -> dict:
    """Project an index entry onto the public contract fields.

    when_not is optional in the schema — emitted only when present.
    """
    out = {k: entry.get(k) for k in PUBLIC_KEYS}
    if entry.get("when_not") is not None:
        out["when_not"] = entry["when_not"]
    return out


def format_text(tools: list[dict]) -> str:
    """Compact text: one line per entry, tab-separated public fields."""
    lines = []
    for t in tools:
        lines.append("\t".join(str(t.get(k, ""))
                               for k in ("name", "category", "capability",
                                         "tier", "cost_tier")))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="deterministic tool catalog query over tools/_INDEX.yaml "
                    "(issue #278 P4-a)")
    ap.add_argument("--capability", default=None,
                    help="capability tag, exact or prefix match "
                         "(e.g. crypto:decode, ghidra)")
    ap.add_argument("--tier", choices=TIERS, default=None,
                    help="exact tier match (T1 static / T2 emulation / "
                         "T3 VM-dynamic)")
    ap.add_argument("--cost-max", choices=COST_ORDER, default=None,
                    help="cost budget filter, inclusive: probe < cheap < deep")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON {count, tools} instead of compact text")
    ap.add_argument("index_path", nargs="?", default=None,
                    help="index yaml (default: tools/_INDEX.yaml next to "
                         "this script)")
    args = ap.parse_args(argv)

    index_path = Path(args.index_path) if args.index_path \
        else Path(__file__).resolve().parent / "_INDEX.yaml"
    if not index_path.is_file():
        print(f"error: index file not found: {index_path}", file=sys.stderr)
        return 3
    try:
        tools = load_index(index_path)
    except Exception as exc:  # noqa: BLE001 - report any unreadable index
        print(f"error: cannot read index {index_path}: {exc}", file=sys.stderr)
        return 3

    hits = [entry_public(t) for t in tools
            if matches(t, args.capability, args.tier, args.cost_max)]

    if args.json:
        print(json.dumps({"count": len(hits), "tools": hits},
                         ensure_ascii=False))
    else:
        text = format_text(hits)
        if text:
            print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
