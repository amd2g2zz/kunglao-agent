# -*- coding: utf-8 -*-
"""rl_digest.py — the per-decision RL digest line (the round-closure visibility face).

The RL decides every round (strategy compose, settlements, credit) but the
scrolling transcript carried none of it: an operator watching a live
session had to open ``runs/*.jsonl`` by hand to see "the RL just settled
X / is leading with family Y". This module owns the rendering of ONE
digest line over surfaces that already exist — no new stores:

    RL: lead=<method_lead|none>(<age>) last-settle=<anchor:band|none> round=<n>

Sources (both read-only):
  - the strategy object IN FORCE — the latest versioned tick file the
    compose single-point wrote (``rlvr.compose.read_strategy``; schema
    ``round-strategy/1``). ``lead`` and ``round`` are copied verbatim;
    the age derives from the object's own ``ts`` (never the wall clock
    standing in for a missing timestamp: an unreadable ts renders "?");
  - the settled-ledger tail (``rlvr.ledger.settled``): the newest folded
    settled row's ``anchor:band`` (the claim:outcome pair), or the
    explicit ``none`` when the ledger holds no settlement yet.

Determinism wall: the line is a pure template over those fields — no
model call, no invented sentence. Same (strategy object, ledger tail) ->
byte-identical line.

Rate limit (one line per DECISION, never per event): the closure event
fires on every SubagentStop, so an unconditional line would repeat an
unchanged decision forever. ``emit`` records the emitted decision in
``runs/.rl-digest.json`` and stays SILENT while the (round, lead,
last-settle) triple is unchanged — re-arming on any real movement, plus
one idle heartbeat per ``RATE_LIMIT_MINUTES`` so the displayed age cannot
rot silently.

Fail-open by contract (the consumer-seam posture, strategy_sections.py):
no strategy object / unknown schema / unreadable ledger -> the clean
absent face (``None``, nothing printed), never an exception into the
closure face.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from _common import atomic_write_text, read_yaml
from kunglao_log import warn  # canonical warn: ONE implementation

SCHEMA = "rl-digest/1"
#: The strategy-object schema this consumer understands (the seam token
#: shared with scripts/strategy_sections.py and rlvr.compose).
STRATEGY_SCHEMA = "round-strategy/1"
#: Sibling of the strategy dir the versioned tick objects live in.
STRATEGY_DIR_REL = Path("runs") / "round-strategy"
#: The rate-limit marker: the last emitted decision (T0 state under runs/).
MARKER_REL = Path("runs") / ".rl-digest.json"
#: Idle heartbeat: an unchanged decision re-emits at most this often. The
#: line carries an age, and a stale age must not sit on screen forever;
#: the window is also the spam ceiling (2 lines/hour when nothing moves).
RATE_LIMIT_MINUTES = 30
#: The user-visible line prefix every consumer/test pins on.
LINE_PREFIX = "RL:"


def _now(now: datetime | None = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _epoch(value) -> float | None:
    """ISO8601 Z -> epoch seconds; None on anything unparseable (the
    absent face, never a fabricated clock read)."""
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError, OSError):
        return None


def _fmt_age(seconds: float | None) -> str:
    """Compact deterministic age: ``42s`` / ``7m`` / ``5h`` / ``3d``.
    None (unreadable ts) -> ``?`` — the honest unknown, never 0."""
    if seconds is None:
        return "?"
    value = max(0.0, float(seconds))
    if value < 60:
        return f"{int(value)}s"
    if value < 3600:
        return f"{int(value // 60)}m"
    if value < 86400:
        return f"{int(value // 3600)}h"
    return f"{int(value // 86400)}d"


def _latest_strategy(ws: Path) -> dict | None:
    """The strategy object in force: the latest parseable versioned tick
    object, or None when none exists / the schema is unknown (the clean
    absent face — consumers stay silent, no placeholder noise)."""
    directory = Path(ws) / STRATEGY_DIR_REL
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob("tick-*.yaml"), reverse=True):
        doc, err = read_yaml(path)
        if doc is None:
            if err is not None:
                warn("rl_digest.strategy", f"{path.name}: {err}")
            continue
        if doc.get("schema") != STRATEGY_SCHEMA:
            warn("rl_digest.schema",
                 f"{path.name}: schema {doc.get('schema')!r} != "
                 f"{STRATEGY_SCHEMA!r} — consumer predates producer; "
                 f"rendering nothing")
            return None
        return doc
    return None


def _last_settlement(ws: Path) -> str | None:
    """``anchor:band`` of the newest settled rollout, or None when the
    ledger carries no settlement yet. Fail-open: an unreadable ledger
    degrades to the absent face (the digest still renders)."""
    try:
        from rlvr import ledger as rl  # noqa: PLC0415 — lazy leaf import
        rows = rl.settled(ws)
    except Exception as exc:  # noqa: BLE001 — fail-open, loud per house rule
        warn("rl_digest.ledger", f"{type(exc).__name__}: {exc}")
        return None
    if not rows:
        return None
    row = rows[-1]
    settlement = row.get("settlement") or {}
    anchor = str(row.get("anchor") or row.get("rollout_id") or "").strip()
    band = str(settlement.get("band") or "").strip()
    if not anchor:
        return None
    return f"{anchor}:{band or '?'}"


def digest(ws, *, now: datetime | None = None) -> dict | None:
    """The digest document from the strategy object in force:

        {"line", "lead", "round", "last_settle", "age_s"}

    None when no (readable, v1) strategy object is in force — the
    clean silent face every consumer contracts on."""
    ws = Path(ws)
    obj = _latest_strategy(ws)
    if obj is None:
        return None
    dispatch = obj.get("dispatch") or {}
    lead = str(dispatch.get("method_lead") or "").strip() or None
    try:
        round_number = int(obj.get("tick"))
    except (TypeError, ValueError):
        warn("rl_digest.round", f"{obj.get('tick')!r}: not an int — rendering nothing")
        return None
    ts_epoch = _epoch(obj.get("ts"))
    age_s = (None if ts_epoch is None
             else round(max(0.0, _now(now).timestamp() - ts_epoch), 1))
    last_settle = _last_settlement(ws)
    line = (f"{LINE_PREFIX} lead={lead or 'none'}({_fmt_age(age_s)}) "
            f"last-settle={last_settle or 'none'} round={round_number}")
    return {"line": line, "lead": lead, "round": round_number,
            "last_settle": last_settle, "age_s": age_s}


def render(ws, *, now: datetime | None = None) -> str | None:
    """The one digest line, or None on the silent faces."""
    doc = digest(ws, now=now)
    return None if doc is None else doc["line"]


def _read_marker(ws: Path) -> dict | None:
    """The last emitted decision (T0 marker). None when absent/unreadable —
    treated as "never emitted" (emit once, then re-limit)."""
    path = Path(ws) / MARKER_REL
    try:
        if not path.is_file():
            return None
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        warn("rl_digest.marker", f"{type(exc).__name__}: {exc}")
        return None
    return doc if isinstance(doc, dict) else None


def _unchanged_recent(marker: dict | None, doc: dict,
                      now: datetime) -> bool:
    """True when the marker holds the SAME decision and the last emit is
    inside the rate window (the suppression face)."""
    if not isinstance(marker, dict):
        return False
    same = (marker.get("round") == doc["round"]
            and marker.get("lead") == doc["lead"]
            and marker.get("last_settle") == doc["last_settle"])
    if not same:
        return False
    emitted = _epoch(marker.get("ts"))
    if emitted is None:
        return False  # unreadable emit clock -> re-arm (never a silent lock)
    return (now.timestamp() - emitted) < RATE_LIMIT_MINUTES * 60


def emit(ws, *, now: datetime | None = None) -> str | None:
    """The rate-limited emit face: the digest line when this decision is
    NEW (round/lead/settlement moved) or the idle window elapsed, else
    None. Records the emitted decision in the marker (best-effort: the
    write never gates the line — visibility first, a failed marker only
    re-arms the rate limit)."""
    ws = Path(ws)
    moment = _now(now)
    doc = digest(ws, now=moment)
    if doc is None:
        return None
    marker = _read_marker(ws)
    if _unchanged_recent(marker, doc, moment):
        return None
    payload = {"schema": SCHEMA,
               "ts": moment.astimezone(timezone.utc).isoformat(
                   timespec="seconds").replace("+00:00", "Z"),
               "round": doc["round"], "lead": doc["lead"],
               "last_settle": doc["last_settle"], "line": doc["line"]}
    try:
        atomic_write_text(ws / MARKER_REL,
                          json.dumps(payload, ensure_ascii=False,
                                     sort_keys=True) + "\n")
    except OSError as exc:
        warn("rl_digest.marker_write", f"{type(exc).__name__}: {exc}")
    return doc["line"]


def main(argv: list[str] | None = None) -> int:
    """CLI face: print the (rate-limited) digest line for one workspace,
    exit 64 on a missing argument (the house usage code)."""
    import argparse  # noqa: PLC0415 — CLI-only import
    parser = argparse.ArgumentParser(
        description="Render the per-decision RL digest line.")
    parser.add_argument("workspace", nargs="?")
    parser.add_argument("--render-only", action="store_true",
                        help="bypass the rate limit (render the face)")
    args = parser.parse_args(argv)
    if not args.workspace:
        parser.print_usage()
        return 64
    line = (render(args.workspace) if args.render_only
            else emit(args.workspace))
    print(line if line else "(no digest: no strategy object in force)")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI face
    import sys

    sys.exit(main())
