# -*- coding: utf-8 -*-
"""tools/_lib/index_schema.py — THE single facts/_INDEX.md schema + parser (#538 W-5).

Two readers previously carried divergent contracts (update_index.py 4-col
vs digest_build.py 5-col) and field parsing accepted free text — a live
workspace index parsed status as "endpoints-and-auth (login path)". This
module is the one parser both consumers import; validation is strict on the
columns that downstream gates branch on (status), structural on the rest.

Format (one row per fact, ` | ` separated):

    F<id> | <status> | <claim_id> | <one-line conclusion>

- status ∈ FACT_STATUSES (aligned with references/schema.md fact.status —
  the same set lint_facts validates).
- The conclusion column is free text and may itself contain ` | `; parsers
  must join, not split on, trailing separators (update_index parity).
- Lines starting with `#` are comments; blank lines are skipped. Rows with
  fewer than 4 columns are skipped (parse tolerance for hand-edited files
  predating this contract), BUT a well-formed 4+ column row carrying a
  non-canonical status REJECTS (IndexSchemaError) — that is the audit
  reproducer case and must never parse as data.

Write side (update_index.upsert) validates the same way before writing, so
a malformed row cannot land on disk (畸形行拒写).
"""
from __future__ import annotations

import re
from pathlib import Path

SEP = " | "

# references/schema.md fact.status — single canonical set (not duplicated
# semantics: the schema doc owns the meaning, this owns the parse set).
FACT_STATUSES = (
    "PROVEN", "INFERRED", "NEGATIVE", "REFUTED", "OPEN", "DEFERRED", "VERIFIED",
)

FACT_ID_RE = re.compile(r"^F[0-9A-Za-z-]+$")
CLAIM_ID_RE = re.compile(r"^C-\d{1,4}[a-z]?$")


class IndexSchemaError(ValueError):
    """A row pretended to be data but violated the single schema."""


def parse_index_text(text: str) -> list[dict]:
    """Parse _INDEX.md content into row dicts ({} keys: fact_id, status,
    claim_id, conclusion). Comments/blanks/short lines are skipped; a 4+
    column row with a non-canonical status raises IndexSchemaError."""
    rows: list[dict] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(SEP)]
        if len(parts) < 4:
            continue  # not a row shape — tolerate (hand-edited residue)
        status = parts[1]
        if status not in FACT_STATUSES:
            raise IndexSchemaError(
                f"facts/_INDEX.md row status {status!r} not in canonical set "
                f"{FACT_STATUSES}: {line!r}")
        rows.append({
            "fact_id": parts[0],
            "status": status,
            "claim_id": parts[2],
            "conclusion": SEP.join(parts[3:]),
        })
    return rows


def read_index(path: Path) -> list[dict]:
    """parse_index_text over a file path (empty when missing)."""
    p = Path(path)
    if not p.exists():
        return []
    return parse_index_text(p.read_text(encoding="utf-8", errors="replace"))


def validate_row(fact_id: str, status: str, claim_id: str, conclusion: str) -> None:
    """Write-side gate: raise IndexSchemaError if a would-be row violates
    the single schema. Called by update_index.upsert before any disk write."""
    if status not in FACT_STATUSES:
        raise IndexSchemaError(
            f"refusing write: status {status!r} not in canonical set "
            f"{FACT_STATUSES} (fact {fact_id!r})")
    if not fact_id or SEP in fact_id or "\n" in fact_id:
        raise IndexSchemaError(f"refusing write: bad fact_id {fact_id!r}")
    if not claim_id or SEP in claim_id or "\n" in claim_id:
        raise IndexSchemaError(f"refusing write: bad claim_id {claim_id!r}")
    if "\n" in conclusion:
        raise IndexSchemaError(f"refusing write: conclusion must be one line (fact {fact_id!r})")


def format_row(row: dict) -> str:
    """Serialize one row dict in the canonical single-schema form."""
    return SEP.join((
        row["fact_id"], row["status"], row["claim_id"], row["conclusion"]))
