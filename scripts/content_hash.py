# -*- coding: utf-8 -*-
"""content_hash — fact_id = content-sha256 for idempotent fact writes.

Used by WAL (DESIGN §14) and _INDEX (§13) to deduplicate re-dispatched work:
same (claim, reproduce, expected) → same fact_id → same file, no collision.

fact_id = 'F' + sha256(sha256(claim) || sha256(reproduce) || sha256(expected)).hexdigest()[:16]

Each field is hashed independently (fixed 32-byte length), so the combination is
unambiguous — no separator that could appear in inputs.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PREFIX = 'F'
HEX_LEN = 16  # 64 bits — collision-safe for fact-base scale


def fact_id(claim: str, reproduce: str, expected: str) -> str:
    """Content-addressed fact ID (unambiguous: each field hashed independently).

    Deterministic: identical inputs always produce the same ID, so re-dispatching
    the same worker (same claim + reproduce + expected) writes to the same path —
    idempotent, no duplicate facts. Independent per-field hashing avoids separator
    ambiguity when an input contains a NUL byte.
    """
    def _h(s: str) -> bytes:
        return hashlib.sha256(s.encode('utf-8')).digest()
    combined = _h(claim) + _h(reproduce) + _h(expected)  # 96 bytes, unambiguous
    return PREFIX + hashlib.sha256(combined).hexdigest()[:HEX_LEN]


def main(argv: list[str]) -> int:
    """CLI: python content_hash.py <claim_file> <reproduce_file> <expected_file>

    Reads each input from a file (so multi-line reproduce/expected work).
    Prints the fact_id to stdout.
    """
    if len(argv) != 4:
        print(
            'Usage: python content_hash.py <claim_file> <reproduce_file> <expected_file>',
            file=sys.stderr,
        )
        return 2
    claim = Path(argv[1]).read_text(encoding='utf-8')
    reproduce = Path(argv[2]).read_text(encoding='utf-8')
    expected = Path(argv[3]).read_text(encoding='utf-8')
    print(fact_id(claim, reproduce, expected))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
