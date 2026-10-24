# -*- coding: utf-8 -*-
"""negative_cache — TTL-bounded negative-result cache for toolfirst
search (#812 acceptance 2).

The production shape (logs-panel RC5): toolfirst ran identical negative
queries repeatedly ("static-decompile/android-apk/jadx" 8x,
"mitm/capture/tls" -> no 5x, "mitm" -> no 2x) with zero negative caching,
so the dead lane kept being re-probed and the correct pivot came a day
late. This module is the cache face; tools/tool-search.py --find is the
wired consumer (THE agent search entry, #162/#476).

Contract:
  - a NEGATIVE search (0 hits) is a fact worth remembering: recorded PER
    FAMILY — the family key is the query's normalized term set
    (sorted/unique/lowercase), so "jadx apk" and "APK jadx" are one lane;
  - within TTL, an identical negative query is ANSWERED from the cache —
    the four-source scan does not re-run (the dead lane is not re-probed;
    the served row carries occurrence/cached_at/ttl_remaining so the
    agent SEES the repetition);
  - Standard 11 (bounded repetition + ownership transfer): occurrences
    count PER FAMILY; the occurrence AT the limit escalates
    (`escalated: true` — the dead-lane verdict, bounded silence on the
    nagging while the count keeps accruing). The count never resets on
    TTL expiry — the audit keeps counting.
  - fail-open everywhere: an unreadable store degrades to silence (no
    cache, full scan) — one bad JSON file must not brick the query face.

ZERO LEARNING POSTURE: no model call, no fitted parameter. The TTL and
the repeat limit are documented policy constants.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

#: how long a negative answer stays authoritative (re-probe after this)
NEGATIVE_TTL_SECONDS = 1800

#: Standard 11: the family occurrence AT this limit escalates to the
#: dead-lane verdict (`escalated: true`); beyond it, the cache still
#: answers (bounded re-probe prevention) while the count keeps accruing
NEGATIVE_REPEAT_LIMIT = 3

STORE_REL = Path("runs") / ".toolsearch-negative-cache.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_family(terms) -> str:
    """The family key: the query's term set, sorted/unique/lowercase,
    pipe-joined ("jadx apk" and "APK jadx" are one lane)."""
    cleaned = {str(t).strip().lower() for t in (terms or [])
               if str(t).strip()}
    return "|".join(sorted(cleaned))


def _load(ws) -> dict:
    path = Path(ws) / STORE_REL
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _save(ws, doc: dict) -> None:
    path = Path(ws) / STORE_REL
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass  # fail-open: the cache never blocks the query face


def store_negative_state(ws, doc: dict) -> None:
    """Test/audit seam: replace the whole store document (best-effort
    save, fail-open like every face here)."""
    _save(ws, doc if isinstance(doc, dict) else {})


def lookup(ws, family: str, *, now=None,
           ttl: int = NEGATIVE_TTL_SECONDS) -> dict | None:
    """The fresh cached row for `family`, or None (expired/absent/unreadable
    -> full scan proceeds). Served rows carry occurrence / escalated /
    cached_at / ttl_remaining — the agent sees the repetition."""
    doc = _load(ws)
    fams = doc.get("families")
    entry = fams.get(family) if isinstance(fams, dict) else None
    if not isinstance(entry, dict):
        return None
    last = _parse_ts(str(entry.get("last_ts") or ""))
    if last is None:
        return None
    now = now or _utc_now()
    drift = (now - last).total_seconds()
    if drift > ttl:
        return None
    return {"family": family,
            "occurrence": int(entry.get("occurrence") or 0),
            "escalated": bool(entry.get("escalated")),
            "cached_at": str(entry.get("last_ts") or ""),
            "ttl_remaining": max(0, int(ttl - drift))}


def record_negative(ws, family: str, query: str, *, now=None,
                    limit: int = NEGATIVE_REPEAT_LIMIT) -> dict:
    """Record one negative occurrence for `family`; returns the stored
    row (occurrence counting is PER FAMILY — Standard 11)."""
    ws = Path(ws)
    now = now or _utc_now()
    ts = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    doc = _load(ws)
    fams = doc.setdefault("families", {})
    entry = fams.get(family)
    if not isinstance(entry, dict):
        entry = {"occurrence": 0, "first_ts": ts, "escalated": False,
                 "query": str(query or "")[:200]}
    entry["occurrence"] = int(entry.get("occurrence") or 0) + 1
    entry["last_ts"] = ts
    entry["query"] = str(query or "")[:200]
    if entry["occurrence"] >= limit:
        entry["escalated"] = True
    fams[family] = entry
    _save(ws, doc)
    return {"family": family,
            "occurrence": entry["occurrence"],
            "escalated": entry["escalated"],
            "cached_at": entry["last_ts"]}
