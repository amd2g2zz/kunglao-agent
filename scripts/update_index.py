# -*- coding: utf-8 -*-
"""update_index — atomic facts/_INDEX.md maintenance (DESIGN §13.6).

_INDEX.md is the orchestrator's O(1) status-count source for cold-restart.
Format: one row per fact:
  F<id> | <status> | <claim_id> | <one-line conclusion>

#538 W-5: the row schema and its parser live in THE single module
(tools/_lib/index_schema.py) shared with digest_build.py — this file is a
write-side consumer: it validates through the shared validator before any
disk write, so a malformed row (e.g. free text in the status column) is
refused, never persisted (畸形行拒写).

Lines starting with '#' are comments (preserved across upserts).
All writes are atomic (tmp→rename) so concurrent/interleaved upserts don't lose rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent.parent / "tools" / "_lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))
from index_schema import (  # noqa: E402
    IndexSchemaError,
    format_row,
    parse_index_text,
    read_index,
    validate_row,
)

SEP = ' | '


def count_by_status(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in read_index(path):
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return counts


def upsert(path: Path, fact_id: str, status: str, claim_id: str, conclusion: str) -> None:
    """Insert or update the row for fact_id. Atomic write.

    Raises IndexSchemaError BEFORE touching disk when the row violates the
    single schema (#538: malformed status/ids never land on disk)."""
    validate_row(fact_id, status, claim_id, conclusion)
    rows = read_index(path)
    found = False
    for r in rows:
        if r['fact_id'] == fact_id:
            r['status'] = status
            r['claim_id'] = claim_id
            r['conclusion'] = conclusion
            found = True
            break
    if not found:
        rows.append({'fact_id': fact_id, 'status': status,
                     'claim_id': claim_id, 'conclusion': conclusion})
    _write(path, rows)


def _write(path: Path, rows: list[dict]) -> None:
    comments: list[str] = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip().startswith('#'):
                comments.append(line)
    out = list(comments)
    if comments and rows:
        out.append('')
    for r in rows:
        out.append(format_row(r))
    _atomic_write(path, '\n'.join(out) + '\n')


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)


def main(argv: list[str]) -> int:
    if len(argv) == 7 and argv[1] == 'upsert':
        _, _, path, fid, status, cid, conclusion = argv
        upsert(Path(path), fid, status, cid, conclusion)
        return 0
    print('Usage: update_index.py upsert <index_path> <fact_id> <status> <claim_id> <conclusion>',
          file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv))
