#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler_watch.py — the scheduler's NON-LLM event watcher.

Watches the scheduler events stream (``runs/scheduler/events.jsonl``,
the scheduler_events module) from OUTSIDE the session — a cron job or a
background process — and, on NEW material events, DELIVERS the wake
contract: staged to the trigger artifact ``runs/.scheduler-wake.json``
(atomic, exactly once per material batch) AND printed to stdout. The
artifact is what the session side CONSUMES: the drain face
(loop_scheduler --drain-events) reads it into its receipt and clears it
after the drain — the same staged-artifact shape the external kicker
uses (staged prompt file + a declared OS cron line; registration is a
one-time manual step, the kicker's D5 precedent). The session then runs
the drain per the contract's prompt — the materiality gate ran BEFORE
any LLM turn, and a quiet stream costs zero output and therefore zero
LLM tokens.

The watcher NEVER calls the model — enforced by the import-allowlist
AST pin in tests/test_scheduler_events_1001.py (the settlement-wall
shape). It is a byte-tail poll loop (fswatch/inotify not required —
portable), reading only COMPLETE lines per pass (a partial trailing
line stays for the next pass) and advancing a persisted byte cursor
(runs/scheduler/watch-state.json). A truncated/rotated file resets the
cursor. The FIRST read seeds the byte cursor past rows the drain cursor
already consumed (the drain's row cursor is the consumption truth — a
watcher restart must never re-emit an already-drained batch); with no
drain state it falls back to the bounded tail window (the ledger event
bus's convention: a fresh watcher reads the tail, not the big bang).

Mutual exclusion: a lockfile (runs/scheduler/.watcher.lock, non-
blocking flock) lets exactly ONE watcher run per workspace — a second
instance skips with rc 3, never double-emitting.

Path discipline (the session-cd caveat — an in-session FileChanged
watch stops firing after a ``cd``, which is exactly why THIS watcher
runs outside the session): the watch list
resolves ABSOLUTE from the workspace argument at startup, so a session
``cd`` can never empty it nor move it; an empty watch list — at startup
OR mid-run (workspace renamed/deleted under a live watcher) — is a
visible stderr warn + rc 2, never a silently dead watcher.

Usage:
    python scripts/scheduler_watch.py <WORKSPACE> [--interval 15]
        [--once] [--max-passes N]

Exit codes: 0 = a pass completed (quiet: nothing printed; wake: the
contract staged + on stdout); 2 = the watch list is empty (the warn is
on stderr); 3 = another watcher instance holds the lock.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kunglao_log import iter_jsonl  # noqa: E402  (tolerant reader)
from scheduler_events import (  # noqa: E402
    EVENTS_REL, is_material, state_path,
)

#: the watcher's byte cursor (a runs/scheduler/ sibling of the stream)
WATCH_STATE_NAME = "watch-state.json"

#: the mutual-exclusion lock (a second watcher must never double-emit)
WATCHER_LOCK_NAME = ".watcher.lock"

#: the trigger artifact the session side consumes (the external
#: kicker's staged-prompt shape: write the artifact, the consumer face
#: reads-and-clears it — the drain face owns the clear)
WAKE_REL = Path("runs") / ".scheduler-wake.json"

#: the first read's bounded tail window (bytes) — the ledger event bus's
#: convention: a fresh watcher reads the tail, not the big bang
FIRST_READ_WINDOW_BYTES = 65536

#: the prompt's identity prefix (the wake contract's recognizable face)
_PROMPT_PREFIX = "[kunglao scheduler events]"


def resolve_watch_paths(ws) -> list[Path]:
    """The watch list: the events file resolved ABSOLUTE from the
    workspace argument. A pure function of the argument — a session
    ``cd`` never empties it nor moves it (the cd caveat). An empty or
    unresolvable workspace yields an EMPTY list (the caller warns
    visibly)."""
    token = str(ws or "").strip()
    if not token:
        return []
    try:
        root = Path(token).expanduser().resolve()
    except OSError:
        return []
    if not root.is_dir():
        return []
    return [root / EVENTS_REL]


def wake_contract(events: list[dict]) -> dict:
    """The wake contract for one batch of material events — the same
    shape family the one-shot timer wake publishes (kind / once / steps
    / may_start_rollout / prompt). NEVER starts a rollout: the only
    step is the mechanical drain face."""
    n = len(events)
    kinds = sorted({str(e.get("kind")) for e in events})
    return {
        "kind": "scheduler-event",
        "once": True,
        "events": list(events),
        "steps": ["drain"],
        "may_start_rollout": False,
        "prompt": (
            f"{_PROMPT_PREFIX} {n} material scheduler event(s) landed "
            f"({', '.join(kinds)}). Run the drain face once: "
            f"python scripts/loop_scheduler.py <workspace> --drain-events "
            f"— it drains each unread event exactly once, acts per "
            f"type through the existing faces, and consumes the staged "
            f"wake artifact. Nothing else: no polling sweep, no new "
            f"rollout."
        ),
    }


def stage_wake(ws, contract: dict) -> bool:
    """Stage the trigger artifact (``runs/.scheduler-wake.json``) the
    session side consumes — the delivery half of the wake path (stdout
    alone is a contract nobody reads). Atomic tmp+replace; best-effort
    (a failed stage is one stderr note — the stdout contract still
    prints)."""
    p = Path(ws) / WAKE_REL
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(contract, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        return True
    except OSError as exc:
        print(f"scheduler_watch: wake artifact write failed ({exc!r})",
              file=sys.stderr, flush=True)
        return False


def _acquire_lock(lock_path: Path) -> int | None:
    """Non-blocking single-instance lock: the fd when acquired, None
    when another watcher holds it (or the lock file is uncreatable —
    the caller's own watch-list check then reports the real problem).
    flock where available; the unlocked fallback keeps single-writer
    correctness on platforms without it (the house posture — declared,
    not silent)."""
    import os
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        return None
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except ImportError:
        return fd  # no fcntl: single-writer posture, no lock
    except OSError:
        os.close(fd)
        return None
    try:
        os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    except OSError as exc:  # noqa: BLE001 — pid stamp is cosmetic
        print(f"scheduler_watch: lock pid stamp failed ({exc!r})",
              file=sys.stderr, flush=True)
    return fd


def _release_lock(fd: int | None) -> None:
    import os
    if fd is None:
        return
    try:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)
    except (ImportError, OSError) as exc:  # noqa: BLE001 — best-effort unlock
        print(f"scheduler_watch: lock unlock failed ({exc!r})",
              file=sys.stderr, flush=True)
    try:
        os.close(fd)
    except OSError as exc:  # noqa: BLE001 — best-effort close
        print(f"scheduler_watch: lock close failed ({exc!r})",
              file=sys.stderr, flush=True)


def _read_offset(ws: Path) -> int:
    """The persisted byte cursor; absent/dirty state reads 0 (first
    read -> seeded from the drain cursor, else the bounded tail)."""
    p = state_path(ws, WATCH_STATE_NAME)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return max(0, int(doc.get("offset") or 0))
    except (OSError, ValueError, TypeError):
        return 0


def _read_drained_rows(ws: Path) -> int:
    """The drain face's consumption truth (its persisted row cursor);
    absent/dirty reads 0."""
    p = Path(ws) / "runs" / "scheduler" / "drain-state.json"
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return max(0, int(doc.get("rows") or 0))
    except (OSError, ValueError, TypeError):
        return 0


def _offset_past_drained(path: Path, drained_rows: int) -> int | None:
    """The byte offset just past the ``drained_rows``-th MATERIAL row of
    the stream (the drain cursor's byte equivalent). None when the scan
    cannot answer (unreadable file) — the caller falls back to the tail
    window. More drained rows than the stream holds -> the full size
    (everything the drain consumed is behind us)."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    consumed = 0
    seen = 0
    for line in raw.splitlines(keepends=True):
        consumed += len(line)
        if not line.strip():
            continue
        try:
            row = json.loads(line.decode("utf-8", errors="replace"))
        except ValueError:
            continue
        if isinstance(row, dict) and is_material(row.get("kind")):
            seen += 1
            if seen >= drained_rows:
                return consumed
    return consumed  # fewer material rows than drained -> everything


def poll_once(ws, *, commit: bool = True) -> dict | None:
    """One poll pass: tail the stream past the persisted byte cursor,
    consume only COMPLETE lines, filter to MATERIAL rows (the reader-side
    closed-vocabulary gate), and return the batch's wake contract —
    None on a quiet pass. The cursor advances over quiet rows too (they
    are consumed, never woken on). With ``commit=False`` the pass is a
    peek (identical read, cursor untouched). A truncated/rotated file
    resets the cursor; a FIRST read seeds past the rows the drain cursor
    already consumed (a watcher restart never re-emits a drained batch),
    falling back to the bounded tail window when no drain state exists."""
    root = Path(ws)
    paths = resolve_watch_paths(root)
    if not paths:
        return None
    path = paths[0]
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    state_file = state_path(root, WATCH_STATE_NAME)
    offset = _read_offset(root)
    first_read = not state_file.exists()
    if offset < 0 or offset > size:
        offset = 0  # truncated / rotated / unknown
        first_read = True
    if offset == 0 and first_read:
        drained = _read_drained_rows(root)
        seeded = (_offset_past_drained(path, drained)
                  if drained > 0 else None)
        offset = seeded if seeded is not None \
            else max(0, size - FIRST_READ_WINDOW_BYTES)
    try:
        with path.open("rb") as fh:
            fh.seek(offset)
            chunk = fh.read()
    except OSError:
        return None
    # only COMPLETE lines are consumed (byte-exact: no decode before split)
    cut = chunk.rfind(b"\n")
    if cut < 0:
        return None  # a partial line stays for the next pass
    consumed = cut + 1
    lines = [raw.decode("utf-8", errors="replace")
             for raw in chunk[:consumed].split(b"\n") if raw.strip()]
    rows = [row for row in iter_jsonl(lines) if isinstance(row, dict)]
    material = [row for row in rows if is_material(row.get("kind"))]
    if commit:
        _persist_offset(root, offset + consumed)
    if not material:
        return None
    return wake_contract(material)


def _persist_offset(ws: Path, offset: int) -> None:
    """Persist the byte cursor atomically; best-effort — a failed write
    only re-reads bytes (the rows stay material; the drain cursor, not
    this file, is the exactly-once processing guarantee)."""
    p = state_path(ws, WATCH_STATE_NAME)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"offset": int(offset)}),
                       encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:
        print(f"scheduler_watch: cursor write failed ({exc!r}) — "
              f"bytes may be re-read", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="scheduler_watch.py",
        description="The scheduler's non-LLM event watcher: tail the "
                    "events stream, stage + print the wake contract on "
                    "new material events, stay silent when quiet.")
    ap.add_argument("workspace", help="the analysis workspace root")
    ap.add_argument("--interval", type=float, default=15.0,
                    help="poll interval seconds (default 15)")
    ap.add_argument("--once", action="store_true",
                    help="one poll pass, then exit (the test/replay face)")
    ap.add_argument("--max-passes", type=int, default=None,
                    help="stop after N passes (the replay face; default "
                         "unlimited)")
    args = ap.parse_args(argv)

    ws_token = str(args.workspace or "").strip()
    lock_fd = None
    if ws_token and Path(ws_token).is_dir():
        # lock only a real workspace: a missing one falls through to the
        # per-pass empty-watch-list warn (rc 2), never a lock-skip rc 3
        lock_fd = _acquire_lock(Path(ws_token) / "runs" / "scheduler"
                                / WATCHER_LOCK_NAME)
        if lock_fd is None:
            print("scheduler_watch: another watcher instance holds "
                  f"{WATCHER_LOCK_NAME} — skipping (never double-emit)",
                  file=sys.stderr, flush=True)
            return 3
    try:
        passes = 0
        while True:
            # the watch list is checked EVERY pass: an empty list at
            # startup OR mid-run (workspace renamed/deleted under a
            # live watcher) is a visible warn + rc 2, never a silent
            # dead watcher
            if not resolve_watch_paths(args.workspace):
                print("scheduler_watch: watch list is EMPTY — no events "
                      "file is watched and the event wake path is dead "
                      "(the workspace argument must name an existing "
                      "directory; watch paths resolve absolute)",
                      file=sys.stderr, flush=True)
                return 2
            contract = poll_once(args.workspace)
            if contract is not None:
                stage_wake(args.workspace, contract)
                print(json.dumps(contract, ensure_ascii=False), flush=True)
            passes += 1
            if args.once or (args.max_passes is not None
                             and passes >= args.max_passes):
                return 0
            time.sleep(max(0.1, args.interval))
    finally:
        _release_lock(lock_fd)


if __name__ == "__main__":
    sys.exit(main())
