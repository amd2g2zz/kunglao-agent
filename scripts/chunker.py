# -*- coding: utf-8 -*-
"""chunker.py — length-measured batch chunking (issue #309).

Absorbed idea: amruth-sn/kong supervisor.py:332-362 (split large batches by
the model's measured character budget), re-implemented for the kunglao
tool/worker contract. Prevents context overflow when a worker receives a
large function batch (e.g. 500 decompiled functions): items are packed
greedily into chunks whose MEASURED prompt length stays within the budget.

Measured length is the actual prompt contribution:
    chunk_len = PER_CHUNK_OVERHEAD_CHARS
              + sum(PER_ITEM_OVERHEAD_CHARS + len(name) + len(text))
    budget_chars = budget_tokens * chars_per_token   (default 3.5 chars/token)

An item larger than the budget alone gets its own chunk flagged
`overflow: true` (never silently dropped or split mid-text).

Usage:
  python scripts/chunker.py --input functions.json --budget-tokens 4096 --json
Input JSON: {"functions": [{"name": ..., "text": ...}, ...]} or a bare list.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

CHARS_PER_TOKEN_DEFAULT = 3.5
PER_ITEM_OVERHEAD_CHARS = 40
PER_CHUNK_OVERHEAD_CHARS = 200

SCRIPT_PATH = Path(__file__).resolve()


def item_chars(item: dict, name_key: str = "name", text_key: str = "text") -> int:
    """Measured prompt contribution of one item (framing + name + text)."""
    name = str(item.get(name_key, "") or "")
    text = str(item.get(text_key, "") or "")
    return PER_ITEM_OVERHEAD_CHARS + len(name) + len(text)


def chunk_items(items: list[dict], budget_tokens: int,
                chars_per_token: float = CHARS_PER_TOKEN_DEFAULT) -> list[dict]:
    """Greedy pack into chunks within the measured character budget.

    Returns [{"index", "items", "measured_chars", "estimated_tokens",
    "budget_chars", "overflow"}]. Deterministic: same input -> same output.
    """
    if not items:
        return []
    budget_chars = float(budget_tokens) * float(chars_per_token)
    chunks: list[dict] = []
    current: list[dict] = []
    current_len = PER_CHUNK_OVERHEAD_CHARS
    for item in items:
        size = item_chars(item)
        if size > budget_chars - PER_CHUNK_OVERHEAD_CHARS:
            # oversized single item: flush current, then own flagged chunk
            if current:
                chunks.append(_make_chunk(len(chunks), current, current_len,
                                          budget_chars, chars_per_token))
                current, current_len = [], PER_CHUNK_OVERHEAD_CHARS
            chunks.append(_make_chunk(len(chunks), [item],
                                      PER_CHUNK_OVERHEAD_CHARS + size,
                                      budget_chars, chars_per_token,
                                      overflow=True))
            continue
        if current and current_len + size > budget_chars:
            chunks.append(_make_chunk(len(chunks), current, current_len,
                                      budget_chars, chars_per_token))
            current, current_len = [], PER_CHUNK_OVERHEAD_CHARS
        current.append(item)
        current_len += size
    if current:
        chunks.append(_make_chunk(len(chunks), current, current_len,
                                  budget_chars, chars_per_token))
    return chunks


def _make_chunk(index: int, items: list[dict], measured: float,
                budget_chars: float, chars_per_token: float,
                overflow: bool = False) -> dict:
    return {
        "index": index,
        "items": items,
        "measured_chars": measured,
        "estimated_tokens": measured / chars_per_token,
        "budget_chars": budget_chars,
        "overflow": overflow,
    }


def _load_input(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        funcs = data.get("functions")
        if isinstance(funcs, list):
            return funcs
        raise ValueError("input JSON must be a list or {'functions': [...]}")
    raise ValueError("input JSON must be a list or {'functions': [...]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="chunker.py",
        description="split a function batch into chunks within a measured "
                    "prompt-length budget (#309)")
    ap.add_argument("--input", required=True, help="JSON file: list or {'functions': [...]}")
    ap.add_argument("--budget-tokens", type=int, required=True,
                    help="model token budget per chunk")
    ap.add_argument("--chars-per-token", type=float, default=CHARS_PER_TOKEN_DEFAULT,
                    help="length estimate (default 3.5 chars/token)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value input lines (kunglao_verify parseable)")
    args = ap.parse_args(argv)

    inp = Path(args.input)
    if args.reproduce:
        print(f"input={inp}")
        print(f"budget_tokens={args.budget_tokens}")
        print(f"chars_per_token={args.chars_per_token}")
        return 0
    if not inp.exists():
        print(f"error: input not found: {inp}", file=sys.stderr)
        return 1
    try:
        items = _load_input(inp)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    chunks = chunk_items(items, args.budget_tokens, args.chars_per_token)
    payload = {
        "n_items": len(items),
        "n_chunks": len(chunks),
        "budget_tokens": args.budget_tokens,
        "chars_per_token": args.chars_per_token,
        "chunks": chunks,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{len(items)} items -> {len(chunks)} chunk(s) "
              f"(budget {args.budget_tokens} tokens, {args.chars_per_token} chars/token)")
        for c in chunks:
            flag = " OVERFLOW" if c["overflow"] else ""
            print(f"  chunk {c['index']}: {len(c['items'])} items, "
                  f"{c['measured_chars']:.0f}/{c['budget_chars']:.0f} chars{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
