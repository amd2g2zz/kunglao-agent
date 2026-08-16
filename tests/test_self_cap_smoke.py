# -*- coding: utf-8 -*-
"""Smoke test suite for `worker_budget.detect_self_cap` and `check_no_self_cap`.

Validates both directions:
- 14 cases that MUST trigger the gate (negative-pattern detection)
- 10 cases from SKILL.md §7 paraphrase table that MUST NOT trigger (zero FP)
- 7 negation allowlist cases that MUST suppress the gate

Run: python -m pytest tests/test_self_cap_smoke.py -q
Exit: 0 if all pass, 1 if any fail.

Tests assert their failure lists (return-based tests were vacuous under
pytest — a returned non-None list never fails a test, #368).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import yaml

# Make worker_budget importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import worker_budget as wb


def _make_tmp_yaml(content: str) -> Path:
    """Create a temp .yaml file with content; close the OS handle immediately
    so subsequent unlink() works on Windows."""
    fd, name = tempfile.mkstemp(suffix=".yaml")
    os.write(fd, content.encode("utf-8"))
    os.close(fd)
    return Path(name)


# ===== Test data =====

# 14 cases that MUST trigger _SELF_CAP_RE (negative patterns)
MUST_TRIGGER = [
    ("cap 5 min", "pattern-1 cap+N+unit"),
    ("hard cap 30s", "pattern-1 hard-cap+30s"),
    ("wall-clock cap 1 hour", "pattern-1 wall-clock-cap+hour"),
    ("maximum 60 minutes", "pattern-1 maximum+minutes"),
    ("limit 10 min", "pattern-1 limit+10min"),
    ("30 min cap", "pattern-2 30min+cap"),
    ("5 min window", "pattern-2 5min+window"),
    ("60s timeout", "pattern-2 60s+timeout"),
    ("1 hour budget", "pattern-2 1hour+budget"),
    ("15 min deadline", "pattern-2 15min+deadline"),
    ("run for 30 min", "pattern-3 run-for+30min"),
    ("idle for 5 min", "pattern-3 idle-for+5min"),
    ("stop after 30 min", "pattern-4 stop-after+30min"),
    ("stop after 60 sec", "pattern-4 stop-after+60sec"),
]

# 10 cases from SKILL.md §7 paraphrase table — MUST NOT trigger
MUST_NOT_TRIGGER = [
    "every ~5 min",
    "long-running frida trace",
    "long task (no self-cap)",
    "heartbeat until done",
    "TaskStop on 3-strike silence (no self-cap)",
    "ping with \u00a76f.1 cadence",
    "freshness window per \u00a76f.1",
    "tier-driven cadence",
    "use the tier-based interval from \u00a76b.2",
    "Status file is necessary, not sufficient",
]

# 7 cases from negation allowlist — MUST suppress the gate
NEGATION_ALLOWLIST = [
    "no self-cap dispatch",
    "no time cap here",
    "no budget, run until done",
    "without a time cap",
    "without time cap",
    "until convergence",
    "don't stop for 30 min",
]


# ===== Tests =====

def test_must_trigger():
    print("\n=== TEST: 14 cases that MUST trigger _SELF_CAP_RE ===")
    failures = []
    for desc, label in MUST_TRIGGER:
        found, offenders = wb.detect_self_cap(desc)
        status = "OK " if found else "FAIL"
        print(f"  [{status}] {label}: '{desc[:60]}'  found={found}")
        if not found:
            failures.append((label, desc))
    assert not failures, f"{len(failures)}/{len(MUST_TRIGGER)} MUST_TRIGGER cases missed _SELF_CAP_RE: {failures}"


def test_must_not_trigger():
    print("\n=== TEST: 10 SKILL.md \u00a77 paraphrase cases that MUST NOT trigger (zero FP) ===")
    failures = []
    for desc in MUST_NOT_TRIGGER:
        found, offenders = wb.detect_self_cap(desc)
        status = "OK " if not found else "FAIL"
        print(f"  [{status}] '{desc[:60]}'  found={found}")
        if found:
            failures.append(desc)
    assert not failures, f"{len(failures)}/{len(MUST_NOT_TRIGGER)} SKILL.md §7 paraphrase cases false-positived: {failures}"


def test_negation_allowlist():
    print("\n=== TEST: 7 negation allowlist cases that MUST suppress ===")
    failures = []
    for desc in NEGATION_ALLOWLIST:
        found, offenders = wb.detect_self_cap(desc)
        status = "OK " if not found else "FAIL"
        print(f"  [{status}] '{desc[:60]}'  found={found}")
        if found:
            failures.append(desc)
    assert not failures, f"{len(failures)}/{len(NEGATION_ALLOWLIST)} negation-allowlist cases failed to suppress: {failures}"


def test_check_no_self_cap_integration():
    """Integration: check_no_self_cap reads task_spec.time_budget_minutes.
    With 0 budget, MUST_TRIGGER dispatch returns (False, reason).
    With negation phrase, it returns (True, 'no self-cap detected' or similar).
    """
    print("\n=== TEST: check_no_self_cap integration ===")
    fails = []

    # Case A: clean dispatch, no task_spec
    task_spec_empty = _make_tmp_yaml("")
    ok, msg = wb.check_no_self_cap("[T1 tools=grep,xxd] claim C-001 grep for marker", task_spec_empty)
    print(f"  [{'OK ' if ok else 'FAIL'}] clean + empty task_spec: ok={ok}, msg={msg!r}")
    if not ok:
        fails.append("case_a")
    task_spec_empty.unlink()

    # Case B: MUST_TRIGGER dispatch + task_spec with budget=0 → reject
    task_spec_0 = _make_tmp_yaml(yaml.safe_dump({"time_budget_minutes": 0}))
    ok, msg = wb.check_no_self_cap("stop after 30 min then dispatch claim C-003", task_spec_0)
    print(f"  [{'OK ' if not ok else 'FAIL'}] MUST_TRIGGER + budget=0: ok={ok}, msg={msg!r}")
    if ok:
        fails.append("case_b")
    task_spec_0.unlink()

    # Case C: task_spec with budget=0 + negation phrase → allowed
    task_spec_neg = _make_tmp_yaml(yaml.safe_dump({"time_budget_minutes": 0}))
    ok, msg = wb.check_no_self_cap("heartbeat until done (no self-cap)", task_spec_neg)
    print(f"  [{'OK ' if ok else 'FAIL'}] negation + budget=0: ok={ok}, msg={msg!r}")
    if not ok:
        fails.append("case_c")
    task_spec_neg.unlink()

    assert not fails, f"check_no_self_cap integration failures: {fails}"


# ===== Main =====

def main() -> int:
    print("=" * 70)
    print("kunglao-agent _SELF_CAP_RE smoke suite (v1.8.2)")
    print("=" * 70)

    suites = [
        ("MUST_TRIGGER", test_must_trigger),
        ("MUST_NOT_TRIGGER", test_must_not_trigger),
        ("negation_allowlist", test_negation_allowlist),
        ("check_no_self_cap_integration", test_check_no_self_cap_integration),
    ]
    failed = []
    for name, fn in suites:
        try:
            fn()
        except AssertionError as e:
            failed.append((name, str(e)))

    print("\n" + "=" * 70)
    if not failed:
        total_cases = len(MUST_TRIGGER) + len(MUST_NOT_TRIGGER) + len(NEGATION_ALLOWLIST) + 3
        print(f"ALL_OK ({total_cases} cases passed)")
        return 0
    print(f"FAILURES: {len(failed)}")
    for name, msg in failed:
        print(f"  {name}: {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())