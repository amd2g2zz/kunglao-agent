#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_status_watch.py — disk-vs-event-stream reconciliation for verify stamps (#718 P3).

WHY: `sed -i 's/verify_status: pending-verifier/verify_status: passes/'`
rewrote a note OUTSIDE the Write/Edit face in the sample-incident-01 0.1.2 incident
and left zero trace anywhere. violation_capture.py (#718 P2) now records the
sed itself — but a tamper arriving by any OTHER out-of-band path (a new file
written directly by shell heredoc, an editor, a python one-liner) still
produces no event. The reconciliation closes the class, not just the
instance: every tick, snapshot the verify_status of every notes/**.md
frontmatter, compare against the LAST snapshot + the event stream, and emit
`verify_status_change` for every disk transition with NO corresponding
mechanical event between the two snapshots.

Legit transitions carry events: write_guard adjudicates the Write face;
verify mirrors kunglao_verify verdicts; write_blocked mirrors refusals.
The FIRST snapshot pass is BASELINE (stamps recorded as-is, no change
events) — only LATER transitions are reconciled. A transition with no
matching witness event in the window is flagged `unwitnessed: true` — the
exact fingerprint of the incident tamper.

State file: runs/.verify-watch.json — {"ts": <ISO8601Z>, "stamps":
{<note relpath>: <status>}}. Fail-open everywhere: this is a WATCH, not a
gate; any error returns an empty report and never fails the tick.

Usage (from heartbeat_tick, advisory):
  python verify_status_watch.py <workspace> [--json]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
VERIFY_RE = re.compile(r"^verify_status:\s*(\S+)", re.MULTILINE)

# Mechanical events that may LEGITIMATELY explain a stamp transition in the
# stream between two snapshots. verify_status_change = this watch (or the
# worker note layer); verify = kunglao_verify's own verdict mirror;
# write_blocked = write_guard refusing a carrier write.
WITNESS_ACTIONS = {"verify_status_change", "verify", "write_blocked"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def scan_stamps(ws: Path) -> dict[str, str]:
    """{note relpath: verify_status} for every notes/**.md with the field.
    Fail-open: unreadable note / no notes dir → {} contribution."""
    stamps: dict[str, str] = {}
    notes = ws / "notes"
    if not notes.is_dir():
        return stamps
    for p in notes.rglob("*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = FRONTMATTER_RE.match(text)
        if not m:
            continue
        vm = VERIFY_RE.search(m.group(1))
        if vm:
            stamps[p.relative_to(ws).as_posix()] = vm.group(1)
    return stamps


def _witnessed_between(ws: Path, note_rel: str) -> bool:
    """True if the event stream (recent tail) carries a witness event that
    can LEGITIMATELY explain this note's transition. r1-718 review H1: the
    naive note_rel-substring match fails BOTH directions against real
    emitters — kunglao_verify emits artifact=<FACT id> (e.g. 'F-101'), not
    a note path, so legit flips flagged UNWITNESSED; and the watch's own
    prior verify_status_change launders repeat tampers to witnessed. The
    join is now:
      1. read the note's CURRENT frontmatter claim_id (C-101 shape);
      2. a witness is an event (a) whose actor is NOT verify_status_watch
         (self-events never witness), (b) in WITNESS_ACTIONS, and
         (c) whose claim == the note's claim_id OR whose artifact/detail
         names the note path itself (write_guard blocks carry the path).
    Fail-open: unreadable stream or note → witnessed (no noise). A REAL
    tamper still trips this only if the actor ALSO forges a matching claim
    event — at which point the event stream itself is the evidence trail.
    """
    try:
        note_path = ws / note_rel
        text = note_path.read_text(encoding="utf-8", errors="replace")
        fm = FRONTMATTER_RE.match(text)
        claim_id = ""
        if fm:
            cm = re.search(r"^claim_id:\s*(\S+)", fm.group(1), re.MULTILINE)
            if cm:
                claim_id = cm.group(1)
    except OSError:
        return True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import kunglao_log
        for ev in kunglao_log.tail(ws, 500):
            if ev.get("action") not in WITNESS_ACTIONS:
                continue
            if ev.get("actor") == "verify_status_watch":
                continue  # self-events never witness (anti-laundering)
            if claim_id and ev.get("claim") == claim_id:
                return True
            blob = str(ev.get("artifact") or "") + " " + str(
                ev.get("detail") or "")
            if note_rel in blob:
                return True
    except Exception:  # noqa: BLE001 — watch, not gate
        return True
    return False


def reconcile(ws: Path) -> dict:
    """One pass: load prior snapshot, diff, emit change events, store new.
    Returns the report dict (also printed with --json)."""
    state_path = ws / "runs" / ".verify-watch.json"
    try:
        prior = json.loads(state_path.read_text(encoding="utf-8")).get(
            "stamps", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        prior = None  # first run → baseline, no events

    current = scan_stamps(ws)
    report: dict = {"ts": _utc_now(), "notes_scanned": len(current),
                    "changes": []}

    if prior is not None:
        for note_rel, status in sorted(current.items()):
            old = prior.get(note_rel)
            if old is None or old == status:
                continue
            witnessed = _witnessed_between(ws, note_rel)
            record = {"note": note_rel, "from": old, "to": status,
                      "unwitnessed": not witnessed}
            report["changes"].append(record)
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import kunglao_log
                kunglao_log.emit(
                    ws, actor="verify_status_watch",
                    action="verify_status_change",
                    artifact=note_rel,
                    detail=f"{old} -> {status}"
                           f"{' UNWITNESSED (out-of-band write)' if not witnessed else ''}")
            except Exception:  # noqa: BLE001 — watch, not gate
                pass
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"ts": report["ts"], "stamps": current}, indent=2),
            encoding="utf-8")
    except OSError:
        pass
    return report


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    ws = Path(args[0]).resolve()
    if not ws.is_dir():
        print(f"verify_status_watch: no such workspace: {ws}", file=sys.stderr)
        return 0  # fail-open
    report = reconcile(ws)
    if "--json" in args[1:]:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    elif report["changes"]:
        for c in report["changes"]:
            flag = " UNWITNESSED" if c["unwitnessed"] else ""
            print(f"[verify-status] {c['note']}: {c['from']} -> "
                  f"{c['to']}{flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
