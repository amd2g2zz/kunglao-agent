#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""emit_gate.py — EMIT vocabulary double-ended gate (#880).

The write-side word table (event_taxonomy.EMIT_ACTIONS) is only honest while
BOTH directions hold:

  forward  (vocabulary → code): every registered word must have >= 1
           PRODUCTION emitter — a quoted literal of the word in scripts/*.py
           or hooks/*.py. event_taxonomy.py itself is excluded (the table is
           not its own producer) and so is prose: `tool_call` hid for months
           as an UNQUOTED docstring mention in kunglao_log.py while having
           zero emitters (#880 RC1) — a broad quoted-literal net does not
           count prose, which is exactly the point.
  reverse  (code → vocabulary): every emit-site action literal in production
           code must be a registered word (issue #459 acceptance: "action
           字段 100% 来自受控词表").

Emitter detection note (#880 Recon): the reverse side uses the strict
emit-site pattern table (same shapes as the #459 CI anchor in
tests/test_event_stream_adoption.py — kept inline so this gate runs
standalone, without pytest). The forward side deliberately uses the BROADER
quoted-literal net: several legitimate producers route their action word
through an emit helper (dual_gate._emit, lessons_telemetry._bump,
recall_inject._trace, kunglao_upgrade._emit) — the strict table false-positives
on all 25 of them (measured 2026-09-02), which would criminalize live emitters.

CI mount: tests/test_emit_gate_880.py (clean repo green; a synthetic orphan
and a synthetic unregistered literal both turn it red).

Exit codes: 0 = both directions hold; 1 = violations (orphans and/or
unregistered literals); 64 = usage error.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

RC_OK = 0
RC_VIOLATIONS = 1
RC_USAGE = 64

# reverse-side pattern table — mirrors tests/test_event_stream_adoption.py
# (keyword form, the two trace-helper first-arg forms, the positional
# emit(ws, actor, "word") forms). See the module docstring for why the
# forward side does NOT reuse it.
_UNREGISTERED_PATTERNS = [
    re.compile(r'action=["\']([a-z0-9_]+)["\']'),
    re.compile(r'_emit_trace\(\s*ws,\s*["\']([a-z0-9_]+)["\']'),
    re.compile(r'_emit_interception\(\s*workspace,\s*["\']([a-z0-9_]+)["\']'),
    re.compile(r'\.emit\(\s*[^,()]+,\s*["\'][^"\']+["\'],\s*'
               r'["\']([a-z0-9_]+)["\']'),
    re.compile(r'(?<![\w.])emit\(\s*[^,()]+,\s*["\'][^"\']+["\'],\s*'
               r'["\']([a-z0-9_]+)["\']'),
]

# argparse's own `action=` kwarg — same keyword, different contract (#459).
_ARGPARSE_ACTIONS = {
    "store", "store_true", "store_false", "store_const",
    "append", "append_const", "count", "help", "version",
    "extend", "raise",
}
# MCP tool kwargs quoted in documentation text (#728) — same exclusion as the
# #459 anchor.
_MCP_DOC_KWARG_ACTIONS = {"start"}

_QUOTED_WORD = re.compile(r'["\']([a-z0-9_]{3,})["\']')


def _production_files(root: Path) -> list[tuple[str, str]]:
    """[(relpath, text)] for scripts/*.py + hooks/*.py (the production face)."""
    out: list[tuple[str, str]] = []
    for sub in ("scripts", "hooks"):
        sdir = Path(root) / sub
        if not sdir.is_dir():
            continue
        for p in sorted(sdir.glob("*.py")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            out.append((f"{sub}/{p.name}", text))
    return out


def load_vocabulary(root: Path) -> list[str]:
    """EMIT_ACTIONS from <root>/scripts/event_taxonomy.py (import by path so
    a synthetic mini-repo can carry its own table)."""
    vocab_path = Path(root) / "scripts" / "event_taxonomy.py"
    if not vocab_path.is_file():
        return []
    # #863 Family B: the by-path prologue delegates to the canonical loader.
    # scan() loads DIFFERENT table files under one process (real repo +
    # synthetic mini-repos in tests), so the registration name is keyed by
    # the resolved path — a fixed name would make the loader's get-or-create
    # return the FIRST repo's cached module for every later root.
    # The loader RAISES on broken files while this caller keeps the
    # fail-open policy — hence the try/except stays HERE, on top.
    name = "event_taxonomy_emit_gate_" + str(hash(vocab_path.resolve()))
    try:
        from _hooks_path import load_module_by_path

        mod = load_module_by_path(name, vocab_path)
        return list(getattr(mod, "EMIT_ACTIONS", []) or [])
    except Exception:  # noqa: BLE001 — a broken vocab file must name itself
        return []


def emitter_files(root: Path, word: str) -> list[str]:
    """Production files carrying `word` as a quoted literal (the forward-side
    producer proof). event_taxonomy.py is never a producer of its own words."""
    hits = []
    for rel, text in _production_files(root):
        if rel.endswith("event_taxonomy.py"):
            continue
        if any(m.group(1) == word for m in _QUOTED_WORD.finditer(text)):
            hits.append(rel)
    return hits


def scan(root: Path) -> dict:
    """Both directions. Returns {orphans: {word: [producer files — always
    empty when listed]}, unregistered: {relpath: {words}}}."""
    root = Path(root)
    vocab = load_vocabulary(root)
    files = _production_files(root)

    # forward: vocabulary → code (broad quoted-literal net, no prose, no self)
    quoted: dict[str, set[str]] = {}
    for rel, text in files:
        if rel.endswith("event_taxonomy.py"):
            continue
        for m in _QUOTED_WORD.finditer(text):
            quoted.setdefault(m.group(1), set()).add(rel)
    orphans = {w: [] for w in vocab if w not in quoted}

    # reverse: code → vocabulary (strict emit-site pattern table)
    known = set(vocab) | _ARGPARSE_ACTIONS | _MCP_DOC_KWARG_ACTIONS
    unregistered: dict[str, set[str]] = {}
    for rel, text in files:
        found: set[str] = set()
        for pat in _UNREGISTERED_PATTERNS:
            found |= set(pat.findall(text))
        bad = found - known
        if bad:
            unregistered[rel] = bad
    return {"orphans": orphans, "unregistered": unregistered}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="emit_gate.py",
        description="EMIT_ACTIONS double-ended gate (#880): orphans + "
                    "unregistered literals")
    ap.add_argument("root", help="repo root (containing scripts/ and hooks/)")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if not (root / "scripts" / "event_taxonomy.py").is_file():
        print(f"FAIL: no scripts/event_taxonomy.py under {root}",
              file=sys.stderr)
        return RC_USAGE
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    report = scan(root)
    for word in sorted(report["orphans"]):
        print(f"ORPHAN action {word!r}: registered in EMIT_ACTIONS but no "
              f"production emitter (delete the word or wire a real emitter)")
    for rel, words in sorted(report["unregistered"].items()):
        for w in sorted(words):
            print(f"UNREGISTERED action {w!r} in {rel} (extend EMIT_ACTIONS "
                  f"in scripts/event_taxonomy.py)")
    n = len(report["orphans"]) + sum(len(v) for v in
                                     report["unregistered"].values())
    print(f"emit_gate: {len(report['orphans'])} orphan(s), "
          f"{sum(len(v) for v in report['unregistered'].values())} "
          f"unregistered literal(s)")
    return RC_OK if n == 0 else RC_VIOLATIONS


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
