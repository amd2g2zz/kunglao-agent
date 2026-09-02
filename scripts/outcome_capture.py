# -*- coding: utf-8 -*-
"""outcome_capture.py - external-checker verification results -> ledger OUTCOME rows (#35).

R6 premise: the sensing layer has no outcome signal. verify-note / red-team
results currently live only in runs/*.md files and never enter the ledger, so
the loop cannot tell "producing" from "spinning" (r3: 75.6% of rounds had zero
fact delta). This script turns those results into independent OUTCOME rows on
.convergence_ledger.jsonl (contract frozen in status_defs.LedgerLineType), and
aggregate_reward() is a pure function over them.

reward is a SOFT signal only (future priority factor / prompt injection) — it
does NOT gate any mechanical gate. Wiring it into a decision is deferred to a
later change (pending >=2 samples to avoid overfitting).

Usage:
  python outcome_capture.py <workspace>            # capture runs/*.md -> OUTCOME rows
  python outcome_capture.py <workspace> --reward   # print aggregate reward scalar
  python outcome_capture.py <workspace> --json     # machine-readable
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="outcome_capture", action="converge",
                              detail="module wired")
except NameError:
    pass

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from status_defs import LedgerLineType, ledger_line_type
from kunglao_log import iter_jsonl  # noqa: E402  (#863 Family K single source)

LEDGER_NAME = ".convergence_ledger.jsonl"

# verify-note: "## Overall verdict\n<passes|partial|fails>" — tolerant of blank
# lines / leading whitespace between the heading and the value token.
VERDICT_RE = re.compile(r"## Overall verdict\s*\n+\s*(\S+)", re.IGNORECASE)

# red-team: "RED-TEAM VERDICT: CONFIRMED|REFUTED|UNVERIFIED(-WITH-GAP)".
REDTEAM_RE = re.compile(
    r"RED-TEAM VERDICT\s*[:\-]?\s*(CONFIRMED|REFUTED|UNVERIFIED(?:\s*-\s*WITH-GAP)?)",
    re.IGNORECASE,
)

# result value -> reward score (pure mapping, no LLM).
RESULT_SCORE = {
    "passes": 1.0, "partial": 0.5, "fails": 0.0,
    "CONFIRMED": 1.0, "REFUTED": 0.0,
    "UNVERIFIED": 0.5, "UNVERIFIED-WITH-GAP": 0.5,
}


def utc_now_iso() -> str:
    """UTC ISO-8601, second precision (Z-suffix form for ledger consistency)."""
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds")


def read_outcome_rows(workspace: Path) -> list[dict]:
    """Return only type==outcome rows.

    Mirrors convergence_health._read_ledger tolerant line-by-line read; bad /
    blank lines are skipped. ledger_line_type() (from #34) classifies rows so a
    contract upgrade is one-place in status_defs — SNAPSHOT rows (no `type` or
    `type=="snapshot"`) are excluded so aggregation never consumes them.
    """
    p = workspace / LEDGER_NAME
    if not p.exists():
        return []
    out: list[dict] = []
    for row in iter_jsonl(
            p.read_text(encoding="utf-8", errors="replace").splitlines()):
        if ledger_line_type(row) == LedgerLineType.OUTCOME:
            out.append(row)
    return out


def _seen_key(row: dict) -> str:
    """Idempotency key: claim_id + checker + result.

    Mirrors kunglao_record.record_event event_id dedup, but EXCLUDES the
    volatile `ts` — otherwise every capture would look like a new event.
    `result` is included so an evolving verdict (partial -> passes) records both
    states; only an identical (claim, checker, result) triple is a true duplicate
    (e.g. the same verify file scanned twice).
    """
    return f"{row.get('claim_id')}|{row.get('checker')}|{row.get('result')}"


def _claim_from_note(text: str, name: str) -> str:
    """Extract claim_id from note YAML frontmatter; fall back to filename."""
    parts = text.split("---", 2)
    if len(parts) >= 3:
        m = re.search(r"^claim_id:\s*([^\n]+)", parts[1], re.M)
        if m:
            return m.group(1).strip()
    return name


def _claim_from_redteam(text: str, name: str) -> str:
    """Extract C-NNN from red-team body (claim:/target:); fall back to filename."""
    m = re.search(r"(?:claim\s*[:=]?\s*|target\s*[:=]?\s*)(C-\d+)", text, re.IGNORECASE)
    return m.group(1) if m else name


def _parse_run(p: Path) -> dict | None:
    """Parse one runs/*.md into an OUTCOME row, or None if no verdict found."""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if "verify-redteam" in p.name:
        m = REDTEAM_RE.search(text)
        if not m:
            return None
        return {"type": "outcome", "ts": utc_now_iso(),
                "claim_id": _claim_from_redteam(text, p.name),
                "result": m.group(1).strip(), "checker": "red-team"}
    # verify-note path
    m = VERDICT_RE.search(text)
    if not m:
        return None
    return {"type": "outcome", "ts": utc_now_iso(),
            "claim_id": _claim_from_note(text, p.name),
            "result": m.group(1).strip().lower(), "checker": "verify-note"}


def capture(workspace: Path) -> int:
    """Scan runs/*.md and append OUTCOME rows (idempotent).

    Returns the number of newly appended rows. Files are filtered to the
    verify-note convention (name contains `-verify-`) or red-team convention
    (name contains `verify-redteam`); other runs/*.md are left alone.
    """
    runs = workspace / "runs"
    if not runs.exists():
        return 0
    seen = {_seen_key(r) for r in read_outcome_rows(workspace)}
    new_lines: list[str] = []
    for p in sorted(runs.glob("*.md")):
        if "-verify-" not in p.name and "verify-redteam" not in p.name:
            continue
        entry = _parse_run(p)
        if entry is None:
            continue
        key = _seen_key(entry)
        if key in seen:
            continue
        seen.add(key)
        new_lines.append(json.dumps(entry, ensure_ascii=False))
    if new_lines:
        with open(workspace / LEDGER_NAME, "a", encoding="utf-8") as f:
            f.write("\n".join(new_lines) + "\n")
    return len(new_lines)


def aggregate_reward(rows: list[dict]) -> float | None:
    """Pure function: mean of RESULT_SCORE over OUTCOME rows.

    - passes / CONFIRMED = 1.0; partial / UNVERIFIED* = 0.5; fails / REFUTED /
      unknown = 0.0.
    - Returns None when there are zero outcome rows — None distinguishes "no
      signal" from "all-fails" (0.0) and "average" (0.5), so a caller must not
      mistake absence for a low reward.
    - Defensively filters type==OUTCOME even when handed the full ledger, so
      SNAPSHOT rows never contaminate the score.
    """
    scores = [RESULT_SCORE.get(r.get("result"), 0.0) for r in rows
              if r.get("type") == LedgerLineType.OUTCOME]
    return sum(scores) / len(scores) if scores else None


def main(argv: list[str] | None = None) -> int:
    """CLI: capture runs/*.md -> OUTCOME rows; optionally print reward."""
    ap = argparse.ArgumentParser(
        prog="outcome_capture.py",
        description="external-checker outcomes -> ledger OUTCOME rows + aggregate reward (#35)")
    ap.add_argument("workspace", help="workspace root (contains runs/ and the ledger)")
    ap.add_argument("--reward", action="store_true",
                    help="print the aggregate reward scalar over OUTCOME rows")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    ws = Path(args.workspace)
    added = capture(ws)
    rows = read_outcome_rows(ws)
    reward = aggregate_reward(rows)
    if args.reward:
        payload = {"reward": reward, "outcome_rows": len(rows), "captured": added}
        print(json.dumps(payload, ensure_ascii=False) if args.json
              else f"reward={reward} (over {len(rows)} outcome row(s); +{added} new)")
    else:
        print(f"captured {added} new outcome row(s); {len(rows)} total")
    return 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
