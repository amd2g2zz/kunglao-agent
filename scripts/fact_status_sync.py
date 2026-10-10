#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fact_status_sync.py — the promotion write-back face.

The settle path promotes the claim register but the citing facts' frontmatter
status used to stay behind (register PROVEN, facts INFERRED): the completion
transaction recomputed dirty and the completion gate starved. The sync is one
mechanical write inside the same settle: when a claim settles PROVEN, every
fact citing it moves its status with the register.

Sync semantics (the credibility matrix is never violated):
  - synced   — a citing fact whose status is INFERRED or OPEN flips to the
               register's status; confidence moves to the only value the
               status legally carries (PROVEN pairs with high); the body
               `## Status` line and the facts/_INDEX.md row follow;
  - skipped  — a fact already carrying a terminal/negative status (NEGATIVE,
               REFUTED, ... — promotion never erases a falsification), a
               fact whose source is a judgment word (inference /
               analyst-judgment: a judgment cannot legally carry PROVEN —
               the information-vs-judgment separation), an unparsable fact;
               every skip names its reason and rides the settlement's
               observability row.
Fail-open: a broken fact, a broken index, an unwritable file — none blocks
the settlement; the sync reports what moved and what did not.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path

from _common import atomic_write_text
from kunglao_log import warn  # canonical warn: ONE implementation

#: statuses a promotion may move into the register's status
PROMOTABLE = frozenset({"INFERRED", "OPEN"})
#: sources that can never legally carry PROVEN (the credibility matrix)
JUDGMENT_SOURCES = frozenset({"inference", "analyst-judgment"})

_BODY_STATUS_RE = re.compile(r"(^##\s+Status\s*$\n+^\s*)([A-Z][A-Z-]*)\s*$",
                             re.MULTILINE)


def _today(created: str) -> str:
    """The sync date: today, never before the fact's created date (the
    never-backdate rule)."""
    today = datetime.date.today().isoformat()
    return max(today, created) if re.fullmatch(r"\d{4}-\d{2}-\d{2}",
                                               str(created)) else today


def _rewrite_fact(text: str, *, to_status: str, today: str) -> str:
    """Frontmatter status/confidence/last_reviewed + the body Status line,
    in one text pass (only the sync's own fields move)."""
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    in_fm = False
    fm_end = False
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            if not in_fm:
                in_fm = True
            elif not fm_end:
                fm_end = True
            out.append(line)
            continue
        if in_fm and not fm_end:
            key_match = re.match(r"^([a-z_]+)\s*:", line)
            if key_match and key_match.group(1) == "status":
                out.append(f"status: {to_status}\n")
                continue
            if key_match and key_match.group(1) == "confidence" \
                    and to_status == "PROVEN":
                out.append("confidence: high\n")
                continue
            if key_match and key_match.group(1) == "last_reviewed" \
                    and to_status == "PROVEN":
                out.append(f"last_reviewed: {today}\n")
                continue
        out.append(line)
    text = "".join(out)

    def _body_sub(m: "re.Match[str]") -> str:
        return f"{m.group(1)}{to_status}"

    return _BODY_STATUS_RE.sub(_body_sub, text)


def _sync_index_row(ws: Path, fid: str, to_status: str) -> int:
    """The facts/_INDEX.md row's status cell follows the fact (the completion
    transaction reads the index). Returns rows updated (0/1)."""
    rel = ws / "facts" / "_INDEX.md"
    if not rel.is_file():
        return 0
    try:
        text = rel.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        warn("fact_status_sync", f"index unreadable: {exc}")
        return 0
    rows = text.splitlines(keepends=True)
    out: list[str] = []
    changed = 0
    promotable_cells = PROMOTABLE | {to_status.upper()}
    for line in rows:
        has_nl = line.endswith("\n")
        stripped = line.rstrip("\n")
        lead = stripped.startswith("|")
        tail = stripped.endswith("|")
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) >= 2 and cells[0] == fid \
                and cells[1].upper() in promotable_cells \
                and cells[1].upper() != to_status.upper():
            cells[1] = to_status
            prefix = "| " if lead else ""
            suffix = " |" if tail else ""
            line = f"{prefix}{' | '.join(cells)}{suffix}" \
                   + ("\n" if has_nl else "")
            changed = 1
        out.append(line)
    if changed:
        try:
            atomic_write_text(rel, "".join(out))
        except OSError as exc:
            warn("fact_status_sync", f"index unwritable: {exc}")
            return 0
    return changed


def promote_citing_facts(ws, claim_id: str,
                         to_status: str = "PROVEN") -> dict:
    """Sync every citing fact's frontmatter with the register's promotion.

    Returns {"synced": [fact ids], "skipped": {fact id: reason}} — the
    settlement's observability row carries this verbatim. Only facts whose
    status is INFERRED/OPEN move; every other face is named and left alone."""
    ws = Path(ws)
    synced: list[str] = []
    skipped: dict[str, str] = {}
    try:
        from lint_facts import _load_fact
    except ImportError:
        return {"synced": [], "skipped": {}}
    facts_dir = ws / "facts"
    if not facts_dir.is_dir():
        return {"synced": [], "skipped": {}}
    for path in sorted(facts_dir.glob("*.md")):
        if path.name.startswith("_"):
            continue
        fid = path.stem
        try:
            fm = _load_fact(path)
        except Exception as exc:  # noqa: BLE001 — a broken fact never blocks
            skipped[fid] = f"unparsable: {type(exc).__name__}"
            continue
        if not isinstance(fm, dict):
            skipped[fid] = "unparsable"
            continue
        from register_proven_gate import _fact_claim_refs
        refs = _fact_claim_refs(fm)
        if claim_id not in refs:
            continue
        status = str(fm.get("status") or "").strip().upper()
        source = str(fm.get("source") or "").strip().lower()
        if status not in PROMOTABLE:
            skipped[fid] = f"status={status or 'unknown'} not promotable"
            continue
        if to_status == "PROVEN" and source in JUDGMENT_SOURCES:
            skipped[fid] = f"source={source} cannot carry PROVEN"
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            skipped[fid] = f"unreadable: {exc}"
            continue
        new_text = _rewrite_fact(text, to_status=to_status,
                                 today=_today(str(fm.get("created") or "")))
        try:
            atomic_write_text(path, new_text)
        except OSError as exc:
            skipped[fid] = f"unwritable: {exc}"
            continue
        _sync_index_row(ws, fid, to_status)
        synced.append(fid)
    return {"synced": synced, "skipped": skipped}
