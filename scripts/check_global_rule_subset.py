#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_global_rule_subset.py — Validate global-rule hard prohibitions are a
semantic subset of SKILL.md hard prohibitions.

Issue #99 D14. Mechanical regex/keyword parser (no LLM).

Performs bidirectional check:
  Forward:  every global-rule item must be covered by a SKILL item
            (no fabricated prohibitions in the global rule)
  Reverse:  every SKILL item must be covered by a global-rule item
            (no missing critical prohibitions in the global rule)

Exit codes:
    0 — all checks pass (both directions)
    1 — gaps detected (missing prohibitions printed to stdout)
    2 — usage error / file not found

Usage:
    python scripts/check_global_rule_subset.py [--skill PATH] [--global-rule PATH]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Known HOST_FORBIDDEN_TOOLS (from hooks/worker_budget.py)
# ---------------------------------------------------------------------------
KNOWN_FORBIDDEN_TOOLS = frozenset({
    "mcp__x64dbg__start_session",
    "mcp__x64dbg__connect_to_session",
    "mcp__x64dbg__terminate_session",
    "mcp__x64dbg__connect_to_instance",
    "mcp__frida__spawn",
    "mcp__frida__attach",
})

# VM-related markers
_VM_MARKERS = frozenset({
    "vm-only", "vm_only", "vm-resident", "vm_only",
    "vmip", "vm_ip", "vmr-shell",
})

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _normalize_keywords(text: str) -> set[str]:
    """Extract lowercase alphanumeric keywords from text, dropping short words.

    Hyphenated words like 'poll-workers' are split into individual parts
    ('poll', 'workers') so that keyword matching works across different
    hyphenation styles in SKILL.md vs global rules.
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
    # Split hyphenated words into parts for better cross-file matching
    expanded = set()
    for w in words:
        expanded.add(w)
        if "-" in w:
            parts = w.split("-")
            expanded.update(p for p in parts if len(p) >= 3)
    return expanded


def _extract_section(text: str, heading_pattern: str) -> str:
    """Extract text from heading_pattern until the next same-or-higher heading.

    Stops at ## for ## sections, and at ### for ### sections (prevents
    subsection content from leaking into the parent section's items).
    """
    m = re.search(heading_pattern, text, re.IGNORECASE)
    if not m:
        return ""
    start = m.end()
    # Detect heading level from the pattern (count leading #)
    level = heading_pattern.count('#')
    # Build stop pattern: same level and all higher levels (fewer #)
    stop_parts = []
    for lvl in range(1, level + 1):
        stop_parts.append(r"\n(?=" + "#" * lvl + r"\s)")
    stop_pattern = "|".join(stop_parts)
    next_heading = re.search(stop_pattern, text[start:])
    if next_heading:
        return text[start : start + next_heading.start()]
    return text[start:]


def _split_numbered_items(section_text: str) -> list[dict[str, Any]]:
    """Split a section into numbered items.

    Handles two formats:
      SKILL.md: "N. **Title.** Body text" (period inside bold, no separator)
      Global:   "N. **Title** — Body text" (em-dash separator)
    """
    items = []
    # Pattern 1: "N. **Title.** Body" (SKILL.md style — period inside bold)
    # Pattern 2: "N. **Title** — Body" (global-rule style — em-dash separator)
    # Both: capture everything after the bold closing ** as the body
    pattern = re.compile(
        r"(\d+)\.\s+\*\*(.+?)\*\*\s*(?:[-—–.]*)?\s*(.+?)(?=\n\d+\.\s+\*\*|\n##\s|\Z)",
        re.DOTALL,
    )
    for m in pattern.finditer(section_text):
        number = int(m.group(1))
        title_raw = m.group(2).strip().rstrip(".")
        body_raw = m.group(3).strip().lstrip(":. ")
        # Collapse internal newlines in body
        body = " ".join(body_raw.split())
        title_keywords = _normalize_keywords(title_raw)
        body_keywords = _normalize_keywords(body)
        all_keywords = title_keywords | body_keywords
        items.append({
            "number": number,
            "title_raw": title_raw,
            "body": body,
            "title_keywords": title_keywords,
            "body_keywords": body_keywords,
            "all_keywords": all_keywords,
        })
    return items


def _detect_vm_only(item: dict[str, Any]) -> bool:
    """Detect if an item is about VM-only / host-forbidden tools."""
    text_lower = (item.get("title_raw", "") + " " + item.get("body", "")).lower()
    # Check VM markers
    for marker in _VM_MARKERS:
        if marker in text_lower:
            return True
    # Check HOST_FORBIDDEN_TOOLS references
    for tool in KNOWN_FORBIDDEN_TOOLS:
        if tool in text_lower:
            return True
    # Check for "host" + "forbidden" pattern
    if "host" in text_lower and ("forbidden" in text_lower or "forbid" in text_lower):
        return True
    return False


def parse_skill_prohibitions(skill_md: Path) -> list[dict[str, Any]]:
    """Parse SKILL.md Hard prohibitions section."""
    text = skill_md.read_text(encoding="utf-8")
    section = _extract_section(text, r"##\s+Hard\s+prohibitions")
    if not section:
        return []
    items = _split_numbered_items(section)
    for item in items:
        item["is_vm_only"] = _detect_vm_only(item)
    return items


def parse_global_rule_prohibitions(global_rule: Path) -> list[dict[str, Any]]:
    """Parse global-rule section 7 (硬禁止)."""
    text = global_rule.read_text(encoding="utf-8")
    # Try multiple heading patterns:
    # "## 7. 硬禁止" (Chinese), "## 7. Hard prohibitions" (English), "## Hard prohibitions"
    section = _extract_section(text, r"##\s+7\.\s*硬禁止")
    if not section:
        section = _extract_section(text, r"##\s+7\.\s*Hard\s+prohibitions")
    if not section:
        section = _extract_section(text, r"##\s+Hard\s+prohibitions")
    if not section:
        return []
    items = _split_numbered_items(section)
    return items


# ---------------------------------------------------------------------------
# Subset check
# ---------------------------------------------------------------------------

_OVERLAP_THRESHOLD = 0.25  # 25% keyword overlap is enough to consider "covered"
# (SKILL items are verbose English; global rules are compressed Chinese.
#  A single shared key concept like "mid-iteration" should be enough.)


def _is_item_covered_by_any(
    item: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> bool:
    """Check if an item is semantically covered by any candidate item.
    Direction-agnostic: works for global->SKILL and SKILL->global."""
    i_keys = item.get("all_keywords", set())
    i_title = item.get("title_raw", "").lower()
    i_body = item.get("body", "").lower()

    for candidate in candidates:
        c_title = candidate.get("title_raw", "").lower()
        c_body = candidate.get("body", "").lower()
        c_keys = candidate.get("all_keywords", set())

        # Check 1: title keyword containment (item title keywords subset of candidate body+title)
        i_title_words = _normalize_keywords(i_title)
        if i_title_words and i_title_words.issubset(
            _normalize_keywords(c_title + " " + c_body)
        ):
            return True

        # Check 2: keyword overlap ratio above threshold
        if i_keys and c_keys:
            intersection = i_keys & c_keys
            overlap = len(intersection) / len(i_keys)
            if overlap >= _OVERLAP_THRESHOLD:
                return True

        # Check 3: VM-ONLY specific — both reference VM/host-forbidden tools
        if _detect_vm_only(item) and _detect_vm_only(candidate):
            return True

        # Check 4: key phrase match (2+ word phrase from item body in candidate body)
        i_phrases = set(re.findall(r"\b\w{3,}\b(?:\s+\b\w{3,}\b){1,}", i_body))
        for phrase in i_phrases:
            if len(phrase.split()) >= 2 and phrase in c_body:
                return True

    return False


def parse_skill_behaviors(skill_md: Path) -> list[dict[str, Any]]:
    """Parse SKILL.md 5 behaviors section for additional matching scope.

    Expands SKILL parsing beyond Hard prohibitions so that global-rule items
    referencing behavioral concepts (e.g. false-completion-trap / declare done)
    can find matches in the full SKILL.md.
    """
    text = skill_md.read_text(encoding="utf-8")
    section = _extract_section(text, r"###\s+The\s+5\s+behaviors")
    if not section:
        return []
    return _split_numbered_items(section)


def parse_global_rule_behaviors(global_rule: Path) -> list[dict[str, Any]]:
    """Parse global-rule section 4 (5 behaviors) for bidirectional coverage."""
    text = global_rule.read_text(encoding="utf-8")
    section = _extract_section(text, r"##\s+4\.\s*5\s+behaviors")
    if not section:
        section = _extract_section(text, r"##\s+4\.\s*behaviors")
    if not section:
        return []
    return _split_numbered_items(section)


def _ensure_all_keywords(item: dict[str, Any]) -> None:
    """Compute all_keywords from title+body if not present."""
    if "all_keywords" not in item or not item["all_keywords"]:
        title_kw = item.get("title_keywords", set())
        body_kw = _normalize_keywords(item.get("body", ""))
        item["all_keywords"] = title_kw | body_kw
    if "body_keywords" not in item:
        item["body_keywords"] = _normalize_keywords(item.get("body", ""))


def check_bidirectional(
    global_items: list[dict[str, Any]],
    skill_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Check bidirectional coverage.

    Returns:
        (forward_missing, reverse_missing)
        - forward_missing: global-rule items NOT covered by any SKILL item
        - reverse_missing: SKILL items NOT covered by any global-rule item
    """
    # Ensure all_keywords is computed for all items
    for item in global_items:
        _ensure_all_keywords(item)
    for item in skill_items:
        _ensure_all_keywords(item)

    forward_missing = []
    for g_item in global_items:
        if not _is_item_covered_by_any(g_item, skill_items):
            forward_missing.append(g_item)

    reverse_missing = []
    for s_item in skill_items:
        if not _is_item_covered_by_any(s_item, global_items):
            reverse_missing.append(s_item)

    return forward_missing, reverse_missing


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check global-rule hard prohibitions are subset of SKILL.md"
    )
    parser.add_argument(
        "--skill",
        type=Path,
        default=None,
        help="Path to SKILL.md (default: auto-detect)",
    )
    parser.add_argument(
        "--global-rule",
        type=Path,
        default=None,
        help="Path to global-rule file (default: auto-detect)",
    )
    args = parser.parse_args()

    # Auto-detect paths
    script_dir = Path(__file__).resolve().parent
    skill_md = args.skill or script_dir.parent / "SKILL.md"
    global_rule = args.global_rule or script_dir.parent / "rules" / "kunglao-convergence-loop.md"

    if not skill_md.exists():
        print(f"ERROR: skill file not found: {skill_md}", file=sys.stderr)
        return 2
    if not global_rule.exists():
        print(f"ERROR: global-rule file not found: {global_rule}", file=sys.stderr)
        return 2

    skill_items = parse_skill_prohibitions(skill_md) + parse_skill_behaviors(skill_md)
    global_items = parse_global_rule_prohibitions(global_rule) + parse_global_rule_behaviors(global_rule)

    forward_missing, reverse_missing = check_bidirectional(global_items, skill_items)

    has_gaps = bool(forward_missing or reverse_missing)

    if reverse_missing:
        print(f"FAIL: {len(reverse_missing)} SKILL hard prohibition(s) MISSING from global rule:")
        for item in reverse_missing:
            print(f"  MISSING_FROM_GLOBAL #{item['number']}: {item.get('title_raw', 'unknown')}")
            print(f"    Body: {item.get('body', '')[:120]}")

    if forward_missing:
        print(f"FAIL: {len(forward_missing)} global-rule hard prohibition(s) NOT in SKILL.md:")
        for item in forward_missing:
            print(f"  EXTRA_IN_GLOBAL #{item['number']}: {item.get('title_raw', 'unknown')}")
            print(f"    Body: {item.get('body', '')[:120]}")

    if has_gaps:
        print()
        print(f"SKILL.md has {len(skill_items)} hard prohibition(s).")
        print(f"Global rule has {len(global_items)} hard prohibition(s).")
        print(f"Forward (global->SKILL): {len(global_items) - len(forward_missing)}/{len(global_items)} covered")
        print(f"Reverse (SKILL->global): {len(skill_items) - len(reverse_missing)}/{len(skill_items)} covered")
        return 1
    else:
        print(f"PASS: bidirectional check OK. "
              f"SKILL={len(skill_items)}, global={len(global_items)}, "
              f"all items covered in both directions.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
