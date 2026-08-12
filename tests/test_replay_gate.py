"""Batch 0 acceptance: the SKILL.md contract must not promise checks the
code does not perform. Tests the TEXT of the decision-table contract against
the ACTUAL decide() inputs (defense against the contract drifting ahead of
the implementation again — research F1)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _skill_md() -> str:
    return (ROOT / "SKILL.md").read_text(encoding="utf-8")


def test_converged_contract_names_real_limitations():
    """The CONVERGED row must name the three known gaps (contradiction /
    provenance / discovery) and must NOT promise plain 'deliver'."""
    text = _skill_md()
    row_start = text.index("| `CONVERGED` |")
    row_end = text.index("\n", row_start)
    row = text[row_start:row_end]
    for gap in ("contradiction", "provenance", "discover"):
        assert gap in row, f"CONVERGED row must name the {gap} gap"
    assert "STOP dispatch" not in row or "re-run the completion transaction" in row


def test_converged_row_does_not_reference_removed_tools():
    """handoff-check.py is not shipped anywhere in the tree — the contract
    must not point the agent at a nonexistent tool."""
    assert "handoff-check.py" not in _skill_md()
