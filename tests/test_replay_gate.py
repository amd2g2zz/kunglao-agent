"""Batch 0 acceptance gates for the false-closure elimination.

- The SKILL.md contract must not promise checks the code does not
  perform (research F1, issue #205).
- Pinned digests must match files on disk (issue #192: 6/6 manifest
  digests drifted from eval fixtures, so verify_manifest() failed
  closed and held-out evaluation could never produce a receipt).
- structural_check error lines must be grep-parseable (issue #193).
- No broken links in references/ (issue #194: 3 broken links in
  references/re-library/ made structural_check.py fail on every run).
"""
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


def test_candidate_corpus_digests_match_files():
    """Every sha256 pinned in memory/candidates/corpus/manifest.json must
    match the file on disk (research: 6/6 mismatched → held-out evaluation
    INCONCLUSIVE)."""
    import hashlib
    import json

    manifest = json.loads(
        (ROOT / "memory/candidates/corpus/manifest.json").read_text(encoding="utf-8")
    )
    mismatches = []
    for rel, expected in manifest.get("files", {}).items():
        p = ROOT / rel
        if not p.exists():
            mismatches.append(f"{rel}: missing")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected:
            mismatches.append(f"{rel}: manifest={expected[:12]} actual={actual[:12]}")
    assert not mismatches, f"digest drift: {mismatches}"


def test_structural_check_error_lines_are_prefixed():
    """Grep-parseable contract: IF structural errors exist, each line must
    start with 'ERROR ' (research: CI grep missed unprefixed errors)."""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "scripts/structural_check.py", "."],
        capture_output=True, text=True,
    )
    error_lines = [ln for ln in r.stdout.splitlines() if "BROKEN_LINK" in ln or "MISSING_" in ln]
    assert all(ln.startswith("ERROR ") for ln in error_lines), r.stdout


def test_no_broken_links_in_re_library():
    """Every relative .md link in references/ must resolve (research: 3
    broken links: field-notes -> SKILL.md, field-notes ->
    phishing-case-study.md, quickstart -> README.md)."""
    import subprocess
    import sys

    r = subprocess.run(
        [sys.executable, "scripts/structural_check.py", "."],
        capture_output=True, text=True,
    )
    broken = [ln for ln in r.stdout.splitlines() if "BROKEN_LINK" in ln]
    assert not broken, "\n".join(broken)
