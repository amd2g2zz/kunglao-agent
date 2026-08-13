# -*- coding: utf-8 -*-
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
    """The CONVERGED row must name the three checks the completion
    transaction NOW performs (contradiction / provenance / discovery) —
    the contract may only rise back after the code performs them."""
    text = _skill_md()
    row_start = text.index("| `CONVERGED` |")
    row_end = text.index("\n", row_start)
    row = text[row_start:row_end]
    for term in ("contradiction", "provenance", "discover"):
        assert term in row, f"CONVERGED row must name the {term} check"
    assert "STOP dispatch" in row, "re-raised contract must authorize delivery"


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


def test_references_index_pins_all_reference_files():
    """Every references/*.md and references/re-library/*.md must be pinned
    in references/_INDEX.yaml with a digest matching the file on disk
    (recall-engine precondition: deterministic index before runtime recall)."""
    import hashlib
    import subprocess
    import sys

    import yaml

    index_path = ROOT / "references" / "_INDEX.yaml"
    if not index_path.exists():
        raise AssertionError("references/_INDEX.yaml missing")
    index = yaml.safe_load(index_path.read_text(encoding="utf-8")) or {}
    files = index.get("files", {})
    actual_md = sorted(
        str(p.relative_to(ROOT)).replace("\\", "/")
        for p in (ROOT / "references").glob("**/*.md")
        if "archive/" not in str(p.relative_to(ROOT)).replace("\\", "/")
    )
    missing = [f for f in actual_md if f not in files]
    assert not missing, f"files not pinned in _INDEX.yaml: {missing}"

    mismatches = []
    for rel, expect in files.items():
        p = ROOT / rel
        if not p.exists():
            mismatches.append(f"{rel}: missing on disk")
            continue
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expect:
            mismatches.append(f"{rel}: index={expect[:12]} actual={actual[:12]}")
    assert not mismatches, f"digest drift: {mismatches}"

    r = subprocess.run(
        [sys.executable, "scripts/structural_check.py", "."],
        capture_output=True, text=True,
    )
    assert "INDEX_DRIFT" not in r.stdout, r.stdout
def test_release_manifest_declares_skill_and_references():
    """release-manifest must declare SKILL.md and the re-library digest so
    a run can bind to the exact knowledge-base revision (report §4.5)."""
    import yaml

    manifest = yaml.safe_load(
        (ROOT / "release-manifest.yaml").read_text(encoding="utf-8")
    )
    assets = manifest.get("assets", {})
    assert "SKILL.md" in assets.get("knowledge", []), assets.get("knowledge")
    refs = assets.get("references", [])
    assert any("references/re-library" in r or r == "references/" for r in refs), refs
