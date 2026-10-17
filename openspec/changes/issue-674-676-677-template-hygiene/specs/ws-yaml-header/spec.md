# ws-yaml-header delta — issue-674-676-677-template-hygiene

## ADDED Requirements

### Requirement: The sanctioned writer preserves the leading comment header

`ws_yaml.py` SHALL re-prepend the target file's maximal leading comment
block byte-identically above the canonical body after every `set`,
`append`, and `del` write — the template-version stamp and the marker
family riding the same block (e.g. `[initialized]`) are contractual
carriers, not cosmetic comments. When the header lacks the stamp line,
the writer SHALL recover the stamp value through the existing chain (the
file itself → the same-directory `CLAUDE.md` for the register → the
active skill version) and emit it above the header. The YAML body SHALL
remain the pure canonical round-trip (non-round-tripping writes stay
refused); comments inside the body keep being dropped.

#### Scenario: the header survives every sanctioned operation

- **WHEN** `ws_yaml set`, `append`, and `del` each write a register whose
  header carries the stamp line and an `[initialized]` marker line
- **THEN** after every operation the file's leading comment block still
  begins with the unchanged stamp line and contains the unchanged
  marker line, followed by the canonical body

#### Scenario: a sanctioned write leaves the stamp contract clean

- **WHEN** `ws_yaml set` writes a stamped register, and (in a separate
  workspace) an unstamped register whose sibling `CLAUDE.md` carries the
  stamp
- **THEN** `template_version.verify_stamps()` returns an empty fault map
  for each workspace

#### Scenario: the canonical body is untouched by the header rule

- **WHEN** a sanctioned write round-trips a register
- **THEN** the bytes below the header equal `canonical_dump` of the
  mutated document, and a non-round-tripping write is still refused with
  exit 4
