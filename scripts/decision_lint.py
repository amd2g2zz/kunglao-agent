#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""decision_lint.py — pre-action compatibility lint (issue 213).

Closes the field pattern where facts already gathered did not gate the
next action: an x86_64 libidalib + python 3.14 environment pip-installed
the binding anyway, an incompatibility knowable BEFORE acting. The rule:
facts already gathered MUST gate the next action.

Contract:
- check(action, facts) is PURE — the caller (orchestrator / init-worker)
  gathers facts and passes them in; this module NEVER probes the
  environment.
- BLOCK only on a KNOWN-incompatible (package, fact) pair; unknown
  packages and unknown or missing facts degrade to OK with a note — a
  gate that blocks on unknowns is a false-positive machine the agent
  learns to ignore.
- unknown fact VALUES never block either: an unparseable version or an
  unmatched arch alias cannot ground a block, only a note.

CLI (facts arrive on stdin, never probed):
    echo '{"python_version": "3.14"}' | python scripts/decision_lint.py \
        "pip install idapro"
Exit 0 = OK, 1 = BLOCKED, 2 = usage/bad input.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field

# idapro binding wheels ship for CPython 3.8-3.13; 3.14 has no wheel and
# the binding refuses to import against it.
_MAX_IDAPRO_PY = (3, 13)

_ARCH_ALIASES = {
    "amd64": "x86_64",
    "x86-64": "x86_64",
    "aarch64": "arm64",
}


@dataclass
class Verdict:
    """Outcome of one pre-action compatibility check.

    matrix: rendered fact-vs-demand lines (the evidence a report shows);
    reasons: the verdict explanation, notes ride here prefixed "note:".
    """

    blocked: bool
    reasons: list[str] = field(default_factory=list)
    matrix: list[str] = field(default_factory=list)


def _norm_arch(value: str) -> str:
    v = str(value).strip().lower()
    return _ARCH_ALIASES.get(v, v)


def _parse_py(value) -> tuple[int, int] | None:
    m = re.match(r"(\d+)\.(\d+)", str(value).strip())
    return (int(m.group(1)), int(m.group(2))) if m else None


def _judge_python(value, _facts) -> str | None:
    parsed = _parse_py(value)
    if parsed is None:
        return None  # unparseable -> unknown -> note, never a block
    return "VIOLATION" if parsed > _MAX_IDAPRO_PY else "OK"


def _judge_arch(value, facts) -> str | None:
    other = facts.get("python_arch")
    if not other:
        return None  # one side missing -> cannot judge -> note
    return "VIOLATION" if _norm_arch(value) != _norm_arch(other) else "OK"


# rules table: package -> (fact_key, demand text, judge) entries.
# judge(gathered_value, facts) -> "OK" | "VIOLATION" | None (= unknown).
_RULES: dict[str, tuple[tuple[str, str, object], ...]] = {
    "idapro": (
        ("python_version", "python <= 3.13 (binding wheel support)",
         _judge_python),
        ("libidalib_arch", "arch matches the host python (python_arch)",
         _judge_arch),
    ),
}


def check(action: str, facts: dict) -> Verdict:
    """Gate one action against already-gathered facts (pure, no probing).

    BLOCK only when a known (package, fact) pair is known-incompatible;
    everything else — unknown package, missing fact, unparseable value —
    is OK with a note in reasons.
    """
    facts = facts or {}
    verdict = Verdict(blocked=False)
    tokens = set(re.findall(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", action or ""))
    rules = {pkg: entries for pkg, entries in _RULES.items()
             if pkg in tokens}
    if not rules:
        verdict.reasons.append(
            "note: no compatibility rule matches this action — OK "
            "(unknowns never block)")
        return verdict
    for pkg in sorted(rules):
        for key, demand, judge in rules[pkg]:
            gathered = facts.get(key)
            outcome = (judge(gathered, facts)
                       if gathered not in (None, "") else None)
            if outcome is None:
                verdict.matrix.append(
                    f"{key}: not gathered | {pkg} demands {demand} | UNKNOWN")
                verdict.reasons.append(
                    f"note: {key} not gathered — cannot judge the {pkg} "
                    f"demand ({demand}); gather it before acting")
                continue
            word = "INCOMPATIBLE" if outcome == "VIOLATION" else "ok"
            verdict.matrix.append(
                f"{key}: {gathered} | {pkg} demands {demand} | {word}")
            if outcome == "VIOLATION":
                verdict.blocked = True
                verdict.reasons.append(
                    f"BLOCK {action!r}: gathered fact {key}={gathered} "
                    f"violates the {pkg} demand ({demand}) — repair at "
                    f"that layer first (matching python/arch); do not "
                    f"install against it")
    if not verdict.blocked:
        verdict.reasons.insert(0, f"ok: {action!r} passes every judged "
                                  f"compatibility demand for {sorted(rules)}")
    return verdict


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: echo \'{"fact": "value"}\' | '
              'python scripts/decision_lint.py "<action>"', file=sys.stderr)
        return 2
    try:
        facts = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError as exc:
        print(f"facts must be a JSON object on stdin: {exc}", file=sys.stderr)
        return 2
    if not isinstance(facts, dict):
        print("facts must be a JSON object on stdin", file=sys.stderr)
        return 2
    verdict = check(argv[1], facts)
    for line in verdict.matrix:
        print(f"matrix: {line}")
    for reason in verdict.reasons:
        print(reason)
    print("VERDICT: BLOCKED" if verdict.blocked else "VERDICT: OK")
    return 1 if verdict.blocked else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
