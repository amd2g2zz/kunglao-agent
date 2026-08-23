# -*- coding: utf-8 -*-
"""#46 contract tests: rules/kunglao-convergence-loop.md (distilled always-on rules).

RED phase: the rules file does not exist yet — every test fails.
GREEN phase: the distilled file satisfies all invariants.

Checks:
- file exists, total lines < 150
- 9-point outline markers present (identity / first-tool invariant / decision
  table / 5 behaviors / maker-checker / tool boundary / hard prohibitions /
  file map / pointers)
- "distill != copy": no 80+ char window of the rules text appears in
  references/convergence-loop.md once the defined vocabulary is masked out
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules" / "kunglao-convergence-loop.md"
REFERENCE = ROOT / "references" / "convergence-loop.md"

MIN_SHARED = 80

# Vocabulary legitimately shared between the distilled file and the reference:
# script names / full script invocations, file names, decision tokens, behavior
# labels. Masking these before the substring check keeps the test from flagging
# legitimate reuse while still catching verbatim copied prose.
ALLOWED_VOCABULARY = [
    "python scripts/convergence_check.py <workspace>",
    "python scripts/convergence_health.py <workspace>",
    "python scripts/failure_analysis_gate.py <workspace> <C-NN>",
    "convergence_check.py",
    "convergence_health.py",
    "failure_analysis_gate.py",
    "priority.py",
    "priority_ratio.py",
    "claim-register.yaml",
    "facts/_INDEX.md",
    ".convergence_ledger.jsonl",
    "DISPATCH",
    "DISPATCH_VERIFIER",
    "SATURATED",
    "BLOCKED",
    "CONVERGED",
    "HEALTHY",
    "STALLED",
    "SPINNING",
    "self-recovery",
    "specialist-first",
    "cost-is-noise",
    "poll-workers",
    "false-completion-trap",
    "maker-checker",
]


def _text() -> str:
    return RULES.read_text(encoding="utf-8")


def _normalize(text: str) -> str:
    """Collapse all whitespace runs (incl. newlines) to single spaces."""
    return " ".join(text.split())


def _mask_vocabulary(text: str) -> str:
    """Replace every vocabulary occurrence with same-length spaces."""
    for token in sorted(ALLOWED_VOCABULARY, key=len, reverse=True):
        text = text.replace(token, " " * len(token))
    return text


# ---------- existence / line budget ----------


def test_rules_file_exists() -> None:
    assert RULES.exists(), f"missing {RULES.relative_to(ROOT)}"


def test_rules_file_lte_150_lines() -> None:
    lines = len(_text().splitlines())
    assert lines < 150, f"rules file has {lines} lines, must be < 150"


# ---------- 9-point outline markers ----------

# (marker, required substrings) — each #N outline requirement the distilled
# rules file must satisfy. Merged into one loop: a missing marker fails with
# its name in the assertion message (same detection as the former 9 tests).
OUTLINE_MARKERS = [
    ("identity", ["orchestrator", "not an analyst"]),
    ("first-tool-invariant", ["first tool of every round", "convergence_check"]),
    ("decision-table", ["DISPATCH", "DISPATCH_VERIFIER", "SATURATED", "BLOCKED", "CONVERGED"]),
    ("five-behaviors", ["self-recovery", "specialist-first", "cost-is-noise",
                        "poll-workers", "false-completion-trap"]),
    ("maker-checker", ["maker-checker", "worker=maker"]),
    ("tool-boundary", ["Never call analysis tools directly", "ghidra", "x64dbg", "frida"]),
    ("hard-prohibitions", ["asking the user", "cascade", "declare done", "OPEN"]),
    ("file-map", ["claim-register.yaml", "facts/_INDEX.md", ".convergence_ledger.jsonl", "scripts/"]),
    ("pointers", ["SKILL.md", "references/"]),
]


def test_outline_markers_present() -> None:
    text = _text()
    for marker, substrings in OUTLINE_MARKERS:
        for sub in substrings:
            assert sub in text, f"outline marker '{marker}' missing '{sub}'"


# ---------- distill != copy ----------


def test_no_long_verbatim_blocks_from_reference() -> None:
    """No 80+ char window of the rules text may appear in references/convergence-loop.md
    once the defined vocabulary is masked out."""
    rules_norm = _normalize(_text())
    ref_norm = _normalize(REFERENCE.read_text(encoding="utf-8"))
    ref_windows = {ref_norm[i : i + MIN_SHARED] for i in range(len(ref_norm) - MIN_SHARED + 1)}
    masked_rules = _mask_vocabulary(rules_norm)
    violations = []
    for i in range(len(rules_norm) - MIN_SHARED + 1):
        window = rules_norm[i : i + MIN_SHARED]
        if window in ref_windows and masked_rules[i : i + MIN_SHARED].strip():
            violations.append((i, window))
    assert not violations, (
        f"{len(violations)} verbatim block(s) of >= {MIN_SHARED} chars shared with "
        f"references/convergence-loop.md: {violations[:3]}"
    )
