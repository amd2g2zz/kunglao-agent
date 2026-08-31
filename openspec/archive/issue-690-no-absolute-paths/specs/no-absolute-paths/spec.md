## ADDED Requirements

### Requirement: tests SHALL contain no hardcoded drive-letter absolute paths

Every file under `tests/**/*.py` SHALL be free of drive-letter
absolute-path literals (regex `[A-Z]:/|[A-Z]:\\(?![nrt])`), enforced by the
guard `tests/test_no_absolute_paths.py`. Exactly three whitelist categories
exist: (1) the guard's own detection mechanics (self-scan safe by
construction), (2) platform-independent sentinels (`/dev/null` class),
(3) lines carrying the `HISTORICAL-PATH-EXAMPLE` sentinel — docstring or
comment prose citing a concrete historical incident.

#### Scenario: guard passes on the live tree
- **WHEN** the guard scans `tests/` and every drive-shaped value is derived, relative, or sentinel-marked
- **THEN** the guard reports zero violations and passes

#### Scenario: guard flags a planted violation (negative sample)
- **WHEN** a file containing a drive-letter literal is planted under a tmp root and the scanner runs on that root
- **THEN** the scanner reports the file and line, proving the guard can go red

#### Scenario: sentinel line is skipped
- **WHEN** a single line contains both a drive literal and the `HISTORICAL-PATH-EXAMPLE` token
- **THEN** the scanner does not report that line

#### Scenario: sentinel does not mask neighbor lines
- **WHEN** a sentinel-marked line is followed by a line with an unmarked drive literal
- **THEN** the scanner reports only the unmarked line

#### Scenario: escape-shaped text is not flagged
- **WHEN** a line contains `WORD:\n` fixture text, `\d\d:` regex classes, or a URL scheme
- **THEN** the scanner does not report it (uppercase-drive + escape-aware regex)

### Requirement: absolute-path-shaped test values SHALL be derived, not literal

When a test needs an absolute-path shape, the value SHALL derive from
`tmp_path` (or `tempfile.gettempdir()` at module scope). Assertions on
path-derived output SHALL derive the expected value from the input
variable (no second literal). Inert string values SHALL use relative forms
or `os.sep` construction. Detection needles and parser fixtures that must
carry a drive shape SHALL be built by concatenation of inert fragments.
Historical compat constants SHALL keep byte-exact values via
concatenation. This is a value move, not a test deletion: suite pass rate
must not drop.

#### Scenario: ghidra home input and assertion share one source
- **WHEN** a test builds a command with `ghidra_home=str(tmp_path / "ghidra")`
- **THEN** the assertion computes the expected headless path from the same `home` variable

#### Scenario: legacy fixture rebase constants stay byte-exact
- **WHEN** a compat sentinel must match pre-#356 captured fixture paths
- **THEN** the constant is assembled as `"C:" + r"\Users\hr\..."` so its runtime value is unchanged
