#!/usr/bin/env python3
"""validate_index.py — tools/_INDEX.yaml machine-contract validator (issue #283).

Validates the machine-readable tool index against the contract:

  name:         unique, non-empty (lowercase kebab-case tool id)
  category:     one of crypto|static|ghidra|dynamic|pipeline|aux
  capability:   "<domain>:<operation>" tag (e.g. crypto:decode), non-empty
  tier:         T1|T2|T3   (T1 static tool / T2 emulation / T3 VM-dynamic)
  cost_tier:    probe|cheap|deep
  input_output: non-empty input->output contract (str, or {input, output})
  when_not:     optional — when NOT to use the tool (non-empty if present)

CLI contract (gate-callable):
  python validate_index.py [path_to_index.yaml]
  exit 0 = pass, exit 1 = fail with an error list printed to stderr.
  Default path: tools/_INDEX.yaml (sibling of this script).

An empty index (`tools: []`, a missing `tools` key, or a null/empty YAML
payload) passes — the file ships as an initially-empty skeleton.

Usage:
  python tools/validate_index.py            # validate the shipped skeleton
  python tools/validate_index.py my-index.yaml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

CATEGORIES = ("crypto", "static", "ghidra", "dynamic", "pipeline", "aux")
TIERS = ("T1", "T2", "T3")
COST_TIERS = ("probe", "cheap", "deep")
REQUIRED_FIELDS = ("name", "category", "capability", "tier", "cost_tier",
                   "input_output")


def _is_nonempty_str(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_domain_operation(value: str) -> bool:
    """capability must be '<domain>:<operation>' with both sides non-empty."""
    if not _is_nonempty_str(value):
        return False
    domain, _, op = value.partition(":")
    return bool(domain.strip()) and bool(op.strip())


def _is_nonempty_io(value) -> bool:
    """input_output non-empty: a non-blank string, or a dict holding a value."""
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, dict):
        return bool(value) and any(_is_nonempty_str(v) for v in value.values())
    return False


def validate_index(data) -> list[str]:
    """Validate a parsed _INDEX.yaml payload. Returns a list of error strings.

    Empty payload / missing `tools` key -> empty index -> no errors.
    """
    errors: list[str] = []
    if data is None:
        return errors
    if not isinstance(data, dict):
        return ["index root must be a YAML mapping"]
    if "tools" not in data:
        return errors  # initially-empty skeleton: no tools list yet
    tools = data["tools"]
    if not isinstance(tools, list):
        return ["'tools' must be a list"]

    seen_names: dict[str, int] = {}
    for i, entry in enumerate(tools):
        loc = f"tools[{i}]"
        if not isinstance(entry, dict):
            errors.append(f"{loc}: entry must be a mapping")
            continue
        name = entry.get("name")
        if not _is_nonempty_str(name):
            errors.append(f"{loc}: missing or empty 'name'")
        elif name in seen_names:
            errors.append(f"{loc}: duplicate 'name' '{name}' (first at tools[{seen_names[name]}])")
        else:
            seen_names[name] = i

        category = entry.get("category")
        if category not in CATEGORIES:
            errors.append(f"{loc}: 'category' must be one of "
                          f"{'/'.join(CATEGORIES)}, got {category!r}")

        capability = entry.get("capability")
        if not _is_domain_operation(capability):
            errors.append(f"{loc}: 'capability' must be '<domain>:<operation>' "
                          f"(e.g. crypto:decode), got {capability!r}")

        tier = entry.get("tier")
        if tier not in TIERS:
            errors.append(f"{loc}: 'tier' must be one of {TIERS}, got {tier!r}")

        cost_tier = entry.get("cost_tier")
        if cost_tier not in COST_TIERS:
            errors.append(f"{loc}: 'cost_tier' must be one of "
                          f"{COST_TIERS}, got {cost_tier!r}")

        if not _is_nonempty_io(entry.get("input_output")):
            errors.append(f"{loc}: 'input_output' must be non-empty "
                          f"(str or {{input, output}})")

        when_not = entry.get("when_not")
        if when_not is not None and not _is_nonempty_str(when_not):
            errors.append(f"{loc}: optional 'when_not' must be a non-empty string")

    return errors


# ---- CLI ----

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="validate tools/_INDEX.yaml (issue #283)")
    ap.add_argument("path", nargs="?", default=None,
                    help="path to the index yaml (default: tools/_INDEX.yaml "
                         "next to this script)")
    args = ap.parse_args(argv)

    if args.path:
        index_path = Path(args.path)
    else:
        index_path = Path(__file__).resolve().parent / "_INDEX.yaml"
    if not index_path.is_file():
        print(f"error: index file not found: {index_path}", file=sys.stderr)
        return 1

    try:
        import yaml
        data = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - report any YAML parse failure
        print(f"error: failed to parse {index_path}: {exc}", file=sys.stderr)
        return 1

    errors = validate_index(data)
    if errors:
        print(f"error: {index_path} has {len(errors)} violation(s):",
              file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"ok: {index_path} passes the tools-index contract "
          f"({len(data.get('tools', [])) if isinstance(data, dict) else 0} tool(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
