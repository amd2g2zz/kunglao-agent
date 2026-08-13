# -*- coding: utf-8 -*-
"""update_index — atomic facts/_INDEX.md maintenance (DESIGN §13.6).

_INDEX.md is the orchestrator's O(1) status-count source for cold-restart.
Format: one row per fact:
  F<hash> | <status> | <claim_id> | <one-line conclusion>

Lines starting with '#' are comments (preserved across upserts).
All writes are atomic (tmp→rename) so concurrent/interleaved upserts don't lose rows.
"""
from __future__ import annotations

import sys
from pathlib import Path

SEP = ' | '


def read_index(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        parts = [p.strip() for p in line.split(SEP)]
        if len(parts) >= 4:
            rows.append({
                'fact_id': parts[0],
                'status': parts[1],
                'claim_id': parts[2],
                'conclusion': SEP.join(parts[3:]),
            })
    return rows


def count_by_status(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in read_index(path):
        counts[r['status']] = counts.get(r['status'], 0) + 1
    return counts


def upsert(path: Path, fact_id: str, status: str, claim_id: str, conclusion: str) -> None:
    """Insert or update the row for fact_id. Atomic write."""
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
        out.append(f"{r['fact_id']}{SEP}{r['status']}{SEP}{r['claim_id']}{SEP}{r['conclusion']}")
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
