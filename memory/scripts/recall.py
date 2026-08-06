"""F2 — Active recall: score longterm/ entries and inject top-K into context.

Triggered by SessionStart hook or cold-restart. Reads memory/longterm/INDEX.md,
loads each entry's frontmatter, scores against current workspace context,
formats top-K as a markdown block, prints to stdout (which Claude Code
captures as additional context per SessionStart hook protocol).

Scoring (sum of weighted signals, all 0..1):
  - keyword_overlap  * 0.4   (entry keywords ∩ task_spec keywords / union)
  - tag_overlap      * 0.3   (entry tag ∈ active claim types / primary_questions)
  - recency_score    * 0.2   (decay: exp(-age_days / 30))
  - citation_density * 0.1   (citations / 5, capped at 1.0)

Skip conditions (exclude from recall):
  - confidence < 0.3
  - superseded_by set in metadata
  - archived (path under longterm/.archived/)
  - last_cited_at < now - 90 days AND citations < 2

Usage:
  python recall.py [--top-k 5] [--inject-format md]
  # SessionStart hook: stdout = injected context block
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
LONGTERM_DIR = SCRIPT_DIR.parent / "longterm"
ARCHIVE_DIR = LONGTERM_DIR / ".archived"

DEFAULT_TOP_K = 5
MIN_CONFIDENCE = 0.3
RECENCY_FLOOR_DAYS = 90
MIN_CITATIONS_FOR_OLD = 2
DECAY_HALF_LIFE_DAYS = 30.0


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_entry(path: Path) -> dict | None:
    if not path.exists():
        return None
    if ARCHIVE_DIR in path.parents:
        return None
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    try:
        fm = yaml.safe_load(text[3:end]) or {}
    except yaml.YAMLError:
        return None
    meta = fm.get("metadata") or {}
    if not meta.get("cross_project"):
        return None
    if "superseded_by" in meta:
        return None
    confidence = float(meta.get("confidence", 0.5))
    if confidence < MIN_CONFIDENCE:
        return None
    citations = int(meta.get("citations", 0))
    modified = meta.get("modified")
    if modified:
        try:
            mod_dt = parse_iso(modified)
        except (ValueError, TypeError):
            mod_dt = utc_now()
    else:
        mod_dt = utc_now()
    age_days = (utc_now() - mod_dt).total_seconds() / 86400
    if age_days > RECENCY_FLOOR_DAYS and citations < MIN_CITATIONS_FOR_OLD:
        return None
    return {
        "path": path,
        "name": fm.get("name", path.stem),
        "description": fm.get("description", ""),
        "confidence": confidence,
        "citations": citations,
        "age_days": age_days,
        "modified": modified,
        "tags": meta.get("tags", []) or [],
        "type": meta.get("type", "rule"),
    }


def score_entry(entry: dict, ctx: dict) -> float:
    entry_kw = set(re.findall(r"\w{4,}", entry["description"].lower()))
    ctx_kw = set(re.findall(r"\w{4,}", (ctx.get("task_spec_keywords") or "").lower()))
    if ctx_kw:
        keyword_overlap = len(entry_kw & ctx_kw) / max(len(entry_kw | ctx_kw), 1)
    else:
        keyword_overlap = 0.5

    ctx_tags = set(ctx.get("active_tags") or [])
    if ctx_tags and entry["tags"]:
        tag_overlap = len(set(entry["tags"]) & ctx_tags) / max(len(ctx_tags), 1)
    else:
        tag_overlap = 0.5

    recency = math.exp(-entry["age_days"] / DECAY_HALF_LIFE_DAYS)
    citation_density = min(entry["citations"] / 5.0, 1.0)

    return (
        keyword_overlap * 0.4
        + tag_overlap * 0.3
        + recency * 0.2
        + citation_density * 0.1
    )


def recall(top_k: int = DEFAULT_TOP_K, ctx: dict | None = None) -> list:
    if ctx is None:
        ctx = {}
    if not LONGTERM_DIR.exists():
        return []
    candidates = []
    for p in LONGTERM_DIR.glob("*.md"):
        e = load_entry(p)
        if e is None:
            continue
        e["score"] = score_entry(e, ctx)
        candidates.append(e)
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]


def format_block(entries: list) -> str:
    if not entries:
        return ""
    lines = [f"## Recalled rules (top {len(entries)} from memory/longterm/)", ""]
    for i, e in enumerate(entries, 1):
        age = f"{e['age_days']:.0f}d ago"
        lines.append(
            f"{i}. **{e['name']}** "
            f"(confidence {e['confidence']:.2f}, {e['citations']} citations, last cited {age})"
        )
        if e["description"]:
            lines.append(f"   {e['description']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recall top-K longterm entries")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    parser.add_argument("--context", type=str, default="{}", help="JSON context (keywords, tags)")
    args = parser.parse_args()

    try:
        ctx = json.loads(args.context) if args.context else {}
    except json.JSONDecodeError as e:
        print(f"FAIL: invalid --context JSON: {e}", file=sys.stderr)
        return 1

    entries = recall(top_k=args.top_k, ctx=ctx)
    if args.json:
        print(json.dumps([
            {"name": e["name"], "description": e["description"], "score": e["score"]}
            for e in entries
        ], indent=2))
    else:
        print(format_block(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())