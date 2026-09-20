#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""progress_timeline — render progress.txt as the complete case timeline (issue-282).

Design (a) derive-and-render (owner directive: progress.txt must carry a
COMPLETE timeline). The kunglao_log event ledger (runs/logs/kunglao-*.jsonl)
is the SOURCE OF TRUTH for machine state changes; this module renders
progress.txt as a tick-ordered view of every ledger event with worker
narrative entries interleaved at their timestamps:

    # progress.txt — rendered case timeline (issue-282) ...
    # events=3 narrative=2
    #---
    E seq=1 tick=0 ts=2026-09-19T10:00:00Z actor=orchestrator action=converge claim=- :: ...
    N tick=0 ts=2026-09-19T10:04:00Z [W-3 DONE] strings table extracted

Narrative preservation without a worker-protocol change: workers keep
appending to progress.txt exactly as today. Before every re-render, lines
outside the rendered block are ingested into the durable sidecar
``runs/progress-narrative.jsonl`` (dedup by exact text); pre-issue-282 legacy
content migrates the same way on the first render. progress.txt alone is
therefore never the only copy of a narrative line — deleting any line is
repaired byte-exactly by the next render (self-healing by construction).

issue-530 disposition holds: progress.txt stays a human-scannable VIEW, never
machine-ingested state (state_anchor / external_kicker still never read it).

Render faces (fail-open — a render failure never blocks the caller):
  1. checkpoint cadence: convergence_check.main(), right after the snapshot
     append (the tick writer) — the timeline stays in lockstep with the axis;
  2. resume: kunglao_resume.main() renders BEFORE building the brief
     (render-then-read; issue-466 read-only contract amended for this one
     derived view — see openspec/changes/issue-282-progress-timeline).
"""
from __future__ import annotations

import json
import re
import sys
from bisect import bisect_right
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from kunglao_log import iter_jsonl  # (kunglao_log Family-K single source)

try:  # advisory cross-process lock; POSIX faces only — on platforms without
    # fcntl the re-check-before-write loop below still guards no-append-lost.
    import fcntl
except ImportError:  # pragma: no cover - platform face
    fcntl = None

PROGRESS_NAME = "progress.txt"
SIDECAR = Path("runs") / "progress-narrative.jsonl"
# The first line of a rendered file — the split point between the rendered
# block and raw narrative appends.
RENDER_MARKER = "# progress.txt — rendered case timeline (issue-282)"
HEADER_SEP = "#---"
# Rendered-row prefixes are deliberately OVER-SPECIFIED ("E seq=", "N tick=",
# not bare "E "/"N "): a worker narrative line that merely starts with the
# letter N must classify as narrative, never as a rendered row.
_EVENT_ROW_PREFIX = "E seq="
_NARR_ROW_PREFIX = "N tick="
# Display cap for one rendered row (the ledger keeps the full row; the view
# stays scannable).
ROW_CAP = 240

# Worker narrative stamp `[YYYY-MM-DD HH:MM]` (optionally `:SS`), the
# agents/kunglao-worker.md step-4 format, plus a bare ISO fallback.
_TS_BRACKET = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})(?::(\d{2}))?\]\s*")
_TS_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|\+00:00)?)\s*")

_UTC = timezone.utc
_DT_MAX = datetime.max.replace(tzinfo=_UTC)


# ---------------------------------------------------------------- parse ----

def parse_entry_ts(text: str) -> datetime | None:
    """Leading timestamp of a narrative line ([YYYY-MM-DD HH:MM] or ISO),
    else None (the line inherits the previous line's ts at ingest)."""
    for rx in (_TS_BRACKET, _TS_ISO):
        m = rx.match(text)
        if not m:
            continue
        raw = m.group(1) if rx is _TS_ISO else \
            f"{m.group(1)}T{m.group(2)}:{m.group(3) or '00'}"
        raw = raw.replace(" ", "T", 1).rstrip("Z")
        try:
            return datetime.fromisoformat(raw[:19]).replace(tzinfo=_UTC)
        except ValueError:
            continue
    return None


def _fmt_dt(dt: datetime | None) -> str:
    return dt.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else "-"


def _parse_event_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    # Normalize naive timestamps to UTC (documented face: a tz-less ts in a
    # hand-edited/foreign day file reads as UTC) — mixed naive/aware values
    # in one sort would otherwise crash render() with a TypeError that both
    # fail-open callers would silently swallow.
    return dt.replace(tzinfo=_UTC) if dt.tzinfo is None else dt


def _warn(reason: str) -> None:
    """The one runtime trace a fail-open skip leaves (issue-275 policy:
    never silent; mirror of the kunglao_log emit-warning style)."""
    print(f"[progress_timeline] warning: {reason}", file=sys.stderr)


def _emit_skip(ws, reason: str) -> None:
    """issue 293: a render SKIP is a decision (the view write was declined) —
    one tagged event with the reason, fail-open (kunglao_record posture).

    Deliberately the SUCCESS face emits nothing: the rendered timeline is a
    derived VIEW (issue 282/issue 530 — never machine-ingested state), and a
    post-write event would break the zero-gap invariant (timeline_gaps)
    while a pre-read event would change the rendered file bytes (the issue
    292 pins). Skip faces carry no such loop — the declined write leaves the
    file untouched, so the event is pure decision visibility."""
    try:
        from kunglao_log import emit
        emit(Path(ws), actor="progress_timeline",
             action="timeline_render_skipped", detail=reason)
    except Exception as exc:  # noqa: BLE001 — observability is best-effort
        _warn(f"render-skip telemetry unavailable ({exc})")


def _cap(row: str) -> str:
    """Per-row display cap with an explicit tail marker (the ledger keeps
    the full row; a clipped view never looks complete)."""
    return row if len(row) <= ROW_CAP else row[:ROW_CAP - 1] + "…"


# ----------------------------------------------------------------- read ----

def read_events(ws) -> list[dict] | None:
    """Every ledger event, chronological stream order.

    None means "genuinely unreadable" (a day file exists but cannot be
    read) — the honest fail-open signal; [] is a real cold-start empty
    ledger. Unparseable lines are skipped (kunglao_log tolerance)."""
    logs = Path(ws) / "runs" / "logs"
    if not logs.is_dir():
        return []
    rows: list[dict] = []
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        rows.extend(r for r in iter_jsonl(text.splitlines())
                    if isinstance(r, dict))
    return rows


def read_narrative(ws) -> list[dict]:
    """The sidecar's narrative entries (tolerant: bad lines skipped)."""
    try:
        text = (Path(ws) / SIDECAR).read_text(encoding="utf-8",
                                              errors="replace")
    except OSError:
        return []
    return [r for r in iter_jsonl(text.splitlines())
            if isinstance(r, dict) and isinstance(r.get("text"), str)]


def read_progress(ws) -> str | None:
    """The on-disk progress.txt, or None when absent/unreadable."""
    try:
        return (Path(ws) / PROGRESS_NAME).read_text(encoding="utf-8",
                                                    errors="replace")
    except OSError:
        return None


# --------------------------------------------------------------- ingest ----

def _split_rendered(content: str) -> list[str]:
    """Non-rendered (narrative) lines of a progress.txt: everything that is
    not the marker header block or an E/N row. Line-by-line classification
    once inside the rows region, so appends AFTER the block AND inserts
    INTO it both classify as narrative — a raw line can never be swallowed
    by the rendered block."""
    out: list[str] = []
    state = "pre"  # pre -> header -> rows
    for line in content.splitlines():
        if state == "pre":
            # PREFIX match, never whole-line equality: an editor that
            # normalizes one character of the marker (em dash, encoding)
            # must not demote the entire rendered block to narrative.
            if line.startswith("# progress.txt"):
                state = "header"
            elif line.strip():
                out.append(line)
        elif state == "header":
            if line.startswith(HEADER_SEP):
                state = "rows"
            elif line.startswith("#") or not line.strip():
                continue
            else:  # malformed render: treat the rest conservatively
                state = "rows"
                if line.strip():
                    out.append(line)
        else:  # rows
            if line.startswith(_EVENT_ROW_PREFIX) or \
                    line.startswith(_NARR_ROW_PREFIX):
                continue
            if line.strip():
                out.append(line)
    return out


def ingest_progress_appends(ws) -> int:
    """Move raw narrative lines of progress.txt into the sidecar.

    Line-level (legacy blobs stay intact at line granularity); dedup keys
    on (ts, text) OCCURRENCE COUNTS, not bare text — two byte-identical
    lines (a retry loop logging the same DONE text twice) are two entries
    and both survive; a line without its own timestamp inherits the
    previous line's ts within the batch. Returns the number of newly
    stored entries. Fail-open: an unreadable progress.txt ingests
    nothing."""
    content = read_progress(ws)
    if content is None:
        return 0
    have = Counter((e.get("ts"), e.get("text")) for e in read_narrative(ws))
    seen: Counter = Counter()
    entries: list[dict] = []
    last_ts: datetime | None = None
    for line in _split_rendered(content):
        ts = parse_entry_ts(line)
        last_ts = ts if ts is not None else last_ts
        key = (_fmt_dt(ts if ts is not None else last_ts), line)
        seen[key] += 1
        if seen[key] <= have[key]:
            continue  # this occurrence is already durably stored
        entries.append({"ts": key[0], "text": line})
    if not entries:
        return 0
    return _append_sidecar(ws, entries)


def _append_sidecar(ws, entries: list[dict]) -> int:
    p = Path(ws) / SIDECAR
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"[progress_timeline] warning: cannot write sidecar {p}: {exc}",
              file=sys.stderr)
        return 0
    return len(entries)


# --------------------------------------------------------------- render ----

class _TickAxis:
    """Epoch anchors (event ts -> tick) with bisect interpolation: a
    narrative entry's tick = the tick of the latest event at or before it."""

    def __init__(self, events: list[dict]):
        pairs = sorted(
            ((ets, int(e["epoch"])) for e in events
             if isinstance(e.get("epoch"), int)
             for ets in [_parse_event_ts(e.get("ts"))]
             if ets is not None),
            key=lambda p: p[0])
        self._times = [p[0] for p in pairs]
        self._ticks = [p[1] for p in pairs]

    def at(self, ts: datetime | None) -> int:
        if ts is None or not self._times:
            return 0
        idx = bisect_right(self._times, ts)
        return self._ticks[idx - 1] if idx else 0


def _event_row(e: dict, seq: int) -> str:
    raw_epoch = e.get("epoch")
    tick = raw_epoch if isinstance(raw_epoch, int) else "?"
    fields = [
        f"{_EVENT_ROW_PREFIX}{seq}",
        f"tick={tick}",
        f"ts={_fmt_dt(_parse_event_ts(e.get('ts')))}",
        f"actor={e.get('actor')}",
        f"action={e.get('action')}",
        f"claim={e.get('claim') or '-'}",
    ]
    if e.get("artifact"):
        fields.append(f"artifact={e['artifact']}")
    row = " ".join(fields)
    detail = e.get("detail")
    if detail:
        row += f" :: {detail}"
    return _cap(row)


def render(ws) -> str:
    """The complete rendered timeline (pure function of ledger + sidecar).

    Rows sort by (ts, kind E<N>, stream order) — the tick axis is monotonic
    with wall clock (assigned at emit time), so ts order is tick order; the
    gap check verifies that invariant instead of trusting it. Callers must
    guard read_events() is not None (the unreadable-ledger face is handled
    by render_and_repair / render_note, never by an empty fake)."""
    events = read_events(ws) or []
    narrative = read_narrative(ws)
    axis = _TickAxis(events)
    merged: list[tuple[datetime, int, int, str]] = []
    for i, e in enumerate(events):
        merged.append((_parse_event_ts(e.get("ts")) or _DT_MAX, 0, i,
                       _event_row(e, i + 1)))
    for i, e in enumerate(narrative):
        ts = _parse_event_ts(e.get("ts")) if e.get("ts") else None
        row = f"{_NARR_ROW_PREFIX}{axis.at(ts)} ts={_fmt_dt(ts)} {e['text']}"
        merged.append((ts or _DT_MAX, 1, i, _cap(row)))
    merged.sort(key=lambda r: (r[0], r[1], r[2]))
    header = [
        RENDER_MARKER,
        "# source of truth: runs/logs/kunglao-*.jsonl (kunglao_log)"
        " + runs/progress-narrative.jsonl (worker narrative)",
        "# rows: E = one ledger event (seq/tick/ts/actor/action/claim ::"
        " detail) | N = narrative entry at its tick",
        f"# events={len(events)} narrative={len(narrative)}",
        HEADER_SEP,
    ]
    return "\n".join(header + [r[3] for r in merged]) + "\n"


# ------------------------------------------------- render + repair face ----

LOCK_REL = Path("runs") / ".progress-render.lock"
_WRITE_RETRIES = 3  # bounded re-check loop: a worker append landing mid-face


@contextmanager
def _render_lock(ws):
    """Advisory cross-process lock around ingest+write (the renderer-vs-
    renderer race: two faces snapshotting the sidecar before either appends
    duplicates entries forever). flock releases on process death — a
    crashed holder cannot wedge the next render. Best-effort: on platforms
    without fcntl the re-check loop still guards no-append-lost."""
    p = Path(ws) / LOCK_REL
    handle = None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        handle = open(p, "a+", encoding="utf-8")  # noqa: SIM115 - held for scope
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except OSError as exc:
        _warn(f"render lock unavailable ({exc}) — proceeding unlocked")
        handle = None
    try:
        yield
    finally:
        if handle is not None:
            handle.close()  # close() releases the flock — no unlock round-trip


def render_and_repair(ws) -> dict:
    """The checkpoint face: ingest appends -> render -> write-on-diff.

    No-append-lost guarantee (review F1): the write fires only when the
    on-disk file is still byte-identical to the state just ingested; an
    append landing mid-face folds into a bounded re-check loop, and if
    appends never settle the write is SKIPPED — the file stays untouched,
    so nothing is lost and the next render picks the appends up. Renderer-
    vs-renderer is serialized by the advisory lock (review F5). Fail-open
    by contract: an unreadable ledger performs NO write (the human file —
    and every narrative line in it — stays untouched), leaves one stderr
    trace (issue-275: never silent), and the skip reason is returned. Returns
    {status, wrote, reason, events, narrative}."""
    ws = Path(ws)
    events = read_events(ws)
    if events is None:
        reason = "ledger unreadable — progress.txt left untouched"
        _warn(reason)
        _emit_skip(ws, reason)  # issue 293: the declined write is a decision
        return {"status": "skipped", "wrote": False, "reason": reason,
                "events": None, "narrative": 0}
    ingested_total = 0
    with _render_lock(ws):
        current = read_progress(ws)
        text = None
        for _ in range(_WRITE_RETRIES):
            ingested_total += ingest_progress_appends(ws)
            text = render(ws)
            now = read_progress(ws)
            if now == current:
                break  # stable snapshot: the write below can clobber nothing
            current = now  # an append landed — fold it in and re-check
        else:
            reason = ("worker appends kept landing — write deferred, "
                      "file untouched (nothing lost; next render picks up)")
            _warn(reason)
            _emit_skip(ws, reason)  # issue 293: the deferred write is a decision
            return {"status": "skipped", "wrote": False, "reason": reason,
                    "events": len(events), "narrative": ingested_total}
        reason = None if not ingested_total else \
            f"ingested {ingested_total} narrative line(s)"
        if current == text:
            return {"status": "rendered", "wrote": False, "reason": reason,
                    "events": len(events), "narrative": ingested_total}
        try:
            (ws / PROGRESS_NAME).write_text(text, encoding="utf-8")
        except OSError as exc:
            reason = f"progress.txt unwritable: {exc}"
            _warn(reason)
            _emit_skip(ws, reason)  # issue 293: the failed write is a decision
            return {"status": "skipped", "wrote": False, "reason": reason,
                    "events": len(events), "narrative": ingested_total}
        return {"status": "rendered", "wrote": True, "reason": reason,
                "events": len(events), "narrative": ingested_total}


# ---------------------------------------------------------- verification ----

def timeline_gaps(ws) -> list[str]:
    """Zero-gap verification: every ledger event present in the rendered
    file, E-ticks non-decreasing. Empty list = gap-free. Read-only; used by
    the pinned tests and the resume note."""
    events = read_events(ws)
    if events is None:
        return ["ledger unreadable"]
    content = read_progress(ws)
    if content is None:
        return ["progress.txt missing (render pending)"]
    rows = [ln for ln in content.splitlines()
            if ln.startswith(_EVENT_ROW_PREFIX)]
    gaps: list[str] = []
    if len(rows) != len(events):
        gaps.append(f"E rows={len(rows)} != ledger events={len(events)}")
    rendered = [_row_key(r) for r in rows]
    ticks = [_row_tick(r) for r in rows]
    for e in events:
        ts = _fmt_dt(_parse_event_ts(e.get("ts")))
        key = (ts, e.get("actor"), e.get("action"))
        if key not in rendered:
            gaps.append(f"missing event ts={key[0]} actor={key[1]} "
                        f"action={key[2]}")
    ordered = [t for t in ticks if t is not None]
    if ordered != sorted(ordered):
        gaps.append("E ticks not non-decreasing")
    return gaps


def _row_key(row: str) -> tuple:
    """Rendered E-row identity — the same normalized shapes the gap check
    compares ledger events against (ts in _fmt_dt form, actor, action)."""
    return (_search_group(r"\bts=(\S+)", row),
            _search_group(r"\bactor=(\S+)", row),
            _search_group(r"\baction=(\S+)", row))


def _row_tick(row: str) -> int | None:
    raw = _search_group(r"\btick=(\S+)", row)
    try:
        return int(raw) if raw is not None else None
    except ValueError:
        return None


def _search_group(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text)
    return m.group(1) if m else None


def render_note(ws) -> str:
    """One-line state note for the resume brief's progress row (pure read)."""
    events = read_events(ws)
    if events is None:
        return "timeline render skipped: ledger unreadable — file untouched"
    content = read_progress(ws)
    if content is None:
        return "progress.txt missing (renders at the next checkpoint)"
    if not any(ln.startswith("# progress.txt")
               for ln in content.splitlines()):
        return "legacy progress.txt (pre-issue-282) — renders at the next checkpoint"
    gaps = timeline_gaps(ws)
    if gaps:
        return f"timeline stale ({gaps[0]})"
    # degraded-axis face: an all-"?" timeline is complete but un-ticked —
    # never fabricated, yet the reader must see why no tick appears.
    ticks = [_row_tick(ln) for ln in content.splitlines()
             if ln.startswith(_EVENT_ROW_PREFIX)]
    if ticks and all(t is None for t in ticks):
        return (f"timeline current (events={len(events)}; "
                f"tick axis unavailable for all rows)")
    return f"timeline current (events={len(events)})"
