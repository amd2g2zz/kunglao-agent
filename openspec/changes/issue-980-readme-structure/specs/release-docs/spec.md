# release-docs

## ADDED Requirements

### Requirement: readme-navigation-resolves
Every in-page link in the README pair SHALL resolve to a heading GitHub
actually generates an anchor for. A link pointing at a `<summary>`, a bold
line, or a collapsed block is a dead link even when the text is on the page.

#### Scenario: collapsed blocks are not link targets
- **WHEN** a README links to a section that lives inside `<details><summary>`
- **THEN** the block gains a real heading before the link ships

### Requirement: readme-toc-is-navigable
The table of contents SHALL consist of links, and SHALL cover every
second-level section except License.

#### Scenario: decorative TOC rejected
- **WHEN** the contents line is a plain string with `·` separators
- **THEN** it is replaced with links, one per section

### Requirement: bilingual-section-parity
`README.md` and `README.zh-CN.md` SHALL carry the same second-level sections
in the same order; a section present in one language and absent in the other
is a parity defect.

#### Scenario: section counts match
- **WHEN** the two READMEs are compared by heading level 2
- **THEN** the counts are equal and the sequence corresponds
