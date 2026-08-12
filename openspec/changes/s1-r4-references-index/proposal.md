# Proposal — references/INDEX.md navigation index (#115)

## Why

The `references/` directory has 48 markdown files (20 top-level + 28 in `re-library/`)
with no index or directory. Workers and orchestrators cannot quickly determine "which
reference to read when." The skill-creator progressive-disclosure manual requires
references to have navigation support so agents can load only the relevant file on
demand instead of scanning all files.

## What Changes

- **`references/INDEX.md`** (new): A navigation index with one table entry per file,
  covering all 48 `.md` files in `references/` (including `re-library/` subdirectory).
  Each entry has three columns: File (relative path), Purpose (one sentence), and
  When to read (trigger scenario). The index itself is excluded from the table since
  it is the navigation artifact, not a reference document.

- **`tests/test_references_index.py`** (new): Automated guard with 5 assertions:
  1. INDEX.md exists.
  2. Every `*.md` file in `references/` (excluding INDEX.md) has an entry.
  3. No ghost entries (every listed file exists on disk).
  4. Every entry has non-empty Purpose and When to read columns.
  5. Entry count matches file count.

## Non-goals

- Does NOT edit any existing reference files.
- Does NOT edit SKILL.md.
- Does NOT change the content or organization of any reference.
- Does NOT add cross-references within individual reference files.

## Capabilities

### Added Capabilities

- `references-index`: a navigable index of all reference documents with purpose and
  trigger-scenario descriptions, enabling agents to locate the right reference without
  scanning the directory.

## Impact

- `references/INDEX.md`: new, ~120 lines (header + two tables).
- `tests/test_references_index.py`: new, ~86 lines (5 tests).
- Suite impact: +5 new passing tests; 0 existing tests modified; no regressions.
- Related: #110 (verdict schema), #108 (SKILL.md CTI removal) — no overlap.
