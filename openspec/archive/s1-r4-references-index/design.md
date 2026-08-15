# Design — references/INDEX.md navigation index (#115)

## Architecture

Single markdown file at `references/INDEX.md` parsed by both humans and automated tests.
Two tables: one for top-level references, one for `re-library/` subdirectory.
All file paths use backtick-quoted relative paths from `references/`.

## Data Flow

```
references/*.md  ----(find + rglob)---->  test discovers all files
                                                 |
                                                 v
                                        INDEX.md entries parsed via regex
                                                 |
                                                 v
                                        set difference: missing / ghost / empty
```

## Key Decisions

1. **Exclude INDEX.md from its own table** — it is a navigation artifact, not a
   reference. The test explicitly filters it from `_all_md_files()`.

2. **Backtick-quoted paths** — enables regex parsing with a simple pattern
   `r"^\|\s*\`([^`]+)\`\s*\|"` without ambiguity from whitespace or special
   characters.

3. **Two tables (top-level + re-library)** — improves readability over a single
   48-row table. Subdirectory files are prefixed with `re-library/` in the File
   column.

4. **Purpose + When to read columns** — the progressive-disclosure model needs
   both "what is this" and "when should I load it" to enable on-demand file
   loading without reading the entire index.

## Test Strategy

5 assertions in `TestReferencesIndex`:

| Test | Assertion | Failure mode |
|------|-----------|--------------|
| `test_index_file_exists` | INDEX.md is a file | Index deleted |
| `test_all_md_files_are_indexed` | `all_files <= indexed` | New reference added without index update |
| `test_index_has_no_ghost_entries` | `indexed <= all_files` | Reference renamed/deleted without index update |
| `test_index_has_purpose_and_when_to_read` | No empty/dash cells | Incomplete row added |
| `test_total_entry_count` | `len(indexed) == len(all_files)` | Catch-all count mismatch |

## Constraints

- Pure stdlib test (re, pathlib). No external dependencies.
- Regex-based parsing — no markdown library required.
- Paths use Posix separators (`/`) for cross-platform consistency in test assertions.
