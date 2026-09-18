# Spec Delta — plan epistemics (issue #250)

## ADDED Requirements

### Requirement: Plans SHALL carry a per-step contingency branch

Every enumerated step entry in a worker plan (`runs/plan-<KEY>*.md`) MUST
be followed by an `if-fails:` branch carrying a condition and an action.
The plan-first gate (`check_worker_plan`) MUST reject a re-dispatch whose
on-disk plan enumerates steps without if-fails coverage. Plans that carry
no enumerated step entries (legacy inline single-value shape) are NOT
rejected by this requirement. The FIRST dispatch of a claim remains
plan-free (issue #239 v2 contract).

#### Scenario: enumerated linear plan is rejected on re-dispatch

- **WHEN** `runs/plan-C001.md` lists two numbered steps with expected
  outputs but no `if-fails:` line, and C-001 is re-dispatched (anchor log
  has prior rows)
- **THEN** the plan gate REJECTS with a per-step contingency repair reason

#### Scenario: branched plan passes

- **WHEN** each enumerated step of `runs/plan-C001.md` is followed by an
  `if-fails:` line with condition + action, provenance intact
- **THEN** the plan gate passes the re-dispatch

#### Scenario: legacy inline plan unaffected

- **WHEN** the plan uses the legacy inline shape (`steps: dump strings`,
  no enumerated entries)
- **THEN** the contingency requirement does not reject it

### Requirement: Situational unknowns SHALL be minted as epistemic claims

The MUST-MASTER situational unknown list SHALL be derived (not
user-articulated) for at least the vmp and android target classes.
Unresolved unknowns SHALL be minted as claims with
`boundary_type: epistemic` whose `answers_question` is the situational
question id (pq_id). Minting SHALL seed a situational `PQCategorical`
into `runs/posteriors.yaml` keyed by that pq_id (candidates from task_spec
`model_selection` where available, else the derived competitor set) and
record `h_standing_bits` and `delta_h_bits` as separate fields. ΔH is
SIGNED information gain (H_before − H_after); it MAY be negative and MUST
NOT be clamped.

#### Scenario: vmp target derives dispatch-mode unknown

- **WHEN** evidence/die.json reports detected_packer vmprotect and the
  mint CLI runs against the workspace
- **THEN** an epistemic claim exists whose answers_question is the
  dispatch-mode situational question, OPEN, with ΔH fields, and
  `ledger.pqs` carries the matching categorical

#### Scenario: minting is idempotent

- **WHEN** the mint CLI runs twice
- **THEN** no duplicate epistemic claims appear and the ledger is stable

### Requirement: Epistemic claims SHALL be priced by the existing ΔH term

An epistemic claim whose answers_question keys a ledger PQ SHALL enter
priority_ratio ranking through the existing LAMBDA_DH ΔH term with no
formula or parameter change. The rank feed SHALL identify the situational
source.

#### Scenario: seeded situational PQ yields nonzero ΔH price

- **WHEN** a register holds an OPEN epistemic claim and the ledger holds
  its seeded situational categorical (entropy > 0)
- **THEN** the claim's score includes LAMBDA_DH * H > 0 and the feed line
  names the situational/epistemic source

### Requirement: Facts SHALL carry assumptions with semantic refutation

Fact frontmatter MUST accept `assumptions: [<topic>=<polarity>]` entries. When a
PROVEN/VERIFIED fact or claim's content matches an assumption's topic with
a contradicting polarity, refutation_propagate SHALL flag the
assumption-carrying fact's claim `needs_re-eval: true` (marking only, no
cascade, idempotent). lint_facts SHALL reject malformed assumptions and
SHALL flag a world-existential title on an observational-source fact that
lacks a tool-scope qualifier.

#### Scenario: xref conclusion invalidated by dynamic registration

- **WHEN** fact F1 ("sub_1234 uncalled", assumptions: [dispatch=static],
  claim C-101) coexists with PROVEN fact F2 ("JNI_OnLoad registers natives
  via RegisterNatives — dispatch resolves calls dynamically", claim C-102)
- **THEN** refutation_propagate flags C-101 needs_re-eval and reports F1
- **AND** C-102 and the structural depends_on face are unchanged

#### Scenario: world-existential title without tool scope

- **WHEN** an observational-source fact is titled "No callers of sub_1234"
- **THEN** lint_facts errors with an observation-vs-world violation
- **WHEN** the title is "xref: no callers of sub_1234"
- **THEN** the fact lints clean on that rule

### Requirement: Settlement SHALL annotate epistemic coverage, never block on it

At settlement time the system MUST compute whether the settling claim's
fact assumptions resolve to terminal epistemic claims, and SHALL record
the result as an annotation (event log + completion-gate pass note). The
annotation MUST NOT change an exit code, block settlement, or block
promotion (anti-Goodhart: sort-shaped signal only).

#### Scenario: open presupposition annotated on PASS

- **WHEN** a claim settles while an epistemic claim answering its fact
  assumption's question is still OPEN
- **THEN** the settlement path emits an epistemic_coverage annotation
  naming the unresolved question and the session still ends (non-blocking)
