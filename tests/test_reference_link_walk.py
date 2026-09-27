# -*- coding: utf-8 -*-
"""Contract tests for scripts/reference_link_walk.py.

Fixtures build a tmp references-like tree whose links break in the two
observed ways — bare filenames that only resolve from the LINKED file's
directory (the post-move re-library breakage), and genuinely missing
targets. The walker must report exactly the broken set, path-correct the
resolvable ones on --fix (anchor preserved), refuse ambiguous bare names,
and ignore links inside fenced code blocks.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import reference_link_walk as rlw  # noqa: E402


def _tree(tmp_path: Path) -> Path:
    refs = tmp_path / "references"
    (refs / "a").mkdir(parents=True)
    (refs / "b").mkdir(parents=True)
    # target card lives under b/; a/links.md refers to it bare
    (refs / "b" / "target-card.md").write_text(
        "# Target\n\n## Some Anchor\n\nbody\n", encoding="utf-8")
    (refs / "a" / "links.md").write_text(
        "link one: [Target](target-card.md#some-anchor)\n"
        "link two: [Missing](no-such-file.md)\n"
        "fine: [Sibling](../b/target-card.md)\n"
        "external: [Web](https://example.com/x.md)\n"
        "pure anchor: [Jump](#section)\n"
        "```bash\n"
        "code-fence link: [Ignored](also-missing.md)\n"
        "```\n",
        encoding="utf-8")
    (refs / "a" / "dup.md").write_text("dup target\n", encoding="utf-8")
    (refs / "b" / "dup.md").write_text("dup target\n", encoding="utf-8")
    # from c/, neither dup.md copy is the local one -> broken AND ambiguous
    (refs / "c").mkdir()
    (refs / "c" / "ambiguous.md").write_text(
        "ambiguous: [Dup](dup.md#x)\n", encoding="utf-8")
    return refs


def test_reports_only_broken_links(tmp_path: Path) -> None:
    refs = _tree(tmp_path)
    broken = rlw.walk(refs)
    assert {b.file.name for b in broken} == {"links.md", "ambiguous.md"}
    targets = {b.target for b in broken}
    assert "no-such-file.md" in targets
    assert "dup.md#x" in targets


def test_bare_filename_resolves_from_linked_files_directory(tmp_path: Path) -> None:
    refs = _tree(tmp_path)
    broken = rlw.walk(refs)
    targets = [b.target for b in broken if b.file.name == "links.md"]
    assert "target-card.md#some-anchor" in targets
    assert "no-such-file.md" in targets


def test_fix_rewrites_unique_bare_names_and_keeps_anchor(tmp_path: Path) -> None:
    refs = _tree(tmp_path)
    fixed = rlw.fix(refs)
    links = refs / "a" / "links.md"
    text = links.read_text(encoding="utf-8")
    assert "(../b/target-card.md#some-anchor)" in text
    assert "no-such-file.md" in text  # unresolvable stays untouched
    assert {f.file.name for f in fixed} == {"links.md", "ambiguous.md"}


def test_fix_refuses_ambiguous_bare_name(tmp_path: Path) -> None:
    refs = _tree(tmp_path)
    fixed = rlw.fix(refs)
    amb = refs / "c" / "ambiguous.md"
    assert "dup.md#x" in amb.read_text(encoding="utf-8")  # unchanged
    # reported as unfixable, not silently rewritten
    assert any(b.file.name == "ambiguous.md" for b in fixed)


def test_check_exit_code(tmp_path: Path, capsys) -> None:
    refs = _tree(tmp_path)
    assert rlw.main([str(refs), "--check"]) == 1
    out = capsys.readouterr().out
    assert "no-such-file.md" in out
    rlw.fix(refs)
    # still broken: the missing + ambiguous links remain
    assert rlw.main([str(refs), "--check"]) == 1
    capsys.readouterr()
    # a clean tree passes
    clean = tmp_path / "clean"
    clean.mkdir()
    (clean / "x.md").write_text("[y](y.md)\n", encoding="utf-8")
    (clean / "y.md").write_text("y\n", encoding="utf-8")
    assert rlw.main([str(clean), "--check"]) == 0


def test_real_references_tree_link_walk_is_clean() -> None:
    """Acceptance gate for #395: zero broken relative links repo-wide."""
    refs = Path(__file__).resolve().parents[1] / "references"
    broken = rlw.walk(refs)
    assert not broken, "\n".join(
        f"{b.file}: {b.target}" for b in broken)
