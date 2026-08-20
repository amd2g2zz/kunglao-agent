# -*- coding: utf-8 -*-
"""Anchors #537 contract-text fixes so they cannot regress: F-C3 (the
SKILL.md hook wire-up row), F-C4 (the bundled-rules channel + its
byte-identity with the repo-top source), and the completion_gate.py
docstring's post-#200 block semantics."""
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parent.parent / "skills" / "kunglao-agent" / "SKILL.md"


def test_skill_md_112_removed_contradiction():
    """#461 made init self-install hooks; the row at :112 must say so, not contradict."""
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "Hook wire-up NOT auto-installed" not in text, (
        "F-C3 regression: SKILL.md still asserts hooks are NOT auto-installed; "
        "this contradicts #461 (init self-installs) and :124 (Phase 1 MUST --wire-up)"
    )


def test_skill_md_112_explains_461_self_install():
    """The Hook wire-up row must state that #461 handles auto-install."""
    text = SKILL_MD.read_text(encoding="utf-8")
    lines = text.splitlines()
    row_112 = next(l for l in lines if "Hook wire-up" in l)
    assert "#461" in row_112 or "self-install" in row_112.lower() or "auto" in row_112.lower(), (
        f"F-C3 regression: the Hook wire-up row does not mention #461 / self-install. "
        f"Got: {row_112!r}"
    )


def test_skill_md_112_row_is_affirmative_auto_install():
    """Supplementary anchor (#537): the exact-string check above is defeated by
    the table-cell pipe ("| Hook wire-up | NOT auto-installed"), so pin the
    Hook wire-up row itself — it must not carry the v0.1.1-era
    NOT-auto-installed posture and must reference #461."""
    lines = SKILL_MD.read_text(encoding="utf-8").splitlines()
    row_112 = next(l for l in lines if "Hook wire-up" in l)
    assert "not auto-installed" not in row_112.lower(), (
        f"F-C3 regression: the Hook wire-up row still says NOT auto-installed. Got: {row_112!r}"
    )
    assert "auto-installed" in row_112.lower() and "repair" in row_112.lower(), (
        f"F-C3: the Hook wire-up row must state auto-install and repair-only manual chain. "
        f"Got: {row_112!r}"
    )


def test_bundled_rule_matches_source():
    """#537 F-C4: the bundled copy external installs read must stay
    byte-identical to the declared source in repo-top rules/."""
    root = Path(__file__).resolve().parent.parent
    src = (root / "rules" / "kunglao-convergence-loop.md").read_bytes()
    bundled = (root / "skills" / "kunglao-agent" / "rules" / "kunglao-convergence-loop.md").read_bytes()
    assert src == bundled, (
        "bundled rule copy drifted from repo-top source (rules/): "
        f"src sha256 mismatch vs bundled — re-copy or update source"
    )


def test_skill_md_rules_channel_explained():
    text = SKILL_MD.read_text(encoding="utf-8")
    # Must either reference bundled rules path OR explicitly mark internal-only
    assert "rules/" in text or "internal-deployment-only" in text, (
        "F-C4: SKILL.md must clarify global-rules distribution"
    )


def test_skill_md_no_undefined_rules_path():
    text = SKILL_MD.read_text(encoding="utf-8")
    # The claim "~/.claude/rules/common/" must NOT appear as a user promise
    assert "~/.claude/rules/common/" not in text or "internal" in text.lower(), (
        "F-C4: SKILL.md claims ~/.claude/rules/common/ which does not exist in external installs"
    )


def test_completion_gate_docstring_no_pre200_allow_semantics():
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "hooks" / "completion_gate.py"
    text = src.read_text(encoding="utf-8")
    docstring_block = text.split('"""', 2)[1] if text.count('"""') >= 2 else text[:200]
    forbidden_phrases = ["allow without", "passes when not activated", "no-op when inactive"]
    for bad in forbidden_phrases:
        assert bad not in docstring_block.lower(), (
            f"completion_gate.py docstring still claims pre-#200 allow semantics: {bad!r}"
        )


def test_completion_gate_docstring_matches_current_block_semantics():
    """Supplementary anchor (#537): the plan's forbidden-phrase list does not
    catch the actual staleness — the old docstring claimed pre-#200 allow
    semantics for the no-oracle and second-stop cases while the code BLOCKS.
    Pin the docstring to the post-#200 fail-closed posture."""
    from pathlib import Path
    src = Path(__file__).resolve().parent.parent / "hooks" / "completion_gate.py"
    docstring_block = src.read_text(encoding="utf-8").split('"""', 2)[1].lower()
    # #200: activated + no oracle must be documented as BLOCK, not pass-through
    assert "no task-oracle.yaml" in docstring_block and "exit 3" in docstring_block, (
        "docstring must document the #200 no-oracle BLOCK (exit 3)"
    )
    assert "not the pre-#200 oracle-presence pass-through" in docstring_block, (
        "docstring must explicitly negate the stale pre-#200 allow posture"
    )
    # #147/#199: second stop passes only with oracle sanction
    assert "sanctioned-pass record passes" in docstring_block.replace("only that ", ""), (
        "docstring must document sanctioned-PASS-only second-stop semantics"
    )
