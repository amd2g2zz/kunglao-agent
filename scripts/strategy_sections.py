#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""strategy_sections.py — the round-strategy object seam (event-wakeup
topology, issue 434 design item (b)).

The loop prompt splits into constitution (static, injected once at
SessionStart), STRATEGY SECTIONS (per decision, injected dynamically) and
guard guidance (dynamic, on Stop-hook fires). This module is the single
VERSIONED SEAM through which every consumer reads the round strategy:

    <ws>/runs/round-strategy.json
    {"schema": "round-strategy/1",
     "round": <int>,
     "sections": [{"title": str, "body": str}, ...]}

The PRODUCER of this object is the compose single-point's write face
(``rlvr.compose.write_strategy`` -> ``write_seam``, issue 462 W2): every
versioned compose re-emits this file as the derived projection of the
strategy in force. The seam contract that holds today:

  - absent file            -> render() == "" and pointer() is None
                             (renders NOTHING, cleanly — consumers stay
                             silent, no placeholder noise);
  - v1 object              -> render() emits one marked block per section;
  - unknown schema version -> render nothing + ONE canonical warn trace
                             (a future producer's format must never crash
                             a consumer that predates it);
  - unreadable/malformed   -> render nothing + ONE canonical warn trace.

Pure read side: this module never writes the strategy object and never
mutates workspace state. Fail-open by contract — an observation seam must
not become a failure source for its consumers.
"""
from __future__ import annotations

import json
from pathlib import Path

from kunglao_log import warn  # canonical warn: ONE implementation

STRATEGY_OBJECT_REL = Path("runs") / "round-strategy.json"
#: The schema token this consumer understands. Bump on a breaking change
#: to the sections shape; unknown tokens render nothing (see module
#: docstring) so old consumers survive new producers.
STRATEGY_SCHEMA = "round-strategy/1"

SECTION_MARK = "round-strategy"


def strategy_path(ws: Path) -> Path:
    return Path(ws) / STRATEGY_OBJECT_REL


def pointer(ws: Path) -> str | None:
    """The strategy pointer for continuity notes: the object's relative
    path when the object exists, None when it does not (the producer has
    not landed or no round strategy was ever written)."""
    p = strategy_path(ws)
    try:
        return STRATEGY_OBJECT_REL.as_posix() if p.is_file() else None
    except OSError as exc:
        warn("strategy_pointer", f"{type(exc).__name__}: {exc}")
        return None


def load(ws: Path) -> dict | None:
    """Parsed v1 strategy object, or None on every absent/unreadable/
    unknown-schema face. None is the CLEAN no-strategy verdict, never an
    exception."""
    p = strategy_path(ws)
    try:
        if not p.is_file():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn("strategy_load", f"{type(exc).__name__}: {p}: {exc}")
        return None
    if not isinstance(data, dict):
        warn("strategy_load", f"{p}: not a JSON object")
        return None
    if data.get("schema") != STRATEGY_SCHEMA:
        warn("strategy_schema",
             f"{p}: schema {data.get('schema')!r} != {STRATEGY_SCHEMA!r} — "
             f"consumer predates producer; rendering nothing")
        return None
    return data


def render(ws: Path) -> str:
    """The dynamic strategy sections: one marked block per section, or ""
    when there is no (readable, v1) strategy object. Consumers append the
    result to their injection face; an empty string must render NOTHING
    (no headers, no placeholders)."""
    data = load(ws)
    if data is None:
        return ""
    sections = data.get("sections")
    if not isinstance(sections, list):
        warn("strategy_render", "sections field missing or not a list")
        return ""
    blocks: list[str] = []
    for i, sec in enumerate(sections):
        if not isinstance(sec, dict):
            warn("strategy_render", f"section {i} is not an object — skipped")
            continue
        title = str(sec.get("title") or "").strip() or f"section-{i}"
        body = str(sec.get("body") or "").strip()
        if not body:
            continue
        blocks.append(f"<{SECTION_MARK} section=\"{title}\">\n{body}\n"
                      f"</{SECTION_MARK}>")
    return "\n".join(blocks)
