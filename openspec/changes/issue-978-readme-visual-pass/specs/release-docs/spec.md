# release-docs

## ADDED Requirements

### Requirement: readme-asset-integrity
Every image the README pair embeds SHALL resolve to a file tracked in the
repository. A reference without its asset is a documentation defect, not a
rendering quirk — the section loses its evidence.

#### Scenario: missing chart blocks the change
- **WHEN** a README embeds `docs/assets/<name>` and that file is absent from the tree
- **THEN** the documentation change is rejected until the asset is rendered or the reference is removed

### Requirement: bilingual-doc-parity
`README.md` and `README.zh-CN.md` SHALL carry the same visuals in the same
order, and a figure's reading key SHALL appear in both languages.

#### Scenario: figure order stays aligned
- **WHEN** a section gains a figure in one language
- **THEN** the other language gains the same figure at the same position before the change lands

#### Scenario: reading key is bilingual
- **WHEN** a chart plots two measures on two axes
- **THEN** both READMEs state what each axis carries, in their own language
