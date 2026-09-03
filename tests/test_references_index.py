"""Test that references/INDEX.md covers every *.md file in references/."""

from __future__ import annotations

import re
from pathlib import Path


REFERENCES_DIR = Path(__file__).resolve().parent.parent / "references"
INDEX_FILE = REFERENCES_DIR / "_INDEX.md"


def _all_md_files() -> set[str]:
    """Return relative paths (Posix style) of every .md file under references/, excluding _INDEX.md itself and archived files."""
    return {
        p.relative_to(REFERENCES_DIR).as_posix()
        for p in REFERENCES_DIR.rglob("*.md")
        if p.name not in ("_INDEX.md", "_INDEX.yaml")
        and "archive/" not in p.relative_to(REFERENCES_DIR).as_posix()
    }


def _indexed_files() -> set[str]:
    """Parse INDEX.md table rows and return the set of relative file paths."""
    text = INDEX_FILE.read_text(encoding="utf-8")
    # Match markdown table rows: | `path` | ... | ... |
    pattern = r"^\|\s*`([^`]+)`\s*\|"
    return {m.group(1) for m in re.finditer(pattern, text, re.MULTILINE)}


class TestReferencesIndex:
    def test_index_file_exists(self) -> None:
        assert INDEX_FILE.is_file(), f"{INDEX_FILE} does not exist"

    def test_all_md_files_are_indexed(self) -> None:
        all_files = _all_md_files()
        indexed = _indexed_files()

        missing = all_files - indexed
        assert not missing, (
            f"The following .md files are missing from references/INDEX.md:\n"
            + "\n".join(f"  - {f}" for f in sorted(missing))
        )

    def test_index_has_no_ghost_entries(self) -> None:
        """Every entry in INDEX.md should correspond to a real file."""
        all_files = _all_md_files()
        indexed = _indexed_files()

        ghosts = indexed - all_files
        assert not ghosts, (
            f"The following INDEX.md entries do not correspond to real files:\n"
            + "\n".join(f"  - {f}" for f in sorted(ghosts))
        )

    def test_index_has_purpose_and_when_to_read(self) -> None:
        """Every table row must have a non-empty Purpose and When to read column."""
        text = INDEX_FILE.read_text(encoding="utf-8")
        # Match rows with file path
        row_pattern = r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|$"
        matches = list(re.finditer(row_pattern, text, re.MULTILINE))

        empty_purpose = []
        empty_when = []
        for m in matches:
            filepath, purpose, when = m.group(1), m.group(2).strip(), m.group(3).strip()
            if not purpose or purpose == "-":
                empty_purpose.append(filepath)
            if not when or when == "-":
                empty_when.append(filepath)

        assert not empty_purpose, (
            "Entries with empty Purpose:\n"
            + "\n".join(f"  - {f}" for f in empty_purpose)
        )
        assert not empty_when, (
            "Entries with empty 'When to read':\n"
            + "\n".join(f"  - {f}" for f in empty_when)
        )

    def test_total_entry_count(self) -> None:
        """INDEX.md should index all reference files (excluding INDEX.md itself)."""
        all_files = _all_md_files()
        indexed = _indexed_files()
        assert len(indexed) == len(all_files), (
            f"Expected {len(all_files)} entries but found {len(indexed)}"
        )
