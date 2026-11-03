# verifier-integrity-809 delta — issue-809-verifier-integrity

## ADDED Requirements

### Requirement: PROVEN settlement resolves to a PASSED verification record

The claims store SHALL treat a PASSED independent-verification record
as a HARD precondition of `settle_proven` and `settle_verified`: the
`verification` reference SHALL resolve (workspace-relative explicit
path, else the canonical claim surfaces
`runs/verification-<claim>.md` / `runs/<claim>-verify-note.md` /
`runs/verify-redteam-<claim>.md` / `evidence/verdict.json`) to an
existing record whose verdict word classifies as PASSED. Absence,
traversal escape, unparseable content, unknown verdict words, and
failing verdicts SHALL refuse the mint with one provenance row —
settlement cannot mint PROVEN/VERIFIED around a failing, missing, or
not-yet-arrived verifier. Reference resolution SHALL be
case-folded and containment-guarded (resolved path stays inside the
workspace). Negative settlements (NEGATIVE/REFUTED/DEFERRED) SHALL
stay exempt. Resolver faults SHALL fail CLOSED (refuse), never
fail-open.

#### Scenario: settlement preceding a REJECT replay is refused (production shape A)

- **WHEN** a claim's verification record on disk reads
  `verdict: REJECTED` (the verifier's reject arrived after the
  attempted settlement mint) and `apply(settle_proven)` references it
- **THEN** the transition is refused with reason
  `verification-not-passed`, the register is byte-unchanged, and
  `runs/claims-provenance.jsonl` gains one `outcome=refused` row

#### Scenario: a 9/9 false-reject corpus cannot mint PROVEN (production shape B)

- **WHEN** every verification record present for a claim is a FAIL-
  class verdict (the verifier rejected the whole corpus) and a
  `settle_proven` mint is attempted
- **THEN** the mint is refused with `verification-not-passed` naming
  the failing record — no passing record, no PROVEN

#### Scenario: a passing record mints PROVEN

- **WHEN** `runs/verification-<claim>.md` carries `verdict: verified`
  and the #800 ordering guard is satisfied
- **THEN** `apply(settle_proven)` applies and the provenance row
  records the applied edge

#### Scenario: an explicit reference cannot escape the workspace

- **WHEN** the `verification` argument names a path that resolves
  outside the workspace (`../`, absolute, alias segments)
- **THEN** the mint is refused with `verification-not-passed`

### Requirement: A 100 percent one-sided verifier is BROKEN, loudly and boundedly

The verifier calibration self-check SHALL group verdict records by
verifier identity (the `verifier-identity:` header; unattributed
records form their own bucket) and flag any verifier with
`CALIBRATION_MIN_SAMPLE` or more records that are 100% REJECT-class
(and symmetrically 100% PASS-class) as BROKEN. Each flagged verifier
SHOULD emit ONE loud `verifier_calibration_broken` event per scan
occurrence, counted PER VERIFIER under the Standard 11 bounded-
repetition rule: at the limit the event escalates (trust burned,
`escalated: true`) and beyond it the emit degrades to silence while
the audit keeps counting. The check SHALL be fail-open telemetry — it
never raises into its caller.

#### Scenario: an all-reject verifier is flagged broken once per occurrence

- **WHEN** a workspace holds the sample floor of REJECT records for one
  verifier identity and the calibration check runs
- **THEN** one `verifier_calibration_broken` event lands naming the
  identity, its pass/fail counts, and occurrence 1

#### Scenario: repetition is bounded and escalates at the limit

- **WHEN** the calibration check runs repeatedly with no corpus change
- **THEN** occurrences increment per scan, the occurrence at the
  Standard 11 limit carries `escalated: true`, and scans beyond the
  limit emit nothing new while the returned audit rows keep counting

#### Scenario: mixed or thin verdicts are never broken

- **WHEN** a verifier's records mix PASS and FAIL classes, or number
  below the sample floor
- **THEN** no BROKEN event fires

### Requirement: YAML block-scalar format differences warn, never reject

The L1 verify face's fact frontmatter parser SHALL support YAML block
scalars (literal `|` and folded `>` styles, chomping indicators, and
explicit indentation hints) and extract the block's semantic value. A
format-only difference — block style, folding, chomping, indentation
width — SHALL degrade to a WARN sidecar (`_format_warnings` on the
loaded fact, mirrored into the L1 verdict detail) without changing the
verdict. Semantic comparisons over the extracted value SHALL still
FAIL on real mismatches exactly as before.

#### Scenario: a literal-block expected with matching reproduce output passes

- **WHEN** a fact carries `expected: |` with value-assertion lines and
  the reproduce output matches every assertion
- **THEN** the L1 verdict is PASS (the pre-fix shape rejected it for
  format) and the block-scalar normalization is recorded as a warning,
  not a rejection

#### Scenario: folding style differs but semantics match — warn and pass

- **WHEN** the same semantic expected is written as a folded `>`
  block with a different chomping indicator
- **THEN** the verdict is unchanged by the style difference and the
  normalization lands in the warn sidecar

#### Scenario: a semantic mismatch inside a block scalar still fails

- **WHEN** a block-scalar expected carries a wrong value
- **THEN** the L1 verdict is FAIL with the usual mismatch detail

### Requirement: Oracle registration is asserted at run start

The run-start face (`oracle_cadence.assert_run_start`) SHALL emit a
loud bounded `oracle_cadence_warn` event (face `run_start`, reason
`client_not_registered`) when armed oracle cases exist but no
implementation-under-test is registered, and `claims_store.
begin_dispatch` SHALL invoke it fail-open (telemetry, never a dispatch
blocker) so the condition surfaces before the first dispatch instead
of surviving a whole run silently. Workspaces with no armed cases or a
registered client SHALL stay silent. Emission SHALL be bounded per the
Standard 11 rule (per-workspace counter, escalate at the limit,
bounded silence beyond).

#### Scenario: armed cases without a registered client are loud at dispatch time

- **WHEN** `begin_dispatch` runs in a workspace with armed oracle cases
  and no registered client
- **THEN** a loud `oracle_cadence_warn` event lands with
  face=run_start before the dispatch intent is journaled, the dispatch
  itself proceeds, and repeated dispatches do not spam (bounded counter)

#### Scenario: registered or unarmed workspaces stay silent

- **WHEN** the client is registered or no armed cases exist
- **THEN** the run-start face is silent
