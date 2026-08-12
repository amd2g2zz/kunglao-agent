## ADDED Requirements

### Requirement: The repo SHALL ship a distilled convergence-loop rules file under rules/

`rules/kunglao-convergence-loop.md` SHALL exist, SHALL be under 150 lines, SHALL cover the 9-point outline (identity / first-tool invariant / convergence decision table / 5 behaviors / maker-checker split / tool boundary / hard prohibitions / file map / pointers), and SHALL NOT contain long verbatim blocks copied from `references/convergence-loop.md` (no shared substring of 80+ characters beyond an allowlisted vocabulary of paths, script invocations, file names, and decision tokens). SKILL.md and `references/convergence-loop.md` SHALL remain unmodified.

#### Scenario: the rules file exists and fits the line budget
- **WHEN** `rules/kunglao-convergence-loop.md` is read from the repo root
- **THEN** it exists and its total line count is less than 150

#### Scenario: the first-tool invariant is present
- **WHEN** the rules file is read
- **THEN** it contains the marker "每轮第一个工具" and the token `convergence_check`

#### Scenario: the convergence decision table is present
- **WHEN** the rules file is read
- **THEN** it contains the decision tokens `DISPATCH`, `DISPATCH_VERIFIER`, `SATURATED`, `BLOCKED`, and `CONVERGED`

#### Scenario: the 5 behaviors are present one line each
- **WHEN** the rules file is read
- **THEN** it contains each of the labels `self-recovery`, `specialist-first`, `cost-is-noise`, `poll-workers`, and `false-completion-trap`

#### Scenario: the maker-checker split is present
- **WHEN** the rules file is read
- **THEN** it contains `maker-checker` and the worker-as-maker / orchestrator-as-checker relationship (`worker=maker`)

#### Scenario: the tool boundary is present
- **WHEN** the rules file is read
- **THEN** it forbids direct analysis-tool calls — contains `永不直接` together with `ghidra`, `x64dbg`, and `frida`

#### Scenario: the hard prohibitions are present
- **WHEN** the rules file is read
- **THEN** it contains the mid-iteration-questioning prohibition (`反问`), the cascade-abort prohibition (`cascade`), and the no-declare-done-with-OPEN-claims prohibition (`declare done` together with `OPEN`)

#### Scenario: the file map is present
- **WHEN** the rules file is read
- **THEN** it contains `claim-register.yaml`, `facts/_INDEX.md`, `.convergence_ledger.jsonl`, and `scripts/`

#### Scenario: pointers to the full contract are present
- **WHEN** the rules file is read
- **THEN** it references `SKILL.md` and `references/` as the full-contract locations

#### Scenario: no long verbatim blocks are copied from the reference
- **WHEN** every 80-character window of the whitespace-normalized rules text is checked against the whitespace-normalized text of `references/convergence-loop.md`, after masking allowlisted vocabulary
- **THEN** no window (minus its masked vocabulary) contains non-whitespace residue — i.e. no window is a verbatim copy of the reference beyond shared vocabulary

#### Scenario: the reference and SKILL.md remain untouched
- **WHEN** the git diff of the change is inspected
- **THEN** `references/convergence-loop.md` and `SKILL.md` have no modifications
