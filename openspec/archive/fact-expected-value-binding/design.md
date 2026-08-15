## Context

`kunglao_verify.py::l1_mechanical` is the byte-exact verification layer: rerun reproduce, sha256-compare actual vs `expected`. Two gaps exposed by a2b5e25c (customer incident, F015):

1. `expected` may carry only API-call sequences (semantic prose), no concrete assignment values. `l1_mechanical` hashes the whole `expected` blob as one sha256 target - when the blob is semantic prose, the byte-exact compare reduces to matching prose, not field values.
2. No gate refuses assignment-class facts whose `expected` lacks value targets. verifier falls back to semantic key-calls review (known limitation) - a correct call sequence passes while field assignments are wrong.

Current machinery: `l1_mechanical` (sha256 compare), `_expected_hash` (64-hex passthrough or sha256 of stripped text), `anchor_check` (requires anchors: byte_offset/cmd/expected).

## Goals / Non-Goals

**Goals:**
- Assignment/numeric facts MUST list concrete value assertions in `expected` (field=value + offset/register/immediate source)
- `kunglao_verify.py` rejects (lint-level) assignment-class `expected` lacking value assertions
- byte-exact compare targets the value assertions, not whole-blob sha256
- a2b5e25c regression: F015 rejected until backfilled with values

**Non-Goals:**
- NOT reworking the whole verify taxonomy (#47 fact-contradiction / #48 blind-scope handle other layers)
- NOT auto-deriving values from binary - workers still author `expected`; this change forces them to be concrete
- NOT touching malware-veri-notes (separate skill, unrelated to this change)
- NOT changing reproduce/fixture mechanics - only what `expected` MUST contain + how it is compared

## Decisions

### D1: lint-reject (hard gate), not warn-only
Assignment-class `expected` without value assertions -> reject promotion, not warn.
- Why: a2b5e25c showed warn-only lets wrong assignments reach reports under convergence pressure.
- Alt considered: warn-only - rejected; the customer incident proves soft signals get ignored.

### D2: targeted byte-exact on value assertions, not whole-blob sha256
Parse value assertions out of `expected`; compare each (field -> expected value) against reproduce output / fixture, not sha256 of the whole `expected` text.
- Why: whole-blob sha256 of semantic prose is exactly what F015 defeated. Per-assertion compare gives a real target.
- Alt considered: require `expected` to be the literal reproduce stdout - rejected, too rigid for assignment lists spanning offsets/registers; per-assertion is the right granularity.

### D3: enforce inside `kunglao_verify.py`, not a new module
Add `check_assignment_expected()` + extend `l1_mechanical` in `kunglao_verify.py`; do not create a separate lint-notes.py.
- Why: the verify path already owns `expected` semantics (`_expected_hash`, `anchor_check`); splitting lint from verify recreates the drift this change fixes. Single owner.
- Alt considered: separate lint-notes.py (matches malware-veri-notes naming) - rejected per scope (malware-veri-notes unrelated); kunglao-agent keeps its own machinery.

### D4: assignment-class detection by keyword heuristic
Classify `expected` as assignment-class if it contains assignment indicators: `=` (not `==`), field-name patterns, hex immediates (`0x...`), register references, offset references. Pure API-sequence facts (no such tokens) pass unchanged.
- Why: deterministic classifier needed to decide whether value-assertions are required.
- Alt considered: explicit `fact_class:` frontmatter tag - viable future extension, but keyword heuristic works now without backfilling the frontmatter of every fact. Captured as Open Question.

## Risks / Trade-offs

- Existing PROVEN facts with assignment content get rejected -> Mitigation: backfill F015-class facts with value assertions; the rejection IS the intended catch. Ship behind `--grace` (warn-only) for one cycle if migration volume is high.
- Keyword heuristic over/under-classifies -> Mitigation: RED1-RED3 + a2b5e25c regression pin the boundary; heuristic tuned on F015 + sibling facts.
- Workers author more verbose `expected` -> accepted cost; the verbosity IS the byte-exact target.

## Migration Plan

1. Ship check + lint-reject behind `--grace` (warn-only) for one cycle; enumerate affected facts (F015 + siblings).
2. Backfill the `expected` of affected facts with value assertions.
3. Flip to hard-reject; a2b5e25c regression must pass (F015 rejected pre-backfill, accepted post-backfill with correct values).

Rollback: revert to warn-only via flag.

## Open Questions

- D4: adopt an explicit `fact_class:` frontmatter tag later (more robust than keyword heuristic)?
- Value-assertion format: structured (YAML list of field/value/source) or free-form text with convention? Lean free-form + convention now (lower friction), structure later if diff needs it.
