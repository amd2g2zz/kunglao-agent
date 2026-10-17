# -*- coding: utf-8 -*-
"""belief.py — the POMDP b: per-claim observation ingestion.

Before this face the loop decided on a class fingerprint; what the
worker SAW never re-entered the decision state. The belief is the
per-claim record of what is SEEN (the step's facts with statuses) and
what the worker DECLARED unknown (fact frontmatter ``unknown:`` —
tolerated absent, never fabricated: an undeclared unknown does not
exist in the state). One row lands per settled step; the latest row
for a claim is its current belief.

Consumers: the state signature carries a ``bf=`` dim (declared
unknowns present), and the knowledge query's audit faces expose the
belief so information-gathering actions can be priced against the
unknown set. The belief is audit and state — never graded knowledge.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BELIEF_SCHEMA = "belief/1"
BELIEF_REL = "runs/belief.jsonl"

_DECLARED_KEYS = ("unknown", "open_question")


def _append_row(ws, row: dict) -> bool:
    from rlvr import q_cells  # noqa: PLC0415 — lazy (the shared primitive)
    return q_cells._append_row(Path(ws) / BELIEF_REL, row)


def _open_status(ws, claim: str) -> str | None:
    """The claim's register lifecycle status (tolerant read: no
    register / no such claim -> None)."""
    try:
        import yaml  # noqa: PLC0415 — lazy
        p = Path(ws) / "claim-register.yaml"
        if not p.is_file():
            return None
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        for c in (doc.get("claims") or []):
            if isinstance(c, dict) and \
                    str(c.get("id") or "") == claim:
                return str(c.get("status") or "") or None
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        from kunglao_log import warn  # noqa: PLC0415 — lazy
        warn("rlvr.belief.open_status", f"{type(exc).__name__}: {exc}")
    return None


def record_belief(ws, *, claim: str, step_ref: str,
                  evidence: list[dict] | None) -> dict | None:
    """One settled step's belief row: what the step SAW (its facts with
    statuses) and what it DECLARED unknown. Zero fabrication: an
    undeclared unknown does not exist in the state. Fail-open: an
    unwritable store yields no row and never raises into the settle."""
    try:
        from harness_common import utc_now_z  # noqa: PLC0415 — lazy
        claim = str(claim or "").strip()
        if not claim:
            return None
        metas = [m for m in (evidence or []) if isinstance(m, dict)]
        seen = [{"id": str(m.get("id") or ""),
                 "status": str(m.get("status") or "")}
                for m in metas if m.get("id")]
        declared: set[str] = set()
        for m in metas:
            for key in _DECLARED_KEYS:
                val = m.get(key)
                if isinstance(val, str) and val.strip():
                    declared.add(val.strip())
                elif isinstance(val, list):
                    for item in val:
                        # str-only: junk (numbers/None/nested) is not a
                        # declaration — coercing it would FABRICATE
                        # tokens in the dim that re-keys the signature
                        if isinstance(item, str) and item.strip():
                            declared.add(item.strip())
        prior = sum(1 for r in read_rows(ws) if r.get("claim") == claim)
        row = {
            "schema": BELIEF_SCHEMA,
            "ts": utc_now_z(),
            "claim": claim,
            "step_ref": str(step_ref or ""),
            "seen": seen,
            "declared_unknown": sorted(declared),
            "open_status": _open_status(ws, claim),
            "steps": prior + 1,
        }
        return row if _append_row(ws, row) else None
    except Exception as exc:  # noqa: BLE001 — never the settle
        from kunglao_log import warn  # noqa: PLC0415 — lazy
        warn("rlvr.belief.record", f"{type(exc).__name__}: {exc}")
        return None


def read_rows(ws) -> list[dict]:
    """Tolerant read: belief rows oldest first; missing file -> [],
    corrupt lines skipped."""
    try:
        text = (Path(ws) / BELIEF_REL).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        return []
    from kunglao_log import iter_jsonl  # noqa: PLC0415 — lazy
    return [r for r in iter_jsonl(text.splitlines())
            if isinstance(r, dict)
            and str(r.get("schema") or "") == BELIEF_SCHEMA]


def read_belief(ws, claim: str) -> dict | None:
    """The claim's current belief: its LATEST row (None = cold)."""
    claim = str(claim or "").strip()
    found = None
    for row in read_rows(ws):
        if str(row.get("claim") or "") == claim:
            found = row
    return found


def belief_face(ws, claim: str) -> dict | None:
    """The knowledge query's audit face for this claim's belief."""
    row = read_belief(ws, claim)
    if row is None:
        return None
    return {"source": "belief",
            "declared_unknown": len(row.get("declared_unknown") or []),
            "seen": len(row.get("seen") or []),
            "steps": int(row.get("steps") or 0)}


def declared_unknown_present(ws) -> bool:
    """True when any claim's current belief declares unknowns — the
    state signature's ``bf=`` dim rides on this (absent -> ``-``, so
    belief-less workspaces keep their historical signature)."""
    try:
        latest: dict[str, dict] = {}
        for row in read_rows(ws):
            latest[str(row.get("claim") or "")] = row
        return any(r.get("declared_unknown") for r in latest.values())
    except Exception as exc:  # noqa: BLE001 — fail-open, loud
        from kunglao_log import warn  # noqa: PLC0415 — lazy
        warn("rlvr.belief.present", f"{type(exc).__name__}: {exc}")
        return False
