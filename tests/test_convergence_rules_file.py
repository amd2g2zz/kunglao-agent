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


def test_identity_orchestrator_present() -> None:
    """#1 outline: identity — kunglao-agent is an RE orchestrator, not an analyst."""
    text = _text()
    assert "orchestrator" in text
    assert "不是分析师" in text


def test_first_tool_invariant_present() -> None:
    """#2 outline: every round's first tool = convergence_check."""
    text = _text()
    assert "每轮第一个工具" in text
    assert "convergence_check" in text


def test_convergence_decision_table_present() -> None:
    """#3 outline: DISPATCH / DISPATCH_VERIFIER / SATURATED / BLOCKED / CONVERGED."""
    text = _text()
    for token in ("DISPATCH", "DISPATCH_VERIFIER", "SATURATED", "BLOCKED", "CONVERGED"):
        assert token in text, f"decision-table token missing: {token}"


def test_five_behaviors_present() -> None:
    """#4 outline: 5 behaviors, one line each."""
    text = _text()
    for label in ("self-recovery", "specialist-first", "cost-is-noise",
                  "poll-workers", "false-completion-trap"):
        assert label in text, f"behavior label missing: {label}"


def test_maker_checker_split_present() -> None:
    """#5 outline: worker=maker, orchestrator=checker, no self-stamp."""
    text = _text()
    assert "maker-checker" in text
    assert "worker=maker" in text


def test_tool_boundary_present() -> None:
    """#6 outline: never call analysis tools (ghidra/x64dbg/frida) directly."""
    text = _text()
    assert "永不直接" in text
    for tool in ("ghidra", "x64dbg", "frida"):
        assert tool in text, f"boundary tool missing: {tool}"


def test_hard_prohibitions_present() -> None:
    """#7 outline: no mid-iteration 反问 / no cascade abort / no declare-done with OPEN claims."""
    text = _text()
    assert "反问" in text
    assert "cascade" in text
    assert "declare done" in text
    assert "OPEN" in text


def test_file_map_present() -> None:
    """#8 outline: claim-register.yaml / facts/_INDEX.md / .convergence_ledger.jsonl / scripts/."""
    text = _text()
    for path in ("claim-register.yaml", "facts/_INDEX.md", ".convergence_ledger.jsonl", "scripts/"):
        assert path in text, f"file-map entry missing: {path}"


def test_pointers_present() -> None:
    """#9 outline: full contract lives in SKILL.md + references/."""
    text = _text()
    assert "SKILL.md" in text
    assert "references/" in text


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
